# Available-slot query (issue #71)

`clinic_assistant.slots.list_available_slots(conn, day, clinic_timezone, *, doctor_id=None, specialty=None, limit=50)` returns free slots for one clinic-local day. HTTP exposure is #76.

```python
from datetime import date
from clinic_assistant.database import connection
from clinic_assistant.settings import get_settings
from clinic_assistant.slots import list_available_slots

settings = get_settings()
with connection(settings.database) as conn:
    slots = list_available_slots(
        conn, date(2026, 11, 3), settings.clinic_timezone, specialty="dermatology"
    )
```

## Rules

| Rule | How |
|---|---|
| Filters | `doctor_id`, `specialty`, or both (intersection). At least one is required (#6). `specialty` is trimmed and matched case-insensitively. |
| Clinic-local day | `clinic_day_bounds` turns the date into `[local midnight, next local midnight)` in the given IANA timezone; the query uses `starts_at >= start AND starts_at < end`. The timezone is always passed in; the database or machine timezone is never used. |
| Availability | A slot is available when no booking for it has `status = 'booked'`. Cancelled bookings don't count, so the slot returns. |
| Ordering | `starts_at`, then `slot_id`, so results are stable. |
| Bounds | `limit` 1..100 (default 50, #6) plus the caller's connection statement timeout (#12). |
| Fields | `slot_id`, `doctor_id`, `specialty`, `starts_at`, `ends_at`: the same as the API `Slot` model (#6), so #76 can map it directly. |
| Errors | Missing filters, blank specialty, limit out of range, or an unknown timezone raise `ValueError` before any query runs. |

Not in scope: past-slot filtering, pagination cursors (#76), and booking (#61).

## Why availability comes from active bookings

The slot row never stores "booked". Availability is derived from `bookings`, the single source of truth, whose partial unique index (#39) already guarantees at most one active booking per slot. A separate `is_available` flag could drift from the bookings, for example after a cancellation or a failed transaction.

## Tests

```bash
export TEST_DATABASE_URL=postgresql://clinic:<your-password>@127.0.0.1:5432/clinic
uv run --locked pytest tests/test_slots.py -v
```

Result (2026-11-05): 16 passed; `slots.py` coverage 100%. Seeded slots sit on both Asia/Muscat midnights; one test asks for the same day in `UTC` and gets a different set, proving the clinic timezone decides the day.
