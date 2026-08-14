from typing import Literal

from pydantic import BaseModel, Field

from app.models.execution_preflight import ExecutionPreflightResponse
from app.models.planning_workflow import ApprovalStatus


AllowedOperationType = Literal[
    "read_file",
    "create_text_file",
    "modify_text_file",
    "delete_text_file",
]


class ExecutionHandoffRequest(BaseModel):
    """
    Request body for creating a read-only Coding Agent handoff contract.
    """
    workflow_id: str = Field(..., min_length=1)


class ApprovalMetadata(BaseModel):
    """
    Token-free user approval metadata tied to the persisted workflow.
    """
    approval_status: ApprovalStatus
    approved_at: str | None = None
    approval_reason: str


class RollbackBackupRequirements(BaseModel):
    """
    Required safeguards a future Coding Agent must satisfy before writing.
    """
    backup_required: bool
    rollback_plan_required: bool
    requirements: list[str] = Field(default_factory=list)


class ExecutionHandoffResponse(BaseModel):
    """
    Safe, structured contract for a future Coding Agent.
    """
    workflow_id: str
    approved_plan_fingerprint: str
    workspace_path: str
    preflight_result: ExecutionPreflightResponse
    approved_planned_changes: list[str] = Field(default_factory=list)
    allowed_files: list[str] = Field(default_factory=list)
    allowed_operation_types: list[AllowedOperationType] = Field(default_factory=list)
    expected_tests: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    rollback_backup_requirements: RollbackBackupRequirements
    user_approval_metadata: ApprovalMetadata
    execution_allowed: bool
    message: str
