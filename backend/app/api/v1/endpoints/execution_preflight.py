from fastapi import APIRouter, HTTPException
from starlette import status

from app.core.config import settings
from app.models.execution_preflight import (
    ExecutionPreflightRequest,
    ExecutionPreflightResponse,
)
from app.models.execution_handoff import (
    ExecutionHandoffRequest,
    ExecutionHandoffResponse,
)
from app.services.execution_handoff import (
    ExecutionHandoffBlockedError,
    ExecutionHandoffService,
)
from app.services.execution_preflight import ExecutionPreflightService
from app.services.planning_approval import (
    PlanningApprovalNotFoundError,
    PlanningApprovalStore,
)
from app.services.workspace import WorkspaceService


router = APIRouter(prefix="/workflows/execution")


def get_preflight_service() -> ExecutionPreflightService:
    return ExecutionPreflightService(
        approval_store=PlanningApprovalStore(settings.database_path),
        workspace_service=WorkspaceService(),
    )


def get_handoff_service() -> ExecutionHandoffService:
    approval_store = PlanningApprovalStore(settings.database_path)
    workspace_service = WorkspaceService()
    preflight_service = ExecutionPreflightService(
        approval_store=approval_store,
        workspace_service=workspace_service,
    )

    return ExecutionHandoffService(
        approval_store=approval_store,
        workspace_service=workspace_service,
        preflight_service=preflight_service,
    )


@router.post(
    "/preflight",
    response_model=ExecutionPreflightResponse,
    summary="Run read-only execution preflight",
    description=(
        "Load an approved persisted planning workflow and check whether it can be "
        "safely handed to a future Coding Agent without executing anything."
    ),
)
async def run_execution_preflight(
    request: ExecutionPreflightRequest,
) -> ExecutionPreflightResponse:
    """
    Run read-only preflight for a persisted planning workflow.
    """
    try:
        return get_preflight_service().run(request)
    except PlanningApprovalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/handoff",
    response_model=ExecutionHandoffResponse,
    summary="Create read-only Coding Agent handoff contract",
    description=(
        "Create a structured handoff contract for a future Coding Agent only "
        "when the persisted workflow is approved and preflight is ready."
    ),
)
async def create_execution_handoff(
    request: ExecutionHandoffRequest,
) -> ExecutionHandoffResponse:
    """
    Create a read-only handoff contract. This does not execute or write anything.
    """
    try:
        return get_handoff_service().create_handoff(request)
    except PlanningApprovalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ExecutionHandoffBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
