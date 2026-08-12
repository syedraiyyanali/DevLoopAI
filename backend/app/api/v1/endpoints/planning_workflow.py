from fastapi import APIRouter, HTTPException
from starlette import status

from app.agents.planner import PlannerAgent
from app.agents.reviewer import ReviewerAgent
from app.core.config import settings
from app.models.planning_workflow import (
    PlanningWorkflowRequest,
    PlanningWorkflowResponse,
)
from app.services.ollama import OllamaService
from app.services.workspace import WorkspaceNotFoundError, WorkspaceService
from app.workflows.planning import PlanningWorkflow, PlanningWorkflowError


router = APIRouter(prefix="/workflows/planning")


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
    Run the read-only Planner -> Reviewer workflow.
    """
    workspace_service = WorkspaceService()
    ollama_service = OllamaService(settings)
    workflow = PlanningWorkflow(
        planner_agent=PlannerAgent(
            ollama_service=ollama_service,
            workspace_service=workspace_service,
        ),
        reviewer_agent=ReviewerAgent(ollama_service=ollama_service),
        workspace_service=workspace_service,
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
