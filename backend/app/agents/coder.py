import json
import re

from pydantic import ValidationError

from app.models.chat import ChatRequest
from app.models.coder import (
    CoderDryRunModelPayload,
    CoderDryRunRequest,
    CoderDryRunResponse,
)
from app.models.execution_handoff import ExecutionHandoffRequest, ExecutionHandoffResponse
from app.services.execution_handoff import (
    ExecutionHandoffBlockedError,
    ExecutionHandoffService,
)
from app.services.ollama import OllamaService, OllamaServiceError


class CoderDryRunError(Exception):
    """
    Raised when the Coding Agent dry-run cannot safely complete.
    """


class CoderDryRunBlockedError(CoderDryRunError):
    """
    Raised when the submitted handoff or model proposal is unsafe.
    """


class CoderDryRunAgent:
    """
    Zero-write Coding Agent simulation based on an approved handoff contract.
    """

    def __init__(
        self,
        *,
        ollama_service: OllamaService,
        handoff_service: ExecutionHandoffService,
    ) -> None:
        self.ollama_service = ollama_service
        self.handoff_service = handoff_service

    async def dry_run(self, request: CoderDryRunRequest) -> CoderDryRunResponse:
        """
        Simulate future coding work without writing files or running commands.
        """
        canonical_handoff = self.handoff_service.create_handoff(
            request=ExecutionHandoffRequest(workflow_id=request.handoff.workflow_id)
        )
        self._validate_handoff(
            submitted=request.handoff,
            canonical=canonical_handoff,
        )

        prompt = self._build_prompt(canonical_handoff)

        try:
            model_response = await self.ollama_service.generate_chat_response(
                ChatRequest(
                    message=prompt,
                    model=request.model,
                    response_format="json",
                )
            )
        except OllamaServiceError as exc:
            raise CoderDryRunError(str(exc)) from exc

        model_payload = self._parse_model_payload(model_response.message)
        self._validate_model_payload(
            handoff=canonical_handoff,
            payload=model_payload,
        )

        return CoderDryRunResponse(
            workflow_id=canonical_handoff.workflow_id,
            approved_plan_fingerprint=canonical_handoff.approved_plan_fingerprint,
            workspace_path=canonical_handoff.workspace_path,
            files_would_modify=self._unique(model_payload.files_to_modify),
            files_would_create=self._unique(model_payload.files_to_create),
            files_would_delete=[],
            intended_operations=model_payload.intended_operations,
            proposed_code_change_summary=model_payload.proposed_code_change_summary,
            dependencies_required=self._unique(model_payload.dependencies_required),
            tests_to_run=self._unique(
                [*canonical_handoff.expected_tests, *model_payload.tests_to_run]
            ),
            rollback_backup_plan=self._unique(
                [
                    *canonical_handoff.rollback_backup_requirements.requirements,
                    *model_payload.rollback_backup_plan,
                ]
            ),
            warnings=self._unique([*canonical_handoff.warnings, *model_payload.warnings]),
            blockers=[],
            model=model_response.model,
            execution_performed=False,
            mutation_capabilities_enabled=False,
            message="Dry-run completed. No files were written and no commands were run.",
        )

    def _validate_handoff(
        self,
        *,
        submitted: ExecutionHandoffResponse,
        canonical: ExecutionHandoffResponse,
    ) -> None:
        if submitted.workflow_id != canonical.workflow_id:
            raise CoderDryRunBlockedError("Handoff workflow ID does not match.")

        if submitted.approved_plan_fingerprint != canonical.approved_plan_fingerprint:
            raise CoderDryRunBlockedError("Handoff fingerprint is stale or invalid.")

        if submitted.workspace_path != canonical.workspace_path:
            raise CoderDryRunBlockedError("Handoff workspace path is invalid.")

        if submitted.preflight_result.status != "READY_FOR_EXECUTION":
            raise CoderDryRunBlockedError("Handoff preflight is not ready for execution.")

        if submitted.preflight_result.fingerprint.matches is not True:
            raise CoderDryRunBlockedError("Handoff fingerprint verification failed.")

        if submitted.user_approval_metadata.approval_status != "APPROVED":
            raise CoderDryRunBlockedError("Handoff workflow is not approved.")

        if submitted.allowed_files != canonical.allowed_files:
            raise CoderDryRunBlockedError("Handoff allowed files were changed.")

        if submitted.allowed_operation_types != canonical.allowed_operation_types:
            raise CoderDryRunBlockedError("Handoff allowed operation types were changed.")

    def _validate_model_payload(
        self,
        *,
        handoff: ExecutionHandoffResponse,
        payload: CoderDryRunModelPayload,
    ) -> None:
        allowed_files = set(handoff.allowed_files)
        proposed_paths = [
            *payload.files_to_modify,
            *payload.files_to_create,
            *payload.files_to_delete,
            *[operation.relative_path for operation in payload.intended_operations],
        ]

        blocked_paths = sorted(
            {
                path
                for path in proposed_paths
                if path not in allowed_files
            }
        )

        if blocked_paths:
            raise CoderDryRunBlockedError(
                "Model proposed paths outside the approved handoff: "
                + ", ".join(blocked_paths)
            )

        if payload.files_to_delete:
            raise CoderDryRunBlockedError("Dry-run cannot propose file deletion.")

        allowed_operations = set(handoff.allowed_operation_types)
        unsupported_operations = sorted(
            {
                operation.operation_type
                for operation in payload.intended_operations
                if operation.operation_type not in allowed_operations
            }
        )

        if unsupported_operations:
            raise CoderDryRunBlockedError(
                "Model proposed unsupported operations: "
                + ", ".join(unsupported_operations)
            )

        if payload.blockers:
            raise CoderDryRunBlockedError(
                "Model reported blockers: " + " ".join(payload.blockers)
            )

    def _build_prompt(self, handoff: ExecutionHandoffResponse) -> str:
        safe_handoff_payload = handoff.model_dump(mode="json")

        return (
            "You are DevLoopAI's zero-write Coding Agent dry-run simulator. "
            "Propose what a future Coding Agent would do, but do not claim you "
            "edited files, created files, deleted files, ran commands, installed "
            "dependencies, committed, pushed, or executed anything.\n\n"
            "Return ONLY valid JSON with this exact object shape:\n"
            "{\n"
            '  "files_to_modify": ["path"],\n'
            '  "files_to_create": ["path"],\n'
            '  "files_to_delete": [],\n'
            '  "intended_operations": [\n'
            "    {\n"
            '      "operation_type": "modify_text_file",\n'
            '      "relative_path": "path",\n'
            '      "description": "exact intended change",\n'
            '      "rationale": "why this is needed"\n'
            "    }\n"
            "  ],\n"
            '  "proposed_code_change_summary": "summary",\n'
            '  "dependencies_required": ["dependency"],\n'
            '  "tests_to_run": ["test"],\n'
            '  "rollback_backup_plan": ["step"],\n'
            '  "warnings": ["warning"],\n'
            '  "blockers": []\n'
            "}\n\n"
            "Rules:\n"
            "- Use only allowed files from the handoff.\n"
            "- Use only allowed operation types from the handoff.\n"
            "- Do not propose deleting files.\n"
            "- Do not request command execution or dependency installation.\n"
            "- Keep mutation capabilities disabled.\n\n"
            "Approved handoff contract:\n"
            f"{json.dumps(safe_handoff_payload, ensure_ascii=True)}"
        )

    def _parse_model_payload(self, raw_response: str) -> CoderDryRunModelPayload:
        try:
            payload = json.loads(raw_response)
        except json.JSONDecodeError:
            payload = self._extract_json_object(raw_response)

        payload = self._normalize_model_payload(payload)

        try:
            return CoderDryRunModelPayload.model_validate(payload)
        except ValidationError as exc:
            raise CoderDryRunError(
                "Coder dry-run model returned malformed output"
            ) from exc

    def _normalize_model_payload(self, payload):
        if not isinstance(payload, dict):
            return payload

        normalized = dict(payload)
        list_fields = (
            "files_to_modify",
            "files_to_create",
            "files_to_delete",
            "dependencies_required",
            "tests_to_run",
            "rollback_backup_plan",
            "warnings",
            "blockers",
        )

        for field in list_fields:
            normalized[field] = self._normalize_string_list(normalized.get(field))

        operations = normalized.get("intended_operations")

        if not isinstance(operations, list):
            operations = []

        normalized["intended_operations"] = [
            self._normalize_operation(operation)
            for operation in operations
            if isinstance(operation, dict)
        ]

        return normalized

    def _normalize_string_list(self, value) -> list[str]:
        if value is None:
            return []

        if isinstance(value, str):
            return [] if value.strip().lower() in {"none", "n/a"} else [value]

        if isinstance(value, list):
            return [item for item in value if isinstance(item, str)]

        return []

    def _normalize_operation(self, operation: dict):
        normalized_operation = dict(operation)
        operation_type = normalized_operation.get("operation_type")

        if isinstance(operation_type, str):
            normalized_operation["operation_type"] = {
                "modify_file": "modify_text_file",
                "edit_file": "modify_text_file",
                "update_file": "modify_text_file",
                "update_text_file": "modify_text_file",
                "create_file": "create_text_file",
                "add_file": "create_text_file",
                "read": "read_file",
            }.get(operation_type, operation_type)

        return normalized_operation

    def _extract_json_object(self, raw_response: str):
        match = re.search(r"\{.*\}", raw_response, flags=re.DOTALL)

        if match is None:
            raise CoderDryRunError("Coder dry-run model did not return valid JSON")

        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise CoderDryRunError("Coder dry-run model did not return valid JSON") from exc

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
