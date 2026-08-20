from datetime import datetime, timezone
from uuid import uuid4

from app.models.autonomous_task import (
    AutonomousTaskActionRequest,
    AutonomousTaskSession,
    AutonomousTaskStartRequest,
)
from app.models.task_execution import TaskExecutionPrepareRequest
from app.services.autonomous_task_store import AutonomousTaskStore
from app.services.planning_approval import PlanningApprovalStore
from app.services.task_execution import ControlledTaskExecutionService
from app.workflows.planning import PlanningWorkflow


class AutonomousTaskBlockedError(Exception):
    """Raised when an autonomous task transition is not allowed."""


class BoundedAutonomousTaskService:
    """Coordinates safe autonomous stages while preserving approval boundaries."""

    def __init__(
        self,
        *,
        store: AutonomousTaskStore,
        approval_store: PlanningApprovalStore,
        planning_workflow: PlanningWorkflow,
        task_execution_service: ControlledTaskExecutionService,
    ) -> None:
        self.store = store
        self.approval_store = approval_store
        self.planning_workflow = planning_workflow
        self.task_execution_service = task_execution_service

    async def start(self, request: AutonomousTaskStartRequest) -> AutonomousTaskSession:
        now = self._now()
        session = self.store.create(
            AutonomousTaskSession(
                autonomous_session_id=str(uuid4()),
                state="PLANNING",
                current_stage="planning",
                user_task=request.task,
                workspace_path=request.workspace_path,
                created_at=now,
                updated_at=now,
                progress=["Session created.", "Planning workflow started."],
                message="Running read-only planning workflow.",
            )
        )
        try:
            planning_result = await self.planning_workflow.run(request)
            approval = planning_result.approval
            session.planning_result = planning_result
            session.workflow_id = approval.workflow_id
            session.plan_fingerprint = approval.plan_fingerprint
            session.workspace_path = request.workspace_path
            session.blockers = list(planning_result.final_reviewed_summary.blockers)
            session.warnings = list(planning_result.final_reviewed_summary.warnings)
            if approval.status == "PENDING_APPROVAL":
                session.state = "AWAITING_PLAN_APPROVAL"
                session.current_stage = "plan_approval"
                session.waiting_for = "Explicit plan approval is required."
                session.message = "Planning completed. Waiting for explicit plan approval."
            else:
                session.state = "BLOCKED"
                session.current_stage = "planning_blocked"
                session.waiting_for = None
                session.blockers = [*session.blockers, approval.reason]
                session.message = "Planning completed but approval is blocked."
            session.progress.append(f"Planning workflow persisted as {approval.workflow_id}.")
        except Exception as exc:
            session.state = "BLOCKED"
            session.current_stage = "planning_failed"
            session.blockers = [str(exc)]
            session.message = "Autonomous planning failed safely. No files were modified."
        return self.store.update(session)

    def get(self, autonomous_session_id: str) -> AutonomousTaskSession:
        return self.store.get(autonomous_session_id)

    async def continue_session(
        self,
        autonomous_session_id: str,
        request: AutonomousTaskActionRequest | None = None,
    ) -> AutonomousTaskSession:
        session = self.store.get(autonomous_session_id)
        self._ensure_state_guard(session, request)

        if session.state == "AWAITING_PLAN_APPROVAL":
            return await self._continue_after_plan_approval(session)

        if session.state == "AWAITING_EXECUTION_APPROVAL":
            return await self._continue_after_execution_action(session)

        if session.state in {"QUALITY_PASSED", "RETRY_LIMIT_REACHED", "ROLLED_BACK", "BLOCKED"}:
            raise AutonomousTaskBlockedError(
                f"Autonomous session is terminal or blocked at {session.state}."
            )

        raise AutonomousTaskBlockedError(
            f"Autonomous session cannot continue from {session.state}."
        )

    async def _continue_after_plan_approval(
        self,
        session: AutonomousTaskSession,
    ) -> AutonomousTaskSession:
        if not session.workflow_id:
            raise AutonomousTaskBlockedError("Autonomous session has no workflow ID.")
        workflow = self.approval_store.get_workflow(session.workflow_id)
        if workflow.approval_status == "PENDING_APPROVAL":
            session.waiting_for = "Explicit plan approval is required."
            session.message = "Still waiting for explicit plan approval. No files were modified."
            return self.store.update(session)
        if workflow.approval_status != "APPROVED":
            session.state = "BLOCKED"
            session.current_stage = "plan_approval_blocked"
            session.blockers = [workflow.approval_reason]
            session.waiting_for = None
            session.message = "Autonomous session blocked because the plan is not approved."
            return self.store.update(session)

        session.state = "PREPARING_EXECUTION"
        session.current_stage = "execution_preparation"
        session.waiting_for = None
        session.progress.append("Plan approval detected. Preparing reviewed execution diff.")
        self.store.update(session)

        task = await self._prepare_or_load_task(session)
        session.task_execution = task
        session.task_execution_id = task.task_execution_id
        session.current_attempt = task.current_attempt
        session.max_attempts = task.max_attempts
        session.blockers = list(task.blockers)
        session.warnings = self._unique([*session.warnings, *task.warnings])
        if task.state == "AWAITING_EXECUTION_APPROVAL":
            session.state = "AWAITING_EXECUTION_APPROVAL"
            session.current_stage = "execution_approval"
            session.waiting_for = "Explicit mutation approval is required for the reviewed diff."
            session.message = "Execution diff is prepared. Waiting for explicit Apply."
            session.progress.append(f"Task execution prepared as {task.task_execution_id}.")
        else:
            session.state = "BLOCKED"
            session.current_stage = "execution_preparation_blocked"
            session.waiting_for = None
            session.message = "Execution preparation did not reach the approval boundary."
        return self.store.update(session)

    async def _continue_after_execution_action(
        self,
        session: AutonomousTaskSession,
    ) -> AutonomousTaskSession:
        if not session.task_execution_id:
            raise AutonomousTaskBlockedError("Autonomous session has no task execution ID.")
        task = self.task_execution_service.get(session.task_execution_id)

        if task.state == "AWAITING_EXECUTION_APPROVAL":
            session.task_execution = task
            session.waiting_for = "Explicit mutation approval is required for the reviewed diff."
            session.message = "Still waiting for explicit Apply. No files were modified."
            return self.store.update(session)

        if task.state == "APPLIED":
            session.state = "VERIFYING"
            session.current_stage = "verification"
            session.waiting_for = None
            session.progress.append("Explicit Apply detected. Running required verification.")
            self.store.update(session)
            task = self.task_execution_service.verify(task.task_execution_id)

        if task.state == "QUALITY_FAILED" and task.current_attempt < task.max_attempts:
            session.state = "RETRY_PREPARING"
            session.current_stage = "retry_preparation"
            session.progress.append("Quality failed. Preparing bounded retry proposal.")
            self.store.update(session)
            task = await self.task_execution_service.retry(task.task_execution_id)

        session.task_execution = task
        session.task_execution_id = task.task_execution_id
        session.current_attempt = task.current_attempt
        session.max_attempts = task.max_attempts
        session.blockers = list(task.blockers)
        session.warnings = self._unique([*session.warnings, *task.warnings])
        session.state = self._map_task_state(task.state)
        session.current_stage = self._stage_for_state(session.state)
        session.waiting_for = (
            "Explicit mutation approval is required for the reviewed diff."
            if session.state == "AWAITING_EXECUTION_APPROVAL"
            else None
        )
        session.message = self._message_for_task(task)
        return self.store.update(session)

    async def _prepare_or_load_task(self, session: AutonomousTaskSession):
        if session.task_execution_id:
            return self.task_execution_service.get(session.task_execution_id)
        return await self.task_execution_service.prepare(
            TaskExecutionPrepareRequest(workflow_id=session.workflow_id or "")
        )

    def _map_task_state(self, task_state: str):
        return {
            "AWAITING_EXECUTION_APPROVAL": "AWAITING_EXECUTION_APPROVAL",
            "APPLIED": "AWAITING_EXECUTION_APPROVAL",
            "VERIFYING": "VERIFYING",
            "QUALITY_PASSED": "QUALITY_PASSED",
            "QUALITY_FAILED": "QUALITY_FAILED",
            "QUALITY_INCOMPLETE": "QUALITY_FAILED",
            "RETRY_PREPARING": "RETRY_PREPARING",
            "RETRY_LIMIT_REACHED": "RETRY_LIMIT_REACHED",
            "BLOCKED": "BLOCKED",
            "ROLLED_BACK": "ROLLED_BACK",
            "FAILED": "BLOCKED",
        }.get(task_state, "BLOCKED")

    def _stage_for_state(self, state: str) -> str:
        return {
            "AWAITING_EXECUTION_APPROVAL": "execution_approval",
            "VERIFYING": "verification",
            "QUALITY_PASSED": "quality_passed",
            "QUALITY_FAILED": "quality_failed",
            "RETRY_LIMIT_REACHED": "retry_limit_reached",
            "BLOCKED": "blocked",
            "ROLLED_BACK": "rolled_back",
        }.get(state, "blocked")

    def _message_for_task(self, task) -> str:
        if task.state == "AWAITING_EXECUTION_APPROVAL":
            return "Reviewed diff is ready. Explicit Apply is required before mutation."
        if task.state == "QUALITY_PASSED":
            return "Verification completed and deterministic Quality Gate passed."
        if task.state == "RETRY_LIMIT_REACHED":
            return "Retry limit reached. No further retry proposal will be prepared."
        if task.state == "ROLLED_BACK":
            return "Task execution has been rolled back."
        return task.message

    def _ensure_state_guard(
        self,
        session: AutonomousTaskSession,
        request: AutonomousTaskActionRequest | None,
    ) -> None:
        if request and request.expected_state and request.expected_state != session.state:
            raise AutonomousTaskBlockedError(
                f"Autonomous session state is {session.state}, not {request.expected_state}."
            )

    def _unique(self, values: list[str]) -> list[str]:
        seen = set()
        output = []
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            output.append(value)
        return output

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
