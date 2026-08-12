from pydantic import BaseModel, Field


class OllamaModelInfo(BaseModel):
    """
    Basic metadata for a model reported by Ollama.
    """
    name: str


class OllamaStatus(BaseModel):
    """
    Current status of the configured Ollama backend.
    """
    reachable: bool
    base_url: str
    configured_model: str
    configured_model_available: bool
    models: list[OllamaModelInfo] = Field(default_factory=list)
    error: str | None = None
