from fastapi.testclient import TestClient

from app.main import app
from app.models.ollama import OllamaStatus
from app.services.ollama import OllamaService


def test_ollama_status_endpoint_returns_service_status(monkeypatch):
    async def mock_get_status(self: OllamaService) -> OllamaStatus:
        return OllamaStatus(
            reachable=True,
            base_url="http://localhost:11434",
            configured_model="qwen2.5-coder:7b",
            configured_model_available=False,
            models=[],
        )

    monkeypatch.setattr(OllamaService, "get_status", mock_get_status)

    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/v1/ollama/status")

    assert response.status_code == 200
    assert response.json() == {
        "reachable": True,
        "base_url": "http://localhost:11434",
        "configured_model": "qwen2.5-coder:7b",
        "configured_model_available": False,
        "models": [],
        "error": None,
    }
