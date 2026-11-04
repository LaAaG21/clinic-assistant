# Ordinary-message classification (#63)

The issue assignee confirmed this minimal classification/clarification contract
on 2026-11-03: an existing six-label intent, a boolean `uncertain`, and optional
doctor/specialty/date/slot/appointment details. `IntentResult` and `IntentDetails`
are frozen, strict Pydantic schemas; unknown fields/labels or malformed data are
rejected with a fixed safe `InvalidIntentOutput`, not converted to guessed actions.
Missing details remain null and uncertainty is preserved for #68. Dates must be
real ISO calendar dates. The allowed labels reuse #8's shared `Intent` alias.

`await classify_intent(text, adapter)` sends one fixed system instruction and the
unchanged user text through #46's existing async contract. It parses the configured
raw output and returns a validated result. Recognized provider failures propagate
unchanged, distinct from bad classification output and unsupported evidence.

The emergency guard must run before invoking this ordinary classifier; a model
`emergency` label is not a replacement for that guard. The classifier performs no
storage, retrieval, booking/cancellation, safety-authorizing decision, or routing
side effect. Parsed identifiers are still untrusted model data: later action
consumers must resolve/validate resources, never treat these strings as permission.

Run `uv run --locked pytest tests/test_classification.py -q` plus the shared
Ruff/format/Mypy/coverage commands. Tests configure #46's fake, remove model keys,
guard DB connections, inspect the actual model input, cover all six labels,
preserved details/uncertainty, malformed output, and shared dependency errors.

Draft until #58's real-adapter error boundary merges. The shared typed failure
contract itself is already on main through #43; tests use it with the fake.
Verified 2026-11-03: 24 focused cases and 244 total tests passed with real
PostgreSQL enabled; classification coverage 100%, overall coverage 98.05%.
Ruff lint/format and strict Mypy passed. No live model request was used.
