import subprocess
from pathlib import Path

from app.models.git_status import GitChangedFile, GitCommitSummary, GitStatusRequest, GitStatusResponse
from app.services.execution_store import ExecutionRecordNotFoundError, ExecutionStore
from app.services.workspace import WorkspaceService


class GitStatusService:
    """Read-only Git status/diff integration using fixed command templates."""

    timeout_seconds = 8
    output_limit = 120000

    def __init__(
        self,
        *,
        workspace_service: WorkspaceService,
        execution_store: ExecutionStore | None = None,
    ) -> None:
        self.workspace_service = workspace_service
        self.execution_store = execution_store

    def status(self, request: GitStatusRequest) -> GitStatusResponse:
        workspace = self.workspace_service.open_workspace(request.workspace_path)
        root = Path(workspace.root_path)
        warnings: list[str] = []
        blockers: list[str] = []

        inside = self._run(root, ["rev-parse", "--is-inside-work-tree"])
        if inside.returncode != 0 or inside.stdout.strip() != "true":
            return GitStatusResponse(
                workspace_path=str(root),
                is_git_repository=False,
                warnings=["Workspace is not a Git repository."],
            )

        branch = self._run(root, ["branch", "--show-current"]).stdout.strip() or None
        porcelain = self._run(root, ["status", "--porcelain=v1", "--untracked-files=all"])
        if porcelain.returncode != 0:
            blockers.append("Git status could not be read.")

        all_changed_files = self._parse_porcelain(porcelain.stdout)
        changed_files = [
            item for item in all_changed_files if self._is_safe_git_path(root, item.relative_path)
        ]
        restricted_count = len(all_changed_files) - len(changed_files)
        if restricted_count:
            warnings.append(
                f"{restricted_count} restricted changed file(s) were hidden by workspace safety policy."
            )
        staged = [
            item.relative_path
            for item in changed_files
            if item.index_status not in {" ", "?"}
        ]
        unstaged = [
            item.relative_path
            for item in changed_files
            if item.worktree_status not in {" ", "?"}
        ]
        untracked = [item.relative_path for item in changed_files if item.index_status == "?"]
        if restricted_count:
            diff_summary = ""
            diff_excerpt = ""
            diff_truncated = False
            warnings.append("Diff output was suppressed because restricted files have changes.")
        else:
            diff_summary = self._run(root, ["diff", "--no-ext-diff", "--no-textconv", "--stat"]).stdout
            diff = self._run(root, ["diff", "--no-ext-diff", "--no-textconv", "--", "."]).stdout
            diff_excerpt = diff[: request.max_diff_chars]
            diff_truncated = len(diff) > request.max_diff_chars
        recent_commits = self._recent_commits(root)
        audit_files = self._execution_audit_files(request.execution_id)
        unexpected = []

        if audit_files:
            changed_set = {item.relative_path for item in changed_files}
            audit_set = set(audit_files)
            unexpected = sorted(changed_set - audit_set)

        return GitStatusResponse(
            workspace_path=str(root),
            is_git_repository=True,
            current_branch=branch,
            changed_files=changed_files,
            changed_file_count=len(changed_files),
            restricted_changed_file_count=restricted_count,
            staged_files=staged,
            unstaged_files=unstaged,
            untracked_files=untracked,
            diff_summary=diff_summary[: request.max_diff_chars],
            diff_excerpt=diff_excerpt,
            diff_truncated=diff_truncated,
            recent_commits=recent_commits,
            execution_id=request.execution_id,
            execution_audit_files=audit_files,
            unexpected_changed_files=unexpected,
            warnings=warnings,
            blockers=blockers,
        )

    def _run(self, root: Path, args: list[str]):
        return subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=self.timeout_seconds,
            shell=False,
            check=False,
        )

    def _parse_porcelain(self, output: str) -> list[GitChangedFile]:
        files: list[GitChangedFile] = []
        for line in output.splitlines():
            if len(line) < 4:
                continue
            index_status = line[0]
            worktree_status = line[1]
            path = line[3:]
            if " -> " in path:
                path = path.split(" -> ", 1)[1]
            files.append(
                GitChangedFile(
                    relative_path=path.replace("\\", "/"),
                    index_status=index_status,
                    worktree_status=worktree_status,
                )
            )
        return files

    def _is_safe_git_path(self, root: Path, relative_path: str) -> bool:
        try:
            self.workspace_service._resolve_child_path(root, relative_path)
        except Exception:
            return False
        return True

    def _recent_commits(self, root: Path) -> list[GitCommitSummary]:
        result = self._run(root, ["log", "-5", "--pretty=format:%h%x00%s"])
        if result.returncode != 0:
            return []

        commits = []
        for line in result.stdout.splitlines():
            parts = line.split("\x00", 1)
            if len(parts) != 2:
                continue
            commits.append(GitCommitSummary(commit=parts[0], subject=parts[1]))
        return commits

    def _execution_audit_files(self, execution_id: str | None) -> list[str]:
        if not execution_id or self.execution_store is None:
            return []

        try:
            execution = self.execution_store.get_execution(execution_id)
        except ExecutionRecordNotFoundError:
            return []

        return sorted({item.relative_path for item in execution.file_results})
