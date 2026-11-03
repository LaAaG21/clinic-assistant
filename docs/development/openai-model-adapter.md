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

The #58 error boundary now maps recognized failures to #43's `DependencyFailure`:

| Failure | Shared code / HTTP status |
| --- | --- |
| SDK `APITimeoutError`, expired whole-call deadline, provider HTTP 408/504 | `dependency_timeout` / 504 |
| SDK connectivity, other provider HTTP errors, SDK response-validation failure | `dependency_unavailable` / 503 |
| Failed/incomplete/non-completed response, error payload, or blank output | `dependency_unavailable` / 503 |

Provider authentication errors describe the application's external dependency,
not patient authentication, so they use the safe unavailable response rather
than exposing a provider 401/body. Original exceptions are chained for internal
diagnostics; public exception text contains only the shared code. Existing #43
handlers render the public envelope; no HTTP handlers are duplicated here.
Unknown programming errors, unrelated `TimeoutError`, and cancellation propagate
unchanged. Only this adapter's expired deadline counts as an application timeout.

No failure becomes an unsupported-answer fallback or partial successful answer.
Nonempty raw text is otherwise returned unchanged; consumers still validate
structured content and evidence. The fake can configure the same shared failures
or intentionally invalid raw output. There is no classification, retrieval,
citation/safety policy, logging (#65), or production-route wiring here.

## Verification

```sh
uv sync --locked --group dev
uv run --locked pytest tests/test_openai_adapter.py tests/test_settings.py tests/test_model_adapter.py -q
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy .
```

The original #53 focused run passed 52 cases before #58's failure boundary.
Tests run the actual pinned SDK against `httpx.MockTransport`; no live model key
or external request is used. They check exact request/response shape, SDK timeout,
zero/one-retry counts, whole-call cancellation, client cleanup on success/failure,
fake compatibility, safe settings errors, and rejection of unbounded settings.

Run `uv run --locked pytest tests/test_model_failures.py tests/test_openai_adapter.py tests/test_errors.py -q`
for the controlled failure/public-error boundary. It checks timeouts, connectivity,
provider statuses, invalid/incomplete replies, fake compatibility, unchanged
cancellation/programming errors, and absence of synthetic key/prompt markers in
the actual shared-handler responses. All SDK/HTTP operations are mocked.

Official source: [OpenAI Python SDK reference](https://developers.openai.com/api/reference/python)
documents `AsyncOpenAI`, Responses input/output, timeout, retries, and async
client cleanup. The dependency/lockfile pins SDK 2.54.0 for reproducibility.

Verified 2026-11-03 on Python 3.12.15: **171 application tests passed** with real
PostgreSQL enabled; adapter/settings coverage 100%, overall coverage 98.48%.
Ruff lint/format, strict Mypy, and whitespace checks passed.

#58 completion verification (2026-11-03): 26 controlled failure cases plus the
existing SDK/HTTP contract tests passed; full suite **245 passed**, with real
PostgreSQL and no live model calls. Adapter coverage 100%, overall coverage
98.02%; Ruff lint/format and strict Mypy passed.
