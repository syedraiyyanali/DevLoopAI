import json

from fastapi.testclient import TestClient

from app.main import app
from app.models.chat import ChatRequest, ChatResponse
from app.services.ollama import OllamaService, OllamaServiceError


client = TestClient(app, raise_server_exceptions=False)


def planner_output_payload() -> dict:
    return {
        "task_summary": "Add a read-only label.",
        "assumptions": ["Workspace panel exists."],
        "detected_project_context": {
            "workspace_name": "sample",
            "project_types": ["Node.js"],
            "frameworks": ["Next.js"],
            "languages": {"TypeScript": 3},
        },
        "implementation_steps": [
            "Inspect the workspace panel.",
            "Add a read-only label.",
        ],
        "files_likely_to_change": ["frontend/components/workspace-panel.tsx"],
        "tests_verification_required": ["Run frontend lint."],
        "risks": ["UI text may become noisy."],
        "dependencies_or_user_input_needed": [],
        "model": "qwen2.5-coder:7b",
        "raw_model_response": None,
    }


def project_context_payload() -> dict:
    return {
        "workspace": {
            "name": "sample",
            "root_path": "D:\\sample",
            "total_visible_entries": 2,
        },
        "project_types": ["Node.js"],
        "frameworks": ["Next.js"],
        "important_config_files": ["frontend/package.json"],
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


def review_model_payload(recommendation: str = "APPROVE_WITH_CHANGES") -> str:
    return json.dumps(
        {
            "overall_assessment": "The plan is mostly reasonable.",
            "missing_steps": ["Mention exact validation commands."],
            "incorrect_assumptions": [],
            "architecture_concerns": ["Keep the label inside the existing panel."],
            "security_concerns": [],
            "performance_concerns": [],
            "testing_gaps": ["Add frontend lint verification."],
            "unnecessary_changes": [],
            "recommended_improvements": ["Keep the change read-only and minimal."],
            "approval_recommendation": recommendation,
        }
    )


def build_reviewer_request(**overrides: object) -> dict:
    payload = {
        "task": "Review adding a read-only workspace label.",
        "planner_output": planner_output_payload(),
        "constraints": ["Do not execute the plan."],
    }
    payload.update(overrides)

    return payload


async def mock_review_response(
    self: OllamaService,
    chat_request: ChatRequest,
) -> ChatResponse:
    return ChatResponse(
        message=review_model_payload(),
        model=chat_request.model or "qwen2.5-coder:7b",
    )


def test_reviewer_returns_structured_review_without_project_context(monkeypatch):
    monkeypatch.setattr(OllamaService, "generate_chat_response", mock_review_response)

    response = client.post(
        "/api/v1/agents/reviewer",
        json=build_reviewer_request(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["overall_assessment"] == "The plan is mostly reasonable."
    assert body["missing_steps"] == ["Mention exact validation commands."]
    assert body["approval_recommendation"] == "APPROVE_WITH_CHANGES"
    assert body["model"] == "qwen2.5-coder:7b"
    assert body["raw_model_response"] is None


def test_reviewer_returns_structured_review_with_project_context(monkeypatch):
    monkeypatch.setattr(OllamaService, "generate_chat_response", mock_review_response)

    response = client.post(
        "/api/v1/agents/reviewer",
        json=build_reviewer_request(project_context=project_context_payload()),
    )

    assert response.status_code == 200
    assert response.json()["architecture_concerns"] == [
        "Keep the label inside the existing panel."
    ]


def test_reviewer_supports_approve_result(monkeypatch):
    async def mock_approve(
        self: OllamaService,
        chat_request: ChatRequest,
    ) -> ChatResponse:
        return ChatResponse(
            message=review_model_payload("APPROVE"),
            model="qwen2.5-coder:7b",
        )

    monkeypatch.setattr(OllamaService, "generate_chat_response", mock_approve)

    response = client.post(
        "/api/v1/agents/reviewer",
        json=build_reviewer_request(),
    )

    assert response.status_code == 200
    assert response.json()["approval_recommendation"] == "APPROVE"


def test_reviewer_supports_reject_result(monkeypatch):
    async def mock_reject(
        self: OllamaService,
        chat_request: ChatRequest,
    ) -> ChatResponse:
        return ChatResponse(
            message=review_model_payload("REJECT"),
            model="qwen2.5-coder:7b",
        )

    monkeypatch.setattr(OllamaService, "generate_chat_response", mock_reject)

    response = client.post(
        "/api/v1/agents/reviewer",
        json=build_reviewer_request(),
    )

    assert response.status_code == 200
    assert response.json()["approval_recommendation"] == "REJECT"


def test_reviewer_returns_clear_error_for_malformed_model_output(monkeypatch):
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
        "/api/v1/agents/reviewer",
        json=build_reviewer_request(),
    )

    assert response.status_code == 502
    assert response.json()["error"]["message"] == (
        "Reviewer model did not return valid JSON"
    )


def test_reviewer_maps_ollama_errors_to_bad_gateway(monkeypatch):
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
        "/api/v1/agents/reviewer",
        json=build_reviewer_request(),
    )

    assert response.status_code == 502
    assert response.json()["error"]["message"] == "Unable to connect to Ollama"


def test_reviewer_rejects_missing_planner_data():
    invalid_request = {
        "task": "Review an invalid plan.",
        "planner_output": {
            "task_summary": "Missing required planner fields.",
        },
    }

    response = client.post("/api/v1/agents/reviewer", json=invalid_request)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
