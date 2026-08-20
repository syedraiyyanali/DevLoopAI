from pathlib import Path

from app.models.context_selection import (
    ContextSelectionRequest,
    ContextSelectionResponse,
    SelectedContextFile,
)
from app.services.workspace import (
    WorkspaceAccessError,
    WorkspaceNotFoundError,
    WorkspaceService,
    WorkspaceUnsupportedFileError,
)


class ContextSelectionService:
    """Deterministically selects bounded safe project context for coding proposals."""

    config_names = {
        "package.json",
        "requirements.txt",
        "pyproject.toml",
        "tsconfig.json",
        "next.config.js",
        "next.config.mjs",
        "next.config.ts",
    }
    test_markers = ("test", "spec")
    source_suffixes = {".py", ".js", ".jsx", ".ts", ".tsx", ".css", ".html", ".md", ".json"}

    def __init__(self, workspace_service: WorkspaceService) -> None:
        self.workspace_service = workspace_service

    def select(self, request: ContextSelectionRequest) -> ContextSelectionResponse:
        root = Path(self.workspace_service.open_workspace(request.workspace_path).root_path)
        candidates = self._candidate_paths(root, request)
        selected: list[SelectedContextFile] = []
        skipped: list[SelectedContextFile] = []
        total_bytes = 0
        warnings: list[str] = []

        for relative_path, reason in candidates:
            if len(selected) >= request.max_files:
                skipped.append(
                    SelectedContextFile(
                        relative_path=relative_path,
                        reason=reason,
                        skipped=True,
                        warning="Context file limit reached.",
                    )
                )
                continue

            try:
                file_content = self.workspace_service.read_text_file(
                    request.workspace_path,
                    relative_path,
                )
            except (WorkspaceAccessError, WorkspaceNotFoundError, WorkspaceUnsupportedFileError) as exc:
                skipped.append(
                    SelectedContextFile(
                        relative_path=relative_path,
                        reason=reason,
                        skipped=True,
                        warning=str(exc),
                    )
                )
                continue

            remaining = request.max_total_bytes - total_bytes
            if remaining <= 0:
                skipped.append(
                    SelectedContextFile(
                        relative_path=relative_path,
                        reason=reason,
                        skipped=True,
                        warning="Context byte budget exhausted.",
                    )
                )
                continue

            content = file_content.content
            encoded = content.encode("utf-8")
            truncated = False
            if len(encoded) > request.max_file_bytes:
                content = encoded[: request.max_file_bytes].decode("utf-8", errors="ignore")
                encoded = content.encode("utf-8")
                truncated = True
            if len(encoded) > remaining:
                content = encoded[:remaining].decode("utf-8", errors="ignore")
                encoded = content.encode("utf-8")
                truncated = True

            selected.append(
                SelectedContextFile(
                    relative_path=file_content.relative_path,
                    reason=reason,
                    content=content,
                    size_bytes=file_content.size_bytes,
                    truncated=truncated,
                )
            )
            total_bytes += len(encoded)

        if skipped:
            warnings.append("Some context files were skipped or truncated by safety limits.")

        return ContextSelectionResponse(
            workspace_path=str(root),
            selected_files=selected,
            skipped_files=skipped,
            total_bytes=total_bytes,
            max_files=request.max_files,
            max_total_bytes=request.max_total_bytes,
            warnings=warnings,
        )

    def _candidate_paths(
        self,
        root: Path,
        request: ContextSelectionRequest,
    ) -> list[tuple[str, str]]:
        weighted: dict[str, tuple[int, str]] = {}
        task_terms = self._task_terms(request.task)

        def add(relative_path: str, weight: int, reason: str) -> None:
            normalized = relative_path.replace("\\", "/").strip()
            if not normalized:
                return
            current = weighted.get(normalized)
            if current is None or weight > current[0]:
                weighted[normalized] = (weight, reason)

        for path in request.planned_paths:
            add(path, 100, "Planned file from approved handoff.")
            for related in self._related_test_paths(root, path):
                add(related, 70, "Related test file for a planned source path.")

        if request.project_context is not None:
            for config in request.project_context.important_config_files:
                add(config, 60, "Important project configuration.")
            for entry in request.project_context.likely_entry_points:
                add(entry, 45, "Likely project entry point.")

        for child in self.workspace_service._walk_visible(root):
            if not child.is_file() or child.suffix.lower() not in self.source_suffixes:
                continue
            relative_path = child.relative_to(root).as_posix()
            lowered_name = child.name.lower()
            if child.name in self.config_names:
                add(relative_path, 55, "Detected project configuration.")
            if any(marker in lowered_name for marker in self.test_markers):
                add(relative_path, 40, "Detected test file.")
            if any(term in relative_path.lower() for term in task_terms):
                add(relative_path, 35, "Path matched task text.")

        return [
            (path, reason)
            for path, (_weight, reason) in sorted(
                weighted.items(),
                key=lambda item: (-item[1][0], item[0]),
            )
        ]

    def _related_test_paths(self, root: Path, relative_path: str) -> list[str]:
        source = Path(relative_path.replace("\\", "/"))
        stem = source.stem
        candidates = []
        for child in self.workspace_service._walk_visible(root):
            if not child.is_file():
                continue
            lowered = child.name.lower()
            if stem.lower() in lowered and any(marker in lowered for marker in self.test_markers):
                candidates.append(child.relative_to(root).as_posix())
        return sorted(candidates)

    def _task_terms(self, task: str) -> list[str]:
        return [
            term.lower()
            for term in task.replace("_", " ").replace("-", " ").split()
            if len(term) >= 4
        ][:20]
