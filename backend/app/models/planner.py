from typing import Any

from pydantic import BaseModel, Field

from app.models.workspace import WorkspaceContextSummary


class PlannerRequest(BaseModel):
    """
    Request body for asking the read-only Planner Agent for a plan.
    """
    task: str = Field(..., min_length=1)
    workspace_path: str | None = None
    project_context: WorkspaceContextSummary | None = None
    constraints: list[str] = Field(default_factory=list)
    model: str | None = None


class PlannerProjectContext(BaseModel):
    """
    Compact project context surfaced in the planner response.
    """
    workspace_name: str | None = None
    project_types: list[str] = Field(default_factory=list)
    frameworks: list[str] = Field(default_factory=list)
    languages: dict[str, int] = Field(default_factory=dict)


class PlannerResponse(BaseModel):
    """
    Structured implementation plan returned by the Planner Agent.
    """
    task_summary: str
    assumptions: list[str] = Field(default_factory=list)
    detected_project_context: PlannerProjectContext
    implementation_steps: list[str] = Field(default_factory=list)
    files_likely_to_change: list[str] = Field(default_factory=list)
    tests_verification_required: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    dependencies_or_user_input_needed: list[str] = Field(default_factory=list)
    model: str
    raw_model_response: str | None = None


class PlannerModelPayload(BaseModel):
    """
    Strict shape expected from the model before backend normalization.
    """
    task_summary: str
    assumptions: list[str] = Field(default_factory=list)
    implementation_steps: list[str] = Field(default_factory=list)
    files_likely_to_change: list[str] = Field(default_factory=list)
    tests_verification_required: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    dependencies_or_user_input_needed: list[str] = Field(default_factory=list)


def safe_context_payload(context: WorkspaceContextSummary | None) -> dict[str, Any] | None:
    """
    Convert project context into the compact payload allowed in planner prompts.
    """
    if context is None:
        return None

    return {
        "workspace_name": context.workspace.name,
        "project_types": context.project_types,
        "frameworks": context.frameworks,
        "important_config_files": context.important_config_files,
        "important_source_directories": context.important_source_directories,
        "likely_entry_points": context.likely_entry_points,
        "detected_languages": context.detected_languages,
        "file_count": context.file_count,
        "directory_count": context.directory_count,
        "dependency_manifests": [
            {
                "manifest": metadata.manifest,
                "package_name": metadata.package_name,
                "dependencies": metadata.dependencies,
                "dev_dependencies": metadata.dev_dependencies,
            }
            for metadata in context.dependency_metadata
        ],
        "git": {
            "present": context.git.present,
            "current_branch": context.git.current_branch,
            "remotes": context.git.remotes,
        },
        "warnings": context.warnings,
    }
