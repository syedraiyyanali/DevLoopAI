import pytest
from pydantic import BaseModel

from app.services.model_reliability import StructuredOutputError, StructuredOutputParser
from app.services.ollama import OllamaServiceError


class SamplePayload(BaseModel):
    approval_recommendation: str
    items: list[str]


def test_parser_extracts_json_object_from_wrapped_text():
    parser = StructuredOutputParser()

    result = parser.parse(
        raw_response='Here is JSON: {"approval_recommendation":"APPROVE","items":["a"]}',
        model_type=SamplePayload,
        agent_name="Sample",
    )

    assert result.approval_recommendation == "APPROVE"
    assert result.items == ["a"]


def test_parser_normalizes_known_harmless_enums_only():
    parser = StructuredOutputParser()

    result = parser.parse(
        raw_response='{"approval_recommendation":"approve with changes","items":[]}',
        model_type=SamplePayload,
        agent_name="Sample",
    )

    assert result.approval_recommendation == "APPROVE_WITH_CHANGES"


def test_parser_rejects_unrepairable_malformed_output():
    parser = StructuredOutputParser()

    with pytest.raises(StructuredOutputError):
        parser.parse(
            raw_response="not-json",
            model_type=SamplePayload,
            agent_name="Sample",
        )


@pytest.mark.parametrize(
    ("message", "classification"),
    [
        ("CUDA out of memory while loading model", "MODEL_RESOURCE_EXHAUSTED"),
        ("Unable to connect to Ollama", "MODEL_UNAVAILABLE"),
        ("request timed out", "MODEL_TIMEOUT"),
        ("unexpected response", "MODEL_ERROR"),
    ],
)
def test_ollama_error_classification(message, classification):
    parser = StructuredOutputParser()

    assert parser.classify_ollama_error(OllamaServiceError(message)) == classification
