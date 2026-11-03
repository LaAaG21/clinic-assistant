# Shared API errors

Issue #43 registers the handlers in `clinic_assistant.errors` on the production
app. Tests register the same function on a separate app with controlled failure
routes. The [API design](../design/service-boundaries-and-api.md#errors-and-dependency-failures)
is still **Proposed**: this implementation follows its current mappings, but
does not establish team agreement. Review these mappings and the small adapter
exception interface with callers before merging or building dependent routes.

Every handled exception returns
`{"error":{"code":"...","message":"...","fields":{}}}`. Messages are fixed
public text. Validation adds safe field/reason pairs, without copying Pydantic's
input, context, custom message, or unknown field names. Only the existing message
model's `text` and `client_message_id` paths are exposed; other paths use
`request`. The models retain ownership of validation rules and limits.

| Failure | Status | Public code |
| --- | --- | --- |
| Malformed JSON | 400 | `invalid_json` |
| Invalid request fields | 422 | `validation_error` |
| Missing resource | 404 | `not_found` |
| Explicit workflow conflict | 409 | `conversation_busy`, `idempotency_conflict`, or `decision_conflict` |
| Recognized service outage | 503 | `dependency_unavailable` |
| Durable acceptance cannot be confirmed | 503 | `persistence_unavailable` |
| Recognized external timeout | 504 | `dependency_timeout` |
| Unexpected failure (including response validation) | 500 | `internal_error` |

Adapters raise `DependencyFailure("dependency_unavailable")`,
`DependencyFailure("persistence_unavailable")`, or
`DependencyFailure("dependency_timeout")` **only after identifying that specific
failure**. Chain the original exception with `raise ... from exc`; it is never
serialized. Raw driver exceptions, `TimeoutError`, and `ValueError` are not
automatically classified as service outages. They return generic 500 responses.
Workflow callers can raise `RequestConflict` with one of the three listed codes.
No database/model operations, retries, or workflow decisions are added here.

Framework and explicit `HTTPException` responses retain their status but discard
`detail`. Standard 400/401/403/405/409/429 errors use safe generic codes
(`bad_request`, `unauthorized`, `forbidden`, `method_not_allowed`, `conflict`,
`too_many_requests`); unlisted client statuses use `http_error`, and unlisted
server statuses use `internal_error`. These fallback codes extend the proposal
for framework errors, without guessing domain-specific reasons from raw text.
`Allow`, `WWW-Authenticate`, and `Retry-After` headers are retained. Callers must
provide public, non-sensitive header values; diagnostic headers are dropped.

Explicit endpoint responses are not rewritten. In particular, health's 503 body
and the emergency response with a safety instruction plus persistence error
remain owned by those endpoints. Accepted actions that later fail retain the
request-resource contract rather than becoming exception responses.

Safe diagnostic logging remains the later L10b task. Run with debug disabled
(the production app default); framework debug tracebacks bypass generic 500
handling. These handlers cover failures before a response starts, not failures
after streaming headers have already been sent.

## Verification

`uv run --locked pytest tests/test_errors.py` exercises valid and invalid message
input, malformed JSON, framework 404/405, protocol headers, explicit dependency
and conflict errors, unexpected/driver/response-validation failures, special
responses, and production registration. Synthetic private markers must never
appear in returned bodies. No model key is needed.

Verified 2026-11-03 on the current main baseline: 36 focused handler cases and
215 total application tests passed with real PostgreSQL enabled; overall
application coverage 97.84%. Ruff lint/format, strict Mypy, and whitespace checks
passed. The existing #43 implementation was reused with its authorship preserved.
