# Conversation history API (issue #86)

`GET /conversations/{conversation_id}` returns the complete stored conversation, oldest first. `src/clinic_assistant/history.py`. Read-only: no model call, no resume, no change to stored messages.

| Query parameter | Rule |
|---|---|
| `limit` | Optional, 1..100, default 50 |
| `cursor` | Optional, the `next_cursor` from the previous page |

```json
{
  "conversation_id": "conv_1",
  "messages": [
    {"message_id": "msg_1", "role": "patient", "text": "Book slot_1",
     "created_at": "2026-11-08T05:00:00Z", "citations": [], "request_id": "req_1"},
    {"message_id": "msg_3", "role": "assistant", "text": "Staff approved. Booked.",
     "created_at": "2026-11-08T05:00:05Z", "citations": [], "request_id": "req_1"}
  ],
  "next_cursor": null
}
```

## Rules

| Rule | Behaviour |
|---|---|
| Order | `created_at`, then `message_id` |
| Pagination | Keyset on `(created_at, message_id)`; `next_cursor` is opaque URL-safe base64; `limit + 1` rows detect the last page |
| Content | Every stored patient and assistant message, including staff outcome messages, with `request_id` links and validated citations (stored as a JSONB array, #26) |
| Window | None. The full record is returned; #81's model window only limits what the model sees |
| Errors | Unknown conversation `404 not_found`; invalid `limit`/`cursor` `422 validation_error` before any database call; outage `503`, timeout `504` (shared #43 envelope, no driver text) |
| Caching | `Cache-Control: no-store` |

## Why stored history is separate from the model window

The model needs a short, recent context to stay fast, cheap and inside its input limit (#81). The patient and staff need the whole record, including approvals and outcomes. Keeping both means trimming only the model input, never the stored messages.

## Tests

```bash
export TEST_DATABASE_URL=postgresql://clinic:<your-password>@127.0.0.1:5432/clinic
uv run --locked pytest tests/test_history_api.py -v
```

Result (2026-11-08): 16 passed; `history.py` coverage 100%. Includes a page walk with `limit=2`, a 15-message conversation returned in full, and a before/after database snapshot proving reads change nothing.

## Follow-up

`connection_factory` and the cursor helpers mirror `slots_api.py` (#76). This branch is stacked on #119, which predates #76 on main, so they can't be shared yet; once both are on main they can move to one module.
