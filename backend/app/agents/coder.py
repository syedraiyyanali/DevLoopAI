import json
import re
import difflib
from pathlib import Path

from pydantic import ValidationError

from app.models.chat import ChatRequest
from app.models.coder import (
    CoderDiffPreviewRequest,
    CoderDiffPreviewResponse,
    CoderDiffProposalPayload,
    CoderFileDiffPreview,
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
from app.services.workspace import (
    WorkspaceAccessError,
    WorkspaceService,
    WorkspaceUnsupportedFileError,
    WorkspaceNotFoundError,
)


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
            files_would_delete=self._unique(model_payload.files_to_delete),
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

        if payload.files_to_delete and "delete_text_file" not in handoff.allowed_operation_types:
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
                "delete_file": "delete_text_file",
                "remove_file": "delete_text_file",
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


class CoderDiffPreviewAgent:
    """
    Builds read-only unified diff previews from a valid Coding Agent dry-run.
    """

    def __init__(
        self,
        *,
        ollama_service: OllamaService,
        handoff_service: ExecutionHandoffService,
        workspace_service: WorkspaceService,
    ) -> None:
        self.ollama_service = ollama_service
        self.handoff_service = handoff_service
        self.workspace_service = workspace_service

    async def preview_diff(
        self,
        request: CoderDiffPreviewRequest,
    ) -> CoderDiffPreviewResponse:
        canonical_handoff = self.handoff_service.create_handoff(
            request=ExecutionHandoffRequest(workflow_id=request.dry_run.workflow_id)
        )
        self._validate_dry_run(
            dry_run=request.dry_run,
            handoff=canonical_handoff,
        )
        prompt = self._build_diff_prompt(
            dry_run=request.dry_run,
            handoff=canonical_handoff,
        )

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

        proposal = self._parse_diff_proposal(model_response.message)

        if proposal.blockers:
            raise CoderDryRunBlockedError(
                "Model reported diff preview blockers: " + " ".join(proposal.blockers)
            )

        file_previews = self._build_file_previews(
            dry_run=request.dry_run,
            handoff=canonical_handoff,
            proposal=proposal,
        )

        return CoderDiffPreviewResponse(
            workflow_id=request.dry_run.workflow_id,
            approved_plan_fingerprint=request.dry_run.approved_plan_fingerprint,
            workspace_path=request.dry_run.workspace_path,
            file_previews=file_previews,
            warnings=self._unique([*request.dry_run.warnings, *proposal.warnings]),
            blockers=[],
            model=model_response.model,
            execution_performed=False,
            mutation_capabilities_enabled=False,
            message="Diff preview generated. No files were written and no commands were run.",
        )

    def _validate_dry_run(
        self,
        *,
        dry_run: CoderDryRunResponse,
        handoff: ExecutionHandoffResponse,
    ) -> None:
        if dry_run.workflow_id != handoff.workflow_id:
            raise CoderDryRunBlockedError("Dry-run workflow ID does not match handoff.")

        if dry_run.approved_plan_fingerprint != handoff.approved_plan_fingerprint:
            raise CoderDryRunBlockedError("Dry-run fingerprint is stale or invalid.")

        if dry_run.workspace_path != handoff.workspace_path:
            raise CoderDryRunBlockedError("Dry-run workspace path is invalid.")

        if dry_run.execution_performed or dry_run.mutation_capabilities_enabled:
            raise CoderDryRunBlockedError("Dry-run must not have mutation capabilities enabled.")

        if dry_run.blockers:
            raise CoderDryRunBlockedError("Dry-run contains blockers: " + " ".join(dry_run.blockers))

        allowed_files = set(handoff.allowed_files)
        allowed_operations = set(handoff.allowed_operation_types)

        for operation in dry_run.intended_operations:
            if operation.relative_path not in allowed_files:
                raise CoderDryRunBlockedError(
                    f"Dry-run proposed a path outside the approved handoff: {operation.relative_path}"
                )

            if operation.operation_type not in allowed_operations:
                raise CoderDryRunBlockedError(
                    f"Dry-run proposed unsupported operation: {operation.operation_type}"
                )

        if dry_run.files_would_delete and "delete_text_file" not in allowed_operations:
            raise CoderDryRunBlockedError("Dry-run delete operations are not approved.")

    def _build_diff_prompt(
        self,
        *,
        dry_run: CoderDryRunResponse,
        handoff: ExecutionHandoffResponse,
    ) -> str:
        return (
            "You are DevLoopAI's zero-write diff content proposer. "
            "Return proposed full file contents for approved create/modify operations only. "
            "Do not claim you wrote files, ran commands, installed dependencies, committed, "
            "or executed anything. Python will generate the actual unified diff.\n\n"
            "Return ONLY valid JSON with this exact object shape:\n"
            "{\n"
            '  "file_changes": [\n'
            "    {\n"
            '      "relative_path": "path",\n'
            '      "proposed_content": "full proposed file content",\n'
            '      "warnings": ["warning"]\n'
            "    }\n"
            "  ],\n"
            '  "warnings": ["warning"],\n'
            '  "blockers": []\n'
            "}\n\n"
            "Rules:\n"
            "- Include file_changes only for create_text_file or modify_text_file operations.\n"
            "- Do not include delete_text_file operations in file_changes.\n"
            "- Use only paths from the dry-run intended operations.\n"
            "- Proposed content must be full file content, not a patch.\n\n"
            "Approved handoff:\n"
            f"{json.dumps(handoff.model_dump(mode='json'), ensure_ascii=True)}\n\n"
            "Dry-run:\n"
            f"{json.dumps(dry_run.model_dump(mode='json'), ensure_ascii=True)}"
        )

    def _parse_diff_proposal(self, raw_response: str) -> CoderDiffProposalPayload:
        try:
            payload = json.loads(raw_response)
        except json.JSONDecodeError:
            payload = self._extract_json_object(raw_response)

        payload = self._normalize_diff_payload(payload)

        try:
            return CoderDiffProposalPayload.model_validate(payload)
        except ValidationError as exc:
            raise CoderDryRunError(
                "Coder diff-preview model returned malformed output"
            ) from exc

    def _normalize_diff_payload(self, payload):
        if not isinstance(payload, dict):
            return payload

        normalized = dict(payload)
        normalized["warnings"] = self._normalize_string_list(normalized.get("warnings"))
        normalized["blockers"] = self._normalize_string_list(normalized.get("blockers"))
        file_changes = normalized.get("file_changes")

        if not isinstance(file_changes, list):
            file_changes = []

        normalized["file_changes"] = [
            {
                **change,
                "warnings": self._normalize_string_list(change.get("warnings")),
            }
            for change in file_changes
            if isinstance(change, dict)
        ]

        return normalized

    def _build_file_previews(
        self,
        *,
        dry_run: CoderDryRunResponse,
        handoff: ExecutionHandoffResponse,
        proposal: CoderDiffProposalPayload,
    ) -> list[CoderFileDiffPreview]:
        operation_paths = {
            operation.relative_path
            for operation in dry_run.intended_operations
            if operation.operation_type != "read_file"
        }
        unexpected_proposals = sorted(
            {
                change.relative_path
                for change in proposal.file_changes
                if change.relative_path not in operation_paths
            }
        )

        if unexpected_proposals:
            raise CoderDryRunBlockedError(
                "Model proposed diff content for unapproved paths: "
                + ", ".join(unexpected_proposals)
            )

        proposal_by_path = {
            change.relative_path: change
            for change in proposal.file_changes
        }
        previews = []

        for operation in dry_run.intended_operations:
            relative_path = operation.relative_path
            self._ensure_safe_path(
                workspace_path=handoff.workspace_path,
                relative_path=relative_path,
            )

            if operation.operation_type == "read_file":
                continue

            if operation.operation_type == "modify_text_file":
                current_content = self._read_current_content(
                    handoff.workspace_path,
                    relative_path,
                )
                proposed_content = self._proposal_for_path(
                    proposal_by_path,
                    relative_path,
                )
            elif operation.operation_type == "create_text_file":
                current_content = None
                proposed_content = self._proposal_for_path(
                    proposal_by_path,
                    relative_path,
                )
            elif operation.operation_type == "delete_text_file":
                current_content = self._read_current_content(
                    handoff.workspace_path,
                    relative_path,
                )
                proposed_content = None
            else:
                raise CoderDryRunBlockedError(
                    f"Unsupported diff-preview operation: {operation.operation_type}"
                )

            previews.append(
                CoderFileDiffPreview(
                    relative_path=relative_path,
                    operation_type=operation.operation_type,
                    current_content=current_content,
                    proposed_content=proposed_content,
                    unified_diff=self._unified_diff(
                        relative_path=relative_path,
                        current_content=current_content,
                        proposed_content=proposed_content,
                    ),
                    warnings=self._file_warnings(
                        relative_path=relative_path,
                        current_content=current_content,
                        proposed_content=proposed_content,
                        proposal=proposal_by_path.get(relative_path),
                    ),
                )
            )

        return previews

    def _ensure_safe_path(self, *, workspace_path: str, relative_path: str) -> None:
        root = Path(self.workspace_service.open_workspace(workspace_path).root_path)

        try:
            self.workspace_service._resolve_child_path(root, relative_path)
        except WorkspaceAccessError as exc:
            raise CoderDryRunBlockedError(
                f"Diff preview path is blocked: {relative_path}"
            ) from exc

    def _read_current_content(self, workspace_path: str, relative_path: str) -> str:
        try:
            return self.workspace_service.read_text_file(
                workspace_path,
                relative_path,
            ).content
        except (
            WorkspaceAccessError,
            WorkspaceUnsupportedFileError,
            WorkspaceNotFoundError,
        ) as exc:
            raise CoderDryRunBlockedError(
                f"Current file cannot be safely previewed: {relative_path}"
            ) from exc

    def _proposal_for_path(self, proposal_by_path, relative_path: str) -> str:
        proposal = proposal_by_path.get(relative_path)

        if proposal is None:
            raise CoderDryRunError(
                f"Coder diff-preview model did not propose content for {relative_path}"
            )

        return proposal.proposed_content

    def _unified_diff(
        self,
        *,
        relative_path: str,
        current_content: str | None,
        proposed_content: str | None,
    ) -> str:
        before = [] if current_content is None else current_content.splitlines(keepends=True)
        after = [] if proposed_content is None else proposed_content.splitlines(keepends=True)

        return "".join(
            difflib.unified_diff(
                before,
                after,
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
                lineterm="",
            )
        )

    def _file_warnings(
        self,
        *,
        relative_path: str,
        current_content: str | None,
        proposed_content: str | None,
        proposal,
    ) -> list[str]:
        warnings = [] if proposal is None else list(proposal.warnings)

        if current_content == proposed_content:
            warnings.append(f"No content changes proposed for {relative_path}.")

        return self._unique(warnings)

    def _extract_json_object(self, raw_response: str):
        match = re.search(r"\{.*\}", raw_response, flags=re.DOTALL)

        if match is None:
            raise CoderDryRunError("Coder diff-preview model did not return valid JSON")

        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise CoderDryRunError(
                "Coder diff-preview model did not return valid JSON"
            ) from exc

    def _normalize_string_list(self, value) -> list[str]:
        if value is None:
            return []

        if isinstance(value, str):
            return [] if value.strip().lower() in {"none", "n/a"} else [value]

        if isinstance(value, list):
            return [item for item in value if isinstance(item, str)]

        return []

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
