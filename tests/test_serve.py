"""The container starts only after the shared environment validation succeeds."""

from collections.abc import Iterator
from unittest.mock import patch

import pytest

from clinic_assistant.serve import main
from clinic_assistant.settings import get_settings


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in (
        "DATABASE_URL",
        "CLINIC_TIMEZONE",
        "MODEL_BACKEND",
        "OPENAI_API_KEY",
        "DB_CONNECT_TIMEOUT_SECONDS",
        "DB_QUERY_TIMEOUT_MS",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_fake_mode_starts_without_model_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://clinic:synthetic@db:5432/clinic")
    monkeypatch.setenv("CLINIC_TIMEZONE", "Asia/Dubai")
    with patch("clinic_assistant.serve.uvicorn.run") as run:
        main()
    run.assert_called_once_with("clinic_assistant.main:app", host="0.0.0.0", port=8000)
    assert get_settings().model_backend == "fake"


@pytest.mark.parametrize("url", [None, "private-configuration-marker"])
def test_invalid_settings_prevent_startup(
    monkeypatch: pytest.MonkeyPatch, url: str | None
) -> None:
    if url is not None:
        monkeypatch.setenv("DATABASE_URL", url)
    with patch("clinic_assistant.serve.uvicorn.run") as run:
        with pytest.raises(SystemExit) as error:
            main()
    run.assert_not_called()
    assert "Configuration error: DATABASE_URL" in str(error.value)
    assert "private-configuration-marker" not in str(error.value)
