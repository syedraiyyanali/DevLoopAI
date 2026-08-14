from fastapi import APIRouter, HTTPException
from starlette import status

from app.core.config import settings
from app.models.execution_history import (
    ExecutionHistoryDetail,
    ExecutionHistoryListResponse,
)
from app.services.execution_store import ExecutionRecordNotFoundError, ExecutionStore


router = APIRouter(prefix="/workflows/execution")


def get_execution_store() -> ExecutionStore:
    return ExecutionStore(settings.database_path)


@router.get(
    "",
    response_model=ExecutionHistoryListResponse,
    summary="List persisted controlled execution history",
)
def list_execution_history() -> ExecutionHistoryListResponse:
    """Return newest-first execution audit history without sensitive payloads."""
    return ExecutionHistoryListResponse(
        executions=get_execution_store().list_execution_history()
    )


@router.get(
    "/{execution_id}",
    response_model=ExecutionHistoryDetail,
    summary="Get persisted controlled execution audit detail",
)
def get_execution_history_detail(execution_id: str) -> ExecutionHistoryDetail:
    """Return one execution audit record with persisted verification history."""
    try:
        return get_execution_store().get_execution_history_detail(execution_id)
    except ExecutionRecordNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

