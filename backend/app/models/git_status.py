from pydantic import BaseModel, Field


class GitStatusRequest(BaseModel):
    """Read-only Git status request."""

    workspace_path: str = Field(..., min_length=1)
    execution_id: str | None = None
    max_diff_chars: int = Field(default=20000, ge=1000, le=100000)


class GitChangedFile(BaseModel):
    """One changed path from read-only Git status."""

    relative_path: str
    index_status: str
    worktree_status: str


class GitCommitSummary(BaseModel):
    """Recent commit metadata from read-only Git log."""

    commit: str
    subject: str


class GitStatusResponse(BaseModel):
    """Read-only Git status/diff summary."""

    workspace_path: str
    is_git_repository: bool
    current_branch: str | None = None
    changed_files: list[GitChangedFile] = Field(default_factory=list)
    changed_file_count: int = 0
    staged_files: list[str] = Field(default_factory=list)
    unstaged_files: list[str] = Field(default_factory=list)
    untracked_files: list[str] = Field(default_factory=list)
    diff_summary: str = ""
    diff_excerpt: str = ""
    diff_truncated: bool = False
    recent_commits: list[GitCommitSummary] = Field(default_factory=list)
    execution_id: str | None = None
    execution_audit_files: list[str] = Field(default_factory=list)
    unexpected_changed_files: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
