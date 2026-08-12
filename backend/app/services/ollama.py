import logging
from typing import Any

import httpx2

from app.core.config import Settings
from app.models.chat import ChatRequest, ChatResponse
from app.models.ollama import OllamaModelInfo, OllamaStatus


logger = logging.getLogger(__name__)


class OllamaServiceError(Exception):
    """
    Raised when Ollama cannot complete a service request.
    """


class OllamaService:
    """
    Service layer for communicating with an Ollama model backend.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.configured_model = settings.ollama_model

    async def get_status(self) -> OllamaStatus:
        """
        Check whether Ollama is reachable and list available local models.
        """
        tags_url = f"{self.base_url}/api/tags"

        try:
            async with httpx2.AsyncClient(timeout=5.0) as client:
                response = await client.get(tags_url)
                response.raise_for_status()
        except httpx2.HTTPError as exc:
            logger.warning("Ollama status check failed: %s", exc)
            return OllamaStatus(
                reachable=False,
                base_url=self.base_url,
                configured_model=self.configured_model,
                configured_model_available=False,
                error="Unable to connect to Ollama",
            )

        models = self._parse_models(response.json())
        model_names = {model.name for model in models}

        return OllamaStatus(
            reachable=True,
            base_url=self.base_url,
            configured_model=self.configured_model,
            configured_model_available=self.configured_model in model_names,
            models=models,
        )

    async def generate_chat_response(self, chat_request: ChatRequest) -> ChatResponse:
        """
        Generate a basic non-streaming response through Ollama.
        """
        model = chat_request.model or self.configured_model
        generate_url = f"{self.base_url}/api/generate"
        payload = {
            "model": model,
            "prompt": chat_request.message,
            "stream": False,
        }

        try:
            async with httpx2.AsyncClient(timeout=60.0) as client:
                response = await client.post(generate_url, json=payload)
                response.raise_for_status()
        except httpx2.HTTPStatusError as exc:
            logger.warning(
                "Ollama generation request failed: status_code=%s",
                exc.response.status_code,
            )
            raise OllamaServiceError(
                "Ollama could not generate a response for the requested model"
            ) from exc
        except httpx2.HTTPError as exc:
            logger.warning("Ollama generation request failed: %s", exc)
            raise OllamaServiceError("Unable to connect to Ollama") from exc

        data = response.json()
        generated_text = data.get("response")

        if not isinstance(generated_text, str):
            raise OllamaServiceError("Ollama returned an invalid generation response")

        return ChatResponse(message=generated_text, model=model)

    def _parse_models(self, payload: dict[str, Any]) -> list[OllamaModelInfo]:
        """
        Convert Ollama's model list payload into DevLoopAI's API model shape.
        """
        raw_models = payload.get("models", [])

        if not isinstance(raw_models, list):
            return []

        models: list[OllamaModelInfo] = []

        for raw_model in raw_models:
            if not isinstance(raw_model, dict):
                continue

            name = raw_model.get("name")

            if isinstance(name, str) and name:
                models.append(OllamaModelInfo(name=name))

        return models
