from fastapi.testclient import TestClient

from app.main import app
from app.models.chat import ChatRequest, ChatResponse
from app.services.ollama import OllamaService, OllamaServiceError


def test_chat_endpoint_returns_generated_response(monkeypatch):
    async def mock_generate_chat_response(
        self: OllamaService,
        chat_request: ChatRequest,
    ) -> ChatResponse:
        return ChatResponse(
            message=f"Echo: {chat_request.message}",
            model=chat_request.model or "qwen2.5-coder:7b",
        )

    monkeypatch.setattr(
        OllamaService,
        "generate_chat_response",
        mock_generate_chat_response,
    )

    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/api/v1/chat", json={"message": "Hello"})

    assert response.status_code == 200
    assert response.json() == {
        "message": "Echo: Hello",
        "model": "qwen2.5-coder:7b",
    }


def test_chat_endpoint_rejects_empty_message():
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/api/v1/chat", json={"message": ""})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_chat_endpoint_maps_ollama_errors_to_service_unavailable(monkeypatch):
    async def mock_generate_chat_response(
        self: OllamaService,
        chat_request: ChatRequest,
    ) -> ChatResponse:
        raise OllamaServiceError("Unable to connect to Ollama")

    monkeypatch.setattr(
        OllamaService,
        "generate_chat_response",
        mock_generate_chat_response,
    )

    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/api/v1/chat", json={"message": "Hello"})

    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "HTTP_ERROR",
            "message": "Unable to connect to Ollama",
            "status_code": 503,
        }
    }
