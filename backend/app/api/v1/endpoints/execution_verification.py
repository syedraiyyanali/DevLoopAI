from fastapi import APIRouter, HTTPException
from starlette import status

from app.core.config import settings
from app.models.execution_verification import (
    ExecutionVerificationHistoryResponse,
    ExecutionVerificationRequest,
    ExecutionVerificationResponse,
)
from app.models.execution_verification_plan import ExecutionVerificationPlanResponse
from app.services.execution_store import ExecutionRecordNotFoundError, ExecutionStore
from app.services.execution_verification import ExecutionVerificationRunner
from app.services.planning_approval import (
    PlanningApprovalNotFoundError,
    PlanningApprovalStore,
)
from app.services.workspace import WorkspaceNotFoundError, WorkspaceService


router = APIRouter(prefix="/workflows/execution")


def get_execution_verification_runner() -> ExecutionVerificationRunner:
    return ExecutionVerificationRunner(
        execution_store=ExecutionStore(settings.database_path),
        approval_store=PlanningApprovalStore(settings.database_path),
        workspace_service=WorkspaceService(),
    )


@router.post(
    "/{execution_id}/verify",
    response_model=ExecutionVerificationResponse,
    summary="Run strictly allowlisted post-mutation verification",
)
def verify_execution(
    execution_id: str,
    request: ExecutionVerificationRequest,
) -> ExecutionVerificationResponse:
    """Run fixed verification identifiers without accepting command text."""
    try:
        return get_execution_verification_runner().verify(execution_id, request)
    except (ExecutionRecordNotFoundError, PlanningApprovalNotFoundError) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WorkspaceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get(
    "/{execution_id}/verification-plan",
    response_model=ExecutionVerificationPlanResponse,
    summary="Describe deterministic verification selection for an execution",
)
def get_execution_verification_plan(
    execution_id: str,
) -> ExecutionVerificationPlanResponse:
    """Return required/recommended/skipped allowlisted checks without running them."""
    try:
        return get_execution_verification_runner().plan(execution_id)
    except ExecutionRecordNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/{execution_id}/verifications",
    response_model=ExecutionVerificationHistoryResponse,
    summary="List persisted verification history for an execution",
)
def list_execution_verifications(
    execution_id: str,
) -> ExecutionVerificationHistoryResponse:
    """Return token-free verification audit history for one execution."""
    try:
        return get_execution_verification_runner().history(execution_id)
    except ExecutionRecordNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
