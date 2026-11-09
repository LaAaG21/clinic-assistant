"""Simultaneous booking attempts on real PostgreSQL (#64, U06).

Each contender runs `booking_outcomes.book_request` (#66 over #61) on its own
connection and transaction. A `threading.Barrier` releases every contender at the
same moment. The first contender to finish keeps its transaction open until
PostgreSQL reports that peers are blocked behind it (`pg_blocking_pids`), so the
race is observed inside the database, not inferred from timing. Results are read
back on a fresh connection only after every contender has finished.
"""

import threading
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from uuid import uuid4

import psycopg
import pytest

from clinic_assistant.booking_outcomes import BookingOutcome, book_request
from clinic_assistant.requests import create_request, load_request

Conn = psycopg.Connection[tuple[object, ...]]
Connect = Callable[[], AbstractContextManager[Conn]]

# Below the 1000 ms statement timeout that blocked contenders run under.
HOLD_SECONDS = 0.5
JOIN_SECONDS = 10.0


@dataclass
class Attempt:
    request_id: str
    outcome: BookingOutcome | None = None
    error: BaseException | None = None
    blocked_peers: int = 0


def _blocked_by(conn: Conn, pid: int) -> int:
    row = conn.execute(
        "SELECT count(*) FROM pg_stat_activity WHERE %s = ANY(pg_blocking_pids(pid))",
        (pid,),
    ).fetchone()
    assert row is not None
    return int(str(row[0]))


def _race(connect: Connect, request_ids: list[str]) -> list[Attempt]:
    """Run one booking per request ID at once; return after all have finished."""
    attempts = [Attempt(request_id) for request_id in request_ids]
    barrier = threading.Barrier(len(attempts))
    first_done = threading.Lock()

    def contend(attempt: Attempt) -> None:
        try:
            with connect() as conn, connect() as monitor:
                monitor.commit()  # end the search_path transaction first
                monitor.autocommit = True
                pid = conn.info.backend_pid
                barrier.wait(timeout=JOIN_SECONDS)
                attempt.outcome = book_request(conn, request_id=attempt.request_id)
                if first_done.acquire(blocking=False):
                    # Hold the winning transaction open until peers queue behind it.
                    deadline = time.monotonic() + HOLD_SECONDS
                    while time.monotonic() < deadline:
                        attempt.blocked_peers = _blocked_by(monitor, pid)
                        if attempt.blocked_peers == len(attempts) - 1:
                            break
                        time.sleep(0.01)
        except BaseException as exc:  # reported by the main thread
            barrier.abort()
            attempt.error = exc

    threads = [threading.Thread(target=contend, args=(a,)) for a in attempts]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(JOIN_SECONDS)
    assert not any(thread.is_alive() for thread in threads)
    for attempt in attempts:
        if attempt.error is not None:
            raise attempt.error
    return attempts


def _fresh_slot(conn: Conn, contenders: int) -> tuple[str, list[str]]:
    """Commit a new free slot plus one processing request per contender."""
    tag = uuid4().hex[:12]
    slot_id = f"slot_{tag}"
    # Each new slot starts an hour after the latest one, keeping (doctor, start) unique.
    conn.execute(
        "INSERT INTO slots"
        " SELECT %s, 'd', max(ends_at) + interval '30 minutes',"
        " max(ends_at) + interval '60 minutes' FROM slots",
        (slot_id,),
    )
    request_ids = []
    for n in range(contenders):
        conversation_id = f"conv_{tag}_{n}"
        request_id = f"req_{tag}_{n}"
        conn.execute(
            "INSERT INTO conversations (conversation_id) VALUES (%s)",
            (conversation_id,),
        )
        create_request(
            conn,
            request_id=request_id,
            conversation_id=conversation_id,
            action="book",
            slot_id=slot_id,
            status="processing",
        )
        request_ids.append(request_id)
    return slot_id, request_ids


def _evidence(slot_id: str, attempts: list[Attempt], active: int) -> None:
    """Print the retained run record (shown with `pytest -s`)."""
    outcomes = [
        (a.request_id, a.outcome.code if a.outcome else None, a.blocked_peers)
        for a in attempts
    ]
    print(f"U06 slot={slot_id} active_bookings={active} outcomes={outcomes}")


def _active_bookings(conn: Conn, slot_id: str) -> list[tuple[object, ...]]:
    return conn.execute(
        "SELECT booking_id, conversation_id FROM bookings"
        " WHERE slot_id = %s AND status = 'booked'",
        (slot_id,),
    ).fetchall()


def _unrelated_snapshot(conn: Conn) -> list[tuple[object, ...]]:
    return conn.execute(
        "SELECT booking_id, slot_id, conversation_id, status FROM bookings"
        " WHERE slot_id IN ('s1', 's2') ORDER BY booking_id"
    ).fetchall()


@pytest.mark.parametrize("contenders", [2, 4])
def test_simultaneous_requests_leave_exactly_one_active_booking(
    approval_db: Connect, contenders: int
) -> None:
    with approval_db() as conn:
        unrelated = _unrelated_snapshot(conn)

    # Repeat on new synthetic data each round so one lucky ordering cannot pass.
    for _ in range(3):
        with approval_db() as conn:
            slot_id, request_ids = _fresh_slot(conn, contenders)

        attempts = _race(approval_db, request_ids)

        codes = sorted(a.outcome.code for a in attempts if a.outcome is not None)
        assert codes == ["appointment_booked"] + ["slot_unavailable"] * (contenders - 1)
        winner = next(
            a
            for a in attempts
            if a.outcome is not None and a.outcome.code == "appointment_booked"
        )
        assert winner.outcome is not None and winner.outcome.booking_id is not None
        # Genuine overlap: PostgreSQL saw peers waiting on the winner's transaction.
        assert winner.blocked_peers >= 1

        with approval_db() as conn:
            winning_request = load_request(conn, winner.request_id)
            assert winning_request is not None
            active = _active_bookings(conn, slot_id)
            _evidence(slot_id, attempts, len(active))
            assert active == [
                (winner.outcome.booking_id, winning_request.conversation_id)
            ]
            for attempt in attempts:
                saved = load_request(conn, attempt.request_id)
                assert saved is not None
                expected = winner.outcome.booking_id if attempt is winner else None
                assert saved.booking_id == expected
            assert _unrelated_snapshot(conn) == unrelated


def test_simultaneous_retries_of_one_request_book_once(approval_db: Connect) -> None:
    with approval_db() as conn:
        unrelated = _unrelated_snapshot(conn)

    for _ in range(3):
        with approval_db() as conn:
            slot_id, (request_id,) = _fresh_slot(conn, 1)

        attempts = _race(approval_db, [request_id] * 3)

        outcomes = {a.outcome for a in attempts}
        assert len(outcomes) == 1
        (outcome,) = outcomes
        assert outcome is not None and outcome.code == "appointment_booked"
        assert max(a.blocked_peers for a in attempts) >= 1

        with approval_db() as conn:
            _evidence(slot_id, attempts, len(_active_bookings(conn, slot_id)))
            assert conn.execute(
                "SELECT count(*) FROM bookings WHERE slot_id = %s", (slot_id,)
            ).fetchone() == (1,)
            saved = load_request(conn, request_id)
            assert saved is not None and saved.booking_id == outcome.booking_id
            assert _unrelated_snapshot(conn) == unrelated
