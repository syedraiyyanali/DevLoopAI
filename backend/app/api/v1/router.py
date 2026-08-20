from fastapi import APIRouter

from app.api.v1.endpoints import (
    autonomous_task,
    chat,
    coder,
    execution_history,
    execution_mutation,
    execution_preflight,
    execution_quality,
    execution_verification,
    ollama,
    planner,
    planning_workflow,
    reviewer,
    system,
    task_execution,
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
    task_execution.router,
    tags=["Workflows"],
)

api_router.include_router(
    autonomous_task.router,
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

api_router.include_router(
    execution_quality.router,
    tags=["Workflows"],
)

api_router.include_router(
    execution_history.router,
    tags=["Workflows"],
)
