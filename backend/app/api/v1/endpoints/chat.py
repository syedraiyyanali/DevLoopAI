import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from starlette import status

from app.core.config import settings
from app.models.chat import ChatRequest, ChatResponse
from app.services.ollama import OllamaService, OllamaServiceError, OllamaStreamError


router = APIRouter(prefix="/chat")


@router.post(
    "",
    response_model=ChatResponse,
    summary="Generate a chat response",
    description="Generate a basic non-streaming response through the configured model backend.",
)
async def create_chat_response(chat_request: ChatRequest) -> ChatResponse:
    """
    Generate a non-streaming chat response using the configured Ollama backend.
    """
    service = OllamaService(settings)

    try:
        return await service.generate_chat_response(chat_request)
    except OllamaServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc


@router.post(
    "/stream",
    summary="Stream a chat response",
    description="Stream a basic response through the configured model backend.",
)
async def stream_chat_response(chat_request: ChatRequest) -> StreamingResponse:
    """
    Stream a non-persistent chat response using the configured Ollama backend.
    """
    service = OllamaService(settings)

    return StreamingResponse(
        stream_chat_events(service, chat_request),
        media_type="application/x-ndjson",
    )


async def stream_chat_events(
    service: OllamaService,
    chat_request: ChatRequest,
) -> AsyncIterator[str]:
    """
    Convert service stream chunks into newline-delimited JSON events.
    """
    try:
        async for chunk in service.stream_chat_response(chat_request):
            yield encode_stream_event(
                {
                    "type": "chunk",
                    "content": chunk,
                }
            )

        yield encode_stream_event({"type": "done"})
    except OllamaStreamError as exc:
        yield encode_stream_event(
            {
                "type": "error",
                "message": str(exc),
            }
        )


def encode_stream_event(payload: dict[str, str]) -> str:
    """
    Encode one streaming event as newline-delimited JSON.
    """
    return f"{json.dumps(payload)}\n"
