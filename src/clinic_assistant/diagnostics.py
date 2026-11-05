"""Safe diagnostic logging: fixed codes, types and locations, never values.

A log line names the event, the public error code, the request correlation ID,
the matched route template and the failure's exception type and innermost frame.
It never contains request bodies, model text, connection strings, keys or an
exception's message, because driver and provider messages can embed all of those.
"""

import logging
import re
import traceback
import uuid
from pathlib import PurePath

from fastapi import Request

logger = logging.getLogger("clinic_assistant.diagnostics")
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


def request_id(request: Request) -> str:
    """Reuse a safe client-supplied X-Request-ID, else assign one per request."""
    existing: str | None = getattr(request.state, "request_id", None)
    if existing is not None:
        return existing
    supplied = request.headers.get("x-request-id", "")
    value = supplied if _SAFE_ID.fullmatch(supplied) else uuid.uuid4().hex
    request.state.request_id = value
    return value


def describe(exc: BaseException) -> str:
    """Exception type and innermost frame; the message is deliberately omitted."""
    kind = f"{type(exc).__module__}.{type(exc).__qualname__}"
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return kind
    frame = frames[-1]
    return f"{kind} at {PurePath(frame.filename).name}:{frame.lineno} in {frame.name}"


def log_failure(
    request: Request | None,
    event: str,
    code: str,
    cause: BaseException | None = None,
    *,
    level: int = logging.WARNING,
) -> None:
    """Record one safe line for a dependency, timeout or unexpected failure."""
    parts = [f"event={event}", f"code={code}"]
    if request is not None:
        route = request.scope.get("route")
        template = getattr(route, "path", "unmatched")
        parts += [
            f"request_id={request_id(request)}",
            f"method={request.method}",
            f"route={template}",
        ]
    if cause is not None:
        parts.append(f"cause={describe(cause)}")
    logger.log(level, " ".join(parts))
