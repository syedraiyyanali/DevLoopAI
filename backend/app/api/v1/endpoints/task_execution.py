from fastapi import APIRouter, HTTPException
from starlette import status

from app.agents.coder import CoderDiffPreviewAgent, CoderDryRunAgent
from app.core.config import settings
from app.models.task_execution import (
    TaskExecutionActionRequest,
    TaskExecutionPrepareRequest,
    TaskExecutionSession,
)
from app.models.task_recovery import TaskRecoveryResponse
from app.services.execution_handoff import ExecutionHandoffService
from app.services.execution_mutation import ExecutionMutationService
from app.services.execution_preflight import ExecutionPreflightService
from app.services.execution_quality import ExecutionQualityGate
from app.services.execution_store import ExecutionRecordNotFoundError, ExecutionStore
from app.services.execution_verification import ExecutionVerificationRunner
from app.services.git_commit import GitCommitStore
from app.services.ollama import OllamaService
from app.services.planning_approval import PlanningApprovalNotFoundError, PlanningApprovalStore
from app.services.task_recovery import TaskRecoveryService
from app.services.task_execution import ControlledTaskExecutionService, TaskExecutionBlockedError
from app.services.task_execution_store import TaskExecutionNotFoundError, TaskExecutionStore
from app.services.workspace import WorkspaceService


router = APIRouter(prefix="/workflows/execution/task")


def get_task_execution_service() -> ControlledTaskExecutionService:
    approval_store = PlanningApprovalStore(settings.database_path)
    workspace_service = WorkspaceService()
    execution_store = ExecutionStore(settings.database_path)
    preflight_service = ExecutionPreflightService(
        approval_store=approval_store,
        workspace_service=workspace_service,
    )


def get_task_recovery_service() -> TaskRecoveryService:
    approval_store = PlanningApprovalStore(settings.database_path)
    workspace_service = WorkspaceService()
    execution_store = ExecutionStore(settings.database_path)
    return TaskRecoveryService(
        task_store=TaskExecutionStore(settings.database_path),
        approval_store=approval_store,
        execution_store=execution_store,
        quality_gate=ExecutionQualityGate(
            execution_store=execution_store,
            workspace_service=workspace_service,
        ),
        git_commit_store=GitCommitStore(settings.database_path),
    )
    handoff_service = ExecutionHandoffService(
        approval_store=approval_store,
        workspace_service=workspace_service,
        preflight_service=preflight_service,
    )
    return ControlledTaskExecutionService(
        task_store=TaskExecutionStore(settings.database_path),
        approval_store=approval_store,
        preflight_service=preflight_service,
        handoff_service=handoff_service,
        dry_run_agent=CoderDryRunAgent(
            ollama_service=OllamaService(settings),
            handoff_service=handoff_service,
            workspace_service=workspace_service,
        ),
        diff_preview_agent=CoderDiffPreviewAgent(
            ollama_service=OllamaService(settings),
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


@router.post("", response_model=TaskExecutionSession)
async def prepare_task_execution(
    request: TaskExecutionPrepareRequest,
) -> TaskExecutionSession:
    try:
        return await get_task_execution_service().prepare(request)
    except PlanningApprovalNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{task_execution_id}", response_model=TaskExecutionSession)
def get_task_execution(task_execution_id: str) -> TaskExecutionSession:
    try:
        return get_task_execution_service().get(task_execution_id)
    except TaskExecutionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{task_execution_id}/recovery", response_model=TaskRecoveryResponse)
def recover_task_execution(task_execution_id: str) -> TaskRecoveryResponse:
    try:
        return get_task_recovery_service().recover(task_execution_id)
    except TaskExecutionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{task_execution_id}/resume", response_model=TaskExecutionSession)
def resume_task_execution(task_execution_id: str) -> TaskExecutionSession:
    try:
        return get_task_recovery_service().resume(task_execution_id)
    except TaskExecutionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{task_execution_id}/apply", response_model=TaskExecutionSession)
def apply_task_execution(
    task_execution_id: str,
    request: TaskExecutionActionRequest | None = None,
) -> TaskExecutionSession:
    try:
        return get_task_execution_service().apply(task_execution_id, request)
    except TaskExecutionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (TaskExecutionBlockedError, ExecutionRecordNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{task_execution_id}/verify", response_model=TaskExecutionSession)
def verify_task_execution(
    task_execution_id: str,
    request: TaskExecutionActionRequest | None = None,
) -> TaskExecutionSession:
    try:
        return get_task_execution_service().verify(task_execution_id, request)
    except TaskExecutionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (TaskExecutionBlockedError, ExecutionRecordNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{task_execution_id}/retry", response_model=TaskExecutionSession)
async def retry_task_execution(
    task_execution_id: str,
    request: TaskExecutionActionRequest | None = None,
) -> TaskExecutionSession:
    try:
        return await get_task_execution_service().retry(task_execution_id, request)
    except TaskExecutionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (TaskExecutionBlockedError, ExecutionRecordNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/{task_execution_id}/rollback", response_model=TaskExecutionSession)
def rollback_task_execution(
    task_execution_id: str,
    request: TaskExecutionActionRequest | None = None,
) -> TaskExecutionSession:
    try:
        return get_task_execution_service().rollback(task_execution_id, request)
    except TaskExecutionNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (TaskExecutionBlockedError, ExecutionRecordNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
