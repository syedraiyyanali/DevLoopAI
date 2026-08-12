import json
import re

from pydantic import ValidationError

from app.models.chat import ChatRequest
from app.models.planner import (
    PlannerModelPayload,
    PlannerProjectContext,
    PlannerRequest,
    PlannerResponse,
    safe_context_payload,
)
from app.models.workspace import WorkspaceContextSummary
from app.services.ollama import OllamaService, OllamaServiceError
from app.services.workspace import WorkspaceService


class PlannerAgentError(Exception):
    """
    Raised when the Planner Agent cannot safely produce a structured plan.
    """


class PlannerAgent:
    """
    Read-only planning agent that turns a task and project context into a plan.
    """

    def __init__(
        self,
        ollama_service: OllamaService,
        workspace_service: WorkspaceService,
    ) -> None:
        self.ollama_service = ollama_service
        self.workspace_service = workspace_service

    async def create_plan(self, request: PlannerRequest) -> PlannerResponse:
        """
        Generate a structured plan without editing files or running commands.
        """
        project_context = request.project_context

        if project_context is None and request.workspace_path is not None:
            project_context = self.workspace_service.summarize_context(
                request.workspace_path,
            )

        prompt = self._build_prompt(request, project_context)

        try:
            model_response = await self.ollama_service.generate_chat_response(
                ChatRequest(
                    message=prompt,
                    model=request.model,
                    response_format="json",
                )
            )
        except OllamaServiceError as exc:
            raise PlannerAgentError(str(exc)) from exc

        model_payload = self._parse_model_payload(model_response.message)

        return PlannerResponse(
            task_summary=model_payload.task_summary,
            assumptions=model_payload.assumptions,
            detected_project_context=self._planner_context(project_context),
            implementation_steps=model_payload.implementation_steps,
            files_likely_to_change=model_payload.files_likely_to_change,
            tests_verification_required=model_payload.tests_verification_required,
            risks=model_payload.risks,
            dependencies_or_user_input_needed=(
                model_payload.dependencies_or_user_input_needed
            ),
            model=model_response.model,
        )

    def _build_prompt(
        self,
        request: PlannerRequest,
        project_context: WorkspaceContextSummary | None,
    ) -> str:
        context_payload = safe_context_payload(project_context)
        constraints = request.constraints or []

        return (
            "You are DevLoopAI's read-only Planner Agent. "
            "Create an implementation plan only. Do not edit files, run commands, "
            "commit changes, or claim you executed anything.\n\n"
            "Return ONLY valid JSON with this exact object shape:\n"
            "{\n"
            '  "task_summary": "short summary",\n'
            '  "assumptions": ["assumption"],\n'
            '  "implementation_steps": ["step"],\n'
            '  "files_likely_to_change": ["path"],\n'
            '  "tests_verification_required": ["test"],\n'
            '  "risks": ["risk"],\n'
            '  "dependencies_or_user_input_needed": ["input needed"]\n'
            "}\n\n"
            f"User task:\n{request.task.strip()}\n\n"
            f"Constraints:\n{json.dumps(constraints, ensure_ascii=True)}\n\n"
            "Structured project context. This is a summary, not full project contents:\n"
            f"{json.dumps(context_payload, ensure_ascii=True)}"
        )

    def _parse_model_payload(self, raw_response: str) -> PlannerModelPayload:
        try:
            payload = json.loads(raw_response)
        except json.JSONDecodeError:
            payload = self._extract_json_object(raw_response)

        try:
            return PlannerModelPayload.model_validate(payload)
        except ValidationError as exc:
            raise PlannerAgentError(
                "Planner model returned malformed plan output"
            ) from exc

    def _extract_json_object(self, raw_response: str):
        match = re.search(r"\{.*\}", raw_response, flags=re.DOTALL)

        if match is None:
            raise PlannerAgentError("Planner model did not return valid JSON")

        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise PlannerAgentError("Planner model did not return valid JSON") from exc

    def _planner_context(
        self,
        project_context: WorkspaceContextSummary | None,
    ) -> PlannerProjectContext:
        if project_context is None:
            return PlannerProjectContext()

        return PlannerProjectContext(
            workspace_name=project_context.workspace.name,
            project_types=project_context.project_types,
            frameworks=project_context.frameworks,
            languages=project_context.detected_languages,
        )
