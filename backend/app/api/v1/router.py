from fastapi import APIRouter

from app.api.v1.endpoints import (
    chat,
    coder,
    execution_mutation,
    execution_preflight,
    execution_verification,
    ollama,
    planner,
    planning_workflow,
    reviewer,
    system,
    validator,
    workspace,
)


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

api_router.include_router(
    planner.router,
    tags=["Agents"],
)

api_router.include_router(
    reviewer.router,
    tags=["Agents"],
)

api_router.include_router(
    validator.router,
    tags=["Agents"],
)

api_router.include_router(
    coder.router,
    tags=["Agents"],
)

api_router.include_router(
    planning_workflow.router,
    tags=["Workflows"],
)

api_router.include_router(
    execution_preflight.router,
    tags=["Workflows"],
)

api_router.include_router(
    execution_mutation.router,
    tags=["Workflows"],
)

api_router.include_router(
    execution_verification.router,
    tags=["Workflows"],
)
