from fastapi import APIRouter, HTTPException
from starlette import status

from app.models.workspace import (
    WorkspaceFileContent,
    WorkspaceContextRequest,
    WorkspaceContextSummary,
    WorkspaceListRequest,
    WorkspaceListResponse,
    WorkspaceMetadata,
    WorkspaceOpenRequest,
    WorkspaceReadRequest,
)
from app.services.workspace import (
    WorkspaceAccessError,
    WorkspaceNotFoundError,
    WorkspaceService,
    WorkspaceUnsupportedFileError,
)


router = APIRouter(prefix="/workspace")


@router.post(
    "/open",
    response_model=WorkspaceMetadata,
    summary="Open a local workspace",
    description="Validate a local project directory and return basic metadata.",
)
async def open_workspace(request: WorkspaceOpenRequest) -> WorkspaceMetadata:
    """
    Validate a local project directory before read-only inspection.
    """
    service = WorkspaceService()

    try:
        return service.open_workspace(request.path)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/list",
    response_model=WorkspaceListResponse,
    summary="List workspace files",
    description="List visible files and folders inside a selected workspace.",
)
async def list_workspace(request: WorkspaceListRequest) -> WorkspaceListResponse:
    """
    List a directory inside a selected workspace.
    """
    service = WorkspaceService()

    try:
        return service.list_directory(
            request.workspace_path,
            request.relative_path,
        )
    except WorkspaceAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except WorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/read",
    response_model=WorkspaceFileContent,
    summary="Read a workspace text file",
    description="Safely read a small UTF-8 text file inside a selected workspace.",
)
async def read_workspace_file(request: WorkspaceReadRequest) -> WorkspaceFileContent:
    """
    Read a safe text file inside a selected workspace.
    """
    service = WorkspaceService()

    try:
        return service.read_text_file(
            request.workspace_path,
            request.relative_path,
        )
    except WorkspaceAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    except WorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except WorkspaceUnsupportedFileError as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(exc),
        ) from exc


@router.post(
    "/context",
    response_model=WorkspaceContextSummary,
    summary="Summarize workspace context",
    description="Build a compact deterministic read-only summary of a workspace.",
)
async def summarize_workspace_context(
    request: WorkspaceContextRequest,
) -> WorkspaceContextSummary:
    """
    Summarize project structure without sending project contents to a model.
    """
    service = WorkspaceService()

    try:
        return service.summarize_context(request.workspace_path)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
