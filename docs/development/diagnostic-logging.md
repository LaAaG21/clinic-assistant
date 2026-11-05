# Safe diagnostic logging (#65)

`clinic_assistant.diagnostics` records one line per application, model or
database failure on the `clinic_assistant.diagnostics` logger, and the shared
error handlers from #43 call it. Response bodies and status codes are unchanged;
each error response now also carries an `X-Request-ID` header so a patient or
staff report can be matched with the log line.

```text
event=dependency_failure code=dependency_timeout request_id=3f2c... method=POST route=/conversations/{conversation_id}/messages cause=openai.APITimeoutError at _base_client.py:1670 in request
```

| Field | Content | Never contains |
| --- | --- | --- |
| `event` | Fixed name: `dependency_failure`, `unexpected_failure`, `http_<status>`, or a consumer's own name such as `emergency_flag_persistence` | Free text |
| `code` | The public error code from #43 (`dependency_unavailable`, `persistence_unavailable`, `dependency_timeout`, `internal_error`) | Driver or provider error strings |
| `request_id` | A client-supplied `X-Request-ID` of 1 to 64 letters, digits, `-` or `_`, otherwise a generated 32-character hex value; the same value is returned in the response header | Patient identifiers or arbitrary header text |
| `method`, `route` | HTTP method and the matched route **template** (`unmatched` for 404s) | Path values such as conversation IDs, query strings, request bodies |
| `cause` | Exception type with module, plus the innermost frame's file name, line and function | `str(exc)`: psycopg and OpenAI messages can embed connection strings, keys, prompts or patient text |

Severity: recognized outages and timeouts are `WARNING`; an unconfirmed durable
write (`persistence_unavailable`), an unexpected exception and any 5xx
`HTTPException` are `ERROR`. Client errors (4xx), validation failures and
workflow conflicts are not logged, so patient input never reaches the log by
that path. The health endpoint keeps its own fixed-code log line from #14.

Consumers that return a special response instead of raising, such as the
emergency degradation from the API contract (safety reply plus
`persistence_unavailable`), call `log_failure(request, "emergency_flag_persistence",
exc.code, exc.__cause__, level=logging.ERROR)` themselves and keep their body
unchanged; `request` may be `None` outside HTTP. `describe(exc)` is available for
the same type-and-location summary elsewhere.

This is not a general observability framework: no handlers, formatters,
sampling or exporters are configured here; the process's logging configuration
(Uvicorn's by default) decides where lines go.

## Verification

`uv run --locked pytest tests/test_diagnostics.py tests/test_errors.py -q` plus
the shared Ruff, format, Mypy and coverage commands. The captured-log tests use
synthetic key, connection-string and patient-text markers and assert they appear
in no log record or response for provider timeouts, unconfirmed persistence,
raw driver exceptions, 5xx and 404 framework errors, validation errors and the
emergency consumer; they also check the event context, severities, route
templates and correlation IDs. No model key or database is needed.

## Learning question

*Which diagnostic fields help operators without revealing the patient's message?*
The event name and public code say what failed, the exception type and frame
say where, the route template says which operation, and the request ID lets the
operator find the exact request a user is asking about. None of these needs the
message text, the connection string or the provider's message, which is why
those are excluded by construction rather than by redaction.
