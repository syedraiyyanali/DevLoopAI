import json
from pathlib import Path

from app.models.execution_verification_plan import (
    ExecutionVerificationPlanResponse,
    VerificationPlanCheck,
)
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
COMMAND_IDENTITIES = {
    "python_compile": "python_compile:v1",
    "pytest": "pytest:v1",
    "frontend_lint": "frontend_lint:eslint:v1",
    "frontend_build": "frontend_build:next:v1",
}


class ExecutionVerificationPolicy:
    """Selects the smallest useful allowlisted verification set for an execution."""

    def __init__(
        self,
        *,
        execution_store: ExecutionStore,
        workspace_service: WorkspaceService,
    ) -> None:
        self.execution_store = execution_store
        self.workspace_service = workspace_service

    def plan_for_execution_id(self, execution_id: str) -> ExecutionVerificationPlanResponse:
        return self.plan_for_execution(self.execution_store.get_execution(execution_id))

    def required_verification_types(self, execution) -> list[str]:
        return self.plan_for_execution(execution).required_verification_types

    def plan_for_execution(self, execution) -> ExecutionVerificationPlanResponse:
        root = Path(execution.workspace_path).resolve()
        changed_files = list(execution.files_changed)
        changed_paths = [Path(result.relative_path) for result in execution.file_results]
        python_changed = any(path.suffix.lower() in PYTHON_EXTENSIONS for path in changed_paths)
        frontend_changed = any(path.suffix.lower() in FRONTEND_EXTENSIONS for path in changed_paths)
        checks = []
        warnings = []
        blockers = []

        if not root.is_dir():
            blockers.append("Execution workspace no longer exists.")

        checks.append(self._python_compile_check(python_changed))
        checks.append(self._pytest_check(root, python_changed))
        checks.append(self._frontend_script_check(root, frontend_changed, "frontend_lint", "lint"))
        checks.append(self._frontend_script_check(root, frontend_changed, "frontend_build", "build"))

        if not any(check.selected_by_default for check in checks):
            warnings.append(
                "No required allowlisted verification was selected for the changed file types."
            )

        return ExecutionVerificationPlanResponse(
            execution_id=execution.execution_id,
            workflow_id=execution.workflow_id,
            workspace_path=execution.workspace_path,
            changed_files=changed_files,
            required_verification_types=[
                check.verification_type for check in checks if check.tier == "required"
            ],
            recommended_verification_types=[
                check.verification_type for check in checks if check.tier == "recommended"
            ],
            skipped_verification_types=[
                check.verification_type for check in checks if check.tier == "not_applicable"
            ],
            checks=checks,
            warnings=warnings,
            blockers=blockers,
        )

    def _python_compile_check(self, python_changed: bool) -> VerificationPlanCheck:
        if python_changed:
            return self._check(
                verification_type="python_compile",
                tier="required",
                applicable=True,
                selected=True,
                reason="Python file changes require syntax compilation.",
            )
        return self._check(
            verification_type="python_compile",
            tier="not_applicable",
            applicable=False,
            selected=False,
            reason="No Python files were changed.",
            skip_reason="No changed file has a .py extension.",
        )

    def _pytest_check(self, root: Path, python_changed: bool) -> VerificationPlanCheck:
        if not python_changed:
            return self._check(
                verification_type="pytest",
                tier="not_applicable",
                applicable=False,
                selected=False,
                reason="Pytest is only considered for Python file changes.",
                skip_reason="No Python files were changed.",
            )
        if self._has_pytest_project(root):
            return self._check(
                verification_type="pytest",
                tier="required",
                applicable=True,
                selected=True,
                reason="A pytest-capable project was detected for Python changes.",
            )
        return self._check(
            verification_type="pytest",
            tier="not_applicable",
            applicable=False,
            selected=False,
            reason="Python changed, but no pytest project markers were detected.",
            skip_reason="No tests directory, pytest.ini, pyproject.toml, or root test_*.py was found.",
        )

    def _frontend_script_check(
        self,
        root: Path,
        frontend_changed: bool,
        verification_type: str,
        script_name: str,
    ) -> VerificationPlanCheck:
        if not frontend_changed:
            return self._check(
                verification_type=verification_type,
                tier="not_applicable",
                applicable=False,
                selected=False,
                reason=f"{script_name} is only considered for frontend file changes.",
                skip_reason="No changed file has a frontend source/style extension.",
            )
        if self._has_package_script(root, script_name):
            return self._check(
                verification_type=verification_type,
                tier="required",
                applicable=True,
                selected=True,
                reason=f"A visible package.json defines a {script_name} script for frontend changes.",
            )
        return self._check(
            verification_type=verification_type,
            tier="not_applicable",
            applicable=False,
            selected=False,
            reason=f"Frontend files changed, but no {script_name} script was found.",
            skip_reason=f"No visible package.json defines the {script_name} script.",
        )

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

    def _check(
        self,
        *,
        verification_type: str,
        tier: str,
        applicable: bool,
        selected: bool,
        reason: str,
        skip_reason: str | None = None,
    ) -> VerificationPlanCheck:
        return VerificationPlanCheck(
            verification_type=verification_type,
            command_identity=COMMAND_IDENTITIES[verification_type],
            tier=tier,
            applicable=applicable,
            selected_by_default=selected,
            reason=reason,
            skip_reason=skip_reason,
        )
