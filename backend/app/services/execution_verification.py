import hashlib
import importlib.util
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.models.execution_verification import (
    ExecutionVerificationHistoryResponse,
    ExecutionVerificationRequest,
    ExecutionVerificationResponse,
    ExecutionVerificationResult,
)
from app.services.execution_store import ExecutionStore
from app.services.planning_approval import PlanningApprovalStore
from app.services.workspace import (
    WorkspaceAccessError,
    WorkspaceNotFoundError,
    WorkspaceService,
)


PYTHON_COMPILE_SCRIPT = r"""
from pathlib import Path
import sys

ignored = {
    '.git', '.hg', '.svn', '.venv', 'venv', 'env', '__pycache__',
    '.pytest_cache', '.mypy_cache', '.ruff_cache', '.next', '.nuxt',
    '.cache', 'node_modules', 'dist', 'build', 'coverage'
}
failures = []
checked = 0
for path in Path.cwd().rglob('*.py'):
    if any(part in ignored for part in path.parts):
        continue
    checked += 1
    try:
        source = path.read_bytes().decode('utf-8')
        compile(source, str(path), 'exec')
    except Exception as exc:
        failures.append(f'{path}: {exc}')
print(f'Checked {checked} Python files.')
if failures:
    print('\n'.join(failures), file=sys.stderr)
    raise SystemExit(1)
""".strip()


@dataclass(frozen=True)
class VerificationDefinition:
    command_identity: str
    timeout_seconds: float
    resolver_name: str
    execution_warning: str | None = None


@dataclass(frozen=True)
class VerificationCommand:
    arguments: list[str]
    working_directory: Path


@dataclass(frozen=True)
class ProcessOutcome:
    status: str
    exit_code: int | None
    duration_seconds: float
    stdout: str
    stderr: str
    output_truncated: bool
    output_redacted: bool = False


class _BoundedReader(threading.Thread):
    def __init__(self, stream, limit: int) -> None:
        super().__init__(daemon=True)
        self.stream = stream
        self.limit = limit
        self.buffer = bytearray()
        self.truncated = False

    def run(self) -> None:
        while True:
            chunk = self.stream.read(8192)
            if not chunk:
                return
            remaining = self.limit - len(self.buffer)
            if remaining > 0:
                self.buffer.extend(chunk[:remaining])
            if len(chunk) > remaining:
                self.truncated = True

    def text(self) -> str:
        return bytes(self.buffer).decode("utf-8", errors="replace")


