import json

import pytest
from fastapi.testclient import TestClient

from app.agents.coder import CoderDryRunAgent
from app.api.v1.endpoints import coder as coder_endpoint
from app.main import app
from app.models.chat import ChatResponse
from app.models.execution_handoff import ExecutionHandoffRequest
from app.models.planner import PlannerProjectContext, PlannerResponse
from app.models.planning_workflow import FinalReviewedPlanSummary
from app.models.reviewer import ReviewerResponse
from app.models.validator import ValidatorResponse
from app.services.execution_handoff import ExecutionHandoffService
from app.services.execution_preflight import ExecutionPreflightService
from app.services.ollama import OllamaServiceError
from app.services.planning_approval import PlanningApprovalStore
from app.services.workspace import WorkspaceService


client = TestClient(app, raise_server_exceptions=False)


class FakeOllamaService:
    def __init__(self, *, payload=None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error

    async def generate_chat_response(self, chat_request):
        if self.error is not None:
            raise self.error

        return ChatResponse(
            message=self.payload
            if isinstance(self.payload, str)
            else json.dumps(self.payload),
            model=chat_request.model or "qwen2.5-coder:7b",
        )


@pytest.fixture
def dry_run_context(tmp_path, monkeypatch):
    store = PlanningApprovalStore(tmp_path / "coder-dry-run.sqlite3")
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
        "ollama_payload": valid_model_payload(),
        "ollama_error": None,
    }

    def get_agent():
        return CoderDryRunAgent(
            ollama_service=FakeOllamaService(
                payload=context["ollama_payload"],
                error=context["ollama_error"],
            ),
            handoff_service=handoff_service,
            workspace_service=workspace_service,
        )

    monkeypatch.setattr(coder_endpoint, "get_coder_dry_run_agent", get_agent)
    return context


def create_workspace(tmp_path):
    workspace = tmp_path / "sample-project"
    source_dir = workspace / "src"
    source_dir.mkdir(parents=True)
    (workspace / "package.json").write_text(
        '{"dependencies":{"next":"16.2.10"},"devDependencies":{}}',
        encoding="utf-8",
    )
    (source_dir / "app.ts").write_text("export const status = 'ready';\n", encoding="utf-8")
    (source_dir / "helper.ts").write_text("export const helper = true;\n", encoding="utf-8")
    return workspace


