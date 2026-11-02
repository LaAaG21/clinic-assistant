# Patient-message models (#8)

`clinic_assistant.messages` defines the request and response schemas for the
published `POST /conversations/{conversation_id}/messages` contract in
[the merged #6 document](../design/service-boundaries-and-api.md).
The document still labels broader decisions as proposed; this change implements
its published message fields without claiming new team agreement or choosing
unresolved workflow/storage behavior.

## Request validation

`PatientMessageRequest` requires `client_message_id` (a UUID) and `text` (a strict
string). Text is trimmed before enforcing 1 to 4,000 Unicode code points.
Missing/null/non-string, empty, whitespace-only, and over-limit text is rejected;
4,000 characters after trimming is accepted. Unknown fields are forbidden.
Conversation IDs remain opaque strings supplied in the route, not body fields
or UUIDs. UUID validation does not implement durable retry/idempotency behavior.

## Response schemas

`PatientMessageResponse` contains `conversation_id`, `patient_message_id`,
`reply`, `intent`, `response_type`, `slots`, and nullable `request`.
Nested schemas describe the assistant message, source citations, available slots,
saved staff decision, and booking/cancellation request resources. The action
discriminates the target: bookings use `slot_id`; cancellations use
`appointment_id`. Server IDs remain opaque strings, and timestamps require an
explicit UTC offset. Nullable fields listed by the contract remain required
where specified; null is different from a missing envelope field.

Outcome codes remain strings because the contract's failure-code examples are
not exhaustive. An outcome may include an appointment ID. State transitions,
approval eligibility, same-day rules, citation sufficiency, request/reply
correlation, and idempotency belong to later application/workflow work.

## OpenAPI demonstration and verification

`tests/test_messages.py` connects the models to the documented route in a
**test-only FastAPI app**, with both 200 and 202 response schemas. It validates
the generated OpenAPI document, verifies required fields, UUID format, text
length bounds, nested schemas, and forbidden extras, and exercises valid/invalid
HTTP bodies. The production application is unchanged and has no message route.
The test app uses FastAPI's default 422 response; production error-envelope
handling remains separate work. No classification, model call, persistence,
booking execution, or approval execution is implemented.

From the repository root:

```sh
uv sync --locked --group dev
uv run --locked pytest tests/test_messages.py -q
uv run --locked pytest --cov --cov-report=term-missing
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy
```

Verified on 2026-11-02 using Python 3.12.15 and the committed uv lockfile:
**44 model/OpenAPI tests + 1 foundation startup test passed (45 total)**;
application coverage **100%** (64 executable statements); Ruff lint/format and
strict Mypy passed. Coverage here measures the small boundary-model application,
not clinical behavior or workflow completeness. All inputs are synthetic; no
database or model API key is needed. Pydantic is declared as a direct dependency.

Invalid input should be rejected at the API boundary so malformed messages never
reach classification or side effects, and callers receive actionable field
validation errors before workflow execution starts.
