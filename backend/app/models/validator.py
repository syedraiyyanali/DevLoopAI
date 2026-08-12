from typing import Literal

from pydantic import BaseModel, Field

from app.models.planner import PlannerResponse
from app.models.reviewer import ReviewerResponse
from app.models.workspace import WorkspaceContextSummary


ValidationStatus = Literal["READY", "READY_WITH_WARNINGS", "BLOCKED"]


class ValidatorRequest(BaseModel):
    """
    Request body for validating a reviewed implementation plan.
    """
    task: str = Field(..., min_length=1)
    planner_output: PlannerResponse
    reviewer_output: ReviewerResponse
    project_context: WorkspaceContextSummary | None = None
    constraints: list[str] = Field(default_factory=list)
    model: str | None = None


class ValidatorResponse(BaseModel):
    """
    Structured read-only validation of a reviewed plan.
    """
    overall_validation_status: ValidationStatus
    plan_completeness: list[str] = Field(default_factory=list)
    file_path_validity: list[str] = Field(default_factory=list)
    dependency_concerns: list[str] = Field(default_factory=list)
    environment_tool_requirements: list[str] = Field(default_factory=list)
    security_concerns: list[str] = Field(default_factory=list)
    destructive_operation_warnings: list[str] = Field(default_factory=list)
    missing_user_information: list[str] = Field(default_factory=list)
    test_verification_readiness: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    final_execution_readiness: str
    model: str
    raw_model_response: str | None = None


class ValidatorModelPayload(BaseModel):
    """
    Strict shape expected from the model before backend normalization.
    """
    plan_completeness: list[str] = Field(default_factory=list)
    dependency_concerns: list[str] = Field(default_factory=list)
    environment_tool_requirements: list[str] = Field(default_factory=list)
    security_concerns: list[str] = Field(default_factory=list)
    missing_user_information: list[str] = Field(default_factory=list)
    test_verification_readiness: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    final_execution_readiness: str
