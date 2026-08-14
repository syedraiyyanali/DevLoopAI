from fastapi import APIRouter, HTTPException
from starlette import status

from app.core.config import settings
from app.models.execution_preflight import (
    ExecutionPreflightRequest,
    ExecutionPreflightResponse,
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
