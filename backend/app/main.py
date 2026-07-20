from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import settings


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    description="Autonomous AI-powered software development assistant.",
)


app.include_router(
    api_router,
    prefix=settings.api_prefix,
)


@app.get("/", tags=["System"])
async def root() -> dict[str, str]:
    """
    Return basic information about the DevLoopAI backend.
    """
    return {
        "message": f"{settings.app_name} is running",
        "version": settings.app_version,
        "environment": settings.environment,
        "docs": "/docs",
        "api": settings.api_prefix,
    }