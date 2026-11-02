"""Health checks and an unconfigured model seam, not a clinic workflow API."""

import os
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from clinic_assistant.database import database_is_ready
from clinic_assistant.llm import LanguageModel, ModelError, generate_draft


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class DraftRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    message: str = Field(min_length=1, max_length=4000)


class DraftResponse(BaseModel):
    draft: str


def create_app(
    *, model: LanguageModel | None = None, database_url: str | None = None
) -> FastAPI:
    """Build an API; production model integration is deliberately unimplemented."""
    app = FastAPI(title="Clinic Front-Desk Assistant foundation", version="0.1.0")
    configured_database_url = (
        database_url if database_url is not None else os.getenv("DATABASE_URL")
    )

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        """Report process liveness without relying on external services."""
        return HealthResponse()

    @app.get("/ready", response_model=HealthResponse)
    def ready() -> HealthResponse:
        """Report whether the configured PostgreSQL database is available."""
        if not database_is_ready(configured_database_url):
            raise HTTPException(status_code=503, detail="Database is unavailable")
        return HealthResponse()

    @app.post("/draft", response_model=DraftResponse)
    def draft(request: DraftRequest) -> DraftResponse:
        """Exercise an injected adapter; no model is configured by the default app."""
        if model is None:
            raise HTTPException(
                status_code=503, detail="Model adapter is not configured"
            )
        try:
            return DraftResponse(draft=generate_draft(model, request.message))
        except ModelError as error:
            raise HTTPException(
                status_code=502, detail="Model adapter could not produce a draft"
            ) from error

    return app


app = create_app()
