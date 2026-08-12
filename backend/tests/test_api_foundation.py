from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exception_handlers import register_exception_handlers
from app.main import app


client = TestClient(app, raise_server_exceptions=False)


def test_root_endpoint_returns_backend_metadata():
    response = client.get("/")

    assert response.status_code == 200
    assert response.json() == {
        "message": "DevLoopAI API is running",
        "version": "0.1.0",
        "environment": "development",
        "docs": "/docs",
        "api": "/api/v1",
    }


def test_health_endpoint_is_available_at_root_and_api_prefix():
    root_health = client.get("/health")
    api_health = client.get("/api/v1/health")

    assert root_health.status_code == 200
    assert api_health.status_code == 200
    assert root_health.json()["status"] == "healthy"
    assert api_health.json()["status"] == "healthy"


def test_not_found_errors_use_standard_shape():
    response = client.get("/missing")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "HTTP_ERROR",
            "message": "Not Found",
            "status_code": 404,
        }
    }


def test_validation_errors_use_standard_shape():
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/items/{item_id}")
    async def get_item(item_id: int) -> dict[str, int]:
        return {"item_id": item_id}

    test_client = TestClient(test_app, raise_server_exceptions=False)

    response = test_client.get("/items/not-an-integer")

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["message"] == "Request validation failed"
    assert body["error"]["status_code"] == 422
    assert body["error"]["details"]


def test_unhandled_errors_hide_internal_details():
    test_app = FastAPI()
    register_exception_handlers(test_app)

    @test_app.get("/boom")
    async def boom() -> dict[str, str]:
        raise RuntimeError("secret internal failure")

    test_client = TestClient(test_app, raise_server_exceptions=False)

    response = test_client.get("/boom")

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "INTERNAL_SERVER_ERROR",
            "message": "An unexpected server error occurred",
            "status_code": 500,
        }
    }
