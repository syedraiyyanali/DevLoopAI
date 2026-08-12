from pydantic import BaseModel, Field

from app.models.planner import PlannerResponse
from app.models.reviewer import ReviewerResponse
from app.models.validator import ValidationStatus, ValidatorResponse
from app.models.workspace import WorkspaceContextSummary


class PlanningWorkflowModelOverrides(BaseModel):
    """
    Optional model overrides for workflow agent calls.
    """
    planner: str | None = None
    reviewer: str | None = None
    validator: str | None = None


class PlanningWorkflowRequest(BaseModel):
    """
    Request body for the read-only planning workflow.
    """
    task: str = Field(..., min_length=1)
    workspace_path: str | None = None
    project_context: WorkspaceContextSummary | None = None
    constraints: list[str] = Field(default_factory=list)
    model: str | None = None
    model_overrides: PlanningWorkflowModelOverrides | None = None


class FinalReviewedPlanSummary(BaseModel):
    """
    Deterministic final execution decision derived from all read-only agents.
    """
    final_recommendation: ValidationStatus
    final_execution_readiness: str
    execution_ready: bool
    required_changes_before_execution: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    tests_expected: list[str] = Field(default_factory=list)
    user_approval_required: bool
    summary: str


class PlanningWorkflowResponse(BaseModel):
    """
    Complete read-only Planner -> Reviewer -> Validator workflow result.
    """
    planner_output: PlannerResponse
    reviewer_output: ReviewerResponse
    validator_output: ValidatorResponse
    final_reviewed_summary: FinalReviewedPlanSummary
