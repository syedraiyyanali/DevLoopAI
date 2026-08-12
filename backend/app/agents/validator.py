import json
import re
from pathlib import Path

from pydantic import ValidationError

from app.models.chat import ChatRequest
from app.models.planner import safe_context_payload
from app.models.validator import (
    ValidationStatus,
    ValidatorModelPayload,
    ValidatorRequest,
    ValidatorResponse,
)
from app.services.ollama import OllamaService, OllamaServiceError
from app.services.workspace import WorkspaceAccessError, WorkspaceService


class ValidatorAgentError(Exception):
    """
    Raised when the Validator Agent cannot safely produce a validation.
    """


class ValidatorAgent:
    """
    Read-only validator for final reviewed implementation plans.
    """

    destructive_patterns = (
        "delete ",
        "remove ",
        "rm -rf",
        "rmdir",
        "del ",
        "drop table",
        "truncate table",
        "git reset --hard",
        "force push",
        "force-push",
        "delete branch",
    )
    dependency_patterns = (
        "install ",
        "add dependency",
        "new package",
        "pip install",
        "npm install",
        "pnpm add",
        "yarn add",
    )
    tool_markers = {
        "pytest": "pytest",
        "eslint": "ESLint",
        "next build": "Next.js build",
        "npm run build": "Next.js build",
        "npm run lint": "ESLint",
        "uvicorn": "Uvicorn",
    }

    def __init__(
        self,
        ollama_service: OllamaService,
        workspace_service: WorkspaceService,
    ) -> None:
        self.ollama_service = ollama_service
        self.workspace_service = workspace_service

    async def validate_plan(self, request: ValidatorRequest) -> ValidatorResponse:
        """
        Validate a reviewed plan without editing files or running commands.
        """
        deterministic = self._deterministic_checks(request)
        prompt = self._build_prompt(request, deterministic)

        try:
            model_response = await self.ollama_service.generate_chat_response(
                ChatRequest(
                    message=prompt,
                    model=request.model,
                    response_format="json",
                )
            )
        except OllamaServiceError as exc:
            raise ValidatorAgentError(str(exc)) from exc

        model_payload = self._parse_model_payload(model_response.message)
        merged = self._merge_validation(deterministic, model_payload)
        status = self._status_from_merged(request, merged)

        return ValidatorResponse(
            overall_validation_status=status,
            plan_completeness=merged["plan_completeness"],
            file_path_validity=merged["file_path_validity"],
            dependency_concerns=merged["dependency_concerns"],
            environment_tool_requirements=merged["environment_tool_requirements"],
            security_concerns=merged["security_concerns"],
            destructive_operation_warnings=merged["destructive_operation_warnings"],
            missing_user_information=merged["missing_user_information"],
            test_verification_readiness=merged["test_verification_readiness"],
            blockers=merged["blockers"],
            final_execution_readiness=self._final_readiness(status, model_payload),
            model=model_response.model,
        )

    def _deterministic_checks(self, request: ValidatorRequest) -> dict[str, list[str]]:
        checks: dict[str, list[str]] = {
            "plan_completeness": [],
            "file_path_validity": [],
            "dependency_concerns": [],
            "environment_tool_requirements": [],
            "security_concerns": [],
            "destructive_operation_warnings": [],
            "missing_user_information": [],
            "test_verification_readiness": [],
            "blockers": [],
        }

        if not request.planner_output.implementation_steps:
            checks["blockers"].append("Planner output has no implementation steps.")
        else:
            checks["plan_completeness"].append("Planner output includes implementation steps.")

        if not request.planner_output.files_likely_to_change:
            checks["missing_user_information"].append(
                "Planner output does not identify files likely to change."
            )

        if not request.planner_output.tests_verification_required:
            checks["blockers"].append("Planner output has no test or verification steps.")
        else:
            checks["test_verification_readiness"].append(
                "Planner output includes test or verification steps."
            )

        if request.reviewer_output.approval_recommendation == "REJECT":
            checks["blockers"].append("Reviewer rejected the planner output.")

        checks["file_path_validity"].extend(self._validate_file_paths(request))
        checks["dependency_concerns"].extend(self._detect_dependency_concerns(request))
        checks["environment_tool_requirements"].extend(self._detect_tool_requirements(request))
        checks["destructive_operation_warnings"].extend(
            self._detect_destructive_operations(request)
        )
        checks["security_concerns"].extend(request.reviewer_output.security_concerns)
        checks["missing_user_information"].extend(
            request.planner_output.dependencies_or_user_input_needed
        )
        checks["test_verification_readiness"].extend(request.reviewer_output.testing_gaps)

        return checks

    def _validate_file_paths(self, request: ValidatorRequest) -> list[str]:
        file_notes: list[str] = []
        context = request.project_context

        if context is None:
            return ["Project context was not provided; file paths could not be checked."]

        root = Path(context.workspace.root_path).resolve()

        if not root.exists() or not root.is_dir():
            return ["Project context root is unavailable; file paths could not be checked."]

        for file_path in request.planner_output.files_likely_to_change:
            normalized_path = file_path.strip()

            if not normalized_path:
                file_notes.append("Planner output includes an empty file path.")
                continue

            if Path(normalized_path).is_absolute():
                file_notes.append(f"{normalized_path}: absolute paths should be avoided.")
                continue

            try:
                target = self.workspace_service._resolve_child_path(root, normalized_path)
            except WorkspaceAccessError:
                file_notes.append(f"{normalized_path}: blocked by workspace safety rules.")
                continue

            if target.exists():
                file_notes.append(f"{normalized_path}: path exists.")
            elif target.parent.exists():
                file_notes.append(
                    f"{normalized_path}: file does not exist, but parent folder exists."
                )
            else:
                file_notes.append(f"{normalized_path}: parent folder does not exist.")

        return file_notes

    def _detect_dependency_concerns(self, request: ValidatorRequest) -> list[str]:
        text = self._combined_plan_text(request)
        concerns = []

        if any(pattern in text for pattern in self.dependency_patterns):
            concerns.append(
                "Plan may require dependency changes; user approval is needed before installation."
            )

        if request.project_context is None:
            concerns.append("Project context was not provided; dependencies are unknown.")

        return concerns

    def _detect_tool_requirements(self, request: ValidatorRequest) -> list[str]:
        text = self._combined_plan_text(request)
        tools = [
            display_name
            for marker, display_name in self.tool_markers.items()
            if marker in text
        ]

        if tools:
            return [f"Expected verification/tooling mentioned: {', '.join(sorted(set(tools)))}."]

        return ["No specific verification tooling was detected in the reviewed plan."]

    def _detect_destructive_operations(self, request: ValidatorRequest) -> list[str]:
        text = self._combined_plan_text(request)

        return [
            f"Potentially destructive operation mentioned: {pattern.strip()}."
            for pattern in self.destructive_patterns
            if pattern in text
        ]

    def _combined_plan_text(self, request: ValidatorRequest) -> str:
        payload = {
            "task": request.task,
            "planner": request.planner_output.model_dump(),
            "reviewer": request.reviewer_output.model_dump(),
            "constraints": request.constraints,
        }

        return json.dumps(payload, ensure_ascii=True).lower()

    def _build_prompt(
        self,
        request: ValidatorRequest,
        deterministic: dict[str, list[str]],
    ) -> str:
        return (
            "You are DevLoopAI's read-only Validator Agent. "
            "Validate the reviewed implementation plan before any future execution. "
            "Do not edit files, create files, run commands, install dependencies, "
            "commit changes, or execute the plan.\n\n"
            "Return ONLY valid JSON with this exact object shape:\n"
            "{\n"
            '  "plan_completeness": ["note"],\n'
            '  "dependency_concerns": ["concern"],\n'
            '  "environment_tool_requirements": ["requirement"],\n'
            '  "security_concerns": ["concern"],\n'
            '  "missing_user_information": ["info needed"],\n'
            '  "test_verification_readiness": ["note"],\n'
            '  "blockers": ["blocker"],\n'
            '  "final_execution_readiness": "short readiness summary"\n'
            "}\n\n"
            f"Original task:\n{request.task.strip()}\n\n"
            "Planner output:\n"
            f"{json.dumps(request.planner_output.model_dump(exclude={'raw_model_response'}), ensure_ascii=True)}\n\n"
            "Reviewer output:\n"
            f"{json.dumps(request.reviewer_output.model_dump(exclude={'raw_model_response'}), ensure_ascii=True)}\n\n"
            f"Constraints:\n{json.dumps(request.constraints, ensure_ascii=True)}\n\n"
            "Project context summary:\n"
            f"{json.dumps(safe_context_payload(request.project_context), ensure_ascii=True)}\n\n"
            "Deterministic checks already completed by Python:\n"
            f"{json.dumps(deterministic, ensure_ascii=True)}"
        )

    def _parse_model_payload(self, raw_response: str) -> ValidatorModelPayload:
        try:
            payload = json.loads(raw_response)
        except json.JSONDecodeError:
            payload = self._extract_json_object(raw_response)

        try:
            return ValidatorModelPayload.model_validate(payload)
        except ValidationError as exc:
            raise ValidatorAgentError(
                "Validator model returned malformed validation output"
            ) from exc

    def _extract_json_object(self, raw_response: str):
        match = re.search(r"\{.*\}", raw_response, flags=re.DOTALL)

        if match is None:
            raise ValidatorAgentError("Validator model did not return valid JSON")

        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ValidatorAgentError("Validator model did not return valid JSON") from exc

    def _merge_validation(
        self,
        deterministic: dict[str, list[str]],
        model_payload: ValidatorModelPayload,
    ) -> dict[str, list[str]]:
        merged = {key: list(value) for key, value in deterministic.items()}
        merged["plan_completeness"].extend(model_payload.plan_completeness)
        merged["dependency_concerns"].extend(model_payload.dependency_concerns)
        merged["environment_tool_requirements"].extend(
            model_payload.environment_tool_requirements
        )
        merged["security_concerns"].extend(model_payload.security_concerns)
        merged["missing_user_information"].extend(model_payload.missing_user_information)
        merged["test_verification_readiness"].extend(
            model_payload.test_verification_readiness
        )
        merged["blockers"].extend(model_payload.blockers)

        return {key: self._unique(value) for key, value in merged.items()}

    def _status_from_merged(
        self,
        request: ValidatorRequest,
        merged: dict[str, list[str]],
    ) -> ValidationStatus:
        if merged["blockers"]:
            return "BLOCKED"

        if (
            request.reviewer_output.approval_recommendation == "REJECT"
            or merged["destructive_operation_warnings"]
        ):
            return "BLOCKED"

        if request.reviewer_output.approval_recommendation == "APPROVE_WITH_CHANGES":
            return "READY_WITH_WARNINGS"

        if (
            merged["dependency_concerns"]
            or merged["security_concerns"]
            or merged["missing_user_information"]
            or self._has_file_path_warnings(merged["file_path_validity"])
        ):
            return "READY_WITH_WARNINGS"

        return "READY"

    def _has_file_path_warnings(self, file_path_validity: list[str]) -> bool:
        warning_markers = (
            "could not be checked",
            "does not exist",
            "blocked",
            "absolute paths",
            "empty file path",
        )

        return any(
            any(marker in note for marker in warning_markers)
            for note in file_path_validity
        )

    def _final_readiness(
        self,
        status: ValidationStatus,
        model_payload: ValidatorModelPayload,
    ) -> str:
        if status == "READY":
            return "Reviewed plan is ready for future execution after normal user approval."

        if status == "READY_WITH_WARNINGS":
            return "Reviewed plan needs warnings addressed before future execution."

        if model_payload.final_execution_readiness:
            return model_payload.final_execution_readiness

        return "Reviewed plan is blocked and must not be executed."

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
