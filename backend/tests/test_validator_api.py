import json

from fastapi.testclient import TestClient

from app.main import app
from app.models.chat import ChatRequest, ChatResponse
from app.services.ollama import OllamaService, OllamaServiceError


client = TestClient(app, raise_server_exceptions=False)


def project_context_payload(root_path: str = "D:\\sample") -> dict:
    return {
        "workspace": {
            "name": "sample",
            "root_path": root_path,
            "total_visible_entries": 2,
        },
        "project_types": ["Node.js"],
        "frameworks": ["Next.js"],
        "important_config_files": ["package.json"],
        "important_source_directories": ["frontend/components"],
        "likely_entry_points": ["frontend/app/page.tsx"],
        "detected_languages": {"TypeScript": 3},
        "file_count": 4,
        "directory_count": 2,
        "dependency_metadata": [],
        "git": {
            "present": True,
            "current_branch": "main",
            "remotes": ["origin"],
        },
        "readme_excerpt": "# Sample",
        "ignored_directories": [".git", "node_modules"],
        "warnings": [],
    }


def planner_output_payload(
    *,
    files: list[str] | None = None,
    tests: list[str] | None = None,
    dependencies_needed: list[str] | None = None,
    risks: list[str] | None = None,
) -> dict:
    return {
        "task_summary": "Add a read-only status label.",
        "assumptions": ["Workspace panel exists."],
        "detected_project_context": {
            "workspace_name": "sample",
            "project_types": ["Node.js"],
            "frameworks": ["Next.js"],
            "languages": {"TypeScript": 3},
        },
        "implementation_steps": [
            "Inspect the workspace panel.",
            "Add the read-only label.",
        ],
        "files_likely_to_change": files
        if files is not None
        else ["frontend/components/workspace-panel.tsx"],
        "tests_verification_required": tests
        if tests is not None
        else ["Run npm run lint."],
        "risks": risks if risks is not None else [],
        "dependencies_or_user_input_needed": dependencies_needed
        if dependencies_needed is not None
        else [],
        "model": "qwen2.5-coder:7b",
        "raw_model_response": None,
    }


def reviewer_output_payload(
    recommendation: str = "APPROVE",
    *,
    security: list[str] | None = None,
    testing_gaps: list[str] | None = None,
) -> dict:
    return {
        "overall_assessment": "The plan is reasonable.",
        "missing_steps": [],
        "incorrect_assumptions": [],
        "architecture_concerns": [],
        "security_concerns": security if security is not None else [],
        "performance_concerns": [],
        "testing_gaps": testing_gaps if testing_gaps is not None else [],
        "unnecessary_changes": [],
        "recommended_improvements": [],
        "approval_recommendation": recommendation,
        "model": "qwen2.5-coder:7b",
        "raw_model_response": None,
    }


def validator_model_payload(
    *,
    blockers: list[str] | None = None,
    security: list[str] | None = None,
) -> str:
    return json.dumps(
        {
            "plan_completeness": ["Reasoning check found the plan understandable."],
            "dependency_concerns": [],
            "environment_tool_requirements": [],
            "security_concerns": security if security is not None else [],
            "missing_user_information": [],
            "test_verification_readiness": [],
            "blockers": blockers if blockers is not None else [],
            "final_execution_readiness": "Reasoning validation complete.",
        }
    )


async def mock_validator_response(
    self: OllamaService,
    chat_request: ChatRequest,
) -> ChatResponse:
    return ChatResponse(
        message=validator_model_payload(),
        model=chat_request.model or "qwen2.5-coder:7b",
    )


def build_validator_request(**overrides: object) -> dict:
    payload = {
        "task": "Validate adding a read-only status label.",
        "planner_output": planner_output_payload(),
        "reviewer_output": reviewer_output_payload(),
        "constraints": ["Stay read-only."],
    }
    payload.update(overrides)

    return payload


