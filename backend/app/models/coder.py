from pydantic import BaseModel, Field

from app.models.execution_handoff import AllowedOperationType, ExecutionHandoffResponse


class CoderDryRunRequest(BaseModel):
    """
    Request body for simulating Coding Agent work from an approved handoff.
    """
    handoff: ExecutionHandoffResponse
    model: str | None = None


class CoderDryRunOperation(BaseModel):
    """
    One intended operation the future Coding Agent would perform.
    """
    operation_type: AllowedOperationType
    relative_path: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    rationale: str = ""


class CoderDryRunModelPayload(BaseModel):
    """
    Strict model proposal shape before backend normalization.
    """
    files_to_modify: list[str] = Field(default_factory=list)
    files_to_create: list[str] = Field(default_factory=list)
    files_to_delete: list[str] = Field(default_factory=list)
    intended_operations: list[CoderDryRunOperation] = Field(default_factory=list)
    proposed_code_change_summary: str
    dependencies_required: list[str] = Field(default_factory=list)
    tests_to_run: list[str] = Field(default_factory=list)
    rollback_backup_plan: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)


class CoderDryRunResponse(BaseModel):
    """
    Zero-write Coding Agent simulation result.
    """
    workflow_id: str
    approved_plan_fingerprint: str
    workspace_path: str
    files_would_modify: list[str] = Field(default_factory=list)
    files_would_create: list[str] = Field(default_factory=list)
    files_would_delete: list[str] = Field(default_factory=list)
    intended_operations: list[CoderDryRunOperation] = Field(default_factory=list)
    proposed_code_change_summary: str
    dependencies_required: list[str] = Field(default_factory=list)
    tests_to_run: list[str] = Field(default_factory=list)
    rollback_backup_plan: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    model: str
    execution_performed: bool = False
    mutation_capabilities_enabled: bool = False
    message: str
