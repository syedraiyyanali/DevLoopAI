from fastapi import APIRouter, HTTPException
from starlette import status

from app.core.config import settings
from app.models.execution_mutation import (
    ExecutionApplyRequest,
    ExecutionApplyResponse,
    ExecutionRollbackRequest,
    ExecutionRollbackResponse,
)
from app.services.execution_handoff import (
    ExecutionHandoffBlockedError,
    ExecutionHandoffService,
)
from app.services.execution_mutation import (
    ExecutionMutationBlockedError,
    ExecutionMutationService,
)
from app.services.execution_preflight import ExecutionPreflightService
from app.services.execution_store import ExecutionRecordNotFoundError, ExecutionStore
from app.services.planning_approval import (
    PlanningApprovalNotFoundError,
    PlanningApprovalStore,
)
from app.services.workspace import WorkspaceService


router = APIRouter(prefix="/workflows/execution")


def get_execution_mutation_service() -> ExecutionMutationService:
    approval_store = PlanningApprovalStore(settings.database_path)
    workspace_service = WorkspaceService()
    preflight_service = ExecutionPreflightService(
        approval_store=approval_store,
        workspace_service=workspace_service,
    )
    handoff_service = ExecutionHandoffService(
        approval_store=approval_store,
        workspace_service=workspace_service,
        preflight_service=preflight_service,
    )
    return ExecutionMutationService(
        handoff_service=handoff_service,
        workspace_service=workspace_service,
        execution_store=ExecutionStore(settings.database_path),
    )


@router.post(
    "/apply",
    response_model=ExecutionApplyResponse,
    summary="Apply an exact persisted reviewed diff with snapshots",
)
def apply_reviewed_diff(request: ExecutionApplyRequest) -> ExecutionApplyResponse:
    """Apply only deterministic content from the exact persisted review artifact."""
    try:
        return get_execution_mutation_service().apply(request)
    except (PlanningApprovalNotFoundError, ExecutionRecordNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ExecutionHandoffBlockedError, ExecutionMutationBlockedError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post(
    "/rollback",
    response_model=ExecutionRollbackResponse,
    summary="Rollback a controlled execution from persisted snapshots",
)
def rollback_execution(request: ExecutionRollbackRequest) -> ExecutionRollbackResponse:
    """Restore modified files and remove files created by one execution."""
    try:
        return get_execution_mutation_service().rollback(request)
    except (PlanningApprovalNotFoundError, ExecutionRecordNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ExecutionHandoffBlockedError, ExecutionMutationBlockedError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
