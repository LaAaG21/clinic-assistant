"""Synthetic doctor/slot seed (#29) on real PostgreSQL, inside a throwaway schema.

Set TEST_DATABASE_URL to run. `schema_db` (conftest.py) applies the schema files
without seed files; these tests load db/init/900_seed_doctors_slots.sql themselves.
"""

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import psycopg
import pytest

Conn = psycopg.Connection[tuple[object, ...]]
Connect = Callable[[], AbstractContextManager[Conn]]

SEED_FILE = (
    Path(__file__).resolve().parents[1] / "db" / "init" / "900_seed_doctors_slots.sql"
)
TIMEZONE = "Asia/Dubai"  # Example input only, as in .env.example.
BASE_DATE = "2026-11-10"
DOCTORS = 3
SLOTS = 36  # 3 doctors x 3 days x 4 slots


def load_seed(
    conn: Conn, base_date: str | None = BASE_DATE, tz: str = TIMEZONE
) -> None:
    conn.execute("SELECT set_config('clinic.seed_timezone', %s, false)", (tz,))
    if base_date is not None:
        conn.execute(
            "SELECT set_config('clinic.seed_base_date', %s, false)", (base_date,)
        )
    conn.execute(SEED_FILE.read_bytes())


def counts(conn: Conn) -> tuple[object, ...]:
    row = conn.execute(
        "SELECT (SELECT count(*) FROM doctors), (SELECT count(*) FROM slots)"
    ).fetchone()
    assert row is not None
    return row


def snapshot(conn: Conn) -> list[tuple[object, ...]]:
    return conn.execute(
        "SELECT slot_id, doctor_id, starts_at, ends_at FROM slots ORDER BY slot_id"
    ).fetchall()


def local_slots(conn: Conn) -> list[tuple[str, datetime, datetime]]:
    zone = ZoneInfo(TIMEZONE)
    rows = conn.execute("SELECT doctor_id, starts_at, ends_at FROM slots").fetchall()
    result = []
    for doctor_id, starts_at, ends_at in rows:
        assert isinstance(doctor_id, str)
        assert isinstance(starts_at, datetime) and isinstance(ends_at, datetime)
        result.append((doctor_id, starts_at.astimezone(zone), ends_at.astimezone(zone)))
    return result


def test_seed_loads_small_dataset_with_valid_relationships(schema_db: Connect) -> None:
    with schema_db() as conn:
        load_seed(conn)
        assert counts(conn) == (DOCTORS, SLOTS)
        orphans = conn.execute(
            "SELECT count(*) FROM slots s"
            " LEFT JOIN doctors d USING (doctor_id) WHERE d.doctor_id IS NULL"
        ).fetchone()
        assert orphans == (0,)
        per_doctor = conn.execute(
            "SELECT d.specialty, count(*) FROM slots s JOIN doctors d USING (doctor_id)"
            " GROUP BY d.specialty ORDER BY d.specialty"
        ).fetchall()
        assert per_doctor == [
            ("dermatology", 12),
            ("general practice", 12),
            ("pediatrics", 12),
        ]


def test_seed_slots_use_clinic_wall_clock_times_from_base_date(
    schema_db: Connect,
) -> None:
    with schema_db() as conn:
        load_seed(conn)
        slots = local_slots(conn)
        first = conn.execute(
            "SELECT slot_id, starts_at FROM slots ORDER BY starts_at, slot_id LIMIT 1"
        ).fetchone()

    base = date.fromisoformat(BASE_DATE)
    expected_days = {base + timedelta(days=offset) for offset in range(3)}
    assert {start.date() for _, start, _ in slots} == expected_days
    for _, start, end in slots:
        assert end - start == timedelta(minutes=30)
        assert time(9) <= start.time() and end.time() <= time(16)
        assert start.minute in (0, 30) and start.second == 0
    assert first is not None
    assert first[0] == "slot_seed_gp_20261110T0900"
    assert first[1] == datetime(2026, 11, 10, 9, tzinfo=ZoneInfo(TIMEZONE))


