# Appointments MCP (item 1, port 8001)

Tools (no user argument; the user is `sub` from the verified Bearer JWT):

- `book_appointment(doctor, date_iso, time_hhmm)` needs `appointments:write`. Refuses an invalid date/time or a slot that is already taken.
- `list_my_appointments()` needs `appointments:read`; returns only the caller's appointments.
- `cancel_appointment(appointment_id)` needs `appointments:write`. Someone else's id gets the same `{"error": "appointment not found"}` as a missing id.

Any missing, malformed, expired, wrongly signed or under-scoped token returns
`{"error": "unauthorized"}` and changes nothing. Data is in memory (seeded for
`user-a` and `user-b`) and resets on restart. `auth.py` is a copy of
`shared/auth.py`; a test fails if they differ.

```sh
uv run pytest tests/test_appointments.py
docker compose up --build appointments-mcp
```
