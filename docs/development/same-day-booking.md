# Same-day booking policy — issue #20

`clinic_assistant.booking_policy.is_same_day_booking(appointment_time,
current_time, clinic_timezone)` takes two timezone-aware Python `datetime`
instances and an explicit IANA timezone name. It returns a boolean: `True` when
both instants fall on the same calendar date in that clinic timezone.

```python
from datetime import datetime
from clinic_assistant.booking_policy import is_same_day_booking

same_day = is_same_day_booking(
    appointment_time=datetime.fromisoformat("2026-11-03T01:00:00+00:00"),
    current_time=datetime.fromisoformat("2026-11-02T21:00:00+00:00"),
    clinic_timezone="Asia/Dubai",
)
assert same_day  # Both are November 3 in the clinic, despite different UTC dates.
```

The helper never reads the clock, environment, settings or machine timezone. Callers
provide the current instant. Convert both instants with `astimezone()` before
taking `.date()`; comparing UTC dates or a rolling 24-hour window gives the wrong
answer near local midnight. The configured IANA zone also handles DST changes.
`tzdata` is an application dependency so IANA zones work on Windows.

Naive timestamps (including a tzinfo object returning no UTC offset) raise
`ValueError` identifying the input. Unknown, empty or invalid timezone names raise
`ValueError` identifying `clinic_timezone`; no fallback zone is selected. Input
strings must be parsed by the caller. Type annotations specify supported types;
this helper does not perform HTTP validation. It does not validate the availability
or future ordering of a slot: an earlier time on today's date still returns `True`.
No booking, database or approval workflow is implemented here.

## Contract status

The repository's #6 contract specifies offset-bearing timestamps and clinic-local
dates, but remains **proposed** and records the same-day boundary as a review
question. Issue #6's public discussion supplied no recorded agreement at the time
of implementation. This implementation uses the proposed rules above for review;
it does not claim team agreement or finalize #6. Confirm these rules with the team
before marking #20's contract dependency complete. No production clinic timezone
is chosen: `Asia/Dubai` is only a test/example input.

## Verification

```sh
uv sync --locked --group dev
uv run --locked pytest tests/test_booking_policy.py -v
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy .
```

Fixed-time tests cover same and different days, past times today, equivalent
instants with different offsets, both sides of local midnight, negative offsets,
DST transitions, invalid zones and naive inputs. Subprocess tests vary `TZ` and
call `tzset()` when supported; Windows does not apply `TZ` via `tzset`, but all
conversions still name the clinic zone explicitly.

References: [Python zoneinfo](https://docs.python.org/3.12/library/zoneinfo.html),
[aware and naive datetime objects](https://docs.python.org/3.12/library/datetime.html#determining-if-an-object-is-aware-or-naive).

Verified on 2026-11-02 with Python 3.12.15 on Windows: 21 application tests
passed (20 policy cases plus the existing startup/OpenAPI test), with 100%
statement and branch coverage. Ruff lint/format and strict mypy checks passed.
The timezone-agreement dependency described above remains pending.
