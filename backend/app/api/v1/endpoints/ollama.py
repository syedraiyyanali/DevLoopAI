from fastapi import APIRouter

from app.core.config import settings
from app.models.ollama import OllamaStatus
from app.services.ollama import OllamaService


router = APIRouter(prefix="/ollama")


@router.get(
    "/status",
    response_model=OllamaStatus,
    summary="Check Ollama status",
    description="Confirm whether the configured Ollama backend is reachable.",
)
async def ollama_status() -> OllamaStatus:
    """
    Return the current Ollama backend status.
    """
    service = OllamaService(settings)

    return await service.get_status()
