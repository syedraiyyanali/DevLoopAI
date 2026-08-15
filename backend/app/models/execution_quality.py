from typing import Literal

from pydantic import BaseModel, Field


QualityStatus = Literal[
    "QUALITY_PASSED",
    "QUALITY_FAILED",
    "QUALITY_INCOMPLETE",
    "ROLLED_BACK",
    "BLOCKED",
]


class VerificationSummary(BaseModel):
    """Deterministic summary of persisted verification outcomes."""

    verification_type: str
    latest_status: str | None = None
    runs: int = 0
    required: bool = False


class ExecutionQualityResponse(BaseModel):
    """Authoritative current quality gate result for one persisted execution."""

    execution_id: str
    workflow_id: str
    quality_status: QualityStatus
    execution_status: str
    required_verification_types: list[str] = Field(default_factory=list)
    verification_summary: list[VerificationSummary] = Field(default_factory=list)
    passed_checks: list[str] = Field(default_factory=list)
    failed_checks: list[str] = Field(default_factory=list)
    missing_checks: list[str] = Field(default_factory=list)
    skipped_checks: list[str] = Field(default_factory=list)
    rollback_status: str
    rollback_recommended: bool = False
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    quality_timestamp: str

