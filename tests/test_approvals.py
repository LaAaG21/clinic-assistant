"""Pending staff approvals and pagination on real PostgreSQL (#40)."""

import base64
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any

import psycopg
import pytest
from psycopg import errors

from clinic_assistant.approvals import (
    InvalidApprovalPagination,
    create_pending_approval,
    list_pending_approvals,
)
from clinic_assistant.requests import create_request

Conn = psycopg.Connection[tuple[object, ...]]
Connect = Callable[[], AbstractContextManager[Conn]]


def pending(conn: Conn, approval_id: str, request_id: str) -> None:
    create_request(
        conn,
        request_id=request_id,
        conversation_id="c1",
        action="book",
        slot_id="s2",
    )
    create_pending_approval(conn, approval_id=approval_id, request_id=request_id)


def test_booking_approval_persists_before_a_booking(approval_db: Connect) -> None:
    with approval_db() as conn:
        conn.execute("DELETE FROM bookings")
        create_request(
            conn,
            request_id="r",
            conversation_id="c2",
            action="book",
            slot_id="s2",
        )
        created = create_pending_approval(conn, approval_id="a_'", request_id="r")
    with approval_db() as conn:
        page = list_pending_approvals(conn)
        assert conn.execute("SELECT count(*) FROM bookings").fetchone() == (0,)
    assert len(page.items) == 1
    item = page.items[0]
    assert (item.approval_id, item.request_id, item.conversation_id) == (
        "a_'",
        "r",
        "c2",
    )
    assert (item.action, item.slot_id, item.booking_id) == ("book", "s2", None)
    assert item.created_at == created.created_at
    assert created.decision is None
    assert created.reason is None
    assert created.decided_at is None
    assert page.next_cursor is None


def test_cancellation_approval_keeps_original_target(approval_db: Connect) -> None:
    with approval_db() as conn:
        create_request(
            conn,
            request_id="r",
            conversation_id="c1",
            action="cancel",
            booking_id="b1",
        )
        create_pending_approval(conn, approval_id="a", request_id="r")
    with approval_db() as conn:
        item = list_pending_approvals(conn).items[0]
        assert conn.execute("SELECT status FROM bookings").fetchone() == ("booked",)
    assert (item.action, item.slot_id, item.booking_id) == ("cancel", None, "b1")


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_decided_approvals_are_excluded(
    approval_db: Connect,
    decision: str,
) -> None:
    with approval_db() as conn:
        pending(conn, "a", "r")
        conn.execute(
            "UPDATE approvals SET decision=%s, reason='Reviewed', decided_at=now()",
            (decision,),
        )
    with approval_db() as conn:
        page = list_pending_approvals(conn)
    assert page.items == []
    assert page.next_cursor is None


def test_nonpending_requests_are_excluded(approval_db: Connect) -> None:
    with approval_db() as conn:
        pending(conn, "a", "r")
        conn.execute("UPDATE requests SET status='processing'")
    with approval_db() as conn:
        assert list_pending_approvals(conn).items == []
        with pytest.raises(ValueError, match="pending approval"):
            create_pending_approval(conn, approval_id="another", request_id="r")


def test_approval_requires_a_real_pending_request(approval_db: Connect) -> None:
    with approval_db() as conn:
        with pytest.raises(ValueError, match="pending approval"):
            create_pending_approval(conn, approval_id="a", request_id="missing")
    with pytest.raises(errors.ForeignKeyViolation), approval_db() as conn:
        conn.execute("INSERT INTO approvals VALUES ('a', 'missing')")


def test_one_approval_per_request_and_unique_id(approval_db: Connect) -> None:
    with approval_db() as conn:
        pending(conn, "a", "r")
        create_request(
            conn,
            request_id="r2",
            conversation_id="c1",
            action="book",
            slot_id="s2",
        )
    for approval_id, request_id in (("a2", "r"), ("a", "r2")):
        with pytest.raises(errors.UniqueViolation), approval_db() as conn:
            create_pending_approval(
                conn,
                approval_id=approval_id,
                request_id=request_id,
            )
    with approval_db() as conn:
        assert len(list_pending_approvals(conn).items) == 1