def test_loading_same_input_twice_is_stable_and_keeps_unrelated_rows(
    schema_db: Connect,
) -> None:
    with schema_db() as conn:
        conn.execute(
            "INSERT INTO doctors VALUES ('doctor_other', 'Dr. Other Synthetic', 'ent')"
        )
        conn.execute(
            "INSERT INTO slots VALUES ('slot_other', 'doctor_other',"
            " '2026-11-10T09:00:00+04:00', '2026-11-10T09:30:00+04:00')"
        )
        load_seed(conn)
        first_load = snapshot(conn)
        load_seed(conn)
        assert snapshot(conn) == first_load
        assert counts(conn) == (DOCTORS + 1, SLOTS + 1)
        unrelated = conn.execute(
            "SELECT d.full_name FROM slots s JOIN doctors d USING (doctor_id)"
            " WHERE s.slot_id = 'slot_other'"
        ).fetchone()
        assert unrelated == ("Dr. Other Synthetic",)


def test_seed_skips_existing_slot_at_same_doctor_and_time(schema_db: Connect) -> None:
    with schema_db() as conn:
        conn.execute(
            "INSERT INTO doctors VALUES"
            " ('doctor_seed_gp', 'Dr. Edited Synthetic', 'general practice')"
        )
        conn.execute(
            "INSERT INTO slots VALUES ('slot_manual', 'doctor_seed_gp',"
            " '2026-11-10T09:00:00+04:00', '2026-11-10T09:30:00+04:00')"
        )
        load_seed(conn)
        assert counts(conn) == (DOCTORS, SLOTS)
        kept = conn.execute(
            "SELECT full_name FROM doctors WHERE doctor_id = 'doctor_seed_gp'"
        ).fetchone()
        assert kept == ("Dr. Edited Synthetic",)
        manual = conn.execute(
            "SELECT count(*) FROM slots WHERE slot_id = 'slot_manual'"
        ).fetchone()
        assert manual == (1,)


def test_new_base_date_adds_only_missing_days(schema_db: Connect) -> None:
    with schema_db() as conn:
        load_seed(conn, base_date="2026-11-10")
        load_seed(conn, base_date="2026-11-11")
        days = conn.execute(
            "SELECT count(DISTINCT (starts_at AT TIME ZONE %s)::date) FROM slots",
            (TIMEZONE,),
        ).fetchone()
        assert days == (4,)
        assert counts(conn) == (DOCTORS, 48)


@pytest.mark.parametrize("base_date", [None, "", "  "])
def test_missing_base_date_defaults_to_today_in_clinic_timezone(
    schema_db: Connect, base_date: str | None
) -> None:
    with schema_db() as conn:
        load_seed(conn, base_date=base_date)
        row = conn.execute(
            "SELECT min((starts_at AT TIME ZONE %s)::date)"
            " = (now() AT TIME ZONE %s)::date FROM slots",
            (TIMEZONE, TIMEZONE),
        ).fetchone()
        assert row == (True,)
        assert counts(conn) == (DOCTORS, SLOTS)


@pytest.mark.parametrize(
    ("tz", "base_date", "message"),
    [
        ("", BASE_DATE, "clinic.seed_timezone is required"),
        ("Mars/Olympus", BASE_DATE, "clinic.seed_timezone must be an available"),
        (TIMEZONE, "10/11/2026", "clinic.seed_base_date must be a YYYY-MM-DD"),
        (TIMEZONE, "2026-02-30", "clinic.seed_base_date must be a YYYY-MM-DD"),
    ],
)
def test_invalid_configuration_fails_without_inserting(
    schema_db: Connect, tz: str, base_date: str, message: str
) -> None:
    with pytest.raises(psycopg.errors.RaiseException, match=message):
        with schema_db() as conn:
            load_seed(conn, base_date=base_date, tz=tz)
    with schema_db() as conn:
        assert counts(conn) == (0, 0)
