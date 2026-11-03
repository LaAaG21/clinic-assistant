"""Validated environment configuration without I/O or implicit .env loading."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from psycopg import ProgrammingError
from psycopg.conninfo import conninfo_to_dict
from pydantic import SecretStr

from clinic_assistant.database import DatabaseSettings


class SettingsError(ValueError):
    """Invalid configuration; messages name fields but never echo their values."""


@dataclass(frozen=True)
class AppSettings:
    database: DatabaseSettings
    clinic_timezone: str
    model_backend: Literal["fake", "openai"] = "fake"
    openai_api_key: SecretStr | None = field(default=None, repr=False)
    openai_model: str | None = None
    openai_timeout_seconds: int = 10
    openai_max_retries: int = 0


def _required(environment: Mapping[str, str], name: str) -> str:
    value = environment.get(name, "").strip()
    if not value:
        raise SettingsError(f"{name} is required")
    return value


def _timeout(
    environment: Mapping[str, str], name: str, default: str, minimum: int
) -> int:
    try:
        value = int(environment.get(name, default))
        if value < minimum:
            raise ValueError
    except ValueError:
        raise SettingsError(f"{name} must be an integer >= {minimum}") from None
    return value


def _database(environment: Mapping[str, str]) -> DatabaseSettings:
    url = _required(environment, "DATABASE_URL")
    try:
        if not url.startswith(("postgresql://", "postgres://")):
            raise ValueError
        parameters = {
            key: str(value)
            for key, value in conninfo_to_dict(url).items()
            if value is not None
        }
        if any(not parameters.get(key) for key in ("host", "dbname", "user")):
            raise ValueError
        if any("," in parameters.get(key, "") for key in ("host", "hostaddr")):
            raise ValueError
        if not 1 <= int(parameters.get("port", "5432")) <= 65535:
            raise ValueError
    except (ProgrammingError, ValueError):
        raise SettingsError(
            "DATABASE_URL must be a PostgreSQL URL with one host, user, "
            "database, and a valid port"
        ) from None
    return DatabaseSettings(
        url=url,
        connect_timeout_seconds=_timeout(
            environment, "DB_CONNECT_TIMEOUT_SECONDS", "2", 2
        ),
        query_timeout_ms=_timeout(environment, "DB_QUERY_TIMEOUT_MS", "1000", 1),
    )


def load_settings(environment: Mapping[str, str] | None = None) -> AppSettings:
    """Validate one environment snapshot; never connect to the database/model."""
    values = dict(os.environ if environment is None else environment)
    database = _database(values)
    timezone = _required(values, "CLINIC_TIMEZONE")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise SettingsError(
            "CLINIC_TIMEZONE must be an available IANA timezone"
        ) from None
    backend = values.get("MODEL_BACKEND", "fake")
    if backend not in ("fake", "openai"):
        raise SettingsError("MODEL_BACKEND must be fake or openai")
    mode: Literal["fake", "openai"] = "openai" if backend == "openai" else "fake"
    if mode == "fake":
        return AppSettings(database, timezone)
    key = SecretStr(_required(values, "OPENAI_API_KEY"))
    model = _required(values, "OPENAI_MODEL")
    timeout = _model_integer(values, "OPENAI_TIMEOUT_SECONDS", 10, 1, 120)
    retries = _model_integer(values, "OPENAI_MAX_RETRIES", 0, 0, 2)
    return AppSettings(database, timezone, mode, key, model, timeout, retries)


def _model_integer(
    values: Mapping[str, str], name: str, default: int, minimum: int, maximum: int
) -> int:
    try:
        value = int(values.get(name, str(default)))
        if not minimum <= value <= maximum:
            raise ValueError
    except ValueError:
        raise SettingsError(
            f"{name} must be an integer from {minimum} to {maximum}"
        ) from None
    return value


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Load once per process; restart after changing configuration."""
    return load_settings()
