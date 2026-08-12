import logging
from typing import Any

import httpx2

from app.core.config import Settings
from app.models.ollama import OllamaModelInfo, OllamaStatus


logger = logging.getLogger(__name__)


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
