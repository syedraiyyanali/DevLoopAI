from fastapi import APIRouter, HTTPException
from starlette import status

from app.agents.planner import PlannerAgent
from app.agents.reviewer import ReviewerAgent
from app.agents.validator import ValidatorAgent
from app.core.config import settings
from app.models.planning_workflow import (
    PlanningApprovalActionRequest,
    PlanningApprovalActionResponse,
    PlanningWorkflowHistoryListResponse,
    PlanningWorkflowHistoryRecord,
    PlanningWorkflowRequest,
    PlanningWorkflowResponse,
)
from app.services.ollama import OllamaService
from app.services.planning_approval import (
    PlanningApprovalBlockedError,
    PlanningApprovalNotFoundError,
    PlanningApprovalStaleError,
    PlanningApprovalStore,
)
from app.services.workspace import WorkspaceNotFoundError, WorkspaceService
from app.workflows.planning import PlanningWorkflow, PlanningWorkflowError


router = APIRouter(prefix="/workflows/planning")


def get_approval_store() -> PlanningApprovalStore:
    return PlanningApprovalStore(settings.database_path)


@router.post(
    "",
    response_model=PlanningWorkflowResponse,
    summary="Run read-only planning workflow",
    description="Run Planner Agent then Reviewer Agent and return a final reviewed plan.",
)
async def run_planning_workflow(
    request: PlanningWorkflowRequest,
) -> PlanningWorkflowResponse:
    """
    Run the read-only Planner -> Reviewer -> Validator workflow.
    """
    workspace_service = WorkspaceService()
    ollama_service = OllamaService(settings)
    approval_store = get_approval_store()
    workflow = PlanningWorkflow(
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
    )

    try:
        return await workflow.run(request)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PlanningWorkflowError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc


@router.post(
    "/approve",
    response_model=PlanningApprovalActionResponse,
    summary="Explicitly approve a reviewed planning workflow",
    description="Mark an exact reviewed plan as approved without executing code.",
)
async def approve_planning_workflow(
    request: PlanningApprovalActionRequest,
) -> PlanningApprovalActionResponse:
    """
    Explicitly approve an exact reviewed plan. This remains read-only.
    """
    try:
        return get_approval_store().approve(
            approval_id=request.approval_id,
            approval_token=request.approval_token,
            plan_fingerprint=request.plan_fingerprint,
        )
    except PlanningApprovalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PlanningApprovalStaleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except PlanningApprovalBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.post(
    "/reject",
    response_model=PlanningApprovalActionResponse,
    summary="Explicitly reject a reviewed planning workflow",
    description="Mark an exact reviewed plan as rejected without executing code.",
)
async def reject_planning_workflow(
    request: PlanningApprovalActionRequest,
) -> PlanningApprovalActionResponse:
    """
    Explicitly reject an exact reviewed plan. This remains read-only.
    """
    try:
        return get_approval_store().reject(
            approval_id=request.approval_id,
            approval_token=request.approval_token,
            plan_fingerprint=request.plan_fingerprint,
        )
    except PlanningApprovalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PlanningApprovalStaleError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except PlanningApprovalBlockedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc


@router.get(
    "",
    response_model=PlanningWorkflowHistoryListResponse,
    summary="List persisted planning workflows",
    description="List token-free planning workflow history in newest-first order.",
)
async def list_planning_workflows() -> PlanningWorkflowHistoryListResponse:
    """
    List persisted planning workflow history without approval tokens.
    """
    return PlanningWorkflowHistoryListResponse(
        workflows=get_approval_store().list_workflows()
    )


@router.get(
    "/{workflow_id}",
    response_model=PlanningWorkflowHistoryRecord,
    summary="Get persisted planning workflow",
    description="Get a token-free persisted planning workflow audit record.",
)
async def get_planning_workflow(
    workflow_id: str,
) -> PlanningWorkflowHistoryRecord:
    """
    Retrieve one persisted planning workflow audit record.
    """
    try:
        return get_approval_store().get_workflow(workflow_id)
    except PlanningApprovalNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
