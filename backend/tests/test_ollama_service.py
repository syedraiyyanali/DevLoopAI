import httpx2
import pytest

from app.core.config import Settings
from app.models.chat import ChatRequest
from app.services.ollama import OllamaService, OllamaServiceError


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
    last_get_url: str | None = None
    last_post_url: str | None = None
    last_post_json: dict | None = None

    def __init__(self, timeout: float) -> None:
        self.timeout = timeout

    async def __aenter__(self) -> "MockAsyncClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str) -> MockResponse:
        self.__class__.last_get_url = url

        if self.error is not None:
            raise self.error

        if self.response is None:
            raise AssertionError("MockAsyncClient.response was not configured")

        return self.response

    async def post(self, url: str, json: dict) -> MockResponse:
        self.__class__.last_post_url = url
        self.__class__.last_post_json = json

        if self.error is not None:
            raise self.error

        if self.response is None:
            raise AssertionError("MockAsyncClient.response was not configured")

        return self.response


@pytest.fixture(autouse=True)
def reset_mock_client(monkeypatch):
    MockAsyncClient.response = None
    MockAsyncClient.error = None
    MockAsyncClient.last_get_url = None
    MockAsyncClient.last_post_url = None
    MockAsyncClient.last_post_json = None
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


@pytest.mark.anyio
async def test_generate_chat_response_uses_configured_model_by_default():
    MockAsyncClient.response = MockResponse({"response": "Hello from Ollama"})

    response = await build_service().generate_chat_response(
        ChatRequest(message="Hello")
    )

    assert response.message == "Hello from Ollama"
    assert response.model == "qwen2.5-coder:7b"
    assert MockAsyncClient.last_post_url == "http://localhost:11434/api/generate"
    assert MockAsyncClient.last_post_json == {
        "model": "qwen2.5-coder:7b",
        "prompt": "Hello",
        "stream": False,
    }


@pytest.mark.anyio
async def test_generate_chat_response_uses_requested_model():
    MockAsyncClient.response = MockResponse({"response": "Hello from another model"})

    response = await build_service().generate_chat_response(
        ChatRequest(message="Hello", model="llama3.2:3b")
    )

    assert response.message == "Hello from another model"
    assert response.model == "llama3.2:3b"
    assert MockAsyncClient.last_post_json == {
        "model": "llama3.2:3b",
        "prompt": "Hello",
        "stream": False,
    }


@pytest.mark.anyio
async def test_generate_chat_response_raises_service_error_for_http_error():
    MockAsyncClient.response = MockResponse({"error": "model not found"}, status_code=404)

    with pytest.raises(OllamaServiceError, match="requested model"):
        await build_service().generate_chat_response(ChatRequest(message="Hello"))


@pytest.mark.anyio
async def test_generate_chat_response_raises_service_error_for_connection_failure():
    request = httpx2.Request("POST", "http://localhost:11434/api/generate")
    MockAsyncClient.error = httpx2.ConnectError("connection refused", request=request)

    with pytest.raises(OllamaServiceError, match="Unable to connect"):
        await build_service().generate_chat_response(ChatRequest(message="Hello"))


@pytest.mark.anyio
async def test_generate_chat_response_raises_service_error_for_invalid_payload():
    MockAsyncClient.response = MockResponse({"message": "missing response field"})

    with pytest.raises(OllamaServiceError, match="invalid generation response"):
        await build_service().generate_chat_response(ChatRequest(message="Hello"))
