from pydantic import BaseModel, Field

from app.models.workspace import WorkspaceContextSummary


class SelectedContextFile(BaseModel):
    """One safely selected project-context file for model reasoning."""

    relative_path: str
    reason: str
    content: str | None = None
    size_bytes: int | None = None
    truncated: bool = False
    skipped: bool = False
    warning: str | None = None


class ContextSelectionRequest(BaseModel):
    """Deterministic bounded context-selection input."""

    workspace_path: str
    task: str = ""
    planned_paths: list[str] = Field(default_factory=list)
    project_context: WorkspaceContextSummary | None = None
    max_files: int = Field(default=12, ge=1, le=50)
    max_total_bytes: int = Field(default=48 * 1024, ge=1024, le=256 * 1024)
    max_file_bytes: int = Field(default=16 * 1024, ge=512, le=128 * 1024)


class ContextSelectionResponse(BaseModel):
    """Bounded selected context used by future coding proposals."""

    workspace_path: str
    selected_files: list[SelectedContextFile] = Field(default_factory=list)
    skipped_files: list[SelectedContextFile] = Field(default_factory=list)
    total_bytes: int = 0
    max_files: int
    max_total_bytes: int
    warnings: list[str] = Field(default_factory=list)
