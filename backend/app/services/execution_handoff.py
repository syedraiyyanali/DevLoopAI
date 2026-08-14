from pathlib import Path

from app.models.execution_handoff import (
    ApprovalMetadata,
    ExecutionHandoffRequest,
    ExecutionHandoffResponse,
    RollbackBackupRequirements,
)
from app.models.execution_preflight import ExecutionPreflightRequest
from app.models.planning_workflow import PlanningWorkflowHistoryRecord
from app.services.execution_preflight import ExecutionPreflightService
from app.services.planning_approval import PlanningApprovalStore
from app.services.workspace import WorkspaceAccessError, WorkspaceService


class ExecutionHandoffBlockedError(Exception):
    """
    Raised when a Coding Agent handoff contract cannot be safely created.
    """


class ExecutionHandoffService:
    """
    Creates a read-only handoff contract for a future Coding Agent.
    """

    default_allowed_operation_types = [
        "read_file",
        "create_text_file",
        "modify_text_file",
    ]

    def __init__(
        self,
        *,
        approval_store: PlanningApprovalStore,
        workspace_service: WorkspaceService,
        preflight_service: ExecutionPreflightService,
    ) -> None:
        self.approval_store = approval_store
        self.workspace_service = workspace_service
        self.preflight_service = preflight_service

    def create_handoff(
        self,
        request: ExecutionHandoffRequest,
    ) -> ExecutionHandoffResponse:
        record = self.approval_store.get_workflow(request.workflow_id)
        preflight = self.preflight_service.run(
            ExecutionPreflightRequest(workflow_id=request.workflow_id)
        )
        blockers = self._handoff_blockers(record, preflight)

        if blockers:
            raise ExecutionHandoffBlockedError(" ".join(blockers))

        workspace_path = preflight.workspace.workspace_path

        if workspace_path is None:
            raise ExecutionHandoffBlockedError(
                "Approved workflow is missing a workspace path."
            )

        allowed_files = self._allowed_files(
            workspace_path=workspace_path,
            paths=record.planner_output.files_likely_to_change,
        )

        if not allowed_files:
            raise ExecutionHandoffBlockedError(
                "Planner output did not provide safe allowed files for handoff."
            )

        return ExecutionHandoffResponse(
            workflow_id=record.workflow_id,
            approved_plan_fingerprint=record.plan_fingerprint,
            workspace_path=workspace_path,
            preflight_result=preflight,
            approved_planned_changes=self._unique(
                [
                    record.planner_output.task_summary,
                    *record.planner_output.implementation_steps,
                ]
            ),
            allowed_files=allowed_files,
            allowed_operation_types=self._allowed_operation_types(record),
            expected_tests=self._expected_tests(record),
            warnings=self._unique(
                [
                    *preflight.warnings,
                    *record.final_reviewed_summary.warnings,
                    *record.validator_output.dependency_concerns,
                    *record.validator_output.security_concerns,
                    *record.validator_output.destructive_operation_warnings,
                ]
            ),
            blockers=[],
            rollback_backup_requirements=RollbackBackupRequirements(
                backup_required=True,
                rollback_plan_required=True,
                requirements=[
                    "Capture the original contents of every allowed file before writing.",
                    "Prepare a rollback plan before applying any file modification.",
                    "Do not modify files outside the allowed_files list.",
                    "Run the expected tests after future execution.",
                ],
            ),
            user_approval_metadata=ApprovalMetadata(
                approval_status=record.approval_status,
                approved_at=record.approval_decided_at,
                approval_reason=record.approval_reason,
            ),
            execution_allowed=False,
            message=(
                "Handoff contract created. No files were modified and execution "
                "is still disabled until a future Coding Agent is implemented."
            ),
        )

    def _handoff_blockers(
        self,
        record: PlanningWorkflowHistoryRecord,
        preflight,
    ) -> list[str]:
        blockers = []

        if record.approval_status != "APPROVED":
            blockers.append("Workflow must be APPROVED before handoff.")

        if not preflight.fingerprint.matches:
            blockers.append("Plan fingerprint does not match persisted workflow output.")

        if preflight.status != "READY_FOR_EXECUTION":
            blockers.append(
                f"Preflight must be READY_FOR_EXECUTION before handoff; got {preflight.status}."
            )

        blockers.extend(preflight.blockers)

        return self._unique(blockers)

    def _allowed_files(
        self,
        *,
        workspace_path: str,
        paths: list[str],
    ) -> list[str]:
        root = Path(self.workspace_service.open_workspace(workspace_path).root_path)
        allowed_files: list[str] = []

        for relative_path in self._unique(paths):
            try:
                target = self.workspace_service._resolve_child_path(root, relative_path)
            except WorkspaceAccessError as exc:
                raise ExecutionHandoffBlockedError(
                    f"Path is not allowed in Coding Agent handoff: {relative_path}"
                ) from exc

            if target.exists() and target.is_dir():
                raise ExecutionHandoffBlockedError(
                    f"Directory paths are not allowed in Coding Agent handoff: {relative_path}"
                )

            allowed_files.append(target.relative_to(root).as_posix())

        return allowed_files

    def _expected_tests(self, record: PlanningWorkflowHistoryRecord) -> list[str]:
        return self._unique(
            [
                *record.planner_output.tests_verification_required,
                *record.reviewer_output.testing_gaps,
                *record.validator_output.test_verification_readiness,
                *record.final_reviewed_summary.tests_expected,
            ]
        )

    def _allowed_operation_types(
        self,
        record: PlanningWorkflowHistoryRecord,
    ) -> list[str]:
        operation_types = list(self.default_allowed_operation_types)
        approved_plan_text = " ".join(
            [
                record.planner_output.task_summary,
                *record.planner_output.implementation_steps,
                *record.reviewer_output.recommended_improvements,
                *record.validator_output.plan_completeness,
                record.final_reviewed_summary.summary,
            ]
        ).lower()

        if "delete" in approved_plan_text or "remove" in approved_plan_text:
            operation_types.append("delete_text_file")

        return operation_types

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
