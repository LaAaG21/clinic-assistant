"""Real SDK with intercepted HTTP only: request shape, bounds, and cleanup."""

import asyncio
import json
from dataclasses import replace
from typing import Any

import httpx
import pytest
from openai import AsyncOpenAI, InternalServerError

from clinic_assistant import openai_adapter
from clinic_assistant.model_adapter import FakeModelAdapter, ModelAdapter, ModelMessage
from clinic_assistant.settings import AppSettings, SettingsError, load_settings


def environment(**overrides: str) -> dict[str, str]:
    return {
        "DATABASE_URL": "postgresql://test:db-marker@localhost/test",
        "CLINIC_TIMEZONE": "UTC",
        "MODEL_BACKEND": "openai",
        "OPENAI_API_KEY": "synthetic-key-marker",
        "OPENAI_MODEL": "configured-test-model",
        **overrides,
    }


def sdk_response(text: str) -> dict[str, Any]:
    return {
        "id": "resp_test",
        "object": "response",
        "created_at": 0,
        "model": "configured-test-model",
        "status": "completed",
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "output": [
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            }
        ],
    }


@pytest.mark.parametrize("output", ['{"intent":"clinic_question"}', " raw reply ", ""])
def test_shared_contract_real_sdk_shape_timeout_and_closed_client(
    output: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    requests: list[httpx.Request] = []
    clients: list[AsyncOpenAI] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/v1/responses"
        assert json.loads(request.content) == {
            "model": "configured-test-model",
            "store": False,
            "input": [{"role": m.role, "content": m.content} for m in messages],
        }
        assert all(v == 3.0 for v in request.extensions["timeout"].values())
        return httpx.Response(200, json=sdk_response(output))

    def client_factory(**kwargs: Any) -> AsyncOpenAI:
        assert kwargs == {
            "api_key": "synthetic-key-marker",
            "timeout": 3.0,
            "max_retries": 0,
        }
        client = AsyncOpenAI(
            **kwargs,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        clients.append(client)
        return client

    monkeypatch.setattr(openai_adapter, "AsyncOpenAI", client_factory)
    messages = (
        ModelMessage("system", "Rules"),
        ModelMessage("user", "Question"),
        ModelMessage("assistant", "Prior reply"),
    )
    settings = load_settings(environment(OPENAI_TIMEOUT_SECONDS="3"))
    adapter: ModelAdapter = openai_adapter.OpenAIModelAdapter(settings)
    assert asyncio.run(adapter.generate(messages)) == output
    assert asyncio.run(FakeModelAdapter(output).generate(messages)) == output
    assert clients[0].is_closed()
    assert len(requests) == 1
    assert "synthetic-key-marker" not in repr(settings) + repr(adapter)


@pytest.mark.parametrize("retries", [0, 1])
def test_bounded_sdk_retries_propagate_failure_and_close(
    retries: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    attempts = 0
    clients: list[AsyncOpenAI] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(500, json={"error": {"message": "controlled failure"}})

    def client_factory(**kwargs: Any) -> AsyncOpenAI:
        client = AsyncOpenAI(
            **kwargs,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        clients.append(client)
        return client

    monkeypatch.setattr(openai_adapter, "AsyncOpenAI", client_factory)
    adapter = openai_adapter.OpenAIModelAdapter(
        load_settings(environment(OPENAI_MAX_RETRIES=str(retries)))
    )
    with pytest.raises(InternalServerError):
        asyncio.run(adapter.generate((ModelMessage("user", "Question"),)))
    assert attempts == retries + 1
    assert clients[0].is_closed()


def test_total_deadline_cancels_mocked_wait_and_closes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clients: list[AsyncOpenAI] = []

    async def blocked(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(10)
        pytest.fail("Overall deadline did not cancel the request")

    def client_factory(**kwargs: Any) -> AsyncOpenAI:
        client = AsyncOpenAI(
            **kwargs,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(blocked)),
        )
        clients.append(client)
        return client

    monkeypatch.setattr(openai_adapter, "AsyncOpenAI", client_factory)
    adapter = openai_adapter.OpenAIModelAdapter(
        load_settings(environment(OPENAI_TIMEOUT_SECONDS="1"))
    )
    with pytest.raises(TimeoutError):
        asyncio.run(adapter.generate((ModelMessage("user", "Question"),)))
    assert clients[0].is_closed()


@pytest.mark.parametrize(
    "field,value",
    [
        ("OPENAI_MODEL", ""),
        ("OPENAI_TIMEOUT_SECONDS", "0"),
        ("OPENAI_TIMEOUT_SECONDS", "121"),
        ("OPENAI_TIMEOUT_SECONDS", "nan"),
        ("OPENAI_MAX_RETRIES", "-1"),
        ("OPENAI_MAX_RETRIES", "3"),
        ("OPENAI_MAX_RETRIES", "secret-marker"),
    ],
)
def test_invalid_model_settings_are_safe(field: str, value: str) -> None:
    with pytest.raises(SettingsError) as error:
        load_settings(environment(**{field: value}))
    assert field in str(error.value)
    assert "secret-marker" not in str(error.value)


def test_fake_mode_needs_no_model_configuration() -> None:
    values = environment(MODEL_BACKEND="fake")
    for key in ("OPENAI_API_KEY", "OPENAI_MODEL"):
        del values[key]
    settings = load_settings(values)
    assert settings.openai_api_key is None and settings.openai_model is None
    assert settings.openai_timeout_seconds == 10 and settings.openai_max_retries == 0
    with pytest.raises(SettingsError):
        openai_adapter.OpenAIModelAdapter(settings)


@pytest.mark.parametrize(
    "changes",
    [
        {"openai_api_key": None},
        {"openai_model": " "},
        {"openai_timeout_seconds": 0},
        {"openai_max_retries": 3},
    ],
)
def test_adapter_rejects_invalid_manually_constructed_settings(
    changes: dict[str, Any],
) -> None:
    settings: AppSettings = replace(load_settings(environment()), **changes)
    with pytest.raises(SettingsError):
        openai_adapter.OpenAIModelAdapter(settings)
