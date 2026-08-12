import configparser
import json
from pathlib import Path
from typing import Any

from app.models.workspace import (
    WorkspaceContextSummary,
    WorkspaceDependencySummary,
    WorkspaceEntry,
    WorkspaceFileContent,
    WorkspaceGitSummary,
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
    max_context_files = 5000
    readme_excerpt_chars = 1200
    package_sample_limit = 30
    extension_language_map = {
        ".py": "Python",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".json": "JSON",
        ".md": "Markdown",
        ".html": "HTML",
        ".css": "CSS",
        ".scss": "SCSS",
        ".php": "PHP",
        ".go": "Go",
        ".rs": "Rust",
        ".java": "Java",
        ".cs": "C#",
        ".yml": "YAML",
        ".yaml": "YAML",
        ".toml": "TOML",
    }
    important_config_names = {
        "package.json",
        "package-lock.json",
        "pnpm-lock.yaml",
        "yarn.lock",
        "requirements.txt",
        "pyproject.toml",
        "poetry.lock",
        "Pipfile",
        "next.config.js",
        "next.config.mjs",
        "next.config.ts",
        "vite.config.js",
        "vite.config.ts",
        "tsconfig.json",
        "tailwind.config.js",
        "tailwind.config.ts",
        "postcss.config.js",
        "postcss.config.mjs",
        "docker-compose.yml",
        "Dockerfile",
    }
    source_directory_names = {
        "app",
        "src",
        "pages",
        "components",
        "lib",
        "backend",
        "frontend",
        "api",
        "tests",
    }
    likely_entry_names = {
        "main.py",
        "app.py",
        "server.py",
        "manage.py",
        "index.js",
        "index.ts",
        "main.js",
        "main.ts",
        "page.tsx",
        "layout.tsx",
        "App.tsx",
        "App.jsx",
    }

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

    def summarize_context(self, workspace_path: str) -> WorkspaceContextSummary:
        """
        Build a compact deterministic summary for future agent context.
        """
        root = self._resolve_workspace_root(workspace_path)
        warnings: list[str] = []
        visible_files: list[Path] = []
        visible_directories: list[Path] = []

        for child in self._walk_visible(root):
            if child.is_dir():
                visible_directories.append(child)
                continue

            visible_files.append(child)

            if len(visible_files) >= self.max_context_files:
                warnings.append(
                    f"Context scan stopped after {self.max_context_files} files."
                )
                break

        detected_languages = self._detect_languages(visible_files)
        important_config_files = self._detect_config_files(root, visible_files)
        important_source_directories = self._detect_source_directories(
            root,
            visible_directories,
        )
        dependency_metadata = self._detect_dependency_metadata(root, visible_files)
        project_types, frameworks = self._detect_project_types(
            root,
            visible_files,
            dependency_metadata,
        )

        if not visible_files:
            warnings.append("No visible files were found in the workspace.")

        return WorkspaceContextSummary(
            workspace=self._metadata(root),
            project_types=project_types,
            frameworks=frameworks,
            important_config_files=important_config_files,
            important_source_directories=important_source_directories,
            likely_entry_points=self._detect_entry_points(root, visible_files),
            detected_languages=detected_languages,
            file_count=len(visible_files),
            directory_count=len(visible_directories),
            dependency_metadata=dependency_metadata,
            git=self._detect_git_metadata(root),
            readme_excerpt=self._read_readme_excerpt(root),
            ignored_directories=sorted(self.ignored_directories),
            warnings=warnings,
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

    def _walk_visible(self, root: Path):
        for child in sorted(root.rglob("*"), key=lambda path: path.as_posix().lower()):
            relative_parts = child.relative_to(root).parts

            if any(self._is_ignored_part(part) for part in relative_parts):
                continue

            yield child

    def _detect_languages(self, files: list[Path]) -> dict[str, int]:
        languages: dict[str, int] = {}

        for file_path in files:
            language = self.extension_language_map.get(file_path.suffix.lower())

            if language is None:
                continue

            languages[language] = languages.get(language, 0) + 1

        return dict(sorted(languages.items()))

    def _detect_config_files(self, root: Path, files: list[Path]) -> list[str]:
        config_files = [
            self._relative_path(root, file_path)
            for file_path in files
            if file_path.name in self.important_config_names
        ]

        return sorted(config_files)

    def _detect_source_directories(
        self,
        root: Path,
        directories: list[Path],
    ) -> list[str]:
        source_directories = [
            self._relative_path(root, directory)
            for directory in directories
            if directory.name in self.source_directory_names
        ]

        return sorted(source_directories)

    def _detect_entry_points(self, root: Path, files: list[Path]) -> list[str]:
        entry_points = [
            self._relative_path(root, file_path)
            for file_path in files
            if file_path.name in self.likely_entry_names
        ]

        return sorted(entry_points)

    def _detect_dependency_metadata(
        self,
        root: Path,
        files: list[Path],
    ) -> list[WorkspaceDependencySummary]:
        dependency_metadata: list[WorkspaceDependencySummary] = []

        for manifest in files:
            if manifest.name == "package.json":
                package_summary = self._read_package_json(root, manifest)

                if package_summary is not None:
                    dependency_metadata.append(package_summary)

            if manifest.name == "requirements.txt":
                requirements_summary = self._read_requirements(root, manifest)

                if requirements_summary is not None:
                    dependency_metadata.append(requirements_summary)

        return dependency_metadata

    def _read_package_json(
        self,
        root: Path,
        package_json: Path,
    ) -> WorkspaceDependencySummary | None:
        try:
            package_content = self.read_text_file(
                str(root),
                self._relative_path(root, package_json),
            ).content
            payload = json.loads(package_content)
        except (WorkspaceError, json.JSONDecodeError):
            return None

        if not isinstance(payload, dict):
            return None

        dependencies = self._dependency_names(payload.get("dependencies"))
        dev_dependencies = self._dependency_names(payload.get("devDependencies"))
        package_name = payload.get("name") if isinstance(payload.get("name"), str) else None

        return WorkspaceDependencySummary(
            manifest=self._relative_path(root, package_json),
            package_name=package_name,
            dependencies=dependencies[: self.package_sample_limit],
            dev_dependencies=dev_dependencies[: self.package_sample_limit],
        )

    def _read_requirements(
        self,
        root: Path,
        requirements_file: Path,
    ) -> WorkspaceDependencySummary | None:
        try:
            requirements_content = self.read_text_file(
                str(root),
                self._relative_path(root, requirements_file),
            ).content
        except WorkspaceError:
            return None

        dependencies = []

        for line in requirements_content.splitlines():
            cleaned_line = line.strip()

            if not cleaned_line or cleaned_line.startswith("#") or cleaned_line.startswith("-"):
                continue

            package_name = (
                cleaned_line.split("==")[0]
                .split(">=")[0]
                .split("<=")[0]
                .split("~=")[0]
                .strip()
            )

            if package_name:
                dependencies.append(package_name)

        return WorkspaceDependencySummary(
            manifest=self._relative_path(root, requirements_file),
            dependencies=dependencies[: self.package_sample_limit],
        )

    def _dependency_names(self, dependencies: Any) -> list[str]:
        if not isinstance(dependencies, dict):
            return []

        return sorted(name for name in dependencies if isinstance(name, str))

    def _detect_project_types(
        self,
        root: Path,
        files: list[Path],
        dependency_metadata: list[WorkspaceDependencySummary],
    ) -> tuple[list[str], list[str]]:
        file_names = {file_path.name for file_path in files}
        dependency_names = {
            dependency
            for metadata in dependency_metadata
            for dependency in [*metadata.dependencies, *metadata.dev_dependencies]
        }
        project_types: set[str] = set()
        frameworks: set[str] = set()

        if "package.json" in file_names:
            project_types.add("Node.js")

        if "next" in dependency_names or any(
            (root / config_file).exists()
            for config_file in ("next.config.js", "next.config.mjs", "next.config.ts")
        ):
            frameworks.add("Next.js")

        if any(file_path.suffix == ".py" for file_path in files):
            project_types.add("Python")

        if "fastapi" in dependency_names:
            frameworks.add("FastAPI")

        if "pyproject.toml" in file_names:
            project_types.add("Python")

        if not project_types:
            project_types.add("Generic")

        return sorted(project_types), sorted(frameworks)

    def _detect_git_metadata(self, root: Path) -> WorkspaceGitSummary:
        git_dir = root / ".git"

        if not git_dir.exists() or not git_dir.is_dir():
            return WorkspaceGitSummary(present=False)

        return WorkspaceGitSummary(
            present=True,
            current_branch=self._read_git_branch(git_dir),
            remotes=self._read_git_remotes(git_dir),
        )

    def _read_git_branch(self, git_dir: Path) -> str | None:
        head_file = git_dir / "HEAD"

        try:
            head = head_file.read_text(encoding="utf-8").strip()
        except OSError:
            return None

        if head.startswith("ref: refs/heads/"):
            return head.removeprefix("ref: refs/heads/")

        if head:
            return "detached"

        return None

    def _read_git_remotes(self, git_dir: Path) -> list[str]:
        config_file = git_dir / "config"

        if not config_file.exists():
            return []

        parser = configparser.ConfigParser()

        try:
            parser.read(config_file, encoding="utf-8")
        except configparser.Error:
            return []

        remotes = []

        for section in parser.sections():
            if section.startswith('remote "') and section.endswith('"'):
                remotes.append(section.removeprefix('remote "').removesuffix('"'))

        return sorted(remotes)

    def _read_readme_excerpt(self, root: Path) -> str | None:
        readme_candidates = sorted(root.glob("README*"), key=lambda path: path.name.lower())

        for readme_path in readme_candidates:
            if not readme_path.is_file() or self._is_ignored_path(readme_path):
                continue

            try:
                content = self.read_text_file(
                    str(root),
                    self._relative_path(root, readme_path),
                ).content.strip()
            except WorkspaceError:
                continue

            if content:
                return content[: self.readme_excerpt_chars]

        return None
