from fastapi.testclient import TestClient

from app.main import app
from app.models.chat import ChatRequest, ChatResponse
from app.services.ollama import OllamaService, OllamaServiceError, OllamaStreamError


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


def test_chat_stream_endpoint_returns_chunk_events(monkeypatch):
    async def mock_stream_chat_response(
        self: OllamaService,
        chat_request: ChatRequest,
    ):
        yield "Hello"
        yield " stream"

    monkeypatch.setattr(
        OllamaService,
        "stream_chat_response",
        mock_stream_chat_response,
    )

    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/api/v1/chat/stream", json={"message": "Hello"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert response.text.splitlines() == [
        '{"type": "chunk", "content": "Hello"}',
        '{"type": "chunk", "content": " stream"}',
        '{"type": "done"}',
    ]


def test_chat_stream_endpoint_returns_error_event(monkeypatch):
    async def mock_stream_chat_response(
        self: OllamaService,
        chat_request: ChatRequest,
    ):
        yield "partial"
        raise OllamaStreamError("Unable to connect to Ollama")

    monkeypatch.setattr(
        OllamaService,
        "stream_chat_response",
        mock_stream_chat_response,
    )

    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/api/v1/chat/stream", json={"message": "Hello"})

    assert response.status_code == 200
    assert response.text.splitlines() == [
        '{"type": "chunk", "content": "partial"}',
        '{"type": "error", "message": "Unable to connect to Ollama"}',
    ]
