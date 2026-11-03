# Real OpenAI model adapter (#53)

`OpenAIModelAdapter(settings)` implements #46's asynchronous
`generate(tuple[ModelMessage, ...]) -> str` contract. It copies role/content
messages into the Responses API input in their original order, uses the explicit
configured model, requests `store=False`, and returns raw `output_text` unchanged.
Consumers own structured-output validation, context bounds, and business policy.

Use the shared #18 settings snapshot, not a second environment loader:

```python
from clinic_assistant.openai_adapter import OpenAIModelAdapter
from clinic_assistant.settings import get_settings

adapter = OpenAIModelAdapter(get_settings())
# At an async model-call boundary: reply = await adapter.generate(messages)
```

Real mode requires `MODEL_BACKEND=openai`, `OPENAI_API_KEY`, and `OPENAI_MODEL`.
The model has no hardcoded default; choose one available to the deployment.
`OPENAI_TIMEOUT_SECONDS` is an integer from 1 to 120, default **10**.
`OPENAI_MAX_RETRIES` is an integer from 0 to 2, default **0**. Fake mode requires
neither credentials nor a model, and continues using `FakeModelAdapter` directly.
No live credentials are included in examples or tests.

Each call uses an async SDK context manager for cleanup on success, SDK failure,
or cancellation. The same timeout is configured on the SDK and an outer
`asyncio.timeout` bounds the whole call, including retries/backoff. Therefore
retries do not multiply the configured whole-call deadline. The adapter neither
logs credentials/prompts nor exposes settings secrets through its representation.

Provider errors currently propagate as SDK exceptions; the whole-call deadline
raises `TimeoutError`. Mapping them into safe application errors belongs to #58.
No failure is converted to an unsupported-answer fallback. Empty/malformed raw
text is left for consumers to validate, matching the shared fake contract. There
is no classification, retrieval, citation/safety policy, or production-route
wiring in this task.

## Verification

```sh
uv sync --locked --group dev
uv run --locked pytest tests/test_openai_adapter.py tests/test_settings.py tests/test_model_adapter.py -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy .
```

The focused run passed **52 cases**, including 18 new adapter/configuration cases.
Tests run the actual pinned SDK against `httpx.MockTransport`; no live model key
or external request is used. They check exact request/response shape, SDK timeout,
zero/one-retry counts, whole-call cancellation, client cleanup on success/failure,
fake compatibility, safe settings errors, and rejection of unbounded settings.

Official source: [OpenAI Python SDK reference](https://developers.openai.com/api/reference/python)
documents `AsyncOpenAI`, Responses input/output, timeout, retries, and async
client cleanup. The dependency/lockfile pins SDK 2.54.0 for reproducibility.

Verified 2026-11-03 on Python 3.12.15: **171 application tests passed** with real
PostgreSQL enabled; adapter/settings coverage 100%, overall coverage 98.48%.
Ruff lint/format, strict Mypy, and whitespace checks passed.
