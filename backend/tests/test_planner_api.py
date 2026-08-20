import json

from fastapi.testclient import TestClient

from app.main import app
from app.models.chat import ChatRequest, ChatResponse
from app.services.ollama import OllamaService, OllamaServiceError


client = TestClient(app, raise_server_exceptions=False)


def planner_model_payload() -> str:
    return json.dumps(
        {
            "task_summary": "Add a small feature safely.",
            "assumptions": ["Existing behavior should be preserved."],
            "implementation_steps": [
                "Inspect the related modules.",
                "Implement the smallest safe change.",
            ],
            "files_likely_to_change": ["backend/app/example.py"],
            "tests_verification_required": ["Run backend pytest."],
            "risks": ["Model output may miss edge cases."],
            "dependencies_or_user_input_needed": [],
        }
    )


async def mock_generate_plan_response(
    self: OllamaService,
    chat_request: ChatRequest,
) -> ChatResponse:
    return ChatResponse(
        message=planner_model_payload(),
        model=chat_request.model or "qwen2.5-coder:7b",
    )


def test_planner_request_without_workspace_returns_structured_plan(monkeypatch):
    monkeypatch.setattr(
        OllamaService,
        "generate_chat_response",
        mock_generate_plan_response,
    )

    response = client.post(
        "/api/v1/agents/planner",
        json={"task": "Add a status badge."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["task_summary"] == "Add a small feature safely."
    assert body["detected_project_context"] == {
        "workspace_name": None,
        "project_types": [],
        "frameworks": [],
        "languages": {},
    }
    assert body["implementation_steps"] == [
        "Inspect the related modules.",
        "Implement the smallest safe change.",
    ]
    assert body["model"] == "qwen2.5-coder:7b"
    assert body["raw_model_response"] is None


def test_planner_request_with_project_context_returns_detected_context(monkeypatch):
    monkeypatch.setattr(
        OllamaService,
        "generate_chat_response",
        mock_generate_plan_response,
    )

    response = client.post(
        "/api/v1/agents/planner",
        json={
            "task": "Add a workspace summary panel.",
            "project_context": {
                "workspace": {
                    "name": "sample",
                    "root_path": "D:\\sample",
                    "total_visible_entries": 2,
                },
                "project_types": ["Python", "Node.js"],
                "frameworks": ["FastAPI", "Next.js"],
                "important_config_files": ["backend/requirements.txt"],
                "important_source_directories": ["backend/app", "frontend/app"],
                "likely_entry_points": ["backend/app/main.py"],
                "detected_languages": {"Python": 4, "TypeScript": 2},
                "file_count": 6,
                "directory_count": 3,
                "dependency_metadata": [],
                "git": {
                    "present": True,
                    "current_branch": "main",
                    "remotes": ["origin"],
                },
                "readme_excerpt": "# Sample",
                "ignored_directories": [".git", "node_modules"],
                "warnings": [],
            },
            "constraints": ["Keep it read-only."],
        },
    )

    assert response.status_code == 200
    assert response.json()["detected_project_context"] == {
        "workspace_name": "sample",
        "project_types": ["Python", "Node.js"],
        "frameworks": ["FastAPI", "Next.js"],
        "languages": {"Python": 4, "TypeScript": 2},
    }


def test_planner_request_can_build_context_from_workspace_path(tmp_path, monkeypatch):
    workspace = tmp_path / "planner-project"
    workspace.mkdir()
    (workspace / "requirements.txt").write_bytes(b"fastapi\n")
    (workspace / "app").mkdir()
    (workspace / "app" / "main.py").write_bytes(b"from fastapi import FastAPI\n")

    monkeypatch.setattr(
        OllamaService,
        "generate_chat_response",
        mock_generate_plan_response,
    )

    response = client.post(
        "/api/v1/agents/planner",
        json={
            "task": "Add an endpoint.",
            "workspace_path": str(workspace),
        },
    )

    assert response.status_code == 200
    assert response.json()["detected_project_context"] == {
        "workspace_name": "planner-project",
        "project_types": ["Python"],
        "frameworks": ["FastAPI"],
        "languages": {"Python": 1},
    }


def test_planner_returns_clear_error_for_malformed_model_output(monkeypatch):
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
        "/api/v1/agents/planner",
        json={"task": "Add something."},
    )

    assert response.status_code == 502
    assert response.json()["error"]["message"] == (
        "Planner model did not return valid JSON"
    )


def test_planner_maps_ollama_errors_to_bad_gateway(monkeypatch):
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
        "/api/v1/agents/planner",
        json={"task": "Add something."},
    )

    assert response.status_code == 502
    assert response.json()["error"]["message"] == (
        "MODEL_UNAVAILABLE: Unable to connect to Ollama"
    )
