from app.models.task_execution import TaskExecutionSession
from app.models.task_recovery import TaskRecoveryResponse
from app.services.execution_quality import ExecutionQualityGate
from app.services.execution_store import ExecutionRecordNotFoundError, ExecutionStore
from app.services.git_commit import GitCommitStore
from app.services.planning_approval import PlanningApprovalNotFoundError, PlanningApprovalStore
from app.services.task_execution_store import TaskExecutionStore


class TaskRecoveryService:
    """Reconstructs safe next steps from persisted task/execution audit state."""

    terminal_states = {"QUALITY_PASSED", "RETRY_LIMIT_REACHED", "ROLLED_BACK", "BLOCKED", "FAILED"}
    interrupted_states = {"PREPARING", "APPLYING", "VERIFYING", "RETRY_PREPARING"}

    def __init__(
        self,
        *,
        task_store: TaskExecutionStore,
        approval_store: PlanningApprovalStore,
        execution_store: ExecutionStore,
        quality_gate: ExecutionQualityGate,
        git_commit_store: GitCommitStore,
    ) -> None:
        self.task_store = task_store
        self.approval_store = approval_store
        self.execution_store = execution_store
        self.quality_gate = quality_gate
        self.git_commit_store = git_commit_store

    def recover(self, task_execution_id: str) -> TaskRecoveryResponse:
        session = self.task_store.get(task_execution_id)
        return self._build_response(session)

    def resume(self, task_execution_id: str) -> TaskExecutionSession:
        session = self.task_store.get(task_execution_id)
        recovery = self._build_response(session)

        if session.state == "VERIFYING" and session.mutation_execution_id:
            session.state = "APPLIED"
            session.warnings = self._unique(
                [
                    *session.warnings,
                    "Recovered interrupted verification. No verification result was assumed; rerun required checks explicitly.",
                ]
            )
            session.message = "Recovered interrupted verification. Explicit verification can be run again."
            return self.task_store.update(session)

        if session.state == "RETRY_PREPARING":
            if session.diff_preview and session.attempts and session.attempts[-1].attempt_number == session.current_attempt:
                session.state = "AWAITING_EXECUTION_APPROVAL"
                session.message = "Recovered persisted retry diff. Explicit Apply is still required."
            else:
                session.state = "QUALITY_FAILED"
                session.warnings = self._unique(
                    [
                        *session.warnings,
                        "Retry preparation was interrupted before a complete reviewed diff was persisted.",
                    ]
                )
                session.message = "Recovered interrupted retry preparation. Prepare retry again explicitly if attempts remain."
            return self.task_store.update(session)

        if session.state == "PREPARING":
            session.state = "FAILED"
            session.blockers = self._unique(
                [
                    *session.blockers,
                    "Preparation was interrupted before a complete reviewed diff was persisted.",
                ]
            )
            session.message = "Recovered interrupted preparation. Start a new preparation explicitly."
            return self.task_store.update(session)

        if session.state == "APPLYING":
            session.state = "BLOCKED"
            session.blockers = self._unique(
                [
                    *session.blockers,
                    "Apply was interrupted or ambiguous. DevLoopAI will not replay file mutation automatically.",
                ]
            )
            session.message = "Recovered ambiguous apply state. Manual audit is required before continuing."
            return self.task_store.update(session)

        if recovery.blockers:
            session.warnings = self._unique([*session.warnings, *recovery.warnings])
            session.blockers = self._unique([*session.blockers, *recovery.blockers])
            if recovery.stale_or_corrupt_state_detected:
                session.state = "BLOCKED"
                session.message = "Recovery blocked by stale or inconsistent persisted state."
                return self.task_store.update(session)

        return session

    def _build_response(self, session: TaskExecutionSession) -> TaskRecoveryResponse:
        completed = self._completed_stages(session)
        interrupted = []
        warnings = []
        blockers = []
        mutation_already_performed = False
        rollback_available = False
        quality_status = session.quality_result.quality_status if session.quality_result else None
        required = []
        completed_verifications = []
        missing = []
        commit_state = None
        commit_hash = None
        stale_or_corrupt = False

        workflow = None
        try:
            workflow = self.approval_store.get_workflow(session.workflow_id)
            if session.plan_fingerprint and workflow.plan_fingerprint != session.plan_fingerprint:
                blockers.append("Task workflow fingerprint no longer matches persisted workflow.")
                stale_or_corrupt = True
        except PlanningApprovalNotFoundError:
            blockers.append("Linked planning workflow is missing.")
            stale_or_corrupt = True

        if not session.attempts and session.diff_review_id:
            blockers.append("Task has a diff review but no attempt audit.")
            stale_or_corrupt = True
        if session.attempts:
            latest = session.attempts[-1]
            if latest.attempt_number != session.current_attempt:
                blockers.append("Latest attempt does not match current attempt number.")
                stale_or_corrupt = True
            if session.diff_review_id and latest.diff_review_id != session.diff_review_id:
                blockers.append("Latest attempt diff review does not match active diff review.")
                stale_or_corrupt = True

        execution = None
        if session.mutation_execution_id:
            try:
                audit = self.execution_store.get_execution_audit(session.mutation_execution_id)
                if audit["status"] == "IN_PROGRESS":
                    interrupted.append("Apply")
                    blockers.append("Mutation execution audit is still IN_PROGRESS.")
                    stale_or_corrupt = True
                else:
                    execution = self.execution_store.get_execution(session.mutation_execution_id)
                    mutation_already_performed = execution.status in {"EXECUTED", "ROLLED_BACK"}
                    rollback_available = execution.rollback_available and execution.status == "EXECUTED"
                    completed_verifications = [
                        item.verification_type
                        for item in self.execution_store.list_verifications(execution.execution_id)
                        if item.status == "PASSED"
                    ]
                    quality = self.quality_gate.evaluate(execution.execution_id)
                    quality_status = quality.quality_status
                    required = quality.required_verification_types
                    missing = quality.missing_checks
                    if quality.quality_status == "BLOCKED":
                        blockers.extend(quality.blockers)
                        stale_or_corrupt = True
                    commit = self.git_commit_store.latest_for_execution(execution.execution_id)
                    if commit:
                        commit_state = commit.status
                        commit_hash = commit.commit_hash
            except ExecutionRecordNotFoundError:
                blockers.append("Linked mutation execution record is missing or incomplete.")
                stale_or_corrupt = True

        if session.state in self.interrupted_states:
            interrupted.append(self._interrupted_label(session.state))
            if session.state == "VERIFYING":
                warnings.append("Verification was interrupted or unknown; no success is assumed.")
            if session.state == "APPLYING":
                blockers.append("Apply state is ambiguous; automatic replay is forbidden.")
                stale_or_corrupt = True

        status = self._recovery_status(session, blockers)
        next_action = self._next_action(session, blockers, missing)
        approval_required = session.state in {"AWAITING_EXECUTION_APPROVAL"} or (
            workflow is not None and workflow.approval_status != "APPROVED"
        )

        return TaskRecoveryResponse(
            task_execution_id=session.task_execution_id,
            workflow_id=session.workflow_id,
            current_task_state=session.state,
            recovery_status=status,
            recoverable_next_action=next_action,
            completed_stages=self._unique(completed),
            interrupted_or_unknown_stages=self._unique(interrupted),
            blockers=self._unique(blockers),
            warnings=self._unique(warnings),
            approval_required=approval_required,
            mutation_already_performed=mutation_already_performed,
            rollback_available=rollback_available,
            commit_state=commit_state,
            commit_hash=commit_hash,
            quality_status=quality_status,
            required_verification_types=required,
            completed_verification_types=self._unique(completed_verifications),
            missing_verification_types=missing,
            stale_or_corrupt_state_detected=stale_or_corrupt,
            message=self._message(status, next_action),
        )

    def _completed_stages(self, session: TaskExecutionSession) -> list[str]:
        stages = []
        if session.preflight:
            stages.append("Preflight")
        if session.handoff:
            stages.append("Handoff")
        if session.dry_run:
            stages.append("Dry Run")
        if session.diff_preview:
            stages.append("Diff Review")
        if session.apply_result:
            stages.append("Apply")
        if session.verification_results:
            stages.append("Verification")
        if session.quality_result:
            stages.append("Quality")
        if session.rollback_status == "ROLLED_BACK":
            stages.append("Rollback")
        return stages

    def _recovery_status(self, session: TaskExecutionSession, blockers: list[str]) -> str:
        if blockers:
            return "BLOCKED"
        if session.state in {"QUALITY_PASSED", "ROLLED_BACK", "RETRY_LIMIT_REACHED"}:
            return "COMPLETE"
        if session.state in {"AWAITING_EXECUTION_APPROVAL", "QUALITY_FAILED", "QUALITY_INCOMPLETE", "APPLIED"}:
            return "AWAITING_USER_ACTION"
        return "RECOVERABLE"

    def _next_action(
        self,
        session: TaskExecutionSession,
        blockers: list[str],
        missing_verifications: list[str],
    ) -> str:
        if blockers:
            return "Inspect blockers before continuing."
        if session.state == "AWAITING_EXECUTION_APPROVAL":
            return "Await explicit execution approval; Apply is not automatic."
        if session.state == "APPLIED":
            return "Run required verification explicitly."
        if session.state == "VERIFYING":
            return "Resume can clear interrupted verification; rerun required checks explicitly."
        if session.state == "QUALITY_INCOMPLETE":
            return "Run missing required verification: " + ", ".join(missing_verifications)
        if session.state == "QUALITY_FAILED":
            return "Prepare retry or rollback explicitly."
        if session.state == "QUALITY_PASSED":
            return "Optionally inspect Git status or perform explicit controlled commit."
        if session.state == "ROLLED_BACK":
            return "Rollback already completed; do not replay."
        if session.state == "RETRY_PREPARING":
            return "Resume will recover a persisted retry diff or return to failed attempt."
        if session.state == "RETRY_LIMIT_REACHED":
            return "Retry limit reached."
        return "Reload task state; no destructive action will be replayed."

    def _message(self, status: str, next_action: str) -> str:
        return f"Recovery status: {status}. {next_action}"

    def _interrupted_label(self, state: str) -> str:
        return {
            "PREPARING": "Preparation",
            "APPLYING": "Apply",
            "VERIFYING": "Verification",
            "RETRY_PREPARING": "Retry Preparation",
        }.get(state, state.title().replace("_", " "))

    def _unique(self, values: list[str]) -> list[str]:
        return list(dict.fromkeys(value for value in values if value))
