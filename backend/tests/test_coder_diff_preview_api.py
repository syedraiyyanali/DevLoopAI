import json

import pytest
from fastapi.testclient import TestClient

from app.agents.coder import CoderDiffPreviewAgent
from app.api.v1.endpoints import coder as coder_endpoint
from app.main import app
from app.models.chat import ChatResponse
from app.models.coder import CoderDryRunOperation, CoderDryRunResponse
from app.models.execution_handoff import ExecutionHandoffRequest
from app.models.planner import PlannerProjectContext, PlannerResponse
from app.models.planning_workflow import FinalReviewedPlanSummary
from app.models.reviewer import ReviewerResponse
from app.models.validator import ValidatorResponse
from app.services.execution_handoff import ExecutionHandoffService
from app.services.execution_preflight import ExecutionPreflightService
from app.services.planning_approval import PlanningApprovalStore
from app.services.workspace import WorkspaceService


client = TestClient(app, raise_server_exceptions=False)


class FakeOllamaService:
    def __init__(self, payload) -> None:
        self.payload = payload

    async def generate_chat_response(self, chat_request):
        return ChatResponse(
            message=self.payload
            if isinstance(self.payload, str)
            else json.dumps(self.payload),
            model=chat_request.model or "qwen2.5-coder:7b",
        )


@pytest.fixture
def diff_context(tmp_path, monkeypatch):
    store = PlanningApprovalStore(tmp_path / "coder-diff-preview.sqlite3")
    workspace_service = WorkspaceService()
    preflight_service = ExecutionPreflightService(
        approval_store=store,
        workspace_service=workspace_service,
    )
    handoff_service = ExecutionHandoffService(
        approval_store=store,
        workspace_service=workspace_service,
        preflight_service=preflight_service,
    )
    context = {
        "store": store,
        "workspace_service": workspace_service,
        "handoff_service": handoff_service,
        "ollama_payload": valid_diff_payload("src/app.ts", "export const status = 'updated';\n"),
    }

    def get_agent():
        return CoderDiffPreviewAgent(
            ollama_service=FakeOllamaService(context["ollama_payload"]),
            handoff_service=handoff_service,
            workspace_service=workspace_service,
        )

    monkeypatch.setattr(coder_endpoint, "get_coder_diff_preview_agent", get_agent)
    return context


def create_workspace(tmp_path):
    workspace = tmp_path / "sample-project"
    source_dir = workspace / "src"
    source_dir.mkdir(parents=True)
    (workspace / "package.json").write_bytes(
        b'{"dependencies":{"next":"16.2.10"},"devDependencies":{}}'
    )
    (source_dir / "app.ts").write_bytes(b"export const status = 'ready';\n")
    return workspace


def planner_response(paths=None, *, delete=False) -> PlannerResponse:
    return PlannerResponse(
        task_summary=(
            "Delete the approved file."
            if delete
            else "Add a safe status label."
        ),
        assumptions=["The source file exists."],
        detected_project_context=PlannerProjectContext(
            workspace_name="sample-project",
            project_types=["Node.js"],
            frameworks=["Next.js"],
            languages={"TypeScript": 1},
        ),
        implementation_steps=(
            ["Delete src/app.ts."]
            if delete
            else ["Inspect src/app.ts.", "Add the status label."]
        ),
        files_likely_to_change=paths if paths is not None else ["src/app.ts"],
        tests_verification_required=["Run frontend lint."],
        risks=["Keep changes scoped."],
        dependencies_or_user_input_needed=[],
        model="qwen2.5-coder:7b",
    )


def reviewer_response() -> ReviewerResponse:
    return ReviewerResponse(
        overall_assessment="The plan is safe to prepare for execution.",
        missing_steps=[],
        incorrect_assumptions=[],
        architecture_concerns=[],
        security_concerns=[],
        performance_concerns=[],
        testing_gaps=["Run frontend build."],
        unnecessary_changes=[],
        recommended_improvements=[],
        approval_recommendation="APPROVE",
        model="qwen2.5-coder:7b",
    )


