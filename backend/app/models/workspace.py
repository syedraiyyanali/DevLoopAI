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
