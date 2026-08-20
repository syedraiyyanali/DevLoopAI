from fastapi import APIRouter, HTTPException
from starlette import status

from app.core.config import settings
from app.models.git_commit import GitCommitRequest, GitCommitResponse
from app.services.execution_quality import ExecutionQualityGate
from app.services.execution_store import ExecutionStore
from app.services.git_commit import (
    ControlledGitCommitService,
    GitCommitBlockedError,
    GitCommitStore,
)
from app.services.git_status import GitStatusService
from app.services.workspace import WorkspaceNotFoundError, WorkspaceService


router = APIRouter(prefix="/workflows/git")


def get_git_commit_service() -> ControlledGitCommitService:
    workspace_service = WorkspaceService()
    execution_store = ExecutionStore(settings.database_path)
    return ControlledGitCommitService(
        execution_store=execution_store,
        quality_gate=ExecutionQualityGate(
            execution_store=execution_store,
            workspace_service=workspace_service,
        ),
        git_status_service=GitStatusService(
            workspace_service=workspace_service,
            execution_store=execution_store,
        ),
        commit_store=GitCommitStore(settings.database_path),
        workspace_service=workspace_service,
    )


@router.post(
    "/commit",
    response_model=GitCommitResponse,
    summary="Commit a quality-passed execution locally",
    description="Stage only audited execution paths and create one explicit local Git commit.",
)
def commit_verified_execution(request: GitCommitRequest) -> GitCommitResponse:
    try:
        return get_git_commit_service().commit(request)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except GitCommitBlockedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