def planner_response(paths=None) -> PlannerResponse:
    return PlannerResponse(
        task_summary="Add a safe status label.",
        assumptions=["The source file exists."],
        detected_project_context=PlannerProjectContext(
            workspace_name="sample-project",
            project_types=["Node.js"],
            frameworks=["Next.js"],
            languages={"TypeScript": 2},
        ),
        implementation_steps=["Inspect src/app.ts.", "Add the status label."],
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


def create_approved_handoff(context, workspace, *, paths=None):
    store = context["store"]
    gate = store.create_gate(
        task="Add a safe status label.",
        workspace_path=str(workspace),
        planner_output=planner_response(paths),
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


def valid_model_payload():
    return {
        "files_to_modify": ["src/app.ts"],
        "files_to_create": [],
        "files_to_delete": [],
        "intended_operations": [
            {
                "operation_type": "modify_text_file",
                "relative_path": "src/app.ts",
                "description": "Update the status label implementation.",
                "rationale": "Matches the approved plan.",
            }
        ],
        "proposed_code_change_summary": "Would update the status label in src/app.ts.",
        "dependencies_required": [],
        "tests_to_run": ["Run frontend lint."],
        "rollback_backup_plan": ["Restore the original src/app.ts content."],
        "warnings": [],
        "blockers": [],
    }


def post_dry_run(handoff):
    return client.post(
        "/api/v1/agents/coder/dry-run",
        json={"handoff": handoff.model_dump(mode="json")},
    )


def test_coder_dry_run_returns_zero_write_result(tmp_path, dry_run_context):
    workspace = create_workspace(tmp_path)
    handoff = create_approved_handoff(dry_run_context, workspace)

    response = post_dry_run(handoff)

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_id"] == handoff.workflow_id
    assert body["files_would_modify"] == ["src/app.ts"]
    assert body["files_would_create"] == []
    assert body["files_would_delete"] == []
    assert body["intended_operations"][0]["operation_type"] == "modify_text_file"
    assert "Run frontend lint." in body["tests_to_run"]
    assert body["context_selection"]["selected_files"]
    assert body["context_selection"]["selected_files"][0]["relative_path"] == "src/app.ts"
    assert body["execution_performed"] is False
    assert body["mutation_capabilities_enabled"] is False


def test_coder_dry_run_supports_multi_file_approved_context(tmp_path, dry_run_context):
    workspace = create_workspace(tmp_path)
    handoff = create_approved_handoff(
        dry_run_context,
        workspace,
        paths=["src/app.ts", "src/helper.ts"],
    )
    dry_run_context["ollama_payload"] = {
        "files_to_modify": ["src/app.ts", "src/helper.ts"],
        "files_to_create": [],
        "files_to_delete": [],
        "intended_operations": [
            {
                "operation_type": "modify_text_file",
                "relative_path": "src/app.ts",
                "description": "Update status usage.",
                "rationale": "Approved file.",
            },
            {
                "operation_type": "modify_text_file",
                "relative_path": "src/helper.ts",
                "description": "Update helper export.",
                "rationale": "Approved related file.",
            },
        ],
        "proposed_code_change_summary": "Would update two approved TypeScript files.",
        "dependencies_required": [],
        "tests_to_run": ["Run frontend lint."],
        "rollback_backup_plan": ["Restore original contents."],
        "warnings": [],
        "blockers": [],
    }

    response = post_dry_run(handoff)

    assert response.status_code == 200
    body = response.json()
    assert body["files_would_modify"] == ["src/app.ts", "src/helper.ts"]
    selected_paths = {
        item["relative_path"] for item in body["context_selection"]["selected_files"]
    }
    assert {"src/app.ts", "src/helper.ts"}.issubset(selected_paths)


def test_coder_dry_run_blocks_stale_handoff(tmp_path, dry_run_context):
    workspace = create_workspace(tmp_path)
    handoff = create_approved_handoff(dry_run_context, workspace)
    payload = handoff.model_dump(mode="json")
    payload["approved_plan_fingerprint"] = "0" * 64

    response = client.post(
        "/api/v1/agents/coder/dry-run",
        json={"handoff": payload},
    )

    assert response.status_code == 409
    assert "fingerprint" in response.json()["error"]["message"].lower()


def test_coder_dry_run_blocks_model_disallowed_path(tmp_path, dry_run_context):
    workspace = create_workspace(tmp_path)
    handoff = create_approved_handoff(dry_run_context, workspace)
    dry_run_context["ollama_payload"] = {
        **valid_model_payload(),
        "files_to_modify": ["src/other.ts"],
        "intended_operations": [
            {
                "operation_type": "modify_text_file",
                "relative_path": "src/other.ts",
                "description": "Touch an unapproved file.",
                "rationale": "Unsafe proposal.",
            }
        ],
    }

    response = post_dry_run(handoff)

    assert response.status_code == 409
    assert "outside the approved handoff" in response.json()["error"]["message"]


def test_coder_dry_run_normalizes_common_model_operation_alias(
    tmp_path,
    dry_run_context,
):
    workspace = create_workspace(tmp_path)
    handoff = create_approved_handoff(dry_run_context, workspace)
    dry_run_context["ollama_payload"] = {
        **valid_model_payload(),
        "dependencies_required": None,
        "intended_operations": [
            {
                "operation_type": "edit_file",
                "relative_path": "src/app.ts",
                "description": "Update the status label implementation.",
                "rationale": "Matches the approved plan.",
            }
        ],
    }

    response = post_dry_run(handoff)

    assert response.status_code == 200
    assert response.json()["intended_operations"][0]["operation_type"] == (
        "modify_text_file"
    )


def test_coder_dry_run_blocks_secret_path_tampering(tmp_path, dry_run_context):
    workspace = create_workspace(tmp_path)
    handoff = create_approved_handoff(dry_run_context, workspace)
    payload = handoff.model_dump(mode="json")
    payload["allowed_files"] = [".env"]

    response = client.post(
        "/api/v1/agents/coder/dry-run",
        json={"handoff": payload},
    )

    assert response.status_code == 409
    assert "allowed files were changed" in response.json()["error"]["message"]


def test_coder_dry_run_blocks_unsupported_operation_tampering(
    tmp_path,
    dry_run_context,
):
    workspace = create_workspace(tmp_path)
    handoff = create_approved_handoff(dry_run_context, workspace)
    payload = handoff.model_dump(mode="json")
    payload["allowed_operation_types"] = ["read_file"]

    response = client.post(
        "/api/v1/agents/coder/dry-run",
        json={"handoff": payload},
    )

    assert response.status_code == 409
    assert "allowed operation types were changed" in response.json()["error"]["message"]


def test_coder_dry_run_maps_malformed_model_output(tmp_path, dry_run_context):
    workspace = create_workspace(tmp_path)
    handoff = create_approved_handoff(dry_run_context, workspace)
    dry_run_context["ollama_payload"] = "not-json"

    response = post_dry_run(handoff)

    assert response.status_code == 502
    assert response.json()["error"]["message"] == (
        "Coder dry-run model did not return valid JSON"
    )


def test_coder_dry_run_maps_ollama_unavailable(tmp_path, dry_run_context):
    workspace = create_workspace(tmp_path)
    handoff = create_approved_handoff(dry_run_context, workspace)
    dry_run_context["ollama_error"] = OllamaServiceError("Unable to connect to Ollama")

    response = post_dry_run(handoff)

    assert response.status_code == 502
    assert response.json()["error"]["message"] == (
        "MODEL_UNAVAILABLE: Unable to connect to Ollama"
    )


def test_coder_dry_run_blocks_invalid_workflow_id(tmp_path, dry_run_context):
    workspace = create_workspace(tmp_path)
    handoff = create_approved_handoff(dry_run_context, workspace)
    payload = handoff.model_dump(mode="json")
    payload["workflow_id"] = "missing-workflow"

    response = client.post(
        "/api/v1/agents/coder/dry-run",
        json={"handoff": payload},
    )

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Workflow id is invalid."
