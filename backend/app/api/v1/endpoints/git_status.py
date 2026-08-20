from fastapi import APIRouter, HTTPException
from starlette import status

from app.core.config import settings
from app.models.git_status import GitStatusRequest, GitStatusResponse
from app.services.execution_store import ExecutionStore
from app.services.git_status import GitStatusService
from app.services.workspace import WorkspaceNotFoundError, WorkspaceService


router = APIRouter(prefix="/workflows/git")


def get_git_status_service() -> GitStatusService:
    return GitStatusService(
        workspace_service=WorkspaceService(),
        execution_store=ExecutionStore(settings.database_path),
    )


@router.post(
    "/status",
    response_model=GitStatusResponse,
    summary="Read Git status and bounded diff",
    description="Return read-only Git status/diff data without staging, committing, or mutating.",
)
def get_git_status(request: GitStatusRequest) -> GitStatusResponse:
    try:
        return get_git_status_service().status(request)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