@pytest.mark.parametrize(
    "values,expected",
    [
        ({"approval_id": None}, errors.NotNullViolation),
        ({"approval_id": " "}, errors.CheckViolation),
        ({"request_id": None}, errors.NotNullViolation),
        (
            {"decision": "unknown", "reason": "Reviewed", "decided_at": "now"},
            errors.CheckViolation,
        ),
        ({"decision": "approve"}, errors.CheckViolation),
        ({"reason": "Reviewed"}, errors.CheckViolation),
        ({"decided_at": "now"}, errors.CheckViolation),
        (
            {"decision": "reject", "reason": " ", "decided_at": "now"},
            errors.CheckViolation,
        ),
        (
            {"decision": "reject", "reason": "x" * 1001, "decided_at": "now"},
            errors.CheckViolation,
        ),
        (
            {
                "decision": "reject",
                "reason": "Reviewed",
                "decided_at": "2000-01-01T00:00:00Z",
            },
            errors.CheckViolation,
        ),
    ],
)
def test_approval_constraints(
    approval_db: Connect,
    values: dict[str, Any],
    expected: type[psycopg.Error],
) -> None:
    with approval_db() as conn:
        create_request(
            conn,
            request_id="r",
            conversation_id="c1",
            action="book",
            slot_id="s2",
        )
    payload: dict[str, Any] = {
        "approval_id": "a",
        "request_id": "r",
        "decision": None,
        "reason": None,
        "decided_at": None,
    }
    payload.update(values)
    with pytest.raises(expected), approval_db() as conn:
        conn.execute(
            "INSERT INTO approvals"
            " (approval_id, request_id, decision, reason, decided_at)"
            " VALUES (%(approval_id)s, %(request_id)s, %(decision)s,"
            " %(reason)s, %(decided_at)s)",
            payload,
        )


def test_request_and_approval_creation_roll_back_together(approval_db: Connect) -> None:
    with pytest.raises(RuntimeError, match="rollback"), approval_db() as conn:
        pending(conn, "a", "r")
        raise RuntimeError("rollback")
    with approval_db() as conn:
        assert list_pending_approvals(conn).items == []
        assert conn.execute("SELECT count(*) FROM requests").fetchone() == (0,)


def test_keyset_pages_are_stable_after_a_decision(approval_db: Connect) -> None:
    with approval_db() as conn:
        for approval_id in ("c", "b", "a"):
            pending(conn, approval_id, "r" + approval_id)
        conn.execute("UPDATE approvals SET created_at='2000-01-01T10:00:00Z'")
    with approval_db() as conn:
        first = list_pending_approvals(conn, limit=1)
        assert [item.approval_id for item in first.items] == ["a"]
        conn.execute(
            "UPDATE approvals SET decision='approve', reason='Reviewed',"
            " decided_at=now() WHERE approval_id='a'"
        )
    with approval_db() as conn:
        rest = list_pending_approvals(conn, limit=2, cursor=first.next_cursor)
    assert [item.approval_id for item in rest.items] == ["b", "c"]
    assert rest.next_cursor is None


def test_default_and_maximum_page_sizes(approval_db: Connect) -> None:
    with approval_db() as conn:
        conn.execute(
            "INSERT INTO requests (request_id, conversation_id, action, slot_id)"
            " SELECT 'r' || i, 'c1', 'book', 's2' FROM generate_series(1, 101) i"
        )
        conn.execute(
            "INSERT INTO approvals (approval_id, request_id)"
            " SELECT 'a' || lpad(i::text, 3, '0'), 'r' || i"
            " FROM generate_series(1, 101) i"
        )
    with approval_db() as conn:
        default_page = list_pending_approvals(conn)
        assert len(default_page.items) == 50
        assert default_page.next_cursor is not None
        maximum_page = list_pending_approvals(conn, limit=100)
        assert len(maximum_page.items) == 100
        assert maximum_page.next_cursor is not None
        last = list_pending_approvals(conn, cursor=maximum_page.next_cursor)
        assert [item.approval_id for item in last.items] == ["a101"]
        assert last.next_cursor is None


@pytest.mark.parametrize("limit", [0, 101, -1, True, 1.5, "2"])
def test_invalid_limits(approval_db: Connect, limit: Any) -> None:
    with approval_db() as conn, pytest.raises(InvalidApprovalPagination):
        list_pending_approvals(conn, limit=limit)


@pytest.mark.parametrize(
    "cursor",
    [
        "",
        "!",
        "x" * 4097,
        base64.urlsafe_b64encode(b"{}").decode(),
        base64.urlsafe_b64encode(
            b'{"version":"2","created_at":"2026-11-05T10:00:00Z","approval_id":"a"}'
        ).decode(),
        base64.urlsafe_b64encode(
            b'{"version":"1","created_at":"2026-11-05T10:00:00","approval_id":"a"}'
        ).decode(),
    ],
)
def test_invalid_cursors(approval_db: Connect, cursor: str) -> None:
    with approval_db() as conn, pytest.raises(InvalidApprovalPagination):
        list_pending_approvals(conn, cursor=cursor)
