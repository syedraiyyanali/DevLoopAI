import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from app.models.execution_quality import ExecutionQualityResponse, VerificationSummary
from app.models.execution_verification import ExecutionVerificationResult
from app.services.execution_store import ExecutionStore
from app.services.workspace import WorkspaceAccessError, WorkspaceService


PYTHON_EXTENSIONS = {".py"}
FRONTEND_EXTENSIONS = {
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".mjs",
    ".cjs",
    ".css",
    ".scss",
    ".sass",
}


class ExecutionQualityGate:
    """Deterministically evaluates current execution quality from persisted audit state."""

    def __init__(
        self,
        *,
        execution_store: ExecutionStore,
        workspace_service: WorkspaceService,
    ) -> None:
        self.execution_store = execution_store
        self.workspace_service = workspace_service

    def evaluate(self, execution_id: str) -> ExecutionQualityResponse:
        execution = self.execution_store.get_execution(execution_id)
        audit = self.execution_store.get_execution_audit(execution_id)
        verifications = self.execution_store.list_verifications(execution_id)
        required = self._required_verifications(execution)
        blockers = self._audit_blockers(execution, audit)
        warnings = []
        reasons = []

        if execution.status == "ROLLED_BACK" or audit["status"] == "ROLLED_BACK":
            return self._response(
                execution=execution,
                status="ROLLED_BACK",
                required=required,
                verifications=verifications,
                rollback_status="ROLLED_BACK",
                rollback_recommended=False,
                blockers=blockers,
                warnings=warnings,
                reasons=["execution_rolled_back"],
            )

        if execution.status != "EXECUTED" or audit["status"] != "EXECUTED":
            blockers.append("Execution status is not EXECUTED.")
            reasons.append("invalid_execution_state")

        blockers.extend(self._current_state_blockers(execution))
        if blockers:
            return self._response(
                execution=execution,
                status="BLOCKED",
                required=required,
                verifications=verifications,
                rollback_status="NOT_ROLLED_BACK",
                rollback_recommended=True,
                blockers=blockers,
                warnings=warnings,
                reasons=self._unique([*reasons, "audit_or_current_state_blocked"]),
            )

        grouped = self._group_verifications(verifications)
        passed, failed, missing, skipped, blocked = self._classify_required(
            grouped=grouped,
            required=required,
        )
        if blocked:
            return self._response(
                execution=execution,
                status="BLOCKED",
                required=required,
                verifications=verifications,
                rollback_status="NOT_ROLLED_BACK",
                rollback_recommended=True,
                blockers=[f"Required verification was blocked: {item}" for item in blocked],
                warnings=warnings,
                reasons=["required_verification_blocked"],
            )

        if failed:
            return self._response(
                execution=execution,
                status="QUALITY_FAILED",
                required=required,
                verifications=verifications,
                rollback_status="NOT_ROLLED_BACK",
                rollback_recommended=True,
                blockers=[],
                warnings=warnings,
                reasons=["required_verification_failed"],
            )

        if missing or skipped or not required:
            reason = "required_verification_missing" if missing or not required else "required_verification_skipped"
            if not required:
                warnings.append("No applicable required verification checks were detected.")
            return self._response(
                execution=execution,
                status="QUALITY_INCOMPLETE",
                required=required,
                verifications=verifications,
                rollback_status="NOT_ROLLED_BACK",
                rollback_recommended=False,
                blockers=[],
                warnings=warnings,
                reasons=[reason],
            )

        return self._response(
            execution=execution,
            status="QUALITY_PASSED",
            required=required,
            verifications=verifications,
            rollback_status="NOT_ROLLED_BACK",
            rollback_recommended=False,
            blockers=[],
            warnings=warnings,
            reasons=["all_required_verification_passed"],
        )

    def _required_verifications(self, execution) -> list[str]:
        root = Path(execution.workspace_path).resolve()
        changed_paths = [Path(result.relative_path) for result in execution.file_results]
        required = []

        if any(path.suffix.lower() in PYTHON_EXTENSIONS for path in changed_paths):
            required.append("python_compile")
            if self._has_pytest_project(root):
                required.append("pytest")

        if any(path.suffix.lower() in FRONTEND_EXTENSIONS for path in changed_paths):
            if self._has_package_script(root, "lint"):
                required.append("frontend_lint")
            if self._has_package_script(root, "build"):
                required.append("frontend_build")

        return self._unique(required)

    def _audit_blockers(self, execution, audit: dict[str, str]) -> list[str]:
        blockers = []
        if execution.workflow_id != audit["workflow_id"]:
            blockers.append("Execution workflow linkage is inconsistent.")
        if str(Path(execution.workspace_path).resolve()) != str(Path(audit["workspace_path"]).resolve()):
            blockers.append("Execution workspace linkage is inconsistent.")

        persisted_files = self.execution_store.get_execution_files(execution.execution_id)
        if [item.model_dump(mode="json") for item in persisted_files] != [
            item.model_dump(mode="json") for item in execution.file_results
        ]:
            blockers.append("Persisted file audit differs from the execution response.")
        return blockers

    def _current_state_blockers(self, execution) -> list[str]:
        blockers = []
        root = Path(execution.workspace_path).resolve()
        if not root.is_dir():
            return ["Execution workspace no longer exists."]

        for result in execution.file_results:
            try:
                target = self.workspace_service._resolve_child_path(root, result.relative_path)
            except WorkspaceAccessError:
                blockers.append(f"Changed file path is outside the approved workspace: {result.relative_path}")
                continue

            if result.operation_type == "create_text_file" and not target.exists():
                blockers.append(f"Created file is missing: {result.relative_path}")
                continue
            if not target.is_file():
                blockers.append(f"Changed file is missing: {result.relative_path}")
                continue

            current_hash = hashlib.sha256(target.read_bytes()).hexdigest()
            if current_hash != result.final_content_hash:
                blockers.append(f"Changed file no longer matches execution audit: {result.relative_path}")
        return blockers

    def _classify_required(
        self,
        *,
        grouped: dict[str, list[ExecutionVerificationResult]],
        required: list[str],
    ) -> tuple[list[str], list[str], list[str], list[str], list[str]]:
        passed = []
        failed = []
        missing = []
        skipped = []
        blocked = []
        for verification_type in required:
            latest = grouped.get(verification_type, [])[-1] if grouped.get(verification_type) else None
            if latest is None:
                missing.append(verification_type)
            elif latest.status == "PASSED":
                passed.append(verification_type)
            elif latest.status in {"FAILED", "TIMED_OUT"}:
                failed.append(verification_type)
            elif latest.status == "SKIPPED":
                skipped.append(verification_type)
            elif latest.status == "BLOCKED":
                blocked.append(verification_type)
            else:
                blocked.append(verification_type)
        return passed, failed, missing, skipped, blocked

    def _verification_summary(
        self,
        *,
        verifications: list[ExecutionVerificationResult],
        required: list[str],
    ) -> list[VerificationSummary]:
        grouped = self._group_verifications(verifications)
        verification_types = self._unique([*required, *grouped.keys()])
        return [
            VerificationSummary(
                verification_type=verification_type,
                latest_status=grouped[verification_type][-1].status if grouped.get(verification_type) else None,
                runs=len(grouped.get(verification_type, [])),
                required=verification_type in required,
            )
            for verification_type in verification_types
        ]

    def _group_verifications(
        self,
        verifications: list[ExecutionVerificationResult],
    ) -> dict[str, list[ExecutionVerificationResult]]:
        grouped = defaultdict(list)
        for verification in verifications:
            grouped[verification.verification_type].append(verification)
        return grouped

    def _has_pytest_project(self, root: Path) -> bool:
        if (root / "pytest.ini").is_file() or (root / "pyproject.toml").is_file():
            return True
        if (root / "tests").is_dir():
            return True
        return any(root.glob("test_*.py"))

    def _has_package_script(self, root: Path, script_name: str) -> bool:
        for manifest in sorted(root.rglob("package.json"), key=lambda path: (len(path.parts), str(path))):
            if self.workspace_service._is_ignored_path(manifest):
                continue
            try:
                relative = manifest.resolve().relative_to(root).as_posix()
                content = self.workspace_service.read_text_file(str(root), relative).content
                scripts = json.loads(content).get("scripts", {})
            except (OSError, ValueError, json.JSONDecodeError, AttributeError, WorkspaceAccessError):
                continue
            if isinstance(scripts, dict) and isinstance(scripts.get(script_name), str):
                return True
        return False

    def _response(
        self,
        *,
        execution,
        status: str,
        required: list[str],
        verifications: list[ExecutionVerificationResult],
        rollback_status: str,
        rollback_recommended: bool,
        blockers: list[str],
        warnings: list[str],
        reasons: list[str],
    ) -> ExecutionQualityResponse:
        grouped = self._group_verifications(verifications)
        passed, failed, missing, skipped, blocked = self._classify_required(
            grouped=grouped,
            required=required,
        )
        return ExecutionQualityResponse(
            execution_id=execution.execution_id,
            workflow_id=execution.workflow_id,
            quality_status=status,
            execution_status=execution.status,
            required_verification_types=required,
            verification_summary=self._verification_summary(
                verifications=verifications,
                required=required,
            ),
            passed_checks=passed,
            failed_checks=failed,
            missing_checks=missing,
            skipped_checks=skipped,
            rollback_status=rollback_status,
            rollback_recommended=rollback_recommended,
            blockers=self._unique([*blockers, *[f"Required verification was blocked: {item}" for item in blocked]]),
            warnings=self._unique(warnings),
            reasons=self._unique(reasons),
            quality_timestamp=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        )

    def _unique(self, values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))
