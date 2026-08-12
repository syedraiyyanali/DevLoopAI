from fastapi import APIRouter, HTTPException
from starlette import status

from app.agents.planner import PlannerAgent, PlannerAgentError
from app.core.config import settings
from app.models.planner import PlannerRequest, PlannerResponse
from app.services.ollama import OllamaService
from app.services.workspace import WorkspaceNotFoundError, WorkspaceService


router = APIRouter(prefix="/agents/planner")


@router.post(
    "",
    response_model=PlannerResponse,
    summary="Create an implementation plan",
    description="Use the read-only Planner Agent to create a structured plan.",
)
async def create_planner_plan(request: PlannerRequest) -> PlannerResponse:
    """
    Create a read-only implementation plan from a task and optional context.
    """
    agent = PlannerAgent(
        ollama_service=OllamaService(settings),
        workspace_service=WorkspaceService(),
    )

    try:
        return await agent.create_plan(request)
    except WorkspaceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except PlannerAgentError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
