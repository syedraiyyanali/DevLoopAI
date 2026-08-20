from typing import Literal

from pydantic import BaseModel, Field


GitCommitStatus = Literal["COMMITTED", "BLOCKED", "FAILED"]


class GitCommitRequest(BaseModel):
    """Explicit controlled local Git commit request."""

    execution_id: str = Field(..., min_length=1)
    message: str | None = None


class GitCommitResponse(BaseModel):
    """Persisted audit result for one controlled local Git commit attempt."""

    commit_audit_id: str
    execution_id: str
    workflow_id: str | None = None
    workspace_path: str | None = None
    status: GitCommitStatus
    commit_hash: str | None = None
    message: str
    files_committed: list[str] = Field(default_factory=list)
    timestamp: str
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
