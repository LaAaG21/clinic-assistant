"""HTTP health contract backed by the shared PostgreSQL probe."""

import logging
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel

from clinic_assistant import database

router = APIRouter()
logger = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    api: Literal["reachable"] = "reachable"
    database: Literal["reachable", "unreachable"]


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "Database unavailable"}},
)
def health(response: Response) -> HealthResponse:
    """Run blocking database I/O in FastAPI's synchronous handler thread pool."""
    result = database.probe_database()
    response.headers["Cache-Control"] = "no-store"
    if result.ok:
        return HealthResponse(status="ok", database="reachable")
    logger.warning("Health probe failed: %s", result.error)
    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(status="unavailable", database="unreachable")
