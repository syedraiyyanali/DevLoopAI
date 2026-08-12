from typing import Literal

from pydantic import BaseModel, Field

from app.models.planner import PlannerResponse
from app.models.workspace import WorkspaceContextSummary


ReviewRecommendation = Literal["APPROVE", "APPROVE_WITH_CHANGES", "REJECT"]


class ReviewerRequest(BaseModel):
    """
    Request body for reviewing a Planner Agent output.
    """
    task: str = Field(..., min_length=1)
    planner_output: PlannerResponse
    project_context: WorkspaceContextSummary | None = None
    constraints: list[str] = Field(default_factory=list)
    model: str | None = None


class ReviewerResponse(BaseModel):
    """
    Structured read-only review of a Planner Agent output.
    """
    overall_assessment: str
    missing_steps: list[str] = Field(default_factory=list)
    incorrect_assumptions: list[str] = Field(default_factory=list)
    architecture_concerns: list[str] = Field(default_factory=list)
    security_concerns: list[str] = Field(default_factory=list)
    performance_concerns: list[str] = Field(default_factory=list)
    testing_gaps: list[str] = Field(default_factory=list)
    unnecessary_changes: list[str] = Field(default_factory=list)
    recommended_improvements: list[str] = Field(default_factory=list)
    approval_recommendation: ReviewRecommendation
    model: str
    raw_model_response: str | None = None


class ReviewerModelPayload(BaseModel):
    """
    Strict shape expected from the model before backend normalization.
    """
    overall_assessment: str
    missing_steps: list[str] = Field(default_factory=list)
    incorrect_assumptions: list[str] = Field(default_factory=list)
    architecture_concerns: list[str] = Field(default_factory=list)
    security_concerns: list[str] = Field(default_factory=list)
    performance_concerns: list[str] = Field(default_factory=list)
    testing_gaps: list[str] = Field(default_factory=list)
    unnecessary_changes: list[str] = Field(default_factory=list)
    recommended_improvements: list[str] = Field(default_factory=list)
    approval_recommendation: ReviewRecommendation
