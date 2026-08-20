import json
import re
from dataclasses import dataclass
from time import perf_counter
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from app.services.ollama import OllamaServiceError


ModelPayload = TypeVar("ModelPayload", bound=BaseModel)


class StructuredOutputError(Exception):
    """Raised when model output cannot be safely parsed and validated."""


@dataclass(frozen=True)
class ModelAttemptMetadata:
    """Safe metadata for one bounded model attempt."""

    agent: str
    model: str | None
    attempt_count: int
    duration_seconds: float
    failure_classification: str | None = None


class StructuredOutputParser:
    """Conservative structured-output parser for Ollama-backed agents."""

    enum_normalizations = {
        "approval_recommendation": {
            "approve": "APPROVE",
            "approved": "APPROVE",
            "approve with changes": "APPROVE_WITH_CHANGES",
            "approve_with_changes": "APPROVE_WITH_CHANGES",
            "reject": "REJECT",
            "rejected": "REJECT",
        },
        "overall_validation_status": {
            "ready": "READY",
            "ready with warnings": "READY_WITH_WARNINGS",
            "ready_with_warnings": "READY_WITH_WARNINGS",
            "blocked": "BLOCKED",
        },
    }

    def parse(
        self,
        *,
        raw_response: str,
        model_type: type[ModelPayload],
        agent_name: str,
    ) -> ModelPayload:
        try:
            payload = json.loads(raw_response)
        except json.JSONDecodeError:
            payload = self._extract_json_object(raw_response, agent_name)

        payload = self._normalize_payload(payload)

        try:
            return model_type.model_validate(payload)
        except ValidationError as exc:
            raise StructuredOutputError(
                f"{agent_name} model returned malformed structured output"
            ) from exc

    def classify_ollama_error(self, exc: OllamaServiceError) -> str:
        message = str(exc).lower()

        if any(marker in message for marker in ("cuda", "out of memory", "memory", "oom")):
            return "MODEL_RESOURCE_EXHAUSTED"

        if any(marker in message for marker in ("connect", "connection", "unavailable", "refused")):
            return "MODEL_UNAVAILABLE"

        if "timeout" in message or "timed out" in message:
            return "MODEL_TIMEOUT"

        return "MODEL_ERROR"

    def attempt_metadata(
        self,
        *,
        agent_name: str,
        model: str | None,
        started_at: float,
        attempt_count: int = 1,
        failure_classification: str | None = None,
    ) -> ModelAttemptMetadata:
        return ModelAttemptMetadata(
            agent=agent_name,
            model=model,
            attempt_count=attempt_count,
            duration_seconds=round(perf_counter() - started_at, 6),
            failure_classification=failure_classification,
        )

    def _extract_json_object(self, raw_response: str, agent_name: str) -> Any:
        match = re.search(r"\{.*\}", raw_response, flags=re.DOTALL)

        if match is None:
            raise StructuredOutputError(f"{agent_name} model did not return valid JSON")

        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise StructuredOutputError(f"{agent_name} model did not return valid JSON") from exc

    def _normalize_payload(self, payload: Any) -> Any:
        if not isinstance(payload, dict):
            return payload

        normalized = dict(payload)
        for field_name, mapping in self.enum_normalizations.items():
            value = normalized.get(field_name)
            if isinstance(value, str):
                normalized[field_name] = mapping.get(value.strip().lower(), value)

        return normalized
