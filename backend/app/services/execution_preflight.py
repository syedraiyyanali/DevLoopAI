from datetime import datetime, timezone
from pathlib import Path

from app.models.execution_preflight import (
    ExecutionPreflightRequest,
    ExecutionPreflightResponse,
    FingerprintVerification,
    PreflightFileCheck,
    WorkspacePreflightStatus,
)
from app.models.planning_workflow import PlanningWorkflowHistoryRecord
from app.services.planning_approval import PlanningApprovalStore
from app.services.workspace import (
    WorkspaceAccessError,
    WorkspaceNotFoundError,
    WorkspaceService,
)


class ExecutionPreflightError(Exception):
    """
    Raised when execution preflight cannot load the requested workflow.
    """


class ExecutionPreflightService:
    """
    Read-only preflight checks for approved planning workflow records.
    """

    def __init__(
        self,
        *,
        approval_store: PlanningApprovalStore,
        workspace_service: WorkspaceService,
    ) -> None:
        self.approval_store = approval_store
        self.workspace_service = workspace_service

    def run(
        self,
        request: ExecutionPreflightRequest,
    ) -> ExecutionPreflightResponse:
        record = self.approval_store.get_workflow(request.workflow_id)
        fingerprint = self._fingerprint_verification(record)
        blockers: list[str] = []
        warnings: list[str] = []
        detected_changes: list[str] = []
        file_checks: list[PreflightFileCheck] = []

        if record.approval_status != "APPROVED":
            blockers.append(
                "Workflow approval status must be APPROVED before execution preflight."
            )

        if not fingerprint.matches:
            detected_changes.append(
                "Persisted plan fingerprint no longer matches the stored plan content."
            )

        workspace = self._workspace_status(record.workspace_path)

        if workspace.workspace_path is None:
            detected_changes.append(
                "Workflow record does not include a persisted workspace path."
            )
            warnings.append(
                "Older workflow records must be re-planned so the workspace can be checked."
            )
        elif not workspace.exists or not workspace.is_directory:
            blockers.append("Approved workspace is missing or is not a directory.")

        approval_decided_at = self._parse_timestamp(record.approval_decided_at)

        if record.approval_status == "APPROVED" and approval_decided_at is None:
            warnings.append(
                "Approved workflow is missing an approval timestamp; change detection is limited."
            )

        if workspace.exists and workspace.is_directory and workspace.workspace_path:
            file_checks = self._check_relevant_paths(
                record=record,
                workspace_path=workspace.workspace_path,
                approval_decided_at=approval_decided_at,
                detected_changes=detected_changes,
                warnings=warnings,
            )
            self._check_project_context(
                record=record,
                workspace_path=workspace.workspace_path,
                detected_changes=detected_changes,
                warnings=warnings,
            )

        status, readiness, reapproval_reason = self._final_decision(
            blockers=blockers,
            detected_changes=detected_changes,
        )

        return ExecutionPreflightResponse(
            workflow_id=record.workflow_id,
            approval_status=record.approval_status,
            status=status,
            fingerprint=fingerprint,
            workspace=workspace,
            file_checks=file_checks,
            detected_changes=self._unique(detected_changes),
            warnings=self._unique(warnings),
            blockers=self._unique(blockers),
            execution_readiness=readiness,
            reapproval_reason=reapproval_reason,
        )

    def _fingerprint_verification(
        self,
        record: PlanningWorkflowHistoryRecord,
    ) -> FingerprintVerification:
        recomputed_fingerprint = self.approval_store.plan_fingerprint(
            planner_output=record.planner_output,
            reviewer_output=record.reviewer_output,
            validator_output=record.validator_output,
        )

        return FingerprintVerification(
            stored_fingerprint=record.plan_fingerprint,
            recomputed_fingerprint=recomputed_fingerprint,
            matches=record.plan_fingerprint == recomputed_fingerprint,
        )

    def _workspace_status(
        self,
        workspace_path: str | None,
    ) -> WorkspacePreflightStatus:
        if workspace_path is None:
            return WorkspacePreflightStatus(
                workspace_path=None,
                exists=False,
                is_directory=False,
                status="No workspace path was stored with this workflow.",
            )

        path = Path(workspace_path).expanduser()

        try:
            metadata = self.workspace_service.open_workspace(workspace_path)
        except WorkspaceNotFoundError:
            return WorkspacePreflightStatus(
                workspace_path=workspace_path,
                exists=path.exists(),
                is_directory=path.is_dir(),
                status="Workspace path is missing or is not a directory.",
            )

        return WorkspacePreflightStatus(
            workspace_path=metadata.root_path,
            exists=True,
            is_directory=True,
            status="Workspace exists and is a directory.",
        )

    def _check_relevant_paths(
        self,
        *,
        record: PlanningWorkflowHistoryRecord,
        workspace_path: str,
        approval_decided_at: datetime | None,
        detected_changes: list[str],
        warnings: list[str],
    ) -> list[PreflightFileCheck]:
        root = Path(self.workspace_service.open_workspace(workspace_path).root_path)
        file_checks: list[PreflightFileCheck] = []
        candidate_paths = self._unique(record.planner_output.files_likely_to_change)

        if not candidate_paths:
            warnings.append("Planner output did not name files likely to change.")
            return file_checks

        for relative_path in candidate_paths:
            file_checks.append(
                self._check_one_path(
                    root=root,
                    relative_path=relative_path,
                    approval_decided_at=approval_decided_at,
                    record=record,
                    detected_changes=detected_changes,
                    warnings=warnings,
                )
            )

        return file_checks

    def _check_one_path(
        self,
        *,
        root: Path,
        relative_path: str,
        approval_decided_at: datetime | None,
        record: PlanningWorkflowHistoryRecord,
        detected_changes: list[str],
        warnings: list[str],
    ) -> PreflightFileCheck:
        try:
            target = self.workspace_service._resolve_child_path(root, relative_path)
        except WorkspaceAccessError:
            detected_changes.append(
                f"Relevant path is blocked or escapes the workspace: {relative_path}"
            )
            return PreflightFileCheck(
                relative_path=relative_path,
                exists=False,
                kind="blocked",
                note="Path is blocked by workspace safety rules.",
            )

        if not target.exists():
            note = "Path does not currently exist."

            if self._validator_claimed_path_exists(record, relative_path):
                detected_changes.append(
                    f"Validator previously treated this path as existing, but it is now missing: {relative_path}"
                )
            else:
                warnings.append(
                    f"Relevant path does not currently exist and may be a planned new file: {relative_path}"
                )

            return PreflightFileCheck(
                relative_path=relative_path,
                exists=False,
                kind="missing",
                note=note,
            )

        stat = target.stat()
        modified_after_approval = None

        if approval_decided_at is not None:
            modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
            modified_after_approval = modified_at > approval_decided_at

            if modified_after_approval:
                detected_changes.append(
                    f"Relevant path changed after approval: {relative_path}"
                )

        return PreflightFileCheck(
            relative_path=relative_path,
            exists=True,
            kind="directory" if target.is_dir() else "file",
            size_bytes=None if target.is_dir() else stat.st_size,
            modified_after_approval=modified_after_approval,
            note="Path exists inside the approved workspace.",
        )

    def _check_project_context(
        self,
        *,
        record: PlanningWorkflowHistoryRecord,
        workspace_path: str,
        detected_changes: list[str],
        warnings: list[str],
    ) -> None:
        try:
            current_context = self.workspace_service.summarize_context(workspace_path)
        except (WorkspaceAccessError, WorkspaceNotFoundError) as exc:
            detected_changes.append(f"Workspace context could not be refreshed: {exc}")
            return

        approved_context = record.planner_output.detected_project_context
        self._check_missing_values(
            label="project type",
            approved_values=approved_context.project_types,
            current_values=current_context.project_types,
            detected_changes=detected_changes,
        )
        self._check_missing_values(
            label="framework",
            approved_values=approved_context.frameworks,
            current_values=current_context.frameworks,
            detected_changes=detected_changes,
        )

        missing_languages = sorted(
            set(approved_context.languages) - set(current_context.detected_languages)
        )
        if missing_languages:
            detected_changes.append(
                "Detected project languages changed after approval: "
                + ", ".join(missing_languages)
            )

        if current_context.warnings:
            warnings.extend(
                f"Current workspace context warning: {warning}"
                for warning in current_context.warnings
            )

    def _check_missing_values(
        self,
        *,
        label: str,
        approved_values: list[str],
        current_values: list[str],
        detected_changes: list[str],
    ) -> None:
        missing_values = sorted(set(approved_values) - set(current_values))

        if missing_values:
            detected_changes.append(
                f"Detected {label} changed after approval: "
                + ", ".join(missing_values)
            )

    def _validator_claimed_path_exists(
        self,
        record: PlanningWorkflowHistoryRecord,
        relative_path: str,
    ) -> bool:
        normalized_path = relative_path.lower()

        return any(
            normalized_path in note.lower() and "path exists" in note.lower()
            for note in record.validator_output.file_path_validity
        )

    def _final_decision(
        self,
        *,
        blockers: list[str],
        detected_changes: list[str],
    ) -> tuple[str, str, str | None]:
        if blockers:
            return (
                "BLOCKED",
                "Preflight is blocked; do not hand this workflow to execution.",
                None,
            )

        if detected_changes:
            return (
                "REAPPROVAL_REQUIRED",
                "Preflight found changes after approval; re-plan and reapprove before execution.",
                "Approved workflow changed or can no longer be fully verified.",
            )

        return (
            "READY_FOR_EXECUTION",
            "Approved workflow passed read-only preflight and can be handed to a future Coding Agent.",
            None,
        )

    def _parse_timestamp(self, value: str | None) -> datetime | None:
        if value is None:
            return None

        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
                timezone.utc
            )
        except ValueError:
            return None

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
