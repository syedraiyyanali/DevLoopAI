from pydantic import BaseModel, Field


class WorkspaceOpenRequest(BaseModel):
    """
    Request body for selecting a local project workspace.
    """
    path: str = Field(..., min_length=1)


class WorkspaceMetadata(BaseModel):
    """
    Basic metadata for a selected local workspace.
    """
    name: str
    root_path: str
    total_visible_entries: int


class WorkspaceListRequest(BaseModel):
    """
    Request body for listing a directory inside a workspace.
    """
    workspace_path: str = Field(..., min_length=1)
    relative_path: str = ""


class WorkspaceEntry(BaseModel):
    """
    Safe file or folder metadata returned from a workspace listing.
    """
    name: str
    relative_path: str
    kind: str
    size_bytes: int | None = None


class WorkspaceListResponse(BaseModel):
    """
    Directory listing inside a selected workspace.
    """
    workspace: WorkspaceMetadata
    relative_path: str
    entries: list[WorkspaceEntry] = Field(default_factory=list)


class WorkspaceReadRequest(BaseModel):
    """
    Request body for reading a text file inside a workspace.
    """
    workspace_path: str = Field(..., min_length=1)
    relative_path: str = Field(..., min_length=1)


class WorkspaceFileContent(BaseModel):
    """
    Safe text-file content returned from a workspace read.
    """
    workspace: WorkspaceMetadata
    relative_path: str
    content: str
    size_bytes: int
    truncated: bool = False


class WorkspaceContextRequest(BaseModel):
    """
    Request body for building a deterministic workspace context summary.
    """
    workspace_path: str = Field(..., min_length=1)


class WorkspaceDependencySummary(BaseModel):
    """
    Safe dependency metadata detected from common project manifests.
    """
    manifest: str
    package_name: str | None = None
    dependencies: list[str] = Field(default_factory=list)
    dev_dependencies: list[str] = Field(default_factory=list)


class WorkspaceGitSummary(BaseModel):
    """
    Safe Git metadata that does not expose repository contents.
    """
    present: bool
    current_branch: str | None = None
    remotes: list[str] = Field(default_factory=list)


class WorkspaceContextSummary(BaseModel):
    """
    Compact deterministic summary of a selected workspace.
    """
    workspace: WorkspaceMetadata
    project_types: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    important_config_files: list[str] = Field(default_factory=list)
    important_source_directories: list[str] = Field(default_factory=list)
    likely_entry_points: list[str] = Field(default_factory=list)
    detected_languages: dict[str, int] = Field(default_factory=dict)
    file_count: int
    directory_count: int
    dependency_metadata: list[WorkspaceDependencySummary] = Field(default_factory=list)
    git: WorkspaceGitSummary
    readme_excerpt: str | None = None
    ignored_directories: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
