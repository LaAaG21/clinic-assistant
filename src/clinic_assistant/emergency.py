"""Emergency guard: a deterministic check that runs before any ordinary work.

The guard never calls the model. For an emergency it returns the safety reply
immediately and persists a staff flag with plain SQL (#12) in the agreed table
(#22). A persistence failure still surfaces the reply, reports the failure and
never claims staff were flagged. Nothing here reads or resumes other work.
"""

import logging
import re
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

import psycopg

from clinic_assistant import database

logger = logging.getLogger(__name__)

# Proposed fixed examples (FR-6); wording and coverage still need team review.
EMERGENCY_REPLY = (
    "Seek emergency help now. Call your local emergency number or go to the "
    "nearest emergency department. Do not wait for a chat reply."
)
EMERGENCY_PHRASES = (
    "chest pain",
    "heart attack",
    "stroke",
    "can't breathe",
    "cannot breathe",
    "can not breathe",
    "not breathing",
    "difficulty breathing",
    "trouble breathing",
    "unconscious",
    "unresponsive",
    "severe bleeding",
    "heavy bleeding",
    "bleeding heavily",
    "overdose",
    "suicide",
    "suicidal",
    "kill myself",
    "end my life",
    "seizure",
    "choking",
    "anaphylaxis",
    "severe allergic reaction",
    "medical emergency",
    "this is an emergency",
    "it's an emergency",
)
_PATTERN = re.compile(
    r"\b(?:" + "|".join(re.escape(p) for p in EMERGENCY_PHRASES) + r")\b"
)

Connect = Callable[[], AbstractContextManager[psycopg.Connection[tuple[object, ...]]]]


def is_emergency(text: str) -> bool:
    """Match the fixed phrases on normalized text; no model, no I/O."""
    normalized = re.sub(r"\s+", " ", text.replace("’", "'").casefold())
    return _PATTERN.search(normalized) is not None


@dataclass(frozen=True)
class EmergencyResult:
    """Reply for the patient plus the flag identity for staff and later dispatch."""

    conversation_id: str
    message_id: str
    reply: str = EMERGENCY_REPLY
    flag_id: str | None = None
    flagged_at: datetime | None = None
    error: Literal["persistence_unavailable"] | None = None

    @property
    def flag_persisted(self) -> bool:
        return self.flag_id is not None


def flag_emergency(
    conversation_id: str, message_id: str, connect: Connect = database.connection
) -> EmergencyResult:
    """Persist one flag per message (retries return the same flag) or report failure.

    The reply is returned in every case. Only the fixed error code is logged on
    failure; the driver message may contain the connection string.
    """
    flag_id = "flag_" + uuid.uuid4().hex
    try:
        with connect() as conn:
            row = conn.execute(
                "INSERT INTO emergency_flags (flag_id, conversation_id, message_id)"
                " VALUES (%s, %s, %s)"
                " ON CONFLICT (message_id)"
                " DO UPDATE SET message_id = EXCLUDED.message_id"
                " RETURNING flag_id, created_at",
                (flag_id, conversation_id, message_id),
            ).fetchone()
    except (psycopg.Error, ValueError):
        logger.error("Emergency flag persistence failed: persistence_unavailable")
        return EmergencyResult(
            conversation_id, message_id, error="persistence_unavailable"
        )
    assert row is not None
    saved_id, created_at = row
    assert isinstance(saved_id, str) and isinstance(created_at, datetime)
    return EmergencyResult(
        conversation_id, message_id, flag_id=saved_id, flagged_at=created_at
    )


def guard[T](
    text: str,
    conversation_id: str,
    message_id: str,
    ordinary: Callable[[], T],
    connect: Connect = database.connection,
) -> EmergencyResult | T:
    """Run the guard first; call `ordinary` (classify, busy check, graph) if clear."""
    if is_emergency(text):
        return flag_emergency(conversation_id, message_id, connect)
    return ordinary()
