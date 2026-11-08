# Bounded model context (issue #81)

The model receives only a recent window of the conversation; stored history stays complete. `src/clinic_assistant/model_context.py` never reads or changes the database.

```python
from clinic_assistant.model_context import generate_with_recent_context
from clinic_assistant.settings import get_settings

reply = await generate_with_recent_context(
    adapter,  # real OpenAI adapter or the #46 fake
    [system_instructions, *evidence],
    history,  # full stored conversation turns, oldest first
    get_settings().model_context_messages,
)
```

## Rules

| Rule | Behaviour |
|---|---|
| Window size | `MODEL_CONTEXT_MESSAGES`, integer 1..50, default 10 (proposed; #6 leaves the size open). Applies to both `fake` and `openai` backends. |
| Selection | The last `limit` turns, oldest first. Empty history → empty; shorter than the limit → whole history; exactly the limit → all; longer → the most recent `limit`. |
| Required inputs | System instructions and retrieved evidence go in `required` and are never trimmed; they come first. History must not contain `system` messages. |
| Storage | The source list is never modified; the result is a new tuple. Database messages and checkpoints are never deleted to fit the model. |
| Errors | A limit outside 1..50 or system text inside history raises `ValueError`; adapter failures pass through unchanged. |

Not in scope: loading history from PostgreSQL (needs the messages table, #26) and the history endpoint (#86).

## Why bound the context but keep all history

Sending every message makes calls slower and costlier as a conversation grows and can exceed the model's input limit. Deleting old messages to stay small would lose the patient's record and break history and audit. So the model call is bounded, and storage stays complete.

## Tests

```bash
uv run --locked pytest tests/test_model_context.py -v
```

Result (2026-11-08): 19 passed; `model_context.py` coverage 100%. The adapter test sends a 30-turn history with limit 5 and checks the #46 fake received exactly the two required messages plus turns 26–30, while the source history still holds 30.
