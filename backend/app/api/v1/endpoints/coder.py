from fastapi import APIRouter, HTTPException
from starlette import status

from app.agents.coder import (
    CoderDryRunAgent,
    CoderDryRunBlockedError,
    CoderDryRunError,
    CoderDiffPreviewAgent,
)
from app.core.config import settings
from app.models.coder import (
    CoderDiffPreviewRequest,
    CoderDiffPreviewResponse,
    CoderDryRunRequest,
    CoderDryRunResponse,
)
from app.services.execution_handoff import (
    ExecutionHandoffBlockedError,
    ExecutionHandoffService,
)
from app.services.execution_preflight import ExecutionPreflightService
from app.services.ollama import OllamaService
from app.services.planning_approval import (
    PlanningApprovalNotFoundError,
    PlanningApprovalStore,
)
from app.services.workspace import WorkspaceService


router = APIRouter(prefix="/agents/coder")


def get_coder_dry_run_agent() -> CoderDryRunAgent:
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

    return CoderDryRunAgent(
        ollama_service=OllamaService(settings),
        handoff_service=handoff_service,
    )


def get_coder_diff_preview_agent() -> CoderDiffPreviewAgent:
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

    return CoderDiffPreviewAgent(
        ollama_service=OllamaService(settings),
        handoff_service=handoff_service,
        workspace_service=workspace_service,
    )


@router.post(
    "/dry-run",
    response_model=CoderDryRunResponse,
    summary="Simulate Coding Agent work without mutations",
    description=(
        "Accept a validated execution handoff and return a zero-write Coding Agent "
        "dry-run proposal. This never writes files or runs commands."
    ),
)
async def run_coder_dry_run(
    request: CoderDryRunRequest,
) -> CoderDryRunResponse:
    """
    Run a zero-write Coding Agent dry-run from an approved handoff contract.
    """
    try:
        return await get_coder_dry_run_agent().dry_run(request)
    except PlanningApprovalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (ExecutionHandoffBlockedError, CoderDryRunBlockedError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except CoderDryRunError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.post(
    "/diff-preview",
    response_model=CoderDiffPreviewResponse,
    summary="Preview Coding Agent diffs without mutations",
    description=(
        "Accept a valid zero-write Coding Agent dry-run and return deterministic "
        "unified diffs. This never writes files or runs commands."
    ),
)
async def preview_coder_diff(
    request: CoderDiffPreviewRequest,
) -> CoderDiffPreviewResponse:
    """
    Generate a read-only diff preview from a valid current dry-run.
    """
    try:
        return await get_coder_diff_preview_agent().preview_diff(request)
    except PlanningApprovalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (ExecutionHandoffBlockedError, CoderDryRunBlockedError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except CoderDryRunError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
