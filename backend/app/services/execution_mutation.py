import difflib
import hashlib
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.models.coder import CoderDiffPreviewResponse
from app.models.execution_handoff import ExecutionHandoffRequest, ExecutionHandoffResponse
from app.models.execution_mutation import (
    ExecutionApplyRequest,
    ExecutionApplyResponse,
    ExecutionFileResult,
    ExecutionRollbackRequest,
    ExecutionRollbackResponse,
)
from app.services.execution_handoff import ExecutionHandoffBlockedError, ExecutionHandoffService
from app.services.execution_store import ExecutionStore
from app.services.workspace import (
    WorkspaceAccessError,
    WorkspaceNotFoundError,
    WorkspaceService,
    WorkspaceUnsupportedFileError,
)


class ExecutionMutationBlockedError(Exception):
    """Raised when a reviewed mutation fails a deterministic safety check."""


class ExecutionMutationService:
    """Applies only exact persisted diff content with snapshots and rollback."""

    supported_operations = {"modify_text_file", "create_text_file"}

    def __init__(
        self,
        *,
        handoff_service: ExecutionHandoffService,
        workspace_service: WorkspaceService,
        execution_store: ExecutionStore,
    ) -> None:
        self.handoff_service = handoff_service
        self.workspace_service = workspace_service
        self.execution_store = execution_store

    def apply(self, request: ExecutionApplyRequest) -> ExecutionApplyResponse:
        reviewed = self._load_exact_review(request.diff_preview)
        try:
            canonical_handoff = self.handoff_service.create_handoff(
                ExecutionHandoffRequest(workflow_id=reviewed.workflow_id)
            )
        except ExecutionHandoffBlockedError as exc:
            result_status = (
                "REVIEW_STALE" if "REAPPROVAL_REQUIRED" in str(exc) else "BLOCKED"
            )
            return self._record_blocked(reviewed, result_status, str(exc))
        self._validate_pipeline(request, canonical_handoff)
        previews = reviewed.file_previews
        execution_id = str(uuid4())
        timestamp = self._now()

        self._validate_previews(reviewed, request, canonical_handoff)
        self.execution_store.create_execution(
            execution_id=execution_id,
            workflow_id=reviewed.workflow_id,
            plan_fingerprint=reviewed.approved_plan_fingerprint,
            diff_review_id=reviewed.review_id or "",
            diff_fingerprint=reviewed.review_fingerprint or "",
            workspace_path=reviewed.workspace_path,
            created_at=timestamp,
        )
        try:
            self._validate_current_state(reviewed)
        except ExecutionMutationBlockedError as exc:
            response = self._blocked_response(
                execution_id=execution_id,
                reviewed=reviewed,
                status="REVIEW_STALE" if "REVIEW_STALE" in str(exc) else "BLOCKED",
                reason=str(exc),
                timestamp=timestamp,
            )
            self.execution_store.complete_execution(response)
            return response

        results: list[ExecutionFileResult] = []
        applied: list[tuple[Path, ExecutionFileResult]] = []
        attempted: list[str] = []

        try:
            for ordinal, preview in enumerate(previews):
                attempted.append(preview.relative_path)
                result, target = self._apply_one(
                    execution_id=execution_id,
                    workspace_path=reviewed.workspace_path,
                    preview=preview,
                )
                results.append(result)
                applied.append((target, result))
                self.execution_store.record_file(
                    execution_id=execution_id,
                    ordinal=ordinal,
                    result=result,
                )
        except Exception as exc:
            rollback_errors = self._rollback_applied(applied, enforce_final_hash=False)
            for result in results:
                result.status = "ROLLED_BACK"
            failure_status = "PARTIALLY_FAILED_AND_ROLLED_BACK" if applied else "BLOCKED"
            response = ExecutionApplyResponse(
                execution_id=execution_id,
                workflow_id=reviewed.workflow_id,
                workspace_path=reviewed.workspace_path,
                status=failure_status,
                files_attempted=attempted,
                files_changed=[],
                file_results=results,
                backup_status=(
                    "Backups created for completed modifications before writes."
                    if applied
                    else "Mutation stopped before any file was changed."
                ),
                rollback_available=False,
                warnings=rollback_errors,
                blockers=[f"Mutation failed and stopped: {exc}"],
                execution_timestamp=timestamp,
                message=(
                    "Mutation failed; all completed writes were rolled back."
                    if not rollback_errors
                    else "Mutation failed and rollback encountered errors."
                ),
            )
            self.execution_store.complete_execution(response)
            return response

        response = ExecutionApplyResponse(
            execution_id=execution_id,
            workflow_id=reviewed.workflow_id,
            workspace_path=reviewed.workspace_path,
            status="EXECUTED",
            files_attempted=attempted,
            files_changed=[result.relative_path for result in results],
            file_results=results,
            backup_status="Snapshots recorded for modifications; creates recorded as previously absent.",
            rollback_available=True,
            warnings=list(reviewed.warnings),
            blockers=[],
            execution_timestamp=timestamp,
            message="Reviewed deterministic file content was applied. No commands were run.",
        )
        self.execution_store.complete_execution(response)
        return response

    def _record_blocked(
        self,
        reviewed: CoderDiffPreviewResponse,
        status: str,
        reason: str,
    ) -> ExecutionApplyResponse:
        execution_id = str(uuid4())
        timestamp = self._now()
        self.execution_store.create_execution(
            execution_id=execution_id,
            workflow_id=reviewed.workflow_id,
            plan_fingerprint=reviewed.approved_plan_fingerprint,
            diff_review_id=reviewed.review_id or "",
            diff_fingerprint=reviewed.review_fingerprint or "",
            workspace_path=reviewed.workspace_path,
            created_at=timestamp,
        )
        response = self._blocked_response(
            execution_id=execution_id,
            reviewed=reviewed,
            status=status,
            reason=reason,
            timestamp=timestamp,
        )
        self.execution_store.complete_execution(response)
        return response

    def _blocked_response(
        self,
        *,
        execution_id: str,
        reviewed: CoderDiffPreviewResponse,
        status: str,
        reason: str,
        timestamp: str,
    ) -> ExecutionApplyResponse:
        return ExecutionApplyResponse(
            execution_id=execution_id,
            workflow_id=reviewed.workflow_id,
            workspace_path=reviewed.workspace_path,
            status=status,
            files_attempted=[],
            files_changed=[],
            file_results=[],
            backup_status="No backup was needed because no mutation started.",
            rollback_available=False,
            warnings=[],
            blockers=[reason],
            execution_timestamp=timestamp,
            message="Mutation was blocked; no files were changed.",
        )

    def rollback(self, request: ExecutionRollbackRequest) -> ExecutionRollbackResponse:
        execution = self.execution_store.get_execution(request.execution_id)

        if execution.status == "ROLLED_BACK":
            return ExecutionRollbackResponse(
                execution_id=execution.execution_id,
                workflow_id=execution.workflow_id,
                status="ROLLED_BACK",
                files_restored=[
                    item.relative_path
                    for item in execution.file_results
                    if item.operation_type == "modify_text_file"
                ],
                files_removed=[
                    item.relative_path
                    for item in execution.file_results
                    if item.operation_type == "create_text_file"
                ],
                rolled_back_at=None,
                message="Execution was already rolled back; no additional changes were made.",
            )

        if execution.status != "EXECUTED" or not execution.rollback_available:
            return ExecutionRollbackResponse(
                execution_id=execution.execution_id,
                workflow_id=execution.workflow_id,
                status="BLOCKED",
                blockers=["Only a successfully executed mutation with rollback available can be rolled back."],
                message="Rollback was blocked; no files were changed.",
            )

        workspace = execution.workspace_path
        targets: list[tuple[Path, ExecutionFileResult]] = []

        for result in execution.file_results:
            target = self._safe_target(workspace, result.relative_path)
            self._verify_rollback_state(target, result)
            targets.append((target, result))

        errors = self._rollback_applied(targets, enforce_final_hash=True)
        if errors:
            return ExecutionRollbackResponse(
                execution_id=execution.execution_id,
                workflow_id=execution.workflow_id,
                status="BLOCKED",
                blockers=errors,
                message="Rollback could not safely restore every file.",
            )

        for result in execution.file_results:
            result.status = "ROLLED_BACK"
        execution.status = "ROLLED_BACK"
        execution.rollback_available = False
        execution.files_changed = []
        execution.message = "Execution was rolled back from persisted snapshots."
        rolled_back_at = self.execution_store.mark_rolled_back(execution)
        return ExecutionRollbackResponse(
            execution_id=execution.execution_id,
            workflow_id=execution.workflow_id,
            status="ROLLED_BACK",
            files_restored=[
                item.relative_path
                for item in execution.file_results
                if item.operation_type == "modify_text_file"
            ],
            files_removed=[
                item.relative_path
                for item in execution.file_results
                if item.operation_type == "create_text_file"
            ],
            rolled_back_at=rolled_back_at,
            message="Execution was rolled back from persisted snapshots.",
        )

    def _validate_pipeline(
        self,
        request: ExecutionApplyRequest,
        canonical: ExecutionHandoffResponse,
    ) -> None:
        if request.handoff.model_dump(mode="json") != canonical.model_dump(mode="json"):
            raise ExecutionMutationBlockedError("Submitted handoff is stale or not canonical.")
        if canonical.preflight_result.status != "READY_FOR_EXECUTION":
            raise ExecutionMutationBlockedError("Execution preflight is not ready.")
        if canonical.user_approval_metadata.approval_status != "APPROVED":
            raise ExecutionMutationBlockedError("Workflow is not approved.")
        if request.dry_run.workflow_id != canonical.workflow_id:
            raise ExecutionMutationBlockedError("Dry-run workflow does not match the handoff.")
        if request.dry_run.approved_plan_fingerprint != canonical.approved_plan_fingerprint:
            raise ExecutionMutationBlockedError("Dry-run fingerprint is stale or invalid.")
        if request.dry_run.workspace_path != canonical.workspace_path:
            raise ExecutionMutationBlockedError("Dry-run workspace is invalid.")
        if request.dry_run.execution_performed or request.dry_run.mutation_capabilities_enabled:
            raise ExecutionMutationBlockedError("Dry-run mutation flags are invalid.")
        if request.dry_run.blockers:
            raise ExecutionMutationBlockedError("Dry-run contains blockers.")
        if request.dry_run.files_would_delete:
            raise ExecutionMutationBlockedError("Delete operations are disabled for this step.")

        allowed_files = set(canonical.allowed_files)
        allowed_operations = set(canonical.allowed_operation_types)
        for operation in request.dry_run.intended_operations:
            if operation.relative_path not in allowed_files:
                raise ExecutionMutationBlockedError("Dry-run contains a disallowed path.")
            if operation.operation_type not in allowed_operations:
                raise ExecutionMutationBlockedError("Dry-run contains a disallowed operation.")

        modify_paths = [
            operation.relative_path
            for operation in request.dry_run.intended_operations
            if operation.operation_type == "modify_text_file"
        ]
        create_paths = [
            operation.relative_path
            for operation in request.dry_run.intended_operations
            if operation.operation_type == "create_text_file"
        ]
        if request.dry_run.files_would_modify != modify_paths:
            raise ExecutionMutationBlockedError("Dry-run modify-file list is inconsistent.")
        if request.dry_run.files_would_create != create_paths:
            raise ExecutionMutationBlockedError("Dry-run create-file list is inconsistent.")

    def _load_exact_review(
        self,
        submitted: CoderDiffPreviewResponse,
    ) -> CoderDiffPreviewResponse:
        if not submitted.review_id or not submitted.review_fingerprint:
            raise ExecutionMutationBlockedError("Diff preview is not a persisted reviewed artifact.")
        persisted = self.execution_store.get_diff_review(submitted.review_id)
        if persisted.model_dump(mode="json") != submitted.model_dump(mode="json"):
            raise ExecutionMutationBlockedError("Submitted diff preview differs from the reviewed artifact.")
        recomputed = self.execution_store.diff_fingerprint(persisted)
        if recomputed != persisted.review_fingerprint:
            raise ExecutionMutationBlockedError("Reviewed diff fingerprint is stale or invalid.")
        return persisted

    def _validate_previews(self, reviewed, request, handoff) -> None:
        if reviewed.workflow_id != handoff.workflow_id:
            raise ExecutionMutationBlockedError("Reviewed diff workflow does not match.")
        if reviewed.approved_plan_fingerprint != handoff.approved_plan_fingerprint:
            raise ExecutionMutationBlockedError("Reviewed diff plan fingerprint is stale.")
        if reviewed.workspace_path != handoff.workspace_path:
            raise ExecutionMutationBlockedError("Reviewed diff workspace is invalid.")
        if reviewed.execution_performed or reviewed.mutation_capabilities_enabled or reviewed.blockers:
            raise ExecutionMutationBlockedError("Reviewed diff state is not eligible for execution.")
        if not reviewed.file_previews:
            raise ExecutionMutationBlockedError("Reviewed diff contains no file mutations.")

        expected = [
            (item.relative_path, item.operation_type)
            for item in request.dry_run.intended_operations
            if item.operation_type != "read_file"
        ]
        actual = [(item.relative_path, item.operation_type) for item in reviewed.file_previews]
        if expected != actual:
            raise ExecutionMutationBlockedError("Reviewed diff does not exactly match the dry-run operations.")

        for preview in reviewed.file_previews:
            if preview.operation_type not in self.supported_operations:
                raise ExecutionMutationBlockedError(
                    f"Unsupported mutation operation: {preview.operation_type}"
                )
            if preview.operation_type not in handoff.allowed_operation_types:
                raise ExecutionMutationBlockedError("Mutation operation is not allowed by the handoff.")
            if preview.relative_path not in handoff.allowed_files:
                raise ExecutionMutationBlockedError("Mutation path is not allowed by the handoff.")
            if preview.proposed_content is None:
                raise ExecutionMutationBlockedError("Reviewed proposed content is missing.")
            if len(preview.proposed_content.encode("utf-8")) > self.workspace_service.max_read_bytes:
                raise ExecutionMutationBlockedError("Reviewed proposed content exceeds the safe size limit.")
            if self._unified_diff(preview) != preview.unified_diff:
                raise ExecutionMutationBlockedError("Reviewed unified diff does not match its contents.")

    def _validate_current_state(self, reviewed: CoderDiffPreviewResponse) -> None:
        for preview in reviewed.file_previews:
            target = self._safe_target(reviewed.workspace_path, preview.relative_path)
            if preview.operation_type == "modify_text_file":
                current = self._read_current(reviewed.workspace_path, preview.relative_path)
                if current != preview.current_content:
                    raise ExecutionMutationBlockedError(
                        f"REVIEW_STALE: {preview.relative_path} changed after diff review."
                    )
            elif target.exists():
                raise ExecutionMutationBlockedError(
                    f"REVIEW_STALE: create target now exists: {preview.relative_path}"
                )

    def _apply_one(self, *, execution_id: str, workspace_path: str, preview):
        target = self._safe_target(workspace_path, preview.relative_path)
        proposed_content = preview.proposed_content
        proposed_hash = self._hash(proposed_content)
        original_hash = None
        backup_location = None
        backup_status = "NOT_REQUIRED"

        if preview.operation_type == "modify_text_file":
            current = self._read_current(workspace_path, preview.relative_path)
            if current != preview.current_content:
                raise ExecutionMutationBlockedError(
                    f"REVIEW_STALE: {preview.relative_path} changed immediately before write."
                )
            original_hash = self._hash(current)
            backup_path = self.execution_store.backup_root / execution_id / preview.relative_path
            self._create_snapshot(backup_path, current)
            backup_location = str(backup_path.resolve())
            backup_status = "CREATED"
        elif target.exists():
            raise ExecutionMutationBlockedError(
                f"REVIEW_STALE: create target now exists: {preview.relative_path}"
            )

        if not target.parent.is_dir():
            raise ExecutionMutationBlockedError("Parent directory must already exist for file creation.")
        self._atomic_write(target, proposed_content)
        final_hash = self._hash(target.read_bytes().decode("utf-8"))
        if final_hash != proposed_hash:
            raise OSError("Atomic write verification failed.")

        result = ExecutionFileResult(
            relative_path=preview.relative_path,
            operation_type=preview.operation_type,
            status="CHANGED" if preview.operation_type == "modify_text_file" else "CREATED",
            original_content_hash=original_hash,
            proposed_content_hash=proposed_hash,
            final_content_hash=final_hash,
            backup_location=backup_location,
            backup_status=backup_status,
        )
        return result, target

    def _verify_rollback_state(self, target: Path, result: ExecutionFileResult) -> None:
        if not target.is_file():
            raise ExecutionMutationBlockedError(
                f"Rollback target is missing: {result.relative_path}"
            )
        current_hash = self._hash(target.read_bytes().decode("utf-8"))
        if current_hash != result.final_content_hash:
            raise ExecutionMutationBlockedError(
                f"Rollback blocked because file changed after execution: {result.relative_path}"
            )

    def _rollback_applied(self, applied, *, enforce_final_hash: bool) -> list[str]:
        errors = []
        for target, result in reversed(applied):
            try:
                if enforce_final_hash:
                    self._verify_rollback_state(target, result)
                if result.operation_type == "create_text_file":
                    target.unlink()
                else:
                    if not result.backup_location:
                        raise OSError("Snapshot location is missing.")
                    snapshot = Path(result.backup_location)
                    original = snapshot.read_bytes().decode("utf-8")
                    if self._hash(original) != result.original_content_hash:
                        raise OSError("Snapshot content hash does not match audit metadata.")
                    self._atomic_write(target, original)
            except Exception as exc:
                errors.append(f"Rollback failed for {result.relative_path}: {exc}")
        return errors

    def _safe_target(self, workspace_path: str, relative_path: str) -> Path:
        root = Path(self.workspace_service.open_workspace(workspace_path).root_path)
        try:
            target = self.workspace_service._resolve_child_path(root, relative_path)
        except WorkspaceAccessError as exc:
            raise ExecutionMutationBlockedError(f"Mutation path is blocked: {relative_path}") from exc
        if self.workspace_service._is_ignored_path(target):
            raise ExecutionMutationBlockedError(f"Mutation path is blocked: {relative_path}")
        return target

    def _read_current(self, workspace_path: str, relative_path: str) -> str:
        try:
            return self.workspace_service.read_text_file(workspace_path, relative_path).content
        except (WorkspaceAccessError, WorkspaceNotFoundError, WorkspaceUnsupportedFileError) as exc:
            raise ExecutionMutationBlockedError(
                f"Current file cannot be safely mutated: {relative_path}"
            ) from exc

    def _create_snapshot(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(path, content)

    def _atomic_write(self, target: Path, content: str) -> None:
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=target.parent,
                prefix=f".{target.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)
            if target.exists():
                os.chmod(temporary_path, target.stat().st_mode)
            os.replace(temporary_path, target)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def _unified_diff(self, preview) -> str:
        before = [] if preview.current_content is None else preview.current_content.splitlines(keepends=True)
        after = [] if preview.proposed_content is None else preview.proposed_content.splitlines(keepends=True)
        return "".join(
            difflib.unified_diff(
                before,
                after,
                fromfile=f"a/{preview.relative_path}",
                tofile=f"b/{preview.relative_path}",
                lineterm="",
            )
        )

    def _hash(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
