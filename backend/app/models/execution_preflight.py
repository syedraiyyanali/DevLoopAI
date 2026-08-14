from typing import Literal

from pydantic import BaseModel, Field

from app.models.planning_workflow import ApprovalStatus


ExecutionPreflightStatus = Literal[
    "READY_FOR_EXECUTION",
    "REAPPROVAL_REQUIRED",
    "BLOCKED",
]


class ExecutionPreflightRequest(BaseModel):
    """
    Request body for checking an approved persisted workflow before future execution.
    """
    workflow_id: str = Field(..., min_length=1)


class FingerprintVerification(BaseModel):
    """
    Verification that persisted plan content still matches its stored fingerprint.
    """
    stored_fingerprint: str
    recomputed_fingerprint: str
    matches: bool


class WorkspacePreflightStatus(BaseModel):
    """
    Current workspace availability for the approved workflow.
    """
    workspace_path: str | None = None
    exists: bool
    is_directory: bool
    status: str


class PreflightFileCheck(BaseModel):
    """
    Deterministic check for a file/path named by the reviewed plan.
    """
    relative_path: str
    exists: bool
    kind: Literal["file", "directory", "missing", "blocked"]
    size_bytes: int | None = None
    modified_after_approval: bool | None = None
    note: str


class ExecutionPreflightResponse(BaseModel):
    """
    Read-only decision for whether an approved workflow can be handed to future execution.
    """
    workflow_id: str
    approval_status: ApprovalStatus
    status: ExecutionPreflightStatus
    fingerprint: FingerprintVerification
    workspace: WorkspacePreflightStatus
    file_checks: list[PreflightFileCheck] = Field(default_factory=list)
    detected_changes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    execution_readiness: str
    reapproval_reason: str | None = None
