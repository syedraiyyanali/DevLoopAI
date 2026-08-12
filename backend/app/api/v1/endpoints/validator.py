from fastapi import APIRouter, HTTPException
from starlette import status

from app.agents.validator import ValidatorAgent, ValidatorAgentError
from app.core.config import settings
from app.models.validator import ValidatorRequest, ValidatorResponse
from app.services.ollama import OllamaService
from app.services.workspace import WorkspaceService


router = APIRouter(prefix="/agents/validator")


@router.post(
    "",
    response_model=ValidatorResponse,
    summary="Validate a reviewed implementation plan",
    description="Use the read-only Validator Agent for pre-execution checks.",
)
async def validate_reviewed_plan(request: ValidatorRequest) -> ValidatorResponse:
    """
    Validate a reviewed plan without executing it.
    """
    agent = ValidatorAgent(
        ollama_service=OllamaService(settings),
        workspace_service=WorkspaceService(),
    )

    try:
        return await agent.validate_plan(request)
    except ValidatorAgentError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
