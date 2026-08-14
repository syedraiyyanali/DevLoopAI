from app.agents.planner import PlannerAgent, PlannerAgentError
from app.agents.reviewer import ReviewerAgent, ReviewerAgentError
from app.agents.validator import ValidatorAgent, ValidatorAgentError
from app.models.planner import PlannerRequest, PlannerResponse
from app.models.planning_workflow import (
    FinalReviewedPlanSummary,
    PlanningWorkflowRequest,
    PlanningWorkflowResponse,
)
from app.models.reviewer import ReviewerRequest, ReviewerResponse
from app.models.validator import ValidationStatus, ValidatorRequest, ValidatorResponse
from app.services.planning_approval import PlanningApprovalStore
from app.models.workspace import WorkspaceContextSummary
from app.services.workspace import WorkspaceService


class PlanningWorkflowError(Exception):
    """
    Raised when the read-only planning workflow cannot complete safely.
    """


class PlanningWorkflow:
    """
    Orchestrates Planner, Reviewer, and Validator agents in read-only mode.
    """

    def __init__(
        self,
        planner_agent: PlannerAgent,
        reviewer_agent: ReviewerAgent,
        validator_agent: ValidatorAgent,
        workspace_service: WorkspaceService,
        approval_store: PlanningApprovalStore,
    ) -> None:
        self.planner_agent = planner_agent
        self.reviewer_agent = reviewer_agent
        self.validator_agent = validator_agent
        self.workspace_service = workspace_service
        self.approval_store = approval_store

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
        validator_model = self._agent_model(
            default_model=request.model,
            override_model=(
                request.model_overrides.validator
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

        try:
            validator_output = await self.validator_agent.validate_plan(
                ValidatorRequest(
                    task=request.task,
                    planner_output=planner_output,
                    reviewer_output=reviewer_output,
                    project_context=project_context,
                    constraints=request.constraints,
                    model=validator_model,
                )
            )
        except ValidatorAgentError as exc:
            raise PlanningWorkflowError(f"Validator failed: {exc}") from exc

        final_reviewed_summary = self._final_summary(
            planner_output=planner_output,
            reviewer_output=reviewer_output,
            validator_output=validator_output,
        )

        return PlanningWorkflowResponse(
            planner_output=planner_output,
            reviewer_output=reviewer_output,
            validator_output=validator_output,
            final_reviewed_summary=final_reviewed_summary,
            approval=self.approval_store.create_gate(
                task=request.task,
                planner_output=planner_output,
                reviewer_output=reviewer_output,
                validator_output=validator_output,
                final_reviewed_summary=final_reviewed_summary,
                blockers=final_reviewed_summary.blockers,
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
        planner_output: PlannerResponse,
        reviewer_output: ReviewerResponse,
        validator_output: ValidatorResponse,
    ) -> FinalReviewedPlanSummary:
        final_status = self._final_status(
            reviewer_output=reviewer_output,
            validator_output=validator_output,
        )
        required_changes = [
            *reviewer_output.missing_steps,
            *reviewer_output.recommended_improvements,
            *validator_output.missing_user_information,
            *validator_output.blockers,
        ]
        blockers = [
            *validator_output.blockers,
            *(
                ["Reviewer rejected the planner output."]
                if reviewer_output.approval_recommendation == "REJECT"
                else []
            ),
        ]
        warnings = [
            *reviewer_output.incorrect_assumptions,
            *reviewer_output.architecture_concerns,
            *reviewer_output.security_concerns,
            *reviewer_output.performance_concerns,
            *reviewer_output.testing_gaps,
            *validator_output.dependency_concerns,
            *validator_output.environment_tool_requirements,
            *validator_output.security_concerns,
            *validator_output.destructive_operation_warnings,
            *validator_output.missing_user_information,
            *self._file_path_warnings(validator_output.file_path_validity),
        ]
        risks = [
            *planner_output.risks,
            *reviewer_output.architecture_concerns,
            *reviewer_output.security_concerns,
            *reviewer_output.performance_concerns,
            *validator_output.dependency_concerns,
            *validator_output.security_concerns,
            *validator_output.destructive_operation_warnings,
        ]
        tests_expected = [
            *planner_output.tests_verification_required,
            *reviewer_output.testing_gaps,
            *validator_output.test_verification_readiness,
        ]
        execution_ready = False
        user_approval_required = final_status != "BLOCKED"

        return FinalReviewedPlanSummary(
            final_recommendation=final_status,
            final_execution_readiness=self._final_execution_readiness(
                status=final_status,
                validator_output=validator_output,
            ),
            execution_ready=execution_ready,
            required_changes_before_execution=self._unique(required_changes),
            blockers=self._unique(blockers),
            warnings=self._unique(warnings),
            risks=self._unique(risks),
            tests_expected=self._unique(tests_expected),
            user_approval_required=user_approval_required,
            summary=(
                "Planner, reviewer, and validator completed. "
                f"Final execution readiness: {final_status}."
            ),
        )

    def _final_status(
        self,
        *,
        reviewer_output: ReviewerResponse,
        validator_output: ValidatorResponse,
    ) -> ValidationStatus:
        if reviewer_output.approval_recommendation == "REJECT":
            return "BLOCKED"

        return validator_output.overall_validation_status

    def _final_execution_readiness(
        self,
        *,
        status: ValidationStatus,
        validator_output: ValidatorResponse,
    ) -> str:
        if status == "BLOCKED":
            return "Execution is blocked; do not execute until blockers are resolved."

        return validator_output.final_execution_readiness

    def _file_path_warnings(self, file_path_validity: list[str]) -> list[str]:
        warning_markers = (
            "could not be checked",
            "does not exist",
            "blocked",
            "absolute paths",
            "empty file path",
        )

        return [
            note
            for note in file_path_validity
            if any(marker in note for marker in warning_markers)
        ]

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
