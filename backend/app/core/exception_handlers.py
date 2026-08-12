import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette import status


logger = logging.getLogger(__name__)
HTTP_422_UNPROCESSABLE_CONTENT = 422


def error_content(
    *,
    code: str,
    message: str,
    status_code: int,
    details: Any | None = None,
) -> dict[str, Any]:
    """
    Create the standard DevLoopAI API error response shape.
    """
    content: dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "status_code": status_code,
        }
    }

    if details is not None:
        content["error"]["details"] = details

    return content


async def http_exception_handler(
    request: Request,
    exc: StarletteHTTPException,
) -> JSONResponse:
    """
    Return predictable JSON for HTTP errors such as 404.
    """
    logger.info(
        "HTTP exception: method=%s path=%s status_code=%s",
        request.method,
        request.url.path,
        exc.status_code,
    )

    message = exc.detail if isinstance(exc.detail, str) else "HTTP error"

    return JSONResponse(
        status_code=exc.status_code,
        content=error_content(
            code="HTTP_ERROR",
            message=message,
            status_code=exc.status_code,
        ),
    )


async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """
    Return predictable JSON for invalid request payloads or parameters.
    """
    logger.info(
        "Validation error: method=%s path=%s",
        request.method,
        request.url.path,
    )

    return JSONResponse(
        status_code=HTTP_422_UNPROCESSABLE_CONTENT,
        content=error_content(
            code="VALIDATION_ERROR",
            message="Request validation failed",
            status_code=HTTP_422_UNPROCESSABLE_CONTENT,
            details=exc.errors(),
        ),
    )


async def unhandled_exception_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """
    Hide internal exception details from API clients while logging them.
    """
    logger.exception(
        "Unhandled exception: method=%s path=%s",
        request.method,
        request.url.path,
        exc_info=exc,
    )

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_content(
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected server error occurred",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """
    Register shared exception handlers for the FastAPI application.
    """
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)