class ExecutionVerificationRunner:
    """Runs only fixed, project-aware verification definitions."""

    output_limit_bytes = 32 * 1024
    registry = {
        "python_compile": VerificationDefinition(
            command_identity="python_compile:v1",
            timeout_seconds=30,
            resolver_name="_resolve_python_compile",
        ),
        "pytest": VerificationDefinition(
            command_identity="pytest:v1",
            timeout_seconds=120,
            resolver_name="_resolve_pytest",
            execution_warning="Pytest executes test code already present in the approved workspace.",
        ),
        "frontend_lint": VerificationDefinition(
            command_identity="frontend_lint:eslint:v1",
            timeout_seconds=120,
            resolver_name="_resolve_frontend_lint",
            execution_warning="ESLint may load configuration and plugins from the approved workspace.",
        ),
        "frontend_build": VerificationDefinition(
            command_identity="frontend_build:next:v1",
            timeout_seconds=180,
            resolver_name="_resolve_frontend_build",
            execution_warning="Next.js build evaluates project build configuration from the approved workspace.",
        ),
    }

    def __init__(
        self,
        *,
        execution_store: ExecutionStore,
        approval_store: PlanningApprovalStore,
        workspace_service: WorkspaceService,
    ) -> None:
        self.execution_store = execution_store
        self.approval_store = approval_store
        self.workspace_service = workspace_service

    def verify(
        self,
        execution_id: str,
        request: ExecutionVerificationRequest,
    ) -> ExecutionVerificationResponse:
        execution = self.execution_store.get_execution(execution_id)
        audit = self.execution_store.get_execution_audit(execution_id)
        lifecycle_blockers = self._execution_blockers(execution, audit)
        results = []

        for verification_type in request.verification_types:
            result = self._verify_one(
                verification_type=verification_type,
                execution=execution,
                lifecycle_blockers=lifecycle_blockers,
            )
            self.execution_store.record_verification(result)
            results.append(result)

        return ExecutionVerificationResponse(
            execution_id=execution.execution_id,
            workflow_id=execution.workflow_id,
            results=results,
        )

    def history(self, execution_id: str) -> ExecutionVerificationHistoryResponse:
        execution = self.execution_store.get_execution(execution_id)
        return ExecutionVerificationHistoryResponse(
            execution_id=execution.execution_id,
            workflow_id=execution.workflow_id,
            verifications=self.execution_store.list_verifications(execution_id),
        )

    def _verify_one(self, *, verification_type: str, execution, lifecycle_blockers):
        definition = self.registry.get(verification_type)
        timestamp = self._now()
        verification_id = str(uuid4())

        if definition is None:
            return self._result(
                verification_id=verification_id,
                execution=execution,
                verification_type=verification_type,
                command_identity="unrecognized",
                working_directory=execution.workspace_path,
                status="BLOCKED",
                timestamp=timestamp,
                blockers=["Verification type is not in the server allowlist."],
            )

        if lifecycle_blockers:
            return self._result(
                verification_id=verification_id,
                execution=execution,
                verification_type=verification_type,
                command_identity=definition.command_identity,
                working_directory=execution.workspace_path,
                status="BLOCKED",
                timestamp=timestamp,
                blockers=lifecycle_blockers,
            )

        current_blockers = self._changed_file_blockers(execution)
        if current_blockers:
            return self._result(
                verification_id=verification_id,
                execution=execution,
                verification_type=verification_type,
                command_identity=definition.command_identity,
                working_directory=execution.workspace_path,
                status="BLOCKED",
                timestamp=timestamp,
                blockers=current_blockers,
                rollback_recommended=True,
            )

        resolver = getattr(self, definition.resolver_name)
        workspace_root = Path(execution.workspace_path).resolve()
        command, skip_reason = resolver(workspace_root)
        if command is None:
            return self._result(
                verification_id=verification_id,
                execution=execution,
                verification_type=verification_type,
                command_identity=definition.command_identity,
                working_directory=execution.workspace_path,
                status="SKIPPED",
                timestamp=timestamp,
                warnings=[skip_reason or "Verification is not applicable."],
            )

        command_blockers = self._command_blockers(command, workspace_root)
        if command_blockers:
            return self._result(
                verification_id=verification_id,
                execution=execution,
                verification_type=verification_type,
                command_identity=definition.command_identity,
                working_directory=str(command.working_directory),
                status="BLOCKED",
                timestamp=timestamp,
                blockers=command_blockers,
            )

        outcome = self._run_command(command, definition.timeout_seconds)
        blockers = self._changed_file_blockers(execution)
        status = "BLOCKED" if blockers else outcome.status
        rollback_recommended = status in {"FAILED", "TIMED_OUT", "BLOCKED"}
        warnings = [definition.execution_warning] if definition.execution_warning else []
        if outcome.output_truncated:
            warnings.append(
                f"Output was truncated to {self.output_limit_bytes} bytes per stream."
            )
        if outcome.output_redacted:
            warnings.append("Potential credential values were redacted from captured output.")

        return self._result(
            verification_id=verification_id,
            execution=execution,
            verification_type=verification_type,
            command_identity=definition.command_identity,
            working_directory=str(command.working_directory),
            status=status,
            timestamp=timestamp,
            exit_code=outcome.exit_code,
            duration_seconds=outcome.duration_seconds,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            output_truncated=outcome.output_truncated,
            warnings=warnings,
            blockers=blockers,
            rollback_recommended=rollback_recommended,
        )

    def _execution_blockers(self, execution, audit: dict[str, str]) -> list[str]:
        blockers = []
        if execution.status != "EXECUTED" or audit["status"] != "EXECUTED":
            blockers.append("Execution status must be EXECUTED before verification.")
            return blockers

        workflow = self.approval_store.get_workflow(execution.workflow_id)
        recomputed = self.approval_store.plan_fingerprint(
            planner_output=workflow.planner_output,
            reviewer_output=workflow.reviewer_output,
            validator_output=workflow.validator_output,
        )
        if workflow.approval_status != "APPROVED":
            blockers.append("Workflow is no longer approved.")
        if audit["workflow_id"] != workflow.workflow_id:
            blockers.append("Execution workflow linkage is invalid.")
        if audit["plan_fingerprint"] != workflow.plan_fingerprint:
            blockers.append("Execution plan fingerprint does not match the workflow.")
        if workflow.plan_fingerprint != recomputed:
            blockers.append("Persisted workflow fingerprint is stale or invalid.")

        workspace_paths = [
            workflow.workspace_path,
            execution.workspace_path,
            audit["workspace_path"],
        ]
        if any(path is None for path in workspace_paths):
            blockers.append("Approved workspace linkage is incomplete.")
        else:
            resolved = {str(Path(path).resolve()) for path in workspace_paths if path}
            if len(resolved) != 1:
                blockers.append("Execution workspace does not match the approved workspace.")
            else:
                try:
                    self.workspace_service.open_workspace(execution.workspace_path)
                except WorkspaceNotFoundError:
                    blockers.append("Approved execution workspace is missing or invalid.")

        persisted_files = self.execution_store.get_execution_files(execution.execution_id)
        if [item.model_dump(mode="json") for item in persisted_files] != [
            item.model_dump(mode="json") for item in execution.file_results
        ]:
            blockers.append("Execution file audit does not match the persisted execution result.")
        if execution.files_changed != [item.relative_path for item in execution.file_results]:
            blockers.append("Execution changed-file list does not match its file audit.")
        return blockers

    def _changed_file_blockers(self, execution) -> list[str]:
        blockers = []
        root = Path(self.workspace_service.open_workspace(execution.workspace_path).root_path)
        for result in execution.file_results:
            try:
                target = self.workspace_service._resolve_child_path(root, result.relative_path)
            except WorkspaceAccessError:
                blockers.append(f"Changed file path is outside the approved workspace: {result.relative_path}")
                continue
            if self.workspace_service._is_ignored_path(target):
                blockers.append(f"Changed file path is blocked by workspace policy: {result.relative_path}")
                continue
            if not target.is_file():
                blockers.append(f"Changed file is missing: {result.relative_path}")
                continue
            current_hash = hashlib.sha256(target.read_bytes()).hexdigest()
            if current_hash != result.final_content_hash:
                blockers.append(f"Changed file no longer matches execution audit: {result.relative_path}")
        return blockers

    def _resolve_python_compile(self, root: Path):
        context = self.workspace_service.summarize_context(str(root))
        if context.detected_languages.get("Python", 0) == 0:
            return None, "No visible Python files were detected."
        return VerificationCommand(
            arguments=[sys.executable, "-I", "-c", PYTHON_COMPILE_SCRIPT],
            working_directory=root,
        ), None

    def _resolve_pytest(self, root: Path):
        context = self.workspace_service.summarize_context(str(root))
        if context.detected_languages.get("Python", 0) == 0:
            return None, "No visible Python files were detected."
        test_root = self._python_test_root(root, context)
        if test_root is None:
            return None, "No pytest test directory or test modules were detected."
        if importlib.util.find_spec("pytest") is None:
            return None, "The fixed DevLoopAI Python runtime does not provide pytest."
        return VerificationCommand(
            arguments=[sys.executable, "-m", "pytest", "-q"],
            working_directory=test_root,
        ), None

    def _resolve_frontend_lint(self, root: Path):
        return self._resolve_node_cli(
            root=root,
            script_name="lint",
            cli_relative=Path("eslint") / "bin" / "eslint.js",
            fixed_arguments=["."],
        )

    def _resolve_frontend_build(self, root: Path):
        return self._resolve_node_cli(
            root=root,
            script_name="build",
            cli_relative=Path("next") / "dist" / "bin" / "next",
            fixed_arguments=["build"],
        )

    def _resolve_node_cli(
        self,
        *,
        root: Path,
        script_name: str,
        cli_relative: Path,
        fixed_arguments: list[str],
    ):
        node = shutil.which("node")
        if node is None:
            return None, "Node.js executable is not available."
        manifest = self._package_manifest_for_script(root, script_name)
        if manifest is None:
            return None, f"No visible package.json defines the {script_name} script."
        cli = self._find_local_node_cli(root, manifest.parent, cli_relative)
        if cli is None:
            return None, f"The fixed local {cli_relative.parts[0]} CLI is not installed."
        return VerificationCommand(
            arguments=[str(Path(node).resolve()), str(cli), *fixed_arguments],
            working_directory=manifest.parent,
        ), None

    def _package_manifest_for_script(self, root: Path, script_name: str) -> Path | None:
        context = self.workspace_service.summarize_context(str(root))
        manifests = [
            root / item.manifest
            for item in context.dependency_metadata
            if Path(item.manifest).name == "package.json"
        ]
        for manifest in sorted(set(manifests), key=lambda path: (len(path.parts), str(path))):
            try:
                relative = manifest.resolve().relative_to(root).as_posix()
                content = self.workspace_service.read_text_file(str(root), relative).content
                scripts = json.loads(content).get("scripts", {})
            except (ValueError, json.JSONDecodeError, AttributeError):
                continue
            if isinstance(scripts, dict) and isinstance(scripts.get(script_name), str):
                return manifest.resolve()
        return None

    def _find_local_node_cli(self, root: Path, start: Path, relative: Path) -> Path | None:
        current = start.resolve()
        while current == root or root in current.parents:
            candidate = current / "node_modules" / relative
            if candidate.is_file():
                resolved = candidate.resolve()
                if resolved == root or root in resolved.parents:
                    return resolved
            if current == root:
                break
            current = current.parent
        return None

    def _python_test_root(self, root: Path, context) -> Path | None:
        candidates = [root]
        for config in context.important_config_files:
            path = (root / config).resolve()
            if path.name in {"requirements.txt", "pyproject.toml", "pytest.ini"}:
                candidates.append(path.parent)
        for candidate in sorted(set(candidates), key=lambda path: (-len(path.parts), str(path))):
            if (candidate / "tests").is_dir() or any(candidate.glob("test_*.py")):
                return candidate
        return None

    def _run_command(self, command: VerificationCommand, timeout: float) -> ProcessOutcome:
        started = time.perf_counter()
        popen_kwargs = {
            "args": command.arguments,
            "cwd": str(command.working_directory),
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "shell": False,
            "env": self._safe_environment(),
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            popen_kwargs["start_new_session"] = True

        try:
            process = subprocess.Popen(**popen_kwargs)
        except OSError as exc:
            return ProcessOutcome(
                status="SKIPPED",
                exit_code=None,
                duration_seconds=round(time.perf_counter() - started, 3),
                stdout="",
                stderr=str(exc),
                output_truncated=False,
                output_redacted=False,
            )

        stdout_reader = _BoundedReader(process.stdout, self.output_limit_bytes)
        stderr_reader = _BoundedReader(process.stderr, self.output_limit_bytes)
        stdout_reader.start()
        stderr_reader.start()
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            self._terminate_process(process)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        finally:
            stdout_reader.join(timeout=5)
            stderr_reader.join(timeout=5)

        duration = round(time.perf_counter() - started, 3)
        status = "TIMED_OUT" if timed_out else ("PASSED" if process.returncode == 0 else "FAILED")
        stdout, stdout_redacted = self._redact_output(stdout_reader.text())
        stderr, stderr_redacted = self._redact_output(stderr_reader.text())
        return ProcessOutcome(
            status=status,
            exit_code=None if timed_out else process.returncode,
            duration_seconds=duration,
            stdout=stdout,
            stderr=stderr,
            output_truncated=stdout_reader.truncated or stderr_reader.truncated,
            output_redacted=stdout_redacted or stderr_redacted,
        )

    def _command_blockers(
        self,
        command: VerificationCommand,
        workspace_root: Path,
    ) -> list[str]:
        blockers = []
        working_directory = command.working_directory.resolve()
        if working_directory != workspace_root and workspace_root not in working_directory.parents:
            blockers.append("Verification working directory is outside the approved workspace.")
        if not working_directory.is_dir():
            blockers.append("Verification working directory is missing or invalid.")
        if not command.arguments or not Path(command.arguments[0]).is_absolute():
            blockers.append("Verification executable is not a fixed absolute path.")
        return blockers

    def _terminate_process(self, process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                timeout=5,
                check=False,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)

    def _safe_environment(self) -> dict[str, str]:
        allowed = {
            "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
            "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
        }
        environment = {key: value for key, value in os.environ.items() if key.upper() in allowed}
        environment.update(
            {
                "PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1",
                "NO_COLOR": "1",
                "CI": "1",
                "NEXT_TELEMETRY_DISABLED": "1",
                "NPM_CONFIG_IGNORE_SCRIPTS": "true",
                "NPM_CONFIG_OFFLINE": "true",
                "YARN_ENABLE_SCRIPTS": "false",
                "YARN_ENABLE_NETWORK": "false",
                "PNPM_CONFIG_IGNORE_SCRIPTS": "true",
                "PNPM_CONFIG_OFFLINE": "true",
            }
        )
        return environment

    def _redact_output(self, value: str) -> tuple[str, bool]:
        patterns = [
            re.compile(
                r"(?i)\b(api[_-]?key|access[_-]?token|token|secret|password)"
                r"\s*[:=]\s*([^\s,;]+)"
            ),
            re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*"),
            re.compile(r"\b(?:sk|ghp|github_pat)_[A-Za-z0-9_\-]{12,}\b"),
        ]
        redacted = value
        for pattern in patterns:
            if pattern.pattern.startswith("(?i)\\b(api"):
                redacted = pattern.sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
            else:
                redacted = pattern.sub("[REDACTED]", redacted)
        return redacted, redacted != value

    def _result(
        self,
        *,
        verification_id: str,
        execution,
        verification_type: str,
        command_identity: str,
        working_directory: str,
        status: str,
        timestamp: str,
        exit_code: int | None = None,
        duration_seconds: float = 0,
        stdout: str = "",
        stderr: str = "",
        output_truncated: bool = False,
        rollback_recommended: bool = False,
        warnings: list[str] | None = None,
        blockers: list[str] | None = None,
    ) -> ExecutionVerificationResult:
        return ExecutionVerificationResult(
            verification_id=verification_id,
            execution_id=execution.execution_id,
            workflow_id=execution.workflow_id,
            verification_type=verification_type,
            command_identity=command_identity,
            working_directory=working_directory,
            status=status,
            exit_code=exit_code,
            duration_seconds=duration_seconds,
            stdout_excerpt=stdout,
            stderr_excerpt=stderr,
            output_truncated=output_truncated,
            timestamp=timestamp,
            rollback_recommended=rollback_recommended,
            changed_files=list(execution.files_changed),
            warnings=warnings or [],
            blockers=blockers or [],
        )

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
