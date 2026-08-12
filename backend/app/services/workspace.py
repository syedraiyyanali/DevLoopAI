from pathlib import Path

from app.models.workspace import (
    WorkspaceEntry,
    WorkspaceFileContent,
    WorkspaceListResponse,
    WorkspaceMetadata,
)


class WorkspaceError(Exception):
    """
    Base error for workspace access failures.
    """


class WorkspaceNotFoundError(WorkspaceError):
    """
    Raised when the requested workspace root is invalid.
    """


class WorkspaceAccessError(WorkspaceError):
    """
    Raised when a path is outside the selected workspace or blocked by policy.
    """


class WorkspaceUnsupportedFileError(WorkspaceError):
    """
    Raised when a file cannot be safely read as small text.
    """


class WorkspaceService:
    """
    Read-only filesystem access for a selected local development workspace.
    """

    ignored_directories = {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".next",
        ".nuxt",
        ".cache",
        "node_modules",
        "dist",
        "build",
        "coverage",
    }
    blocked_file_names = {
        ".env",
        ".env.local",
        ".env.development",
        ".env.production",
        ".env.test",
        "id_rsa",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
    }
    blocked_suffixes = {
        ".key",
        ".pem",
        ".p12",
        ".pfx",
        ".crt",
    }
    max_read_bytes = 256 * 1024
    binary_probe_bytes = 4096

    def open_workspace(self, workspace_path: str) -> WorkspaceMetadata:
        """
        Validate and return metadata for a workspace root.
        """
        root = self._resolve_workspace_root(workspace_path)

        return self._metadata(root)

    def list_directory(
        self,
        workspace_path: str,
        relative_path: str = "",
    ) -> WorkspaceListResponse:
        """
        Return safe visible entries inside a workspace directory.
        """
        root = self._resolve_workspace_root(workspace_path)
        target = self._resolve_child_path(root, relative_path)

        if not target.is_dir():
            raise WorkspaceNotFoundError("Workspace path is not a directory")

        entries = [
            self._entry_for(root, child)
            for child in sorted(target.iterdir(), key=self._sort_key)
            if not self._is_ignored_path(child)
        ]

        return WorkspaceListResponse(
            workspace=self._metadata(root),
            relative_path=self._relative_path(root, target),
            entries=entries,
        )

    def read_text_file(
        self,
        workspace_path: str,
        relative_path: str,
    ) -> WorkspaceFileContent:
        """
        Read a small UTF-8 text file inside a selected workspace.
        """
        root = self._resolve_workspace_root(workspace_path)
        target = self._resolve_child_path(root, relative_path)

        if self._is_ignored_path(target):
            raise WorkspaceAccessError("File is blocked by workspace safety rules")

        if not target.is_file():
            raise WorkspaceNotFoundError("Workspace file was not found")

        size_bytes = target.stat().st_size

        if size_bytes > self.max_read_bytes:
            raise WorkspaceUnsupportedFileError("File is too large to read safely")

        probe = target.read_bytes()

        if b"\0" in probe[: self.binary_probe_bytes]:
            raise WorkspaceUnsupportedFileError("Binary files cannot be read")

        try:
            content = probe.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WorkspaceUnsupportedFileError(
                "File is not valid UTF-8 text"
            ) from exc

        return WorkspaceFileContent(
            workspace=self._metadata(root),
            relative_path=self._relative_path(root, target),
            content=content,
            size_bytes=size_bytes,
            truncated=False,
        )

    def _resolve_workspace_root(self, workspace_path: str) -> Path:
        root = Path(workspace_path).expanduser().resolve()

        if not root.exists() or not root.is_dir():
            raise WorkspaceNotFoundError("Workspace path must be an existing directory")

        return root

    def _resolve_child_path(self, root: Path, relative_path: str) -> Path:
        raw_relative_path = relative_path.strip()
        child = (root / raw_relative_path).resolve()

        if child != root and root not in child.parents:
            raise WorkspaceAccessError("Path escapes the selected workspace")

        if any(self._is_ignored_part(part) for part in child.relative_to(root).parts):
            raise WorkspaceAccessError("Path is blocked by workspace safety rules")

        return child

    def _metadata(self, root: Path) -> WorkspaceMetadata:
        return WorkspaceMetadata(
            name=root.name,
            root_path=str(root),
            total_visible_entries=sum(
                1 for child in root.iterdir() if not self._is_ignored_path(child)
            ),
        )

    def _entry_for(self, root: Path, child: Path) -> WorkspaceEntry:
        kind = "directory" if child.is_dir() else "file"
        size_bytes = None if child.is_dir() else child.stat().st_size

        return WorkspaceEntry(
            name=child.name,
            relative_path=self._relative_path(root, child),
            kind=kind,
            size_bytes=size_bytes,
        )

    def _relative_path(self, root: Path, child: Path) -> str:
        if child == root:
            return ""

        return child.relative_to(root).as_posix()

    def _sort_key(self, child: Path) -> tuple[int, str]:
        return (0 if child.is_dir() else 1, child.name.lower())

    def _is_ignored_path(self, path: Path) -> bool:
        return self._is_ignored_part(path.name)

    def _is_ignored_part(self, name: str) -> bool:
        normalized_name = name.lower()

        if normalized_name in self.ignored_directories:
            return True

        if normalized_name in self.blocked_file_names:
            return True

        if normalized_name.startswith(".env."):
            return True

        if normalized_name.startswith("secrets."):
            return True

        return any(normalized_name.endswith(suffix) for suffix in self.blocked_suffixes)
