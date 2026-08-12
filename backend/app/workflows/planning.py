from app.agents.planner import PlannerAgent, PlannerAgentError
from app.agents.reviewer import ReviewerAgent, ReviewerAgentError
from app.models.planner import PlannerRequest
from app.models.planning_workflow import (
    FinalReviewedPlanSummary,
    PlanningWorkflowRequest,
    PlanningWorkflowResponse,
)
from app.models.reviewer import ReviewerRequest, ReviewerResponse
from app.models.workspace import WorkspaceContextSummary
from app.services.workspace import WorkspaceService


class PlanningWorkflowError(Exception):
    """
    Raised when the read-only planning workflow cannot complete safely.
    """


class PlanningWorkflow:
    """
    Orchestrates Planner Agent then Reviewer Agent in read-only mode.
    """

    def __init__(
        self,
        planner_agent: PlannerAgent,
        reviewer_agent: ReviewerAgent,
        workspace_service: WorkspaceService,
    ) -> None:
        self.planner_agent = planner_agent
        self.reviewer_agent = reviewer_agent
        self.workspace_service = workspace_service

    async def run(
        self,
        request: PlanningWorkflowRequest,
    ) -> PlanningWorkflowResponse:
        """
        Run the planning workflow without executing or modifying anything.
        """
        project_context = self._resolve_project_context(request)
        planner_model = self._agent_model(
            default_model=request.model,
            override_model=(
                request.model_overrides.planner
                if request.model_overrides is not None
                else None
            ),
        )
        reviewer_model = self._agent_model(
            default_model=request.model,
            override_model=(
                request.model_overrides.reviewer
                if request.model_overrides is not None
                else None
            ),
        )

        try:
            planner_output = await self.planner_agent.create_plan(
                PlannerRequest(
                    task=request.task,
                    project_context=project_context,
                    constraints=request.constraints,
                    model=planner_model,
                )
            )
        except PlannerAgentError as exc:
            raise PlanningWorkflowError(f"Planner failed: {exc}") from exc

        try:
            reviewer_output = await self.reviewer_agent.review_plan(
                ReviewerRequest(
                    task=request.task,
                    planner_output=planner_output,
                    project_context=project_context,
                    constraints=request.constraints,
                    model=reviewer_model,
                )
            )
        except ReviewerAgentError as exc:
            raise PlanningWorkflowError(f"Reviewer failed: {exc}") from exc

        return PlanningWorkflowResponse(
            planner_output=planner_output,
            reviewer_output=reviewer_output,
            final_reviewed_summary=self._final_summary(
                planner_output=planner_output,
                reviewer_output=reviewer_output,
            ),
        )

    def _resolve_project_context(
        self,
        request: PlanningWorkflowRequest,
    ) -> WorkspaceContextSummary | None:
        if request.project_context is not None:
            return request.project_context

        if request.workspace_path is None:
            return None

        return self.workspace_service.summarize_context(request.workspace_path)

    def _agent_model(
        self,
        *,
        default_model: str | None,
        override_model: str | None,
    ) -> str | None:
        return override_model or default_model

    def _final_summary(
        self,
        *,
        planner_output,
        reviewer_output: ReviewerResponse,
    ) -> FinalReviewedPlanSummary:
        required_changes = [
            *reviewer_output.missing_steps,
            *reviewer_output.recommended_improvements,
        ]
        risks = [
            *planner_output.risks,
            *reviewer_output.architecture_concerns,
            *reviewer_output.security_concerns,
            *reviewer_output.performance_concerns,
        ]
        tests_expected = [
            *planner_output.tests_verification_required,
            *reviewer_output.testing_gaps,
        ]
        user_approval_required = reviewer_output.approval_recommendation != "APPROVE"

        return FinalReviewedPlanSummary(
            final_recommendation=reviewer_output.approval_recommendation,
            required_changes_before_execution=self._unique(required_changes),
            risks=self._unique(risks),
            tests_expected=self._unique(tests_expected),
            user_approval_required=user_approval_required,
            summary=(
                "Planner output was reviewed. "
                f"Recommendation: {reviewer_output.approval_recommendation}."
            ),
        )

    def _unique(self, values: list[str]) -> list[str]:
        seen = set()
        unique_values = []

        for value in values:
            normalized_value = value.strip()

            if not normalized_value or normalized_value in seen:
                continue

            seen.add(normalized_value)
            unique_values.append(normalized_value)

        return unique_values
