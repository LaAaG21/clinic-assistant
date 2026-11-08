# Staff emergency flags endpoint (#60)

`GET /staff/flags` in `clinic_assistant.staff_flags` returns the emergency flags
persisted by the guard (#55) so staff can see that an urgent message was
flagged. It follows the `GET /staff/flags` row of the
[API contract](../design/service-boundaries-and-api.md#endpoint-contract) (#6),
which remains proposed: route, fields and paging are implemented as written
there and still need team confirmation.

```json
{"items":[{"flag_id":"flag_3f2c…","conversation_id":"conv_demo","message_id":"msg_7","created_at":"2026-11-05T09:30:00Z"}],"next_cursor":null}
```

| Aspect | Behaviour |
| --- | --- |
| Fields | `flag_id`, `conversation_id`, `message_id`, `created_at` only. Patient text is never stored in the flag and never returned. |
| Ordering | Newest first (`created_at DESC`, then `flag_id`), served by the `emergency_flags_created_at` index. |
| Paging | `limit` 1 to 100 (default 50) and an opaque keyset `cursor`; `next_cursor` is `null` on the last page. Invalid `limit` or cursor values return `422 validation_error` through the shared handlers (#43). |
| Empty | `{"items": [], "next_cursor": null}` with HTTP 200. |
| Failures | A database or configuration failure raises `DependencyFailure`, so the response is the shared `503 dependency_unavailable` with no driver details. |
| Side effects | None. The route reads persisted rows; it does not rerun detection, resume a graph or change appointments. |

The connection factory is a FastAPI dependency (`get_connect`), which tests
override so the production app reads a throwaway schema; in production it is
the shared `database.connection` from #12 using `DATABASE_URL`. Staff routes
are a distinct interface; deployment access restrictions remain a team decision
(#6), not an authentication feature of this route.

## Verification

```sh
export TEST_DATABASE_URL=postgresql://clinic:<password>@127.0.0.1:5432/clinic
uv run --locked pytest tests/test_staff_flags.py -v
```

Endpoint tests on real PostgreSQL cover the empty list, field set and ordering,
paging across equal timestamps without gaps or repeats, an exact page boundary,
invalid limits and cursors, a safe 503 on database failure (synthetic DSN marker
absent from the response and log), no side effects on bookings or flags across
repeated reads, and the OpenAPI entry. No model key is needed.

## Learning question

*Why should the staff endpoint read persisted flags rather than rerun emergency
detection?* The flag is the durable record of what the guard decided and when,
for the exact message the patient sent. Rerunning detection would recompute a
result from text staff should not need to see, could differ after the phrase
list changes, and would disappear if the message were unavailable. Reading the
stored flag keeps staff visibility consistent with what the patient was told.
