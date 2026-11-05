"""Verify issue #72 on a disposable PostgreSQL database with DATABASE_URL set."""

import os
from pathlib import Path
from uuid import uuid4

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg import sql

from cancellation_pause import (
    CancellationRequest,
    build_cancellation_graph,
    pause_or_load,
)


def verify() -> None:
    url = os.environ["DATABASE_URL"]
    schema = sql.Identifier("cancellation_test_" + uuid4().hex)
    init_dir = Path(__file__).resolve().parents[2] / "db" / "init"
    with psycopg.connect(url, autocommit=True) as db:
        db.execute(sql.SQL("CREATE SCHEMA {}").format(schema))
        try:
            db.execute(sql.SQL("SET search_path TO {}").format(schema))
            for migration in sorted(init_dir.glob("*.sql")):
                db.execute(migration.read_text(encoding="utf-8"))
            db.execute("INSERT INTO doctors VALUES ('d', 'Dr. Example', 'general')")
            db.execute(
                "INSERT INTO slots VALUES"
                " ('today', 'd', now(), now() + interval '30 minutes'),"
                " ('future', 'd', now() + interval '2 days',"
                " now() + interval '2 days 30 minutes')"
            )
            db.execute("INSERT INTO conversations VALUES ('c'), ('other')")
            db.execute(
                "INSERT INTO bookings (booking_id, slot_id, conversation_id)"
                " VALUES ('today', 'today', 'c'), ('future', 'future', 'c')"
            )

            # Synthetic targets in place of the upstream model and router.
            for target, conversation, expected in (
                ("today", "c", "pending_approval"),
                ("future", "c", "pending_approval"),
                ("today", "other", "failed"),
                ("missing", "c", "failed"),
            ):
                thread = uuid4().hex
                request: CancellationRequest = {
                    "request_id": "req_" + thread,
                    "approval_id": "apr_" + thread,
                    "conversation_id": conversation,
                    "appointment_id": target,
                }
                with PostgresSaver.from_conn_string(url) as saver:
                    saver.setup()
                    graph = build_cancellation_graph(saver, db)
                    saved = pause_or_load(graph, thread_id=thread, request=request)
                    assert saved.values["status"] == expected
                    interrupts = [i for task in saved.tasks for i in task.interrupts]
                    if expected == "pending_approval":
                        assert len(interrupts) == 1
                        assert interrupts[0].value["appointment_id"] == target
                    else:
                        assert not interrupts
                with PostgresSaver.from_conn_string(url) as saver:
                    graph = build_cancellation_graph(saver, db)
                    reloaded = pause_or_load(graph, thread_id=thread, request=request)
                    assert reloaded.values == saved.values
                    assert reloaded.tasks == saved.tasks
                    changed_target = request.copy()
                    changed_target["appointment_id"] = "different"
                    try:
                        pause_or_load(graph, thread_id=thread, request=changed_target)
                    except ValueError:
                        pass
                    else:
                        raise AssertionError("Reload accepted a different target")
            assert db.execute(
                "SELECT status, cancelled_at FROM bookings ORDER BY booking_id"
            ).fetchall() == [("booked", None), ("booked", None)]
        finally:
            db.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(schema))


if __name__ == "__main__":
    verify()
    print("Cancellation pause verification passed.")
