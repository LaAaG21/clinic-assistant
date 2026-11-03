"""Doctors and slots schema (#19) on real PostgreSQL, inside a throwaway schema.

Set TEST_DATABASE_URL to run. Each test applies db/init/001_doctors_slots.sql in
its own uniquely named schema and drops it afterwards, so developer data in the
public schema is never touched.
"""

import os
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import errors, sql

from clinic_assistant.database import DatabaseSettings, connection

SCHEMA_FILE = (
    Path(__file__).resolve().parents[1] / "db" / "init" / "001_doctors_slots.sql"
)

Conn = psycopg.Connection[tuple[object, ...]]
Connect = Callable[[], AbstractContextManager[Conn]]


@pytest.fixture
def settings() -> DatabaseSettings:
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run real PostgreSQL tests")
    return DatabaseSettings(url=url)


@pytest.fixture
def db(settings: DatabaseSettings) -> Iterator[Connect]:
    """Apply the schema file in a unique schema; yield a connection factory."""
    schema = sql.Identifier("test_schema_" + uuid4().hex)
    with connection(settings) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(schema))
        conn.execute(sql.SQL("SET search_path TO {}").format(schema))
        conn.execute(SCHEMA_FILE.read_bytes())

    @contextmanager
    def connect() -> Iterator[Conn]:
        with connection(settings) as conn:
            conn.execute(sql.SQL("SET search_path TO {}").format(schema))
            yield conn

    try:
        yield connect
    finally:
        with connection(settings) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(schema))


def add_doctor(conn: Conn, doctor_id: str = "doctor_1") -> None:
    conn.execute(
        "INSERT INTO doctors (doctor_id, full_name, specialty) VALUES (%s, %s, %s)",
        (doctor_id, "Dr. Salma Synthetic", "dermatology"),
    )


def add_slot(
    conn: Conn,
    slot_id: str = "slot_1",
    doctor_id: str = "doctor_1",
    starts_at: str = "2026-11-03T10:00:00+04:00",
    ends_at: str = "2026-11-03T10:30:00+04:00",
) -> None:
    conn.execute(
        "INSERT INTO slots (slot_id, doctor_id, starts_at, ends_at)"
        " VALUES (%s, %s, %s, %s)",
        (slot_id, doctor_id, starts_at, ends_at),
    )


def constraint_of(error: pytest.ExceptionInfo[psycopg.Error]) -> str | None:
    return error.value.diag.constraint_name


def test_valid_doctor_and_slot_are_stored(db: Connect) -> None:
    with db() as conn:
        add_doctor(conn)
        add_slot(conn)
    with db() as conn:
        row = conn.execute(
            "SELECT s.slot_id, d.specialty, s.ends_at - s.starts_at"
            " FROM slots s JOIN doctors d USING (doctor_id)"
        ).fetchone()
    assert row is not None
    assert row[:2] == ("slot_1", "dermatology")
    assert str(row[2]) == "0:30:00"


def test_duplicate_doctor_id_is_rejected(db: Connect) -> None:
    with db() as conn:
        add_doctor(conn)
    with pytest.raises(errors.UniqueViolation) as error, db() as conn:
        add_doctor(conn)
    assert constraint_of(error) == "doctors_pkey"


def test_duplicate_slot_id_is_rejected(db: Connect) -> None:
    with db() as conn:
        add_doctor(conn)
        add_slot(conn)
    with pytest.raises(errors.UniqueViolation) as error, db() as conn:
        add_slot(
            conn,
            starts_at="2026-11-03T11:00:00+04:00",
            ends_at="2026-11-03T11:30:00+04:00",
        )
    assert constraint_of(error) == "slots_pkey"


def test_slot_for_missing_doctor_is_rejected(db: Connect) -> None:
    with pytest.raises(errors.ForeignKeyViolation) as error, db() as conn:
        add_slot(conn, doctor_id="doctor_missing")
    assert constraint_of(error) == "slots_doctor_id_fkey"


def test_doctor_with_slots_cannot_be_deleted(db: Connect) -> None:
    with db() as conn:
        add_doctor(conn)
        add_slot(conn)
    with pytest.raises(errors.ForeignKeyViolation), db() as conn:
        conn.execute("DELETE FROM doctors WHERE doctor_id = 'doctor_1'")


@pytest.mark.parametrize(
    ("starts_at", "ends_at"),
    [
        ("2026-11-03T10:30:00+04:00", "2026-11-03T10:00:00+04:00"),  # ends first
        ("2026-11-03T10:00:00+04:00", "2026-11-03T10:00:00+04:00"),  # zero length
    ],
)
def test_slot_must_start_before_it_ends(
    db: Connect, starts_at: str, ends_at: str
) -> None:
    with db() as conn:
        add_doctor(conn)
    with pytest.raises(errors.CheckViolation) as error, db() as conn:
        add_slot(conn, starts_at=starts_at, ends_at=ends_at)
    assert constraint_of(error) == "slots_starts_before_ends"


def test_same_doctor_cannot_have_two_slots_at_one_start(db: Connect) -> None:
    with db() as conn:
        add_doctor(conn)
        add_doctor(conn, "doctor_2")
        add_slot(conn)
        add_slot(conn, slot_id="slot_other_doctor", doctor_id="doctor_2")
    # Same instant written in UTC: timestamptz compares instants, not text.
    with pytest.raises(errors.UniqueViolation) as error, db() as conn:
        add_slot(
            conn,
            slot_id="slot_2",
            starts_at="2026-11-03T06:00:00Z",
            ends_at="2026-11-03T06:45:00Z",
        )
    assert constraint_of(error) == "slots_doctor_start_unique"


@pytest.mark.parametrize(
    ("column", "value", "expected"),
    [
        ("full_name", "   ", errors.CheckViolation),
        ("specialty", "", errors.CheckViolation),
        ("doctor_id", " ", errors.CheckViolation),
        ("full_name", None, errors.NotNullViolation),
        ("specialty", None, errors.NotNullViolation),
    ],
)
def test_doctor_required_values(
    db: Connect, column: str, value: str | None, expected: type[psycopg.Error]
) -> None:
    doctor: dict[str, str | None] = {
        "doctor_id": "doctor_1",
        "full_name": "Dr. A",
        "specialty": "cardiology",
    }
    doctor[column] = value
    with pytest.raises(expected), db() as conn:
        conn.execute(
            "INSERT INTO doctors (doctor_id, full_name, specialty)"
            " VALUES (%(doctor_id)s, %(full_name)s, %(specialty)s)",
            doctor,
        )


@pytest.mark.parametrize("column", ["starts_at", "ends_at"])
def test_slot_times_are_required(db: Connect, column: str) -> None:
    with db() as conn:
        add_doctor(conn)
    times: dict[str, str | None] = {
        "starts_at": "2026-11-03T10:00:00+04:00",
        "ends_at": "2026-11-03T10:30:00+04:00",
    }
    times[column] = None
    with pytest.raises(errors.NotNullViolation), db() as conn:
        conn.execute(
            "INSERT INTO slots (slot_id, doctor_id, starts_at, ends_at)"
            " VALUES ('slot_1', 'doctor_1', %(starts_at)s, %(ends_at)s)",
            times,
        )
