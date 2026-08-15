from fastapi import APIRouter, HTTPException
from starlette import status

from app.core.config import settings
from app.models.execution_quality import ExecutionQualityResponse
from app.services.execution_quality import ExecutionQualityGate
from app.services.execution_store import ExecutionRecordNotFoundError, ExecutionStore
from app.services.workspace import WorkspaceService


router = APIRouter(prefix="/workflows/execution")


def get_execution_quality_gate() -> ExecutionQualityGate:
    return ExecutionQualityGate(
        execution_store=ExecutionStore(settings.database_path),
        workspace_service=WorkspaceService(),
    )


@router.get(
    "/{execution_id}/quality",
    response_model=ExecutionQualityResponse,
    summary="Evaluate deterministic execution quality gate",
)
def get_execution_quality(execution_id: str) -> ExecutionQualityResponse:
    """Return current authoritative quality state from persisted audit data only."""
    try:
        return get_execution_quality_gate().evaluate(execution_id)
    except ExecutionRecordNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

