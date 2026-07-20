from fastapi import APIRouter

from app.core.config import settings


router = APIRouter()


@router.get(
    "/health",
    summary="Check API health",
    description="Confirm that the DevLoopAI backend is running.",
)
async def health_check() -> dict[str, str]:
    """
    Return the current health status of the backend.
    """
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }