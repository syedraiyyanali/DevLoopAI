import json
import re

from pydantic import ValidationError

from app.models.chat import ChatRequest
from app.models.planner import safe_context_payload
from app.models.reviewer import (
    ReviewerModelPayload,
    ReviewerRequest,
    ReviewerResponse,
)
from app.services.ollama import OllamaService, OllamaServiceError


class ReviewerAgentError(Exception):
    """
    Raised when the Reviewer Agent cannot safely produce a structured review.
    """


class ReviewerAgent:
    """
    Read-only review agent that critiques Planner Agent output.
    """

    def __init__(self, ollama_service: OllamaService) -> None:
        self.ollama_service = ollama_service

    async def review_plan(self, request: ReviewerRequest) -> ReviewerResponse:
        """
        Generate a structured review without executing the plan.
        """
        prompt = self._build_prompt(request)

        try:
            model_response = await self.ollama_service.generate_chat_response(
                ChatRequest(
                    message=prompt,
                    model=request.model,
                    response_format="json",
                )
            )
        except OllamaServiceError as exc:
            raise ReviewerAgentError(str(exc)) from exc

        model_payload = self._parse_model_payload(model_response.message)

        return ReviewerResponse(
            overall_assessment=model_payload.overall_assessment,
            missing_steps=model_payload.missing_steps,
            incorrect_assumptions=model_payload.incorrect_assumptions,
            architecture_concerns=model_payload.architecture_concerns,
            security_concerns=model_payload.security_concerns,
            performance_concerns=model_payload.performance_concerns,
            testing_gaps=model_payload.testing_gaps,
            unnecessary_changes=model_payload.unnecessary_changes,
            recommended_improvements=model_payload.recommended_improvements,
            approval_recommendation=model_payload.approval_recommendation,
            model=model_response.model,
        )

    def _build_prompt(self, request: ReviewerRequest) -> str:
        planner_output = request.planner_output.model_dump(
            exclude={"raw_model_response"}
        )
        context_payload = safe_context_payload(request.project_context)

        return (
            "You are DevLoopAI's read-only Reviewer Agent. "
            "Review the Planner Agent output only. Do not edit files, create files, "
            "run commands, execute the plan, commit changes, or claim you did.\n\n"
            "Return ONLY valid JSON with this exact object shape:\n"
            "{\n"
            '  "overall_assessment": "short assessment",\n'
            '  "missing_steps": ["missing step"],\n'
            '  "incorrect_assumptions": ["incorrect assumption"],\n'
            '  "architecture_concerns": ["concern"],\n'
            '  "security_concerns": ["concern"],\n'
            '  "performance_concerns": ["concern"],\n'
            '  "testing_gaps": ["gap"],\n'
            '  "unnecessary_changes": ["change"],\n'
            '  "recommended_improvements": ["improvement"],\n'
            '  "approval_recommendation": "APPROVE|APPROVE_WITH_CHANGES|REJECT"\n'
            "}\n\n"
            f"Original user task:\n{request.task.strip()}\n\n"
            f"Constraints:\n{json.dumps(request.constraints, ensure_ascii=True)}\n\n"
            "Planner output to review:\n"
            f"{json.dumps(planner_output, ensure_ascii=True)}\n\n"
            "Optional structured project context. This is a summary, not full project contents:\n"
            f"{json.dumps(context_payload, ensure_ascii=True)}"
        )

    def _parse_model_payload(self, raw_response: str) -> ReviewerModelPayload:
        try:
            payload = json.loads(raw_response)
        except json.JSONDecodeError:
            payload = self._extract_json_object(raw_response)

        try:
            return ReviewerModelPayload.model_validate(payload)
        except ValidationError as exc:
            raise ReviewerAgentError(
                "Reviewer model returned malformed review output"
            ) from exc

    def _extract_json_object(self, raw_response: str):
        match = re.search(r"\{.*\}", raw_response, flags=re.DOTALL)

        if match is None:
            raise ReviewerAgentError("Reviewer model did not return valid JSON")

        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ReviewerAgentError("Reviewer model did not return valid JSON") from exc
