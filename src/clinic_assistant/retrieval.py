"""Bounded PostgreSQL English full-text retrieval of caller-supplied passages."""

from collections.abc import Sequence
from typing import Protocol, cast

from clinic_assistant.database import DatabaseSettings, connection


class PassageSource(Protocol):
    @property
    def passage_id(self) -> str: ...

    @property
    def source_id(self) -> str: ...

    @property
    def source_name(self) -> str: ...

    @property
    def text(self) -> str: ...


def retrieve[T: PassageSource](
    question: str, passages: Sequence[T], settings: DatabaseSettings, *, limit: int = 3
) -> list[T]:
    """Return original passage objects, ranked by ts_rank_cd then passage ID.

    The temporary corpus is local to this connection and dropped at commit.
    Database failures propagate; they are not disguised as zero matches.
    """
    if type(limit) is not int or not 1 <= limit <= 10:
        raise ValueError("Retrieval limit must be an integer from 1 to 10")
    by_id = {p.passage_id: p for p in passages}
    if len(by_id) != len(passages):
        raise ValueError("Passage IDs must be unique")
    if not question.strip() or not passages:
        return []
    with connection(settings) as conn, conn.cursor() as cursor:
        cursor.execute("""
            CREATE TEMP TABLE clinic_retrieval_passages (
                passage_id text PRIMARY KEY, body text NOT NULL,
                document tsvector GENERATED ALWAYS AS
                    (to_tsvector('english', body)) STORED
            ) ON COMMIT DROP
        """)
        cursor.executemany(
            "INSERT INTO clinic_retrieval_passages (passage_id, body) VALUES (%s, %s)",
            [(p.passage_id, p.text) for p in passages],
        )
        cursor.execute(
            """
            SELECT passage_id FROM clinic_retrieval_passages,
                plainto_tsquery('english', %s) AS query
            WHERE document @@ query
            ORDER BY ts_rank_cd(document, query) DESC, passage_id COLLATE "C"
            LIMIT %s
            """,
            (question, limit),
        )
        return [by_id[cast(str, row[0])] for row in cursor.fetchall()]
