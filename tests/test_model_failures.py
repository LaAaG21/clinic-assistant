"""Controlled SDK failures use the shared safe errors, never answer fallbacks."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
)

from clinic_assistant import openai_adapter
from clinic_assistant.errors import DependencyFailure, register_error_handlers
from clinic_assistant.model_adapter import FakeModelAdapter, ModelMessage
from clinic_assistant.settings import load_settings

SECRET = "provider-secret-key-and-private-prompt-marker"
MESSAGES = (ModelMessage("user", SECRET),)
REQUEST = httpx.Request("POST", "https://api.openai.com/v1/responses")


def provider_error(kind: str) -> Exception:
    if kind == "timeout":
        return APITimeoutError(request=REQUEST)
    if kind == "connection":
        return APIConnectionError(message=SECRET, request=REQUEST)
    response = httpx.Response(
        503 if kind == "invalid-response" else int(kind), request=REQUEST
    )
    if kind == "invalid-response":
        return APIResponseValidationError(response=response, body={"secret": SECRET})
    return APIStatusError(SECRET, response=response, body={"secret": SECRET})


@pytest.fixture
def sdk(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[openai_adapter.OpenAIModelAdapter, AsyncMock]:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.__aexit__.return_value = False
    monkeypatch.setattr(openai_adapter, "AsyncOpenAI", Mock(return_value=client))
    settings = load_settings(
        {
            "DATABASE_URL": "postgresql://test:test@localhost/test",
            "CLINIC_TIMEZONE": "UTC",
            "MODEL_BACKEND": "openai",
            "OPENAI_API_KEY": SECRET,
            "OPENAI_MODEL": "test-model",
        }
    )
    return openai_adapter.OpenAIModelAdapter(settings), client


@pytest.mark.parametrize(
    "kind",
    [
        "timeout",
        "connection",
        "400",
        "401",
        "403",
        "404",
        "408",
        "422",
        "429",
        "500",
        "504",
        "invalid-response",
    ],
)
def test_recognized_failures_are_safe_and_fake_compatible(
    sdk: tuple[openai_adapter.OpenAIModelAdapter, AsyncMock], kind: str
) -> None:
    adapter, client = sdk
    original = provider_error(kind)
    client.responses.create.side_effect = original
    with pytest.raises(DependencyFailure) as error:
        asyncio.run(adapter.generate(MESSAGES))
    expected = (
        "dependency_timeout"
        if kind in {"timeout", "408", "504"}
        else "dependency_unavailable"
    )
    assert error.value.code == expected
    assert error.value.__cause__ is original
    assert SECRET not in str(error.value)
    fake = FakeModelAdapter(DependencyFailure(error.value.code))
    with pytest.raises(DependencyFailure) as fake_error:
        asyncio.run(fake.generate(MESSAGES))
    assert fake_error.value.code == expected
    client.__aexit__.assert_awaited_once()


@pytest.mark.parametrize(
    "kind,status,code",
    [
        ("timeout", 504, "dependency_timeout"),
        ("connection", 503, "dependency_unavailable"),
        ("401", 503, "dependency_unavailable"),
        ("504", 504, "dependency_timeout"),
    ],
)
def test_shared_http_handler_exposes_no_provider_details(
    sdk: tuple[openai_adapter.OpenAIModelAdapter, AsyncMock],
    kind: str,
    status: int,
    code: str,
) -> None:
    adapter, client = sdk
    client.responses.create.side_effect = provider_error(kind)
    app = FastAPI()
    register_error_handlers(app)

    @app.get("/model-failure")
    async def model_failure() -> str:
        return await adapter.generate(MESSAGES)

    with TestClient(app, raise_server_exceptions=False) as http:
        response = http.get("/model-failure")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["fields"] == {}
    assert SECRET not in response.text
    assert "Traceback" not in response.text


@pytest.mark.parametrize(
    "status,error,incomplete,text",
    [
        ("failed", {"message": SECRET}, None, "partial answer"),
        ("incomplete", None, {"reason": "max_output_tokens"}, "partial answer"),
        ("queued", None, None, "partial answer"),
        (None, None, None, "answer"),
        ("completed", {"message": SECRET}, None, "answer"),
        ("completed", None, None, ""),
        ("completed", None, None, " \n\t"),
    ],
)
def test_failed_incomplete_or_empty_response_is_not_success(
    sdk: tuple[openai_adapter.OpenAIModelAdapter, AsyncMock],
    status: str | None,
    error: object,
    incomplete: object,
    text: str,
) -> None:
    adapter, client = sdk
    client.responses.create.return_value = SimpleNamespace(
        status=status,
        error=error,
        incomplete_details=incomplete,
        output_text=text,
    )
    with pytest.raises(DependencyFailure) as failure:
        asyncio.run(adapter.generate(MESSAGES))
    assert failure.value.code == "dependency_unavailable"
    assert SECRET not in str(failure.value)
    client.__aexit__.assert_awaited_once()


@pytest.mark.parametrize(
    "original", [ValueError(SECRET), TimeoutError(SECRET), asyncio.CancelledError()]
)
def test_unknown_errors_and_cancellation_are_not_disguised(
    sdk: tuple[openai_adapter.OpenAIModelAdapter, AsyncMock], original: BaseException
) -> None:
    adapter, client = sdk
    client.responses.create.side_effect = original
    with pytest.raises(type(original)) as error:
        asyncio.run(adapter.generate(MESSAGES))
    assert error.value is original
    client.__aexit__.assert_awaited_once()
