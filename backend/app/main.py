from fastapi import FastAPI

from app.core.config import settings


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    description="Autonomous AI-powered software development assistant.",
)


@app.get("/", tags=["System"])
async def root() -> dict[str, str]:
    """
    Root endpoint for the DevLoopAI backend.
    """
    return {
        "message": f"{settings.app_name} is running",
        "version": settings.app_version,
        "environment": settings.environment,
        "docs": "/docs",
    }


@app.get("/health", tags=["System"])
async def health_check() -> dict[str, str]:
    """
    Basic health-check endpoint.

    Monitoring systems can use this endpoint to confirm
    that the backend application is running.
    """
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
    }