# Shared model adapter (#46)

Input/output contract confirmed by the issue assignee in the Codex work session
on 2026-11-03: asynchronous `generate(messages) -> str`, where `messages` is an
immutable tuple of frozen `ModelMessage(role, content)` values. Roles are
`system`, `user`, or `assistant`; text is preserved verbatim. This records the
user's implementation decision, not a claim that the research share-out occurred.

`ModelAdapter` is a structural protocol. `FakeModelAdapter(outcome)` accepts either
one explicit string or one exception, repeating that exact outcome on every
call. Each instance records its own inputs in `calls`. There are no global
counters, queues, randomness, credentials, SDK imports, or external calls.
Empty or malformed strings are intentionally allowed for consumer tests.

Callers own prompt construction, bounded context/evidence, structured-output
validation, classification, citations, medical policies, and fallback behavior.
The fake implements none of those decisions. It raises the configured exception
unchanged, so later tests can supply the same typed failures as the real adapter.
Provider-error mapping remains #58; real SDK calls remain #53.

```python
import asyncio
from clinic_assistant.model_adapter import FakeModelAdapter, ModelMessage

fake = FakeModelAdapter('{"intent":"clinic_question"}')
messages = (ModelMessage("user", "When does the clinic open?"),)
assert asyncio.run(fake.generate(messages)) == '{"intent":"clinic_question"}'
assert fake.calls == [messages]
```

Verification: `uv run --locked pytest tests/test_model_adapter.py -q`, followed
by the shared Ruff, format, Mypy, and coverage checks. The offline test removes
model credentials and guards outgoing sockets/DNS while invoking the adapter.
Verified 2026-11-03: 8 focused cases and 72 total application tests passed with
real PostgreSQL tests enabled; adapter coverage 100%, overall coverage 95.92%.
Ruff lint/format and strict Mypy passed. No real provider call was made.
