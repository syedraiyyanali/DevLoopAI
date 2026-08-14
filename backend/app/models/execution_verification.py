from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints


VerificationStatus = Literal[
    "PASSED",
    "FAILED",
    "SKIPPED",
    "TIMED_OUT",
    "BLOCKED",
]


class ExecutionVerificationRequest(BaseModel):
    """Requested server-side verification identifiers, never command text."""

    verification_types: list[
        Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
    ] = Field(..., min_length=1, max_length=8)


class ExecutionVerificationResult(BaseModel):
    """Persisted result for one allowlisted verification attempt."""

    verification_id: str
    execution_id: str
    workflow_id: str
    verification_type: str
    command_identity: str
    working_directory: str
    status: VerificationStatus
    exit_code: int | None = None
    duration_seconds: float
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    output_truncated: bool = False
    timestamp: str
    rollback_recommended: bool = False
    changed_files: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)


class ExecutionVerificationResponse(BaseModel):
    """Results for a controlled verification request."""

    execution_id: str
    workflow_id: str
    results: list[ExecutionVerificationResult] = Field(default_factory=list)


class ExecutionVerificationHistoryResponse(BaseModel):
    """Persisted verification history for one execution."""

    execution_id: str
    workflow_id: str
    verifications: list[ExecutionVerificationResult] = Field(default_factory=list)
