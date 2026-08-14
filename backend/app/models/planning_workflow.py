from typing import Literal

from pydantic import BaseModel, Field

from app.models.planner import PlannerResponse
from app.models.reviewer import ReviewerResponse
from app.models.validator import ValidationStatus, ValidatorResponse
from app.models.workspace import WorkspaceContextSummary


ApprovalStatus = Literal["PENDING_APPROVAL", "APPROVED", "REJECTED", "BLOCKED"]


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


class PlanningApprovalGate(BaseModel):
    """
    Read-only user approval state for the exact reviewed plan.
    """
    workflow_id: str
    approval_id: str
    approval_token: str
    plan_fingerprint: str
    status: ApprovalStatus
    approval_allowed: bool
    reason: str


class PlanningWorkflowResponse(BaseModel):
    """
    Complete read-only Planner -> Reviewer -> Validator workflow result.
    """
    planner_output: PlannerResponse
    reviewer_output: ReviewerResponse
    validator_output: ValidatorResponse
    final_reviewed_summary: FinalReviewedPlanSummary
    approval: PlanningApprovalGate


class PlanningApprovalActionRequest(BaseModel):
    """
    Request body for explicit approval/rejection of a reviewed plan.
    """
    approval_id: str = Field(..., min_length=1)
    approval_token: str = Field(..., min_length=1)
    plan_fingerprint: str = Field(..., min_length=1)


class PlanningApprovalActionResponse(BaseModel):
    """
    Response body after an explicit approval-gate action.
    """
    workflow_id: str
    approval_id: str
    plan_fingerprint: str
    status: ApprovalStatus
    approval_allowed: bool
    message: str


class PlanningWorkflowHistoryItem(BaseModel):
    """
    Token-free summary of a persisted planning workflow.
    """
    workflow_id: str
    user_task: str
    workspace_path: str | None = None
    plan_fingerprint: str
    approval_status: ApprovalStatus
    approval_allowed: bool
    approval_reason: str
    created_at: str
    updated_at: str
    approval_decided_at: str | None = None


class PlanningWorkflowHistoryListResponse(BaseModel):
    """
    Persisted planning workflow history list.
    """
    workflows: list[PlanningWorkflowHistoryItem] = Field(default_factory=list)


class PlanningWorkflowHistoryRecord(PlanningWorkflowHistoryItem):
    """
    Full token-free persisted planning workflow audit record.
    """
    planner_output: PlannerResponse
    reviewer_output: ReviewerResponse
    validator_output: ValidatorResponse
    final_reviewed_summary: FinalReviewedPlanSummary
