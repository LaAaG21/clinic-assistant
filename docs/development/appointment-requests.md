# Appointment-request storage (#52)

`db/init/004_requests.sql` runs after doctors/slots, conversations, and bookings.
Future messages with request foreign keys and approvals follow it. Existing
database volumes need this file applied once through the documented schema
initialization process.

`clinic_assistant.requests.create_request` inserts a caller-supplied opaque
request ID and returns an immutable `AppointmentRequest`.
`load_request` returns the same stored fields or `None`. Both accept a shared
psycopg connection, use parameterized SQL, and leave commit/rollback and closing
to its owner. Use `clinic_assistant.database.connection` as the context manager.
Duplicate request IDs raise a PostgreSQL unique violation and preserve the
original record. An exception must escape the connection context for rollback.

## Targets and states

- A booking request requires a slot. A pending booking has no booking result.
- A cancellation requires an existing booking belonging to the conversation,
  with no separate slot target.
- A booking result must belong to the request's conversation and target slot.
  Composite foreign keys enforce these relationships.
- The default state is `pending_approval`. `processing` is also available for
  ordinary or approved work. Both states have a null outcome code.
- `completed`, `rejected`, and `failed` require a nonblank outcome code.
  Completed requests require a booking. A booking result may also be retained
  during `processing` for future completion recovery.
- Creation and update timestamps are timezone-aware database timestamps.
  Subsequent writers must set `updated_at` without moving it before creation.

The implementation uses the proposed #6/#22 request fields and the dependency
order explicitly requested in #52. Those design documents still carry Proposed
status. Composite booking keys and state/outcome checks are implementation
choices for review in this PR, and do not establish wider team agreement.

Run the real PostgreSQL tests against a dedicated test database with
`TEST_DATABASE_URL` set.

```powershell
uv run --locked pytest tests/test_requests.py -v
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy .
```

The shared schema fixture applies every initialization file inside a unique
schema and drops that schema afterwards.
