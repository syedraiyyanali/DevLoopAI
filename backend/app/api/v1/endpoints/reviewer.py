from fastapi import APIRouter, HTTPException
from starlette import status

from app.agents.reviewer import ReviewerAgent, ReviewerAgentError
from app.core.config import settings
from app.models.reviewer import ReviewerRequest, ReviewerResponse
from app.services.ollama import OllamaService


router = APIRouter(prefix="/agents/reviewer")


@router.post(
    "",
    response_model=ReviewerResponse,
    summary="Review an implementation plan",
    description="Use the read-only Reviewer Agent to critique a planner output.",
)
async def review_planner_output(request: ReviewerRequest) -> ReviewerResponse:
    """
    Review a planner response without executing the plan.
    """
    agent = ReviewerAgent(ollama_service=OllamaService(settings))

    try:
        return await agent.review_plan(request)
    except ReviewerAgentError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
