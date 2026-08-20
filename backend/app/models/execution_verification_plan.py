from typing import Literal

from pydantic import BaseModel, Field


VerificationPlanTier = Literal["required", "recommended", "not_applicable"]


class VerificationPlanCheck(BaseModel):
    """Deterministic policy decision for one allowlisted verification type."""

    verification_type: str
    command_identity: str
    tier: VerificationPlanTier
    applicable: bool
    selected_by_default: bool
    reason: str
    skip_reason: str | None = None


class ExecutionVerificationPlanResponse(BaseModel):
    """Read-only verification strategy for an execution."""

    execution_id: str
    workflow_id: str
    workspace_path: str
    changed_files: list[str] = Field(default_factory=list)
    required_verification_types: list[str] = Field(default_factory=list)
    recommended_verification_types: list[str] = Field(default_factory=list)
    skipped_verification_types: list[str] = Field(default_factory=list)
    checks: list[VerificationPlanCheck] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
