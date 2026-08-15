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

        session.state = "APPLYING"
        self.task_store.update(session)
        apply_result = self.mutation_service.apply(
            ExecutionApplyRequest(
                handoff=session.handoff,
                dry_run=session.dry_run,
                diff_preview=session.diff_preview,
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
        session.message = f"Verification completed. Quality gate returned {quality.quality_status}."
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
