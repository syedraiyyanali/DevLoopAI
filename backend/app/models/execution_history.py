from typing import Literal

from pydantic import BaseModel, Field

from app.models.execution_verification import ExecutionVerificationResult


ExecutionHistoryStatus = Literal[
    "IN_PROGRESS",
    "EXECUTED",
    "BLOCKED",
    "REVIEW_STALE",
    "ROLLED_BACK",
    "PARTIALLY_FAILED_AND_ROLLED_BACK",
]


class ExecutionHistoryFile(BaseModel):
    """Sanitized persisted audit data for one changed file."""

    relative_path: str
    operation_type: str
    mutation_status: str
    original_content_hash: str | None = None
    proposed_content_hash: str
    final_content_hash: str | None = None
    backup_status: str


class ExecutionHistoryItem(BaseModel):
    """Compact token-free persisted execution history row."""

    execution_id: str
    workflow_id: str
    workspace_path: str
    status: ExecutionHistoryStatus
    created_at: str
    completed_at: str | None = None
    rolled_back_at: str | None = None
    changed_files: list[str] = Field(default_factory=list)
    operation_types: list[str] = Field(default_factory=list)
    backup_status: str
    rollback_available: bool
    verification_count: int = 0
    latest_verification_status: str | None = None
    rollback_recommended: bool = False
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    final_current_state: str


class ExecutionHistoryListResponse(BaseModel):
    """Newest-first persisted execution history."""

    executions: list[ExecutionHistoryItem] = Field(default_factory=list)


class ExecutionHistoryDetail(ExecutionHistoryItem):
    """Full persisted execution audit detail with verification history."""

    plan_fingerprint: str
    diff_review_id: str
    diff_fingerprint: str
    files: list[ExecutionHistoryFile] = Field(default_factory=list)
    verifications: list[ExecutionVerificationResult] = Field(default_factory=list)
    message: str

