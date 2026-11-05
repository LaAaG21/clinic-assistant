"""Server-owned conversation creation, committed before HTTP success (#44)."""

from collections.abc import Iterator
from typing import Annotated
from uuid import uuid4

import psycopg
from fastapi import APIRouter, Depends, Response
from pydantic import AwareDatetime

from clinic_assistant import database
from clinic_assistant.errors import DependencyFailure
from clinic_assistant.messages import BoundaryModel, OpaqueID

Conn = psycopg.Connection[tuple[object, ...]]
router = APIRouter()


class CreateConversationRequest(BoundaryModel):
    pass


class CreatedConversation(BoundaryModel):
    conversation_id: OpaqueID
    created_at: AwareDatetime


def conversation_connection() -> Iterator[Conn]:
    try:
        settings = database.DatabaseSettings.from_env()
    except ValueError as exc:
        raise DependencyFailure("persistence_unavailable") from exc
    try:
        with database.connection(settings) as conn:
            yield conn
    except (psycopg.OperationalError, psycopg.InterfaceError) as exc:
        raise DependencyFailure("persistence_unavailable") from exc


@router.post("/conversations", response_model=CreatedConversation, status_code=201)
def create_conversation(
    body: CreateConversationRequest,
    response: Response,
    conn: Annotated[Conn, Depends(conversation_connection)],
) -> CreatedConversation:
    conversation_id = "conv_" + uuid4().hex
    row = conn.execute(
        "INSERT INTO conversations (conversation_id) VALUES (%s) RETURNING created_at",
        (conversation_id,),
    ).fetchone()
    assert row is not None
    result = CreatedConversation.model_validate(
        {"conversation_id": conversation_id, "created_at": row[0]}
    )
    conn.commit()
    response.headers["Location"] = "/conversations/" + conversation_id
    return result
