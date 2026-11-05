# Emergency guard and durable staff flags (#55)

`clinic_assistant.emergency` is the callable guard from the
[workflow diagram](../design/message-workflow.md): it runs before ordinary
classification, busy checks, model, retrieval or appointment work, and it is
usable on its own, so an emergency can be handled while another request in the
same conversation is paused. It builds no diagnosis or treatment logic.

| Function | Behaviour |
| --- | --- |
| `is_emergency(text)` | Deterministic match of fixed phrases (`EMERGENCY_PHRASES`) on case-folded, whitespace-normalised text with word boundaries. No model call, no I/O. |
| `flag_emergency(conversation_id, message_id, connect=database.connection)` | Inserts one `emergency_flags` row with plain SQL (#12) and returns `EmergencyResult` with `flag_id` and `flagged_at`. A retry with the same `message_id` returns the existing flag (`ON CONFLICT`), so safe retries never create duplicates. |
| `guard(text, conversation_id, message_id, ordinary, connect=...)` | Runs the check first; for an emergency returns `EmergencyResult` without calling `ordinary`; otherwise returns `ordinary()`. Later dispatch (#70, #75) passes classification, busy check and graph invocation as `ordinary`. |

`EmergencyResult` always carries the fixed `reply` (`EMERGENCY_REPLY`), the
identities the caller supplied, and either `flag_id`/`flagged_at` or
`error = "persistence_unavailable"`. `flag_persisted` is true only when the row
was written. On any database or configuration failure the reply is still
returned, a fixed-code line is logged (`Emergency flag persistence failed:
persistence_unavailable`, never the driver message) and staff flagging is not
claimed; the message endpoint maps that case to the API contract's special
`503 persistence_unavailable` response with the reply included.

The guard reads and writes nothing else: it does not touch bookings, requests,
approvals or checkpoints, so an unrelated pending action is neither resumed nor
overwritten. The ordering guarantee is the caller's responsibility and the
`guard` helper makes it explicit.

## Storage

[`db/init/010_emergency_flags.sql`](../../db/init/010_emergency_flags.sql)
follows the proposed [database diagram](../design/database-diagram.md):
`flag_id` (PK), `conversation_id` (FK to `conversations`), unique `message_id`,
`created_at`, with blank-text checks and indexes for the staff list (#60: newest
first) and per-conversation lookup. The foreign key from `message_id` to
`messages` is deferred until #26's second portion creates that table; the file is
numbered 010 so the agreed 004–006 order (requests, messages, approvals) keeps
its slots. Patient text is never stored in the flag.

## What still needs team agreement

- The phrase list and the reply wording are fixed proposals for review (the
  contract records guard rules and wording as open). A model `emergency` label
  from #63 is not a substitute for this guard.
- Whether the flag should also store the graph `thread_id` once Q1 of the
  database diagram is decided.

## Verification

```sh
export TEST_DATABASE_URL=postgresql://clinic:<password>@127.0.0.1:5432/clinic
uv run --locked pytest tests/test_emergency.py -v
```

Tests cover six emergency and six non-emergency examples (casing, curly
apostrophes, extra whitespace, look-alike words such as "emergency exit"), the
bypass of a spy and a fake model adapter while a flag is written on real
PostgreSQL, the untouched unrelated booking, the ordinary path running when
clear, same-message retries returning one flag, persistence failure through an
injected and through the default connection (reply kept, error reported, no
secret in the log), a missing conversation, and the table's constraints. No
model key is needed.

## Learning question

*Why must emergency handling remain callable outside an already-paused graph?*
A paused graph is waiting on a staff decision for one request, and the busy rule
rejects new ordinary work for that conversation. If emergency detection lived
only inside the graph, an urgent message during that pause would be refused or
queued behind the decision. Keeping the guard as a separate callable lets the
endpoint answer and flag immediately, without resuming, replacing or
overwriting the pending action.
