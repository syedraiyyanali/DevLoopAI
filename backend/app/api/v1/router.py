from fastapi import APIRouter

from app.api.v1.endpoints import chat, ollama, system, workspace


api_router = APIRouter()

api_router.include_router(
    system.router,
    tags=["System"],
)

api_router.include_router(
    ollama.router,
    tags=["Ollama"],
)

api_router.include_router(
    chat.router,
    tags=["Chat"],
)

api_router.include_router(
    workspace.router,
    tags=["Workspace"],
)
