# Available-slot query (issue #71)

`clinic_assistant.slots.list_available_slots(conn, day, clinic_timezone, *, doctor_id=None, specialty=None, limit=50, after=None)` returns free slots for one clinic-local day. `available_slot_page` returns the same page plus whether more slots follow.

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

Not in scope: past-slot filtering and booking (#61).

## HTTP: `GET /slots` (#76)

`src/clinic_assistant/slots_api.py`. Read-only: a returned slot is not reserved.

| Query parameter | Rule |
|---|---|
| `date` | Required, `YYYY-MM-DD`, clinic-local |
| `doctor_id`, `specialty` | At least one; both mean intersection; blank values are rejected |
| `limit` | Optional, 1..100, default 50 |
| `cursor` | Optional, the `next_cursor` from the previous page |

```json
{
  "clinic_timezone": "Asia/Muscat",
  "slots": [
    {"slot_id": "slot_1", "doctor_id": "doctor_derm", "specialty": "dermatology",
     "starts_at": "2026-11-03T09:00:00+04:00", "ends_at": "2026-11-03T09:30:00+04:00"}
  ],
  "next_cursor": null
}
```

- Times are returned in the clinic timezone with an explicit offset; `Cache-Control: no-store`.
- No match returns `200` with an empty list.
- Pagination is keyset-based: `next_cursor` is an opaque URL-safe base64 of the last slot's `(starts_at, slot_id)`, so pages never skip or repeat a slot. The query fetches `limit + 1` rows to know whether another page exists; `next_cursor` is `null` on the last page.
- Errors use the shared envelope (#43): invalid input and cursors give `422 validation_error` before any database call; a database outage gives `503 dependency_unavailable`, a statement timeout `504 dependency_timeout`. Driver text is never returned.

```bash
curl "http://127.0.0.1:8000/slots?specialty=dermatology&date=2026-11-03&limit=2"
```

## Why availability comes from active bookings

The slot row never stores "booked". Availability is derived from `bookings`, the single source of truth, whose partial unique index (#39) already guarantees at most one active booking per slot. A separate `is_available` flag could drift from the bookings, for example after a cancellation or a failed transaction.

## Tests

```bash
export TEST_DATABASE_URL=postgresql://clinic:<your-password>@127.0.0.1:5432/clinic
uv run --locked pytest tests/test_slots.py tests/test_slots_api.py -v
```

Result (2026-11-05, #76): 35 passed; `slots.py` and `slots_api.py` coverage 100%; full suite 330 passed, coverage 99%. Endpoint tests override `get_settings` and `connection_factory` so requests run inside the throwaway schema; a factory that raises proves invalid input never reaches the database.

Result (2026-11-05): 16 passed; `slots.py` coverage 100%. Seeded slots sit on both Asia/Muscat midnights; one test asks for the same day in `UTC` and gets a different set, proving the clinic timezone decides the day.
