# Atomic booking (#61)

`insert_booking(conn, request_id=...)` uses a caller-owned transaction. The
request must be a processing or completed booking request. A locked request row
serializes retries. Its stored booking result is returned on replay.

Insertion uses the active-slot unique index as its conflict authority. A conflict
returns None without aborting the transaction. On success the request's booking
ID is stored in the same transaction. Later completion code writes its outcome
before commit. A deterministic server-generated booking ID is an explicit review
choice for the shared request idempotency contract.

`booking_outcomes.book_request` (#66) maps the existing insertion result to
`appointment_booked` with the stored booking ID or `slot_unavailable`.
Recognized database errors raise the shared dependency_unavailable or
dependency_timeout failure. The wrapper preserves the caller's transaction.
