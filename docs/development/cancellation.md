# Approved booking cancellation (#67)

`cancel_approved_request(conn, request_id=..., booking_id=...,
conversation_id=...)` is the database entry point for staff-approved completion.
It checks the saved cancellation target, durable approval, and request state.
The shared #62 decision handoff supplies the approved `processing` request.

The safe outcomes distinguish the result.

- `cancelled` when the active booking changes to cancelled.
- `already_completed` when the same approved request already recorded a
  completed `appointment_cancelled` outcome and its booking remains cancelled.
- `target_not_found` when the request/booking/conversation identity mismatches.
- `ineligible_target` for pending/rejected approval, an incompatible request
  state, or a booking cancelled outside this request.

The operation locks request, approval and booking in that order. A conditional
booking update sets `cancelled_at`, and the request's completed cancellation
outcome is recorded in the same caller-owned transaction. It preserves the
original timestamp on replay and targets the original booking after rebooking.

Use a non-autocommit connection from the shared connection context. The production
completion caller saves its assistant outcome message before committing this
same transaction. A failure must escape the context to roll back the booking,
request marker and any message together. #77 owns that graph/message integration.

`cancel_approved_booking` supplies the conditional booking mutation, and
`validate_cancellation_target` supplies the shared non-mutating ownership/state
check. Its optional row lock is retained by the caller's transaction.

Set `TEST_DATABASE_URL` to a disposable PostgreSQL database and run the focused tests.

```powershell
uv run --locked pytest tests/test_approved_cancellation.py tests/test_bookings_schema.py -q
```
