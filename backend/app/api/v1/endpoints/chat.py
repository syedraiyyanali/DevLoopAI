from fastapi import APIRouter, HTTPException
from starlette import status

from app.core.config import settings
from app.models.chat import ChatRequest, ChatResponse
from app.services.ollama import OllamaService, OllamaServiceError


router = APIRouter(prefix="/chat")


@router.post(
    "",
    response_model=ChatResponse,
    summary="Generate a chat response",
    description="Generate a basic non-streaming response through the configured model backend.",
)
async def create_chat_response(chat_request: ChatRequest) -> ChatResponse:
    """
    Generate a non-streaming chat response using the configured Ollama backend.
    """
    service = OllamaService(settings)

    try:
        return await service.generate_chat_response(chat_request)
    except OllamaServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
