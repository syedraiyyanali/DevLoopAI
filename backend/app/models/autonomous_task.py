from typing import Literal

from pydantic import BaseModel, Field

from app.models.planning_workflow import PlanningWorkflowRequest, PlanningWorkflowResponse
from app.models.task_execution import TaskExecutionSession


AutonomousTaskState = Literal[
    "ANALYZING",
    "PLANNING",
    "AWAITING_PLAN_APPROVAL",
    "PREPARING_EXECUTION",
    "AWAITING_EXECUTION_APPROVAL",
    "VERIFYING",
    "QUALITY_PASSED",
    "QUALITY_FAILED",
    "RETRY_PREPARING",
    "RETRY_LIMIT_REACHED",
    "BLOCKED",
    "ROLLED_BACK",
]


class AutonomousTaskStartRequest(PlanningWorkflowRequest):
    """Start a bounded autonomous task session with read-only planning."""


class AutonomousTaskActionRequest(BaseModel):
    """Optional state guard for resumable autonomous-session actions."""

    expected_state: AutonomousTaskState | None = None


class AutonomousTaskSession(BaseModel):
    """Persisted bounded autonomous orchestration audit."""

    autonomous_session_id: str
    state: AutonomousTaskState
    current_stage: str
    user_task: str
    workspace_path: str | None = None
    workflow_id: str | None = None
    plan_fingerprint: str | None = None
    task_execution_id: str | None = None
    current_attempt: int = 0
    max_attempts: int = 3
    planning_result: PlanningWorkflowResponse | None = None
    task_execution: TaskExecutionSession | None = None
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    progress: list[str] = Field(default_factory=list)
    waiting_for: str | None = None
    mutation_performed_by_autonomous_mode: bool = False
    created_at: str
    updated_at: str
    message: str