def validator_response() -> ValidatorResponse:
    return ValidatorResponse(
        overall_validation_status="READY",
        plan_completeness=["Plan has implementation and verification steps."],
        file_path_validity=["src/app.ts: path exists."],
        dependency_concerns=[],
        environment_tool_requirements=["Run frontend lint."],
        security_concerns=[],
        destructive_operation_warnings=[],
        missing_user_information=[],
        test_verification_readiness=["Run frontend lint."],
        blockers=[],
        final_execution_readiness="Reviewed plan is ready for future execution.",
        model="qwen2.5-coder:7b",
    )


def final_summary() -> FinalReviewedPlanSummary:
    return FinalReviewedPlanSummary(
        final_recommendation="READY",
        final_execution_readiness="Reviewed plan is ready for future execution.",
        execution_ready=False,
        required_changes_before_execution=[],
        blockers=[],
        warnings=[],
        risks=[],
        tests_expected=["Run frontend lint."],
        user_approval_required=True,
        summary="Planner, reviewer, and validator completed.",
    )


def create_handoff(context, workspace, *, paths=None, delete=False):
    store = context["store"]
    gate = store.create_gate(
        task="Add a safe status label.",
        workspace_path=str(workspace),
        planner_output=planner_response(paths, delete=delete),
        reviewer_output=reviewer_response(),
        validator_output=validator_response(),
        final_reviewed_summary=final_summary(),
        blockers=[],
    )
    store.approve(
        approval_id=gate.approval_id,
        approval_token=gate.approval_token,
        plan_fingerprint=gate.plan_fingerprint,
    )
    return context["handoff_service"].create_handoff(
        request=ExecutionHandoffRequest(workflow_id=gate.workflow_id)
    )


def dry_run_for(handoff, operation_type="modify_text_file", path="src/app.ts"):
    return CoderDryRunResponse(
        workflow_id=handoff.workflow_id,
        approved_plan_fingerprint=handoff.approved_plan_fingerprint,
        workspace_path=handoff.workspace_path,
        files_would_modify=[path] if operation_type == "modify_text_file" else [],
        files_would_create=[path] if operation_type == "create_text_file" else [],
        files_would_delete=[path] if operation_type == "delete_text_file" else [],
        intended_operations=[
            CoderDryRunOperation(
                operation_type=operation_type,
                relative_path=path,
                description="Preview the approved change.",
                rationale="Matches the approved handoff.",
            )
        ],
        proposed_code_change_summary="Would update the approved file.",
        dependencies_required=[],
        tests_to_run=["Run frontend lint."],
        rollback_backup_plan=["Restore original file content."],
        warnings=[],
        blockers=[],
        model="qwen2.5-coder:7b",
        execution_performed=False,
        mutation_capabilities_enabled=False,
        message="Dry-run completed. No files were written and no commands were run.",
    )


def valid_diff_payload(path, proposed_content):
    return {
        "file_changes": [
            {
                "relative_path": path,
                "proposed_content": proposed_content,
                "warnings": [],
            }
        ],
        "warnings": [],
        "blockers": [],
    }


def post_preview(dry_run):
    return client.post(
        "/api/v1/agents/coder/diff-preview",
        json={"dry_run": dry_run.model_dump(mode="json")},
    )


def test_coder_diff_preview_modify_file_diff(tmp_path, diff_context):
    workspace = create_workspace(tmp_path)
    handoff = create_handoff(diff_context, workspace)
    dry_run = dry_run_for(handoff)

    response = post_preview(dry_run)

    assert response.status_code == 200
    preview = response.json()["file_previews"][0]
    assert preview["operation_type"] == "modify_text_file"
    assert "-export const status = 'ready';" in preview["unified_diff"]
    assert "+export const status = 'updated';" in preview["unified_diff"]
    assert response.json()["execution_performed"] is False


def test_coder_diff_preview_create_file_diff(tmp_path, diff_context):
    workspace = create_workspace(tmp_path)
    handoff = create_handoff(diff_context, workspace, paths=["src/new.ts"])
    dry_run = dry_run_for(handoff, "create_text_file", "src/new.ts")
    diff_context["ollama_payload"] = valid_diff_payload(
        "src/new.ts",
        "export const created = true;\n",
    )

    response = post_preview(dry_run)

    assert response.status_code == 200
    preview = response.json()["file_previews"][0]
    assert preview["operation_type"] == "create_text_file"
    assert preview["current_content"] is None
    assert "+export const created = true;" in preview["unified_diff"]


