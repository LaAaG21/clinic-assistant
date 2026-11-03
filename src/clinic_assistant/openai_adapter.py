"""Real async SDK implementation of the shared raw-text model contract (#53)."""

import asyncio

from openai import AsyncOpenAI
from openai.types.responses import ResponseInputParam

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
        async with (
            asyncio.timeout(settings.openai_timeout_seconds),
            AsyncOpenAI(
                api_key=settings.openai_api_key.get_secret_value(),
                timeout=float(settings.openai_timeout_seconds),
                max_retries=settings.openai_max_retries,
            ) as client,
        ):
            response = await client.responses.create(
                model=settings.openai_model, input=request, store=False
            )
            return response.output_text
