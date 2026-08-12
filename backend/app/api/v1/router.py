from fastapi import APIRouter

from app.api.v1.endpoints import ollama, system


api_router = APIRouter()

api_router.include_router(
    system.router,
    tags=["System"],
)

api_router.include_router(
    ollama.router,
    tags=["Ollama"],
)
