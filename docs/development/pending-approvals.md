# Pending staff approvals (#40)

`006_approvals.sql` references #52's requests through a unique `request_id`.
Conversation, action and target identities come from that request when queried.
A pending booking points to its slot and needs no booking row. The `005` file
position is reserved for #26's message/request-FK portion.

`create_pending_approval(conn, approval_id=..., request_id=...)` locks and checks
the pending request before insertion. Invalid/missing request states raise
`ValueError`. Database foreign keys and uniqueness reject invalid references,
duplicate approval IDs, and multiple approvals for a request. The helper leaves
transactions to the caller, so request and approval creation can commit or roll
back together using the shared connection context.

The schema requires a pending decision/reason/time to be all null. Decided rows
require an approve/reject value, a nonblank reason of at most 1,000 code points,
and a decision time at or after creation.

`list_pending_approvals(conn, limit=50, cursor=None)` returns a
`PendingApprovalPage` with `items` and `next_cursor`. It selects undecided
approvals whose request still has `pending_approval` status.

## Pagination contract for #45

- Pages are ordered by `created_at ASC, approval_id ASC`, oldest work first.
- Limits are integers from 1 through 100, defaulting to 50.
- The opaque cursor contains a versioned timestamp/ID boundary. It is validated
  before the database query, and malformed/unsupported cursors raise
  `InvalidApprovalPagination`.
- The next page starts strictly after the last returned item. Deciding or
  deleting that item between reads keeps the boundary usable.
- An empty or final page returns `next_cursor=None`.

The page order and cursor encoding are explicit implementation choices for review.
The #6 proposal defines list limits and fields but leaves the exact ordering open.
The schema follows #22's proposed approval fields and the request contract in #52.

Run real PostgreSQL tests with `TEST_DATABASE_URL` pointing at a dedicated test
database.

```powershell
uv run --locked pytest tests/test_approvals.py -v
```

## Pending-approval API (#45)

`GET /staff/approvals` calls the storage helper and returns `items` and
`next_cursor`. Each item includes `approval_id`, `request_id`,
`conversation_id`, `action`, `target`, and `created_at`. Booking targets contain
`slot_id`. Cancellation targets expose `appointment_id`, the stored booking ID.

Use `?limit=50` and pass the returned opaque `cursor` to traverse older-to-newer
pages. The final or empty page has a null cursor. Responses use
`Cache-Control: no-store` to keep staff reads current. Invalid limits/cursors
return the shared `422 validation_error` envelope. Recognized database
unavailability returns `503`, and query timeouts return `504`.

The route uses the shared `DATABASE_URL` connection configuration. Apply the SQL
initialization files before serving database reads. The proposal leaves
deployment access restrictions for staff routes to team review.

```powershell
uv run --locked pytest tests/test_staff_approvals.py -v
```
