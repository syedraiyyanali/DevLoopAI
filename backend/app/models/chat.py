from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """
    Request body for a basic non-streaming chat completion.
    """
    message: str = Field(..., min_length=1)
    model: str | None = None
    response_format: str | None = None


class ChatResponse(BaseModel):
    """
    Response body returned after the model generates text.
    """
    message: str
    model: str
