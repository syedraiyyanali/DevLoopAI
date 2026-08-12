from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.api.v1.endpoints.system import router as system_router
from app.core.exception_handlers import register_exception_handlers
from app.core.config import settings
from app.core.logging import configure_logging


configure_logging(settings)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    description="Autonomous AI-powered software development assistant.",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

register_exception_handlers(app)


app.include_router(
    api_router,
    prefix=settings.api_prefix,
)

app.include_router(system_router)


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
