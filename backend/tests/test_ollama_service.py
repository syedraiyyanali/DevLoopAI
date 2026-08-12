import httpx2
import pytest

from app.core.config import Settings
from app.services.ollama import OllamaService


class MockResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> dict:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            request = httpx2.Request("GET", "http://localhost:11434/api/tags")
            response = httpx2.Response(self.status_code, request=request)
            raise httpx2.HTTPStatusError(
                "Ollama returned an error",
                request=request,
                response=response,
            )


class MockAsyncClient:
    response: MockResponse | None = None
    error: httpx2.HTTPError | None = None

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> "MockAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str) -> MockResponse:
        if self.error is not None:
            raise self.error

        if self.response is None:
            raise AssertionError("MockAsyncClient.response was not configured")

        return self.response


@pytest.fixture(autouse=True)
def reset_mock_client(monkeypatch):
    MockAsyncClient.response = None
    MockAsyncClient.error = None
    monkeypatch.setattr(httpx2, "AsyncClient", MockAsyncClient)


def build_service() -> OllamaService:
    settings = Settings(
        _env_file=None,
        ollama_base_url="http://localhost:11434/",
        ollama_model="qwen2.5-coder:7b",
    )

    return OllamaService(settings)


@pytest.mark.anyio
async def test_ollama_status_reports_available_configured_model():
    MockAsyncClient.response = MockResponse(
        {
            "models": [
                {"name": "qwen2.5-coder:7b"},
                {"name": "llama3.2:3b"},
            ]
        }
    )

    status = await build_service().get_status()

    assert status.reachable is True
    assert status.base_url == "http://localhost:11434"
    assert status.configured_model == "qwen2.5-coder:7b"
    assert status.configured_model_available is True
    assert [model.name for model in status.models] == [
        "qwen2.5-coder:7b",
        "llama3.2:3b",
    ]
    assert status.error is None


@pytest.mark.anyio
async def test_ollama_status_reports_missing_configured_model():
    MockAsyncClient.response = MockResponse({"models": [{"name": "llama3.2:3b"}]})

    status = await build_service().get_status()

    assert status.reachable is True
    assert status.configured_model_available is False
    assert [model.name for model in status.models] == ["llama3.2:3b"]


@pytest.mark.anyio
async def test_ollama_status_reports_connection_failure():
    request = httpx2.Request("GET", "http://localhost:11434/api/tags")
    MockAsyncClient.error = httpx2.ConnectError("connection refused", request=request)

    status = await build_service().get_status()

    assert status.reachable is False
    assert status.configured_model_available is False
    assert status.models == []
    assert status.error == "Unable to connect to Ollama"
