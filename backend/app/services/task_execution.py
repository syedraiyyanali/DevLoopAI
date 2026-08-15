import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from app.agents.coder import CoderDiffPreviewAgent, CoderDryRunAgent
from app.models.coder import CoderDiffPreviewRequest, CoderDryRunRequest
from app.models.execution_handoff import ExecutionHandoffRequest
from app.models.execution_mutation import ExecutionApplyRequest, ExecutionRollbackRequest
from app.models.execution_preflight import ExecutionPreflightRequest
from app.models.execution_verification import ExecutionVerificationRequest
from app.models.task_execution import (
    TaskExecutionActionRequest,
    TaskExecutionAttempt,
    TaskExecutionPrepareRequest,
    TaskExecutionSession,
)
from app.services.execution_handoff import ExecutionHandoffService
from app.services.execution_mutation import ExecutionMutationService
from app.services.execution_preflight import ExecutionPreflightService
from app.services.execution_quality import ExecutionQualityGate
from app.services.execution_verification import ExecutionVerificationRunner
from app.services.planning_approval import PlanningApprovalStore
from app.services.task_execution_store import TaskExecutionStore


class TaskExecutionBlockedError(Exception):
    """Raised when a task execution transition is not allowed."""


class ControlledTaskExecutionService:
    """Coordinates one approved workflow through existing safe execution services."""

    def __init__(
        self,
        *,
        task_store: TaskExecutionStore,
        approval_store: PlanningApprovalStore,
        preflight_service: ExecutionPreflightService,
        handoff_service: ExecutionHandoffService,
        dry_run_agent: CoderDryRunAgent,
        diff_preview_agent: CoderDiffPreviewAgent,
        mutation_service: ExecutionMutationService,
        verification_runner: ExecutionVerificationRunner,
        quality_gate: ExecutionQualityGate,
    ) -> None:
        self.task_store = task_store
        self.approval_store = approval_store
        self.preflight_service = preflight_service
        self.handoff_service = handoff_service
        self.dry_run_agent = dry_run_agent
        self.diff_preview_agent = diff_preview_agent
        self.mutation_service = mutation_service
        self.verification_runner = verification_runner
        self.quality_gate = quality_gate

    async def prepare(self, request: TaskExecutionPrepareRequest) -> TaskExecutionSession:
        workflow = self.approval_store.get_workflow(request.workflow_id)
        now = self._now()
        session = self.task_store.create(
            TaskExecutionSession(
                task_execution_id=str(uuid4()),
                workflow_id=workflow.workflow_id,
                plan_fingerprint=workflow.plan_fingerprint,
                workspace_path=workflow.workspace_path,
                state="PREPARING",
                created_at=now,
                updated_at=now,
                message="Preparing controlled task execution. No files have been modified.",
            )
        )
        try:
            preflight = self.preflight_service.run(
                ExecutionPreflightRequest(workflow_id=workflow.workflow_id)
            )
            if preflight.status != "READY_FOR_EXECUTION":
                session.state = "BLOCKED"
                session.preflight = preflight
                session.blockers = list(preflight.blockers)
                session.message = "Preparation blocked by execution preflight."
                return self.task_store.update(session)

            handoff = self.handoff_service.create_handoff(
                ExecutionHandoffRequest(workflow_id=workflow.workflow_id)
            )
            dry_run = await self.dry_run_agent.dry_run(
                CoderDryRunRequest(handoff=handoff, model=request.model)
            )
            diff_preview = await self.diff_preview_agent.preview_diff(
                CoderDiffPreviewRequest(dry_run=dry_run, model=request.model)
            )
            session.preflight = preflight
            session.handoff = handoff
            session.dry_run = dry_run
            session.diff_preview = diff_preview
            session.diff_review_id = diff_preview.review_id
            session.state = "AWAITING_EXECUTION_APPROVAL"
            session.attempts = [
                self._make_attempt(
                    attempt_number=1,
                    state="AWAITING_EXECUTION_APPROVAL",
                    diff_review_id=diff_preview.review_id,
                    message="Initial reviewed diff prepared.",
                )
            ]
            session.warnings = [*handoff.warnings, *dry_run.warnings, *diff_preview.warnings]
            session.blockers = []
            session.message = "Task prepared through reviewed diff. Explicit apply approval is required."
        except Exception as exc:
            session.state = "FAILED"
            session.blockers = [str(exc)]
            session.message = "Task preparation failed safely. No files were modified."
        return self.task_store.update(session)

    def get(self, task_execution_id: str) -> TaskExecutionSession:
        return self.task_store.get(task_execution_id)

    def apply(
        self,
        task_execution_id: str,
        request: TaskExecutionActionRequest | None = None,
    ) -> TaskExecutionSession:
        session = self.task_store.get(task_execution_id)
        self._ensure_state_guard(session, request)
        if session.state == "APPLIED" and session.apply_result is not None:
            raise TaskExecutionBlockedError("Task has already been applied.")
        if session.state != "AWAITING_EXECUTION_APPROVAL":
            raise TaskExecutionBlockedError("Task is not awaiting execution approval.")
        if not session.handoff or not session.dry_run or not session.diff_preview:
            raise TaskExecutionBlockedError("Prepared task artifacts are incomplete.")
        self._ensure_latest_attempt_matches_active_diff(session)

        session.state = "APPLYING"
        self.task_store.update(session)
        apply_result = self.mutation_service.apply(
            ExecutionApplyRequest(
                handoff=session.handoff,
                dry_run=session.dry_run,
                diff_preview=session.diff_preview,
                allow_audited_retry_state=session.current_attempt > 1,
            )
        )
        session.apply_result = apply_result
        session.mutation_execution_id = apply_result.execution_id
        session.blockers = list(apply_result.blockers)
        session.warnings = [*session.warnings, *apply_result.warnings]
        if apply_result.status == "EXECUTED":
            session.state = "APPLIED"
            session.message = "Reviewed changes were applied. Verification is required next."
        elif apply_result.status == "PARTIALLY_FAILED_AND_ROLLED_BACK":
            session.state = "FAILED"
            session.message = "Apply failed and completed writes were transactionally rolled back."
        else:
            session.state = "BLOCKED"
            session.message = "Apply was blocked. No successful task mutation is current."
        self._update_current_attempt(
            session,
            state=session.state,
            mutation_execution_id=apply_result.execution_id,
            message=session.message,
        )
        return self.task_store.update(session)

    def verify(
        self,
        task_execution_id: str,
        request: TaskExecutionActionRequest | None = None,
    ) -> TaskExecutionSession:
        session = self.task_store.get(task_execution_id)
        self._ensure_state_guard(session, request)
        if session.state not in {"APPLIED", "QUALITY_FAILED", "QUALITY_INCOMPLETE"}:
            raise TaskExecutionBlockedError("Task must be applied before verification.")
        if not session.mutation_execution_id:
            raise TaskExecutionBlockedError("Task has no mutation execution ID.")

        execution = self.quality_gate.execution_store.get_execution(session.mutation_execution_id)
        required = self.quality_gate.required_verifications(execution)
        session.state = "VERIFYING"
        self.task_store.update(session)
        results = []
        if required:
            response = self.verification_runner.verify(
                session.mutation_execution_id,
                ExecutionVerificationRequest(verification_types=required),
            )
            results = response.results
        quality = self.quality_gate.evaluate(session.mutation_execution_id)
        session.verification_results = [*session.verification_results, *results]
        session.verification_ids = [*session.verification_ids, *[item.verification_id for item in results]]
        session.quality_result = quality
        session.rollback_recommended = quality.rollback_recommended
        session.blockers = list(quality.blockers)
        session.warnings = [*session.warnings, *quality.warnings]
        session.state = self._quality_state(quality.quality_status)
        if session.state == "QUALITY_FAILED" and session.current_attempt >= session.max_attempts:
            session.state = "RETRY_LIMIT_REACHED"
            session.blockers = [
                *session.blockers,
                "Retry limit reached. No further improvement retry can be prepared.",
            ]
        session.message = f"Verification completed. Quality gate returned {quality.quality_status}."
        self._update_current_attempt(
            session,
            state=session.state,
            verification_ids=[item.verification_id for item in results],
            quality_status=quality.quality_status,
            message=session.message,
        )
        return self.task_store.update(session)

    def rollback(
        self,
        task_execution_id: str,
        request: TaskExecutionActionRequest | None = None,
    ) -> TaskExecutionSession:
        session = self.task_store.get(task_execution_id)
        self._ensure_state_guard(session, request)
        if not session.mutation_execution_id:
            raise TaskExecutionBlockedError("Task has no mutation execution ID to roll back.")
        rollback = self.mutation_service.rollback(
            ExecutionRollbackRequest(execution_id=session.mutation_execution_id)
        )
        session.rollback_result = rollback
        session.rollback_status = rollback.status
        if rollback.status == "ROLLED_BACK":
            session.state = "ROLLED_BACK"
            session.rollback_recommended = False
            session.quality_result = self.quality_gate.evaluate(session.mutation_execution_id)
        else:
            session.state = "BLOCKED"
            session.blockers = [*session.blockers, *rollback.blockers]
        session.message = rollback.message
        self._update_current_attempt(session, state=session.state, message=session.message)
        return self.task_store.update(session)

    async def retry(
        self,
        task_execution_id: str,
        request: TaskExecutionActionRequest | None = None,
    ) -> TaskExecutionSession:
        session = self.task_store.get(task_execution_id)
        self._ensure_state_guard(session, request)
        if session.state != "QUALITY_FAILED":
            raise TaskExecutionBlockedError("Retry is only allowed after QUALITY_FAILED.")
        if session.current_attempt >= session.max_attempts:
            session.state = "RETRY_LIMIT_REACHED"
            session.blockers = [
                *session.blockers,
                "Retry limit reached. No further improvement retry can be prepared.",
            ]
            session.message = "Retry limit reached. No files were modified."
            return self.task_store.update(session)
        if not session.mutation_execution_id or not session.diff_review_id:
            raise TaskExecutionBlockedError("Retry requires an applied failed attempt and reviewed diff.")

        current_quality = self.quality_gate.evaluate(session.mutation_execution_id)
        if current_quality.quality_status != "QUALITY_FAILED":
            session.state = "BLOCKED"
            session.quality_result = current_quality
            session.blockers = [
                *current_quality.blockers,
                "Retry blocked because the failed execution audit is no longer current.",
            ]
            session.message = "Retry blocked by stale or unsafe current execution state."
            return self.task_store.update(session)

        previous_state = session.state
        previous_attempt = session.current_attempt
        retry_context = self._build_retry_context(session, current_quality)
        retry_context_hash = self._stable_hash(retry_context)

        session.state = "RETRY_PREPARING"
        session.message = "Preparing bounded improvement retry. No files have been modified."
        session.updated_at = self._now()
        self.task_store.update(session)

        try:
            workflow = self.approval_store.get_workflow(session.workflow_id)
            if workflow.approval_status != "APPROVED":
                raise TaskExecutionBlockedError("Retry requires an approved workflow.")
            if workflow.plan_fingerprint != session.plan_fingerprint:
                raise TaskExecutionBlockedError("Retry blocked by stale workflow fingerprint.")
            if not session.preflight or session.preflight.status != "READY_FOR_EXECUTION":
                raise TaskExecutionBlockedError("Retry requires a previously ready preflight.")
            if not session.handoff:
                raise TaskExecutionBlockedError("Retry requires the approved handoff contract.")

            preflight = session.preflight
            handoff = session.handoff
            dry_run = await self.dry_run_agent.dry_run(
                CoderDryRunRequest(
                    handoff=handoff,
                    model=None,
                    retry_context=retry_context,
                )
            )
            diff_preview = await self.diff_preview_agent.preview_diff(
                CoderDiffPreviewRequest(
                    dry_run=dry_run,
                    model=None,
                    retry_context=retry_context,
                    handoff=handoff,
                )
            )
            session.current_attempt = previous_attempt + 1
            session.preflight = preflight
            session.handoff = handoff
            session.dry_run = dry_run
            session.diff_preview = diff_preview
            session.diff_review_id = diff_preview.review_id
            session.mutation_execution_id = None
            session.apply_result = None
            session.verification_results = []
            session.verification_ids = []
            session.quality_result = None
            session.rollback_status = None
            session.rollback_result = None
            session.rollback_recommended = False
            session.state = "AWAITING_EXECUTION_APPROVAL"
            session.warnings = self._unique(
                [*session.warnings, *handoff.warnings, *dry_run.warnings, *diff_preview.warnings]
            )
            session.blockers = []
            session.attempts.append(
                self._make_attempt(
                    attempt_number=session.current_attempt,
                    state="AWAITING_EXECUTION_APPROVAL",
                    parent_execution_id=retry_context["parent_execution_id"],
                    parent_diff_review_id=retry_context["parent_diff_review_id"],
                    diff_review_id=diff_preview.review_id,
                    failure_context_hash=retry_context_hash,
                    message="Improvement retry reviewed diff prepared.",
                )
            )
            remaining = session.max_attempts - session.current_attempt
            session.message = (
                f"Attempt {session.current_attempt} prepared through reviewed diff. "
                f"Explicit apply approval is required. Remaining retries after this attempt: {remaining}."
            )
        except Exception as exc:
            session.state = previous_state
            session.current_attempt = previous_attempt
            session.blockers = [str(exc)]
            session.message = "Retry preparation failed safely. No files were modified and no attempt was consumed."
        return self.task_store.update(session)

    def _ensure_state_guard(
        self,
        session: TaskExecutionSession,
        request: TaskExecutionActionRequest | None,
    ) -> None:
        if request and request.expected_state and request.expected_state != session.state:
            raise TaskExecutionBlockedError(
                f"Task state is {session.state}, not {request.expected_state}."
            )

    def _quality_state(self, quality_status: str):
        return {
            "QUALITY_PASSED": "QUALITY_PASSED",
            "QUALITY_FAILED": "QUALITY_FAILED",
            "QUALITY_INCOMPLETE": "QUALITY_INCOMPLETE",
            "ROLLED_BACK": "ROLLED_BACK",
            "BLOCKED": "BLOCKED",
        }[quality_status]

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _make_attempt(
        self,
        *,
        attempt_number: int,
        state: str,
        diff_review_id: str | None = None,
        parent_execution_id: str | None = None,
        parent_diff_review_id: str | None = None,
        mutation_execution_id: str | None = None,
        verification_ids: list[str] | None = None,
        quality_status: str | None = None,
        failure_context_hash: str | None = None,
        message: str = "",
    ) -> TaskExecutionAttempt:
        now = self._now()
        return TaskExecutionAttempt(
            attempt_number=attempt_number,
            state=state,
            parent_execution_id=parent_execution_id,
            parent_diff_review_id=parent_diff_review_id,
            diff_review_id=diff_review_id,
            mutation_execution_id=mutation_execution_id,
            verification_ids=[] if verification_ids is None else verification_ids,
            quality_status=quality_status,
            failure_context_hash=failure_context_hash,
            created_at=now,
            updated_at=now,
            message=message,
        )

    def _update_current_attempt(
        self,
        session: TaskExecutionSession,
        *,
        state: str,
        mutation_execution_id: str | None = None,
        verification_ids: list[str] | None = None,
        quality_status: str | None = None,
        message: str = "",
    ) -> None:
        if not session.attempts:
            return
        attempt = session.attempts[-1]
        if attempt.attempt_number != session.current_attempt:
            return
        attempt.state = state
        attempt.updated_at = self._now()
        attempt.message = message or attempt.message
        if mutation_execution_id is not None:
            attempt.mutation_execution_id = mutation_execution_id
        if verification_ids:
            attempt.verification_ids = self._unique([*attempt.verification_ids, *verification_ids])
        if quality_status is not None:
            attempt.quality_status = quality_status

    def _ensure_latest_attempt_matches_active_diff(self, session: TaskExecutionSession) -> None:
        if not session.attempts:
            raise TaskExecutionBlockedError("Task attempt audit is missing.")
        latest = session.attempts[-1]
        if latest.attempt_number != session.current_attempt:
            raise TaskExecutionBlockedError("Task attempt audit is inconsistent.")
        if latest.diff_review_id != session.diff_review_id:
            raise TaskExecutionBlockedError("Prepared diff is not the latest reviewed attempt.")

    def _build_retry_context(self, session: TaskExecutionSession, quality) -> dict:
        failed_results = [
            {
                "verification_type": result.verification_type,
                "status": result.status,
                "exit_code": result.exit_code,
                "stdout_excerpt": result.stdout_excerpt,
                "stderr_excerpt": result.stderr_excerpt,
            }
            for result in session.verification_results
            if result.status in {"FAILED", "TIMED_OUT", "BLOCKED"}
        ]
        file_summaries = []
        if session.apply_result:
            file_summaries = [
                {
                    "relative_path": item.relative_path,
                    "operation_type": item.operation_type,
                    "original_content_hash": item.original_content_hash,
                    "proposed_content_hash": item.proposed_content_hash,
                }
                for item in session.apply_result.file_results
            ]
        return {
            "original_task_workflow_id": session.workflow_id,
            "current_attempt": session.current_attempt,
            "max_attempts": session.max_attempts,
            "next_attempt": session.current_attempt + 1,
            "parent_execution_id": session.mutation_execution_id,
            "parent_diff_review_id": session.diff_review_id,
            "failed_required_verifications": failed_results,
            "quality_status": quality.quality_status,
            "quality_reasons": quality.reasons,
            "quality_blockers": quality.blockers,
            "changed_files": file_summaries,
            "previous_diff_summary": (
                None
                if session.dry_run is None
                else session.dry_run.proposed_code_change_summary
            ),
        }

    def _stable_hash(self, payload: dict) -> str:
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def _unique(self, values: list[str]) -> list[str]:
        seen = set()
        output = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            output.append(value)
        return output