def test_validator_ready_without_warnings(monkeypatch, tmp_path):
    workspace = tmp_path / "ready-project"
    workspace.mkdir()
    (workspace / "frontend" / "components").mkdir(parents=True)
    (workspace / "frontend" / "components" / "workspace-panel.tsx").write_bytes(
        b"export default function WorkspacePanel() {}\n"
    )

    monkeypatch.setattr(OllamaService, "generate_chat_response", mock_validator_response)

    response = client.post(
        "/api/v1/agents/validator",
        json=build_validator_request(
            project_context=project_context_payload(str(workspace)),
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["overall_validation_status"] == "READY"
    assert body["file_path_validity"] == [
        "frontend/components/workspace-panel.tsx: path exists."
    ]
    assert body["blockers"] == []


def test_validator_ready_with_warnings_for_missing_context(monkeypatch):
    monkeypatch.setattr(OllamaService, "generate_chat_response", mock_validator_response)

    response = client.post(
        "/api/v1/agents/validator",
        json=build_validator_request(project_context=None),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["overall_validation_status"] == "READY_WITH_WARNINGS"
    assert "Project context was not provided" in body["file_path_validity"][0]
    assert "dependencies are unknown" in body["dependency_concerns"][0]


def test_validator_blocks_rejected_review(monkeypatch):
    monkeypatch.setattr(OllamaService, "generate_chat_response", mock_validator_response)

    response = client.post(
        "/api/v1/agents/validator",
        json=build_validator_request(
            reviewer_output=reviewer_output_payload("REJECT"),
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["overall_validation_status"] == "BLOCKED"
    assert "Reviewer rejected the planner output." in body["blockers"]


def test_validator_blocks_destructive_plan_items(monkeypatch):
    monkeypatch.setattr(OllamaService, "generate_chat_response", mock_validator_response)

    response = client.post(
        "/api/v1/agents/validator",
        json=build_validator_request(
            planner_output=planner_output_payload(
                risks=["May need to delete branch and git reset --hard."]
            ),
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["overall_validation_status"] == "BLOCKED"
    assert any(
        "git reset --hard" in warning
        for warning in body["destructive_operation_warnings"]
    )


def test_validator_detects_missing_dependencies(monkeypatch):
    monkeypatch.setattr(OllamaService, "generate_chat_response", mock_validator_response)

    response = client.post(
        "/api/v1/agents/validator",
        json=build_validator_request(
            planner_output=planner_output_payload(
                dependencies_needed=["Need user approval to install a new package."]
            ),
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["overall_validation_status"] == "READY_WITH_WARNINGS"
    assert any(
        "dependency changes" in concern for concern in body["dependency_concerns"]
    )


def test_validator_blocks_model_reported_blockers(monkeypatch):
    async def mock_blocker(
        self: OllamaService,
        chat_request: ChatRequest,
    ) -> ChatResponse:
        return ChatResponse(
            message=validator_model_payload(blockers=["Missing target platform."]),
            model="qwen2.5-coder:7b",
        )

    monkeypatch.setattr(OllamaService, "generate_chat_response", mock_blocker)

    response = client.post(
        "/api/v1/agents/validator",
        json=build_validator_request(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["overall_validation_status"] == "BLOCKED"
    assert "Missing target platform." in body["blockers"]


def test_validator_returns_clear_error_for_malformed_model_output(monkeypatch):
    async def mock_malformed_response(
        self: OllamaService,
        chat_request: ChatRequest,
    ) -> ChatResponse:
        return ChatResponse(message="not json", model="qwen2.5-coder:7b")

    monkeypatch.setattr(
        OllamaService,
        "generate_chat_response",
        mock_malformed_response,
    )

    response = client.post(
        "/api/v1/agents/validator",
        json=build_validator_request(),
    )

    assert response.status_code == 502
    assert response.json()["error"]["message"] == (
        "Validator model did not return valid JSON"
    )


def test_validator_maps_ollama_errors_to_bad_gateway(monkeypatch):
    async def mock_ollama_error(
        self: OllamaService,
        chat_request: ChatRequest,
    ) -> ChatResponse:
        raise OllamaServiceError("Unable to connect to Ollama")

    monkeypatch.setattr(
        OllamaService,
        "generate_chat_response",
        mock_ollama_error,
    )

    response = client.post(
        "/api/v1/agents/validator",
        json=build_validator_request(),
    )

    assert response.status_code == 502
    assert response.json()["error"]["message"] == (
        "MODEL_UNAVAILABLE: Unable to connect to Ollama"
    )
