"""Safe HTTP boundary errors; adapters explicitly identify dependency failures."""

import logging
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from clinic_assistant.diagnostics import log_failure, request_id

DependencyCode = Literal[
    "dependency_unavailable", "persistence_unavailable", "dependency_timeout"
]
ConflictCode = Literal["conversation_busy", "idempotency_conflict", "decision_conflict"]
_CONFLICT_ERRORS = {
    "conversation_busy": "The conversation already has a pending operation.",
    "idempotency_conflict": "The message ID was already used for different input.",
    "decision_conflict": "A different staff decision was already recorded.",
}

_DEPENDENCY_ERRORS: dict[str, tuple[int, str]] = {
    "dependency_unavailable": (503, "A required service is unavailable."),
    "persistence_unavailable": (503, "Durable acceptance could not be confirmed."),
    "dependency_timeout": (504, "A required service timed out."),
}
_HTTP_ERRORS = {
    400: ("bad_request", "The request could not be accepted."),
    401: ("unauthorized", "Authentication is required."),
    403: ("forbidden", "Access is forbidden."),
    404: ("not_found", "The requested resource was not found."),
    405: ("method_not_allowed", "The request method is not allowed."),
    409: ("conflict", "The request conflicts with the current state."),
    422: ("validation_error", "The request contains invalid fields."),
    429: ("too_many_requests", "Too many requests."),
    503: ("dependency_unavailable", _DEPENDENCY_ERRORS["dependency_unavailable"][1]),
    504: ("dependency_timeout", _DEPENDENCY_ERRORS["dependency_timeout"][1]),
}
_VALIDATION_REASONS = {
    "missing": "required",
    "string_too_short": "invalid_length",
    "string_too_long": "invalid_length",
    "string_type": "invalid_type",
    "uuid_parsing": "invalid_uuid",
    "uuid_type": "invalid_uuid",
    "extra_forbidden": "unexpected_field",
}


class DependencyFailure(Exception):
    """Raise only for a recognized adapter failure, chaining the original cause.

    An unknown driver error or arbitrary TimeoutError remains a server defect.
    Raw exception text is never used to construct the public response.
    """

    def __init__(self, code: DependencyCode = "dependency_unavailable") -> None:
        if code not in _DEPENDENCY_ERRORS:
            raise ValueError("Unknown dependency failure code")
        self.code = code
        super().__init__(code)


class RequestConflict(Exception):
    """A recognized workflow conflict; arbitrary HTTPException detail is not public."""

    def __init__(self, code: ConflictCode) -> None:
        if code not in _CONFLICT_ERRORS:
            raise ValueError("Unknown request conflict code")
        self.code = code
        super().__init__(code)


def _response(
    request: Request,
    status: int,
    code: str,
    message: str,
    *,
    fields: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    # The correlation ID lets a patient report be matched with the diagnostic log.
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "fields": fields or {}}},
        headers={**(headers or {}), "X-Request-ID": request_id(request)},
    )


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = exc.errors()
    if any(error["type"] == "json_invalid" for error in errors):
        return _response(
            request, 400, "invalid_json", "The request body must be valid JSON."
        )

    fields: dict[str, str] = {}
    for error in errors:
        # Unknown keys and custom validator messages can contain patient input.
        # Expose only the current message model's declared, public field names.
        loc = error["loc"]
        field = (
            loc[1]
            if len(loc) == 2
            and loc[0] == "body"
            and loc[1] in {"text", "client_message_id"}
            else "request"
        )
        fields.setdefault(
            field, _VALIDATION_REASONS.get(error["type"], "invalid_value")
        )
    return _response(
        request,
        422,
        "validation_error",
        "The request contains invalid fields.",
        fields=fields,
    )


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, HTTPException)
    fallback = (
        ("internal_error", "An unexpected error occurred.")
        if exc.status_code >= 500
        else ("http_error", "The request could not be accepted.")
    )
    code, message = _HTTP_ERRORS.get(exc.status_code, fallback)
    if exc.status_code >= 500:
        log_failure(request, f"http_{exc.status_code}", code, level=logging.ERROR)
    # These protocol headers remain useful to clients. Callers must supply safe
    # public values; internal diagnostic headers and exception detail are dropped.
    headers = {
        name: value
        for name, value in (exc.headers or {}).items()
        if name.lower() in {"allow", "www-authenticate", "retry-after"}
    }
    return _response(request, exc.status_code, code, message, headers=headers)


async def _dependency_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DependencyFailure)
    status, message = _DEPENDENCY_ERRORS[exc.code]
    # Unconfirmed durable acceptance needs operator attention; outages and
    # timeouts are expected dependency conditions.
    level = logging.ERROR if exc.code == "persistence_unavailable" else logging.WARNING
    log_failure(request, "dependency_failure", exc.code, exc.__cause__, level=level)
    return _response(request, status, exc.code, message)


async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    log_failure(
        request, "unexpected_failure", "internal_error", exc, level=logging.ERROR
    )
    return _response(request, 500, "internal_error", "An unexpected error occurred.")


async def _conflict_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestConflict)
    return _response(request, 409, exc.code, _CONFLICT_ERRORS[exc.code])


def register_error_handlers(app: FastAPI) -> None:
    """Register once at app construction; explicit endpoint responses are untouched."""
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(HTTPException, _http_error)
    app.add_exception_handler(DependencyFailure, _dependency_error)
    app.add_exception_handler(RequestConflict, _conflict_error)
    app.add_exception_handler(Exception, _unexpected_error)
