from fastapi import APIRouter, HTTPException
from starlette import status

from app.agents.coder import CoderDiffPreviewAgent, CoderDryRunAgent
from app.agents.planner import PlannerAgent
from app.agents.reviewer import ReviewerAgent
from app.agents.validator import ValidatorAgent
from app.core.config import settings
from app.models.autonomous_task import (
    AutonomousTaskActionRequest,
    AutonomousTaskSession,
    AutonomousTaskStartRequest,
)
from app.services.autonomous_task import BoundedAutonomousTaskService, AutonomousTaskBlockedError
from app.services.autonomous_task_store import AutonomousTaskNotFoundError, AutonomousTaskStore
from app.services.execution_handoff import ExecutionHandoffService
from app.services.execution_mutation import ExecutionMutationService
from app.services.execution_preflight import ExecutionPreflightService
from app.services.execution_quality import ExecutionQualityGate
from app.services.execution_store import ExecutionRecordNotFoundError, ExecutionStore
from app.services.execution_verification import ExecutionVerificationRunner
from app.services.ollama import OllamaService
from app.services.planning_approval import PlanningApprovalNotFoundError, PlanningApprovalStore
from app.services.task_execution import ControlledTaskExecutionService, TaskExecutionBlockedError
from app.services.task_execution_store import TaskExecutionNotFoundError, TaskExecutionStore
from app.services.workspace import WorkspaceNotFoundError, WorkspaceService
from app.workflows.planning import PlanningWorkflow


router = APIRouter(prefix="/workflows/autonomous-task")


def get_autonomous_task_service() -> BoundedAutonomousTaskService:
    approval_store = PlanningApprovalStore(settings.database_path)
    workspace_service = WorkspaceService()
    execution_store = ExecutionStore(settings.database_path)
    ollama_service = OllamaService(settings)
    preflight_service = ExecutionPreflightService(
        approval_store=approval_store,
        workspace_service=workspace_service,
    )
    handoff_service = ExecutionHandoffService(
        approval_store=approval_store,
        workspace_service=workspace_service,
        preflight_service=preflight_service,
    )
    task_execution_service = ControlledTaskExecutionService(
        task_store=TaskExecutionStore(settings.database_path),
        approval_store=approval_store,
        preflight_service=preflight_service,
        handoff_service=handoff_service,
        dry_run_agent=CoderDryRunAgent(
            ollama_service=ollama_service,
            handoff_service=handoff_service,
            workspace_service=workspace_service,
        ),
        diff_preview_agent=CoderDiffPreviewAgent(
            ollama_service=ollama_service,
            handoff_service=handoff_service,
            workspace_service=workspace_service,
            execution_store=execution_store,
        ),
        mutation_service=ExecutionMutationService(
            handoff_service=handoff_service,
            workspace_service=workspace_service,
            execution_store=execution_store,
        ),
        verification_runner=ExecutionVerificationRunner(
            execution_store=execution_store,
            approval_store=approval_store,
            workspace_service=workspace_service,
        ),
        quality_gate=ExecutionQualityGate(
            execution_store=execution_store,
            workspace_service=workspace_service,
        ),
    )
    return BoundedAutonomousTaskService(
        store=AutonomousTaskStore(settings.database_path),
        approval_store=approval_store,
        planning_workflow=PlanningWorkflow(
            planner_agent=PlannerAgent(
                ollama_service=ollama_service,
                workspace_service=workspace_service,
            ),
            reviewer_agent=ReviewerAgent(ollama_service=ollama_service),
            validator_agent=ValidatorAgent(
                ollama_service=ollama_service,
                workspace_service=workspace_service,
            ),
            workspace_service=workspace_service,
            approval_store=approval_store,
        ),
        task_execution_service=task_execution_service,
    )


@router.post("", response_model=AutonomousTaskSession)
async def start_autonomous_task(
    request: AutonomousTaskStartRequest,
) -> AutonomousTaskSession:
    try:
        return await get_autonomous_task_service().start(request)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{autonomous_session_id}", response_model=AutonomousTaskSession)
def get_autonomous_task(autonomous_session_id: str) -> AutonomousTaskSession:
    try:
        return get_autonomous_task_service().get(autonomous_session_id)
    except AutonomousTaskNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{autonomous_session_id}/continue", response_model=AutonomousTaskSession)
async def continue_autonomous_task(
    autonomous_session_id: str,
    request: AutonomousTaskActionRequest | None = None,
) -> AutonomousTaskSession:
    try:
        return await get_autonomous_task_service().continue_session(
            autonomous_session_id,
            request,
        )
    except (AutonomousTaskNotFoundError, PlanningApprovalNotFoundError, TaskExecutionNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (
        AutonomousTaskBlockedError,
        TaskExecutionBlockedError,
        ExecutionRecordNotFoundError,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