def test_coder_diff_preview_delete_file_diff(tmp_path, diff_context):
    workspace = create_workspace(tmp_path)
    handoff = create_handoff(diff_context, workspace, delete=True)
    dry_run = dry_run_for(handoff, "delete_text_file", "src/app.ts")
    diff_context["ollama_payload"] = {"file_changes": [], "warnings": [], "blockers": []}

    response = post_preview(dry_run)

    assert response.status_code == 200
    preview = response.json()["file_previews"][0]
    assert preview["operation_type"] == "delete_text_file"
    assert preview["proposed_content"] is None
    assert "-export const status = 'ready';" in preview["unified_diff"]


def test_coder_diff_preview_warns_when_content_is_unchanged(tmp_path, diff_context):
    workspace = create_workspace(tmp_path)
    handoff = create_handoff(diff_context, workspace)
    dry_run = dry_run_for(handoff)
    diff_context["ollama_payload"] = valid_diff_payload(
        "src/app.ts",
        "export const status = 'ready';\n",
    )

    response = post_preview(dry_run)

    assert response.status_code == 200
    assert response.json()["file_previews"][0]["unified_diff"] == ""
    assert "No content changes proposed" in response.json()["file_previews"][0]["warnings"][0]


def test_coder_diff_preview_blocks_stale_dry_run(tmp_path, diff_context):
    workspace = create_workspace(tmp_path)
    handoff = create_handoff(diff_context, workspace)
    dry_run = dry_run_for(handoff)
    dry_run.approved_plan_fingerprint = "0" * 64

    response = post_preview(dry_run)

    assert response.status_code == 409
    assert "fingerprint" in response.json()["error"]["message"].lower()


def test_coder_diff_preview_blocks_disallowed_path(tmp_path, diff_context):
    workspace = create_workspace(tmp_path)
    handoff = create_handoff(diff_context, workspace)
    dry_run = dry_run_for(handoff, path="src/other.ts")

    response = post_preview(dry_run)

    assert response.status_code == 409
    assert "outside the approved handoff" in response.json()["error"]["message"]


def test_coder_diff_preview_blocks_secret_path(tmp_path, diff_context):
    workspace = create_workspace(tmp_path)
    handoff = create_handoff(diff_context, workspace)
    dry_run = dry_run_for(handoff, path=".env")

    response = post_preview(dry_run)

    assert response.status_code == 409
    assert "outside the approved handoff" in response.json()["error"]["message"]


def test_coder_diff_preview_blocks_binary_file(tmp_path, diff_context):
    workspace = create_workspace(tmp_path)
    (workspace / "image.bin").write_bytes(b"\0\1binary")
    handoff = create_handoff(diff_context, workspace, paths=["image.bin"])
    dry_run = dry_run_for(handoff, path="image.bin")
    diff_context["ollama_payload"] = valid_diff_payload("image.bin", "not binary\n")

    response = post_preview(dry_run)

    assert response.status_code == 409
    assert "cannot be safely previewed" in response.json()["error"]["message"]


def test_coder_diff_preview_blocks_large_file(tmp_path, diff_context):
    workspace = create_workspace(tmp_path)
    (workspace / "large.txt").write_text("x" * (256 * 1024 + 1), encoding="utf-8")
    handoff = create_handoff(diff_context, workspace, paths=["large.txt"])
    dry_run = dry_run_for(handoff, path="large.txt")
    diff_context["ollama_payload"] = valid_diff_payload("large.txt", "small\n")

    response = post_preview(dry_run)

    assert response.status_code == 409
    assert "cannot be safely previewed" in response.json()["error"]["message"]


def test_coder_diff_preview_maps_malformed_ollama_proposal(tmp_path, diff_context):
    workspace = create_workspace(tmp_path)
    handoff = create_handoff(diff_context, workspace)
    dry_run = dry_run_for(handoff)
    diff_context["ollama_payload"] = "not-json"

    response = post_preview(dry_run)

    assert response.status_code == 502
    assert response.json()["error"]["message"] == (
        "Coder diff-preview model did not return valid JSON"
    )
