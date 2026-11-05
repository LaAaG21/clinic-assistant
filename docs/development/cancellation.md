# Approved booking cancellation (#67)

`cancel_approved_booking` is called by staff-approved completion after verifying
the saved approval. It accepts the intended booking and conversation IDs.
The caller owns a non-autocommit transaction and commits the request outcome
together with the cancellation. Failures must escape the shared connection context
to roll back. The helper locks and rechecks the booking before its conditional update.

`validate_cancellation_target` shares those ownership/state checks with the
[cancellation pause](cancellation-workflow.md). It returns `eligible`,
`target_not_found`, or `ineligible_target` without changing the booking.
Its optional row lock is retained by the caller's transaction.

The outcomes are `cancelled`, `target_not_found` for a missing/mismatched target,
and `ineligible_target` for a booking outside the active state. Same-request
replay versus conflicting cancellation belongs to #77's shared completion logic
using #52's saved request. This operation alone leaves that #67 criterion partial.

With `TEST_DATABASE_URL` set to a disposable PostgreSQL database, run
`uv run --locked pytest tests/test_bookings_schema.py -k cancellation -v`.
