"""Settings validation uses isolated synthetic values, never a local .env."""

import os
import traceback
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import NoReturn

import pytest

from clinic_assistant import settings
from clinic_assistant.booking_policy import is_same_day_booking
from clinic_assistant.database import DatabaseSettings


@pytest.fixture
def environment() -> dict[str, str]:
    return {
        "DATABASE_URL": "postgresql://clinic:secret-marker@localhost:5432/clinic",
        "CLINIC_TIMEZONE": "Asia/Dubai",
    }


@pytest.fixture(autouse=True)
def clear_settings_cache() -> Iterator[None]:
    settings.get_settings.cache_clear()
    yield
    settings.get_settings.cache_clear()


def test_fake_settings_need_no_key_or_connection(
    environment: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_connection(*args: object, **kwargs: object) -> NoReturn:
        pytest.fail("Loading settings must not open a database connection")

    monkeypatch.setattr("psycopg.connect", unexpected_connection)
    result = settings.load_settings(environment)
    assert result.database == DatabaseSettings(environment["DATABASE_URL"])
    assert result.clinic_timezone == "Asia/Dubai"
    assert result.model_backend == "fake"
    assert result.openai_api_key is None
    assert "secret-marker" not in repr(result)


@pytest.mark.parametrize("field", ["DATABASE_URL", "CLINIC_TIMEZONE"])
@pytest.mark.parametrize("value", [None, "", "   "])
def test_required_settings(
    environment: dict[str, str], field: str, value: str | None
) -> None:
    environment.pop(field)
    if value is not None:
        environment[field] = value
    with pytest.raises(settings.SettingsError, match=f"^{field} is required$"):
        settings.load_settings(environment)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("DATABASE_URL", "sqlite:///secret-marker"),
        ("DATABASE_URL", "postgresql://user:secret-marker@localhost:bad/db"),
        ("DATABASE_URL", "postgresql://user:secret-marker@localhost:0/db"),
        ("DATABASE_URL", "postgresql://user:secret-marker@localhost:65536/db"),
        ("DATABASE_URL", "postgresql://user:secret-marker@localhost/db?unknown=x"),
        ("DATABASE_URL", "postgresql://user:secret-marker@host1,host2/db"),
        ("DATABASE_URL", "postgresql://localhost/db"),
        ("DATABASE_URL", "postgresql://user:secret-marker@localhost"),
        ("CLINIC_TIMEZONE", "Invalid/secret-marker"),
        ("CLINIC_TIMEZONE", "../secret-marker"),
        ("DB_CONNECT_TIMEOUT_SECONDS", "1"),
        ("DB_CONNECT_TIMEOUT_SECONDS", "secret-marker"),
        ("DB_QUERY_TIMEOUT_MS", "0"),
        ("DB_QUERY_TIMEOUT_MS", "1.5"),
        ("MODEL_BACKEND", "secret-marker"),
    ],
)
def test_invalid_settings_are_secret_safe(
    environment: dict[str, str], field: str, value: str
) -> None:
    environment[field] = value
    with pytest.raises(settings.SettingsError) as error:
        settings.load_settings(environment)
    assert field in str(error.value)
    assert "secret-marker" not in "".join(traceback.format_exception(error.value))


def test_explicit_timeouts_and_model_key(environment: dict[str, str]) -> None:
    environment.update(
        DB_CONNECT_TIMEOUT_SECONDS="3",
        DB_QUERY_TIMEOUT_MS="250",
        MODEL_BACKEND="openai",
        OPENAI_API_KEY="synthetic-key-marker",
        OPENAI_MODEL="configured-test-model",
    )
    result = settings.load_settings(environment)
    assert result.database.connect_timeout_seconds == 3
    assert result.database.query_timeout_ms == 250
    assert result.model_backend == "openai"
    assert result.openai_api_key is not None
    assert result.openai_api_key.get_secret_value() == "synthetic-key-marker"
    assert "synthetic-key-marker" not in repr(result) + str(result.openai_api_key)


def test_real_backend_requires_key(environment: dict[str, str]) -> None:
    environment["MODEL_BACKEND"] = "openai"
    with pytest.raises(settings.SettingsError, match="OPENAI_API_KEY is required"):
        settings.load_settings(environment)


def test_environment_loaded_once_without_dotenv(
    environment: dict[str, str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    (tmp_path / ".env").write_text("CLINIC_TIMEZONE=Invalid/secret-marker\n")
    monkeypatch.chdir(tmp_path)
    # A process snapshot prevents unrelated developer environment values leaking in.
    monkeypatch.setattr(os, "environ", environment.copy())
    first = settings.get_settings()
    monkeypatch.setenv("CLINIC_TIMEZONE", "UTC")
    assert settings.get_settings() is first
    assert first.clinic_timezone == "Asia/Dubai"
    settings.get_settings.cache_clear()
    assert settings.get_settings().clinic_timezone == "UTC"


def test_timezone_feeds_existing_booking_policy(environment: dict[str, str]) -> None:
    result = settings.load_settings(environment)
    assert is_same_day_booking(
        datetime.fromisoformat("2026-11-03T00:30:00+04:00"),
        datetime.fromisoformat("2026-11-02T21:00:00+00:00"),
        result.clinic_timezone,
    )
