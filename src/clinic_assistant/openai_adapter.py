"""Real async SDK implementation of the shared raw-text model contract (#53)."""

import asyncio

from openai import (
    APIConnectionError,
    APIResponseValidationError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
)
from openai.types.responses import ResponseInputParam

from clinic_assistant.errors import DependencyFailure
from clinic_assistant.model_adapter import ModelInput
from clinic_assistant.settings import AppSettings, SettingsError


class OpenAIModelAdapter:
    def __init__(self, settings: AppSettings) -> None:
        if (
            settings.model_backend != "openai"
            or settings.openai_api_key is None
            or not settings.openai_api_key.get_secret_value().strip()
            or not settings.openai_model
            or not settings.openai_model.strip()
        ):
            raise SettingsError(
                "OpenAI adapter requires the real backend, API key, and model"
            )
        if not 1 <= settings.openai_timeout_seconds <= 120:
            raise SettingsError("OPENAI_TIMEOUT_SECONDS must be from 1 to 120")
        if (
            type(settings.openai_max_retries) is not int
            or not 0 <= settings.openai_max_retries <= 2
        ):
            raise SettingsError("OPENAI_MAX_RETRIES must be an integer from 0 to 2")
        self._settings = settings

    async def generate(self, messages: ModelInput) -> str:
        settings = self._settings
        assert settings.openai_api_key is not None
        assert settings.openai_model is not None
        request: ResponseInputParam = [
            {"role": message.role, "content": message.content} for message in messages
        ]
        deadline = asyncio.timeout(settings.openai_timeout_seconds)
        try:
            async with (
                deadline,
                AsyncOpenAI(
                    api_key=settings.openai_api_key.get_secret_value(),
                    timeout=float(settings.openai_timeout_seconds),
                    max_retries=settings.openai_max_retries,
                ) as client,
            ):
                response = await client.responses.create(
                    model=settings.openai_model, input=request, store=False
                )
                if (
                    response.status != "completed"
                    or response.error is not None
                    or response.incomplete_details is not None
                    or not response.output_text.strip()
                ):
                    raise DependencyFailure()
                return response.output_text
        except APITimeoutError as exc:
            raise DependencyFailure("dependency_timeout") from exc
        except APIStatusError as exc:
            raise DependencyFailure(
                "dependency_timeout"
                if exc.status_code in (408, 504)
                else "dependency_unavailable"
            ) from exc
        except (APIConnectionError, APIResponseValidationError) as exc:
            raise DependencyFailure() from exc
        except TimeoutError as exc:
            if not deadline.expired():
                raise  # An unrelated programming/hook timeout is not a provider outage.
            raise DependencyFailure("dependency_timeout") from exc
