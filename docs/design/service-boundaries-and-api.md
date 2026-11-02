# Clinic Assistant Service Boundaries and API Contract

Status: **Proposed, pending research share-out and team review**. Related work:
[issue #6](https://github.com/LaAaG21/clinic-assistant/issues/6).

The clinic assistant is a backend REST service for the clinic's existing chat
client. This contract defines component responsibilities, patient messages,
appointment requests, staff decisions, and observable outcomes. It implements no
endpoints. The source requirements are the repository's
[Clinic Front-Desk Assistant Word brief](../requirements/clinic-front-desk-assistant.docx),
sections 1, 2, 5, and 6, especially FR-1 through FR-7. The brief is an unchanged
copy of the supplied challenge document.

Required behavior comes from the brief. Routes, field names, limits, and handoffs
below are design proposals for review, not recorded team agreement. Research
decisions remain open in the final section; this document does not close #6's
share-out and agreement requirement.

## Scope and service boundaries

The service supports conversation continuity, intent routing, document-grounded
answers, available slots, bookings, approval-controlled cancellations and same-day
bookings, emergency handling, and health reporting. PostgreSQL is the only
database, accessed through parameterized SQL without an ORM. Conversations,
appointments, approvals, emergency flags, and workflow checkpoints must survive
container restarts. Only a bounded recent conversation window goes to the model.

A new UI, real patient data, patient authentication, SMS/email, and payments are
outside this challenge. Synthetic identifiers are for correlation, not proof of
identity. Staff routes are a distinct interface; deployment access restrictions
remain a team decision, not an authentication feature added by this contract.

| Component | Owns | Receives and returns |
| --- | --- | --- |
| FastAPI boundary and Pydantic models | HTTP parsing, field validation, status codes, response serialization, OpenAPI | Receives JSON and path/query IDs; passes validated commands to the workflow/application service; returns the public response or error. |
| LangGraph workflow and application service | Emergency short-circuit, ordinary intent routing, clarification, bounded model context, approval policy, state transitions, patient outcomes | Receives conversation ID and message or staff decision; calls storage/retrieval/model adapters; returns reply, slots, request state, or failure. |
| PostgreSQL repositories | Durable records, parameterized queries, atomic appointment mutations, integrity constraints, stored decisions and outcomes | Receive explicit read/write operations; return records, conflicts, or typed storage failures. A database constraint must prevent simultaneous double booking. |
| PostgreSQL checkpoint adapter | Durable graph state and restoration under a stable internal thread identity | Receives graph checkpoints; restores the correct state after restart. Saver mode, initialization, and identity mapping await #3/#4 agreement. |
| Document retrieval adapter | Loading/splitting clinic documents, retrieval, preservation of evidence provenance | Receives a clinic question; returns passages with `source_id`, `source_name`, `passage_id`, and text, or no supporting evidence. Algorithm awaits #5. |
| Model adapter | Real/fake model interchangeability, explicit timeout, structured output handling | Receives task input, bounded history, and retrieved evidence where relevant; returns candidate classification/reply or a typed failure. It does not authorize appointment writes or staff decisions. |

API handlers must not duplicate workflow policy: a handler validates a message;
the workflow decides whether its requested booking needs approval. Storage enforces
integrity even if two workflow runs compete. All external calls have timeouts;
failures produce a clear response and diagnostic log, not an unhandled crash.

## Patient entry and workflow rules

See the [message and staff-approval workflow](message-workflow.md) for the draft
diagram, restart boundaries, scenario walkthrough, and open research decisions.

**Booking and cancellation enter through patient messages.** This proposal has
no separate public booking/cancellation creation endpoints. A message such as
"Book slot_demo_1" or "Cancel appt_demo_1" enters the same intent workflow as
natural language. Missing or ambiguous details produce a clarifying question;
they must not cause an appointment mutation. The slot endpoint also lets the
existing client show structured choices. Route spelling does not depend on the
retrieval or checkpoint implementation.

1. Validate the message envelope and resolve the conversation. Run the emergency
   guard before ordinary classification, retrieval, or appointment processing.
   An emergency produces an immediate safety reply and a durable staff flag.
   The response must not wait for an ordinary model call. Detection rules and
   exact wording require team review; the ordinary classifier cannot be the
   only emergency guard.
2. Otherwise classify at least `clinic_question`, `find_slots`, `book`, `cancel`,
   or `other`. `emergency` is the recorded intent for the fast path. Ask a
   clarifying question when the intent or its required details are uncertain.
3. Clinic answers use only supporting clinic passages and name their source
   documents. A retrieved hit alone does not prove support. No supporting evidence
   means an explicit fallback; diagnosis/treatment requests receive a refusal.
4. For a booking, resolve one slot and evaluate its local date in the configured
   clinic timezone. A same-day booking pauses for approval. Other bookings use
   the atomic booking operation. Every cancellation pauses for approval.
5. Use a real LangGraph interrupt before an approval-controlled mutation. Persist
   the pending item and checkpoint before returning `pending_approval`. Rejection
   performs no appointment mutation. Approval resumes the original request and
   rechecks current availability/state; it is permission to attempt the action,
   not a guarantee that it will succeed.
6. Persist the final result and a patient-visible conversation message. Clients
   retrieve the outcome using the request endpoint or conversation history;
   no email, SMS, or push service is required.

Proposed concurrency rule: one ordinary workflow operation per conversation at a
time; additional ordinary messages while busy or paused return `409`. The emergency
guard still runs before that busy check. An emergency during a pause uses a
separate safety handoff and must not resume or replace the pending action. Its
checkpoint/record coordination is an open #3/#4 design question.

## Common fields and validation

All bodies are JSON objects. IDs are server-generated opaque strings, not patient
names or secrets; sample IDs below are illustrative. `conversation_id` identifies
the conversation, `message_id` a stored message, `request_id` an appointment action,
`approval_id` its staff review, `slot_id` a slot, `appointment_id` a booking, and
`flag_id` an emergency flag. A public conversation ID need not equal the internal
graph thread ID until the team agrees the mapping.

| Field | Proposed rule |
| --- | --- |
| Message `text` | Required string; trim outer whitespace, then require 1 to 4,000 Unicode code points. Missing, null, non-string, empty, whitespace-only, and longer values are invalid. |
| `client_message_id` | Required client-generated UUID, scoped to a conversation, for safe retries. Same ID and normalized text returns the existing result; same ID with different text returns `409`. |
| Staff `decision` | Required enum: `approve` or `reject`. |
| Staff `reason` | Required string, trimmed, 1 to 1,000 Unicode code points; patient-visible in this proposal. Do not include private staff notes. |
| `date` | Required calendar date `YYYY-MM-DD`, interpreted in the clinic timezone. |
| Slot filters | At least one of `doctor_id` or `specialty`; both means intersection. Specialty must be non-empty after trimming. |
| Timestamps | RFC 3339 with an explicit offset. Responses include the configured IANA `clinic_timezone` where local-day interpretation matters. |
| List reads | Optional `limit` (integer 1 to 100, default 50) and opaque `cursor`. Return `next_cursor`, or null when finished. Invalid cursors return `422`. |

Reject unknown body fields with `422`. Limits and timezone selection await team
review; do not assume the developer's machine timezone. Durable retry handling
must survive restarts. Its storage/transaction mechanism awaits #3/#4.

## Endpoint contract

Paths are relative to the service root. Curly braces denote path parameters.
An accepted pending action is a normal success response, not an HTTP error.

| Method and path | Required input | Success response |
| --- | --- | --- |
| `POST /conversations` | `{}` | `201`: `conversation_id`, `created_at`; `Location` points to the conversation. |
| `POST /conversations/{conversation_id}/messages` | `client_message_id`, `text` | `200` for a reply or terminal action; `202` for pending/processing action. Returns the message envelope below; `Location` points to the request for `202`. |
| `GET /conversations/{conversation_id}` | Conversation ID; optional list parameters | `200`: `conversation_id`, ordered `messages`, `next_cursor`. Each message contains `message_id`, `role` (`patient`/`assistant`), `text`, `created_at`, `citations`, and nullable `request_id`. |
| `GET /slots` | `date` and slot filter(s); optional list parameters | `200`: `clinic_timezone`, `slots`, `next_cursor`. Each slot has `slot_id`, `doctor_id`, `specialty`, `starts_at`, `ends_at`. No availability returns an empty list; results do not reserve slots. |
| `GET /requests/{request_id}` | Request ID | `200`: the current request resource, including decision and final outcome when present. Pending state is still HTTP `200` on reads. |
| `GET /staff/approvals` | Optional list parameters | `200`: `items`, `next_cursor`; only items awaiting a decision. Each item contains `approval_id`, `request_id`, `conversation_id`, `action`, `target`, `created_at`. |
| `POST /staff/approvals/{approval_id}/decision` | `decision`, `reason` | `200` for terminal result or `202` while continuation runs; request resource with saved decision. `Location` points to the request. |
| `GET /staff/flags` | Optional list parameters | `200`: `items`, `next_cursor`; each emergency flag has `flag_id`, `conversation_id`, `message_id`, `created_at`. This provides staff visibility, not the optional general audit API. |
| `GET /health` | None | `200`: `status: ok`, `api: reachable`, `database: reachable`; database failure gives `503`, `status: unavailable`, `api: reachable`, `database: unreachable`. |

Message envelope: `conversation_id`, `patient_message_id`, `reply` (an assistant
message as above), `intent`, `response_type`, `slots` (array), and `request`
(resource or null). `response_type` is `answer`, `clarification`, `unsupported`,
`refusal`, `emergency`, `slots`, or `action`. Citations contain `source_id`,
`source_name`, and `passage_id`; non-document replies use an empty array. The
message endpoint and all response variants must appear in the eventual OpenAPI.

A request contains `request_id`, `conversation_id`, `action` (`book`/`cancel`),
`target` (`slot_id` for booking, `appointment_id` for cancellation), `status`,
nullable `approval_id`, `patient_message`, nullable `decision`, and nullable
`outcome`. A saved decision contains `decision`, `reason`, and `decided_at`.

| Request status | Meaning and outcome |
| --- | --- |
| `pending_approval` | No action executed; `approval_id` present, decision/outcome null. |
| `processing` | Accepted or approved work is running/recovering; outcome null. |
| `completed` | Action succeeded; outcome code `appointment_booked` or `appointment_cancelled`, with `appointment_id`. |
| `rejected` | Staff rejected; outcome code `request_rejected`; appointment unchanged. |
| `failed` | Known failure with no successful requested mutation; outcome code such as `slot_unavailable` or `appointment_not_cancellable`. |

An ordinary booking moves directly to `completed`/`failed` or through `processing`.
Approval-controlled actions move from `pending_approval` to `rejected` or to
`processing`, then `completed`/`failed`. Accept only one staff decision: an exact
retry returns current state; a conflicting decision or reason returns `409`.
An uncertain post-write failure remains `processing` until reconciled; do not
claim failure or blindly repeat a possibly committed mutation. Durable decision,
resume, and outcome coordination is a required invariant with an open mechanism.

## Errors and dependency failures

Except for the health response above, HTTP errors share this envelope:

```json
{"error":{"code":"validation_error","message":"Message text must contain 1 to 4000 characters after trimming.","fields":{"text":"invalid_length"}}}
```

| HTTP status | Codes and conditions |
| --- | --- |
| `400` | `invalid_json`: body cannot be parsed. |
| `404` | `not_found`: conversation, request, approval, or other referenced resource does not exist. |
| `409` | `conversation_busy`, `idempotency_conflict`, `decision_conflict`: request conflicts with current state. |
| `422` | `validation_error`: missing/invalid fields, dates, filters, cursor, enum, or limits. |
| `503` | `dependency_unavailable`: required database/model service unavailable; `persistence_unavailable`: durable acceptance cannot be confirmed. |
| `504` | `dependency_timeout`: a required external call exceeded its timeout. |
| `500` | `internal_error`: unexpected failure, logged with safe diagnostics and no stack trace or secrets in the response. |

A known business failure after an action was accepted is a stored `failed`
request, returned with HTTP `200` by message/decision endpoints and request reads.
A model/database error must not be disguised as a successful unsupported-answer
fallback. After a timeout, retry messages with the same `client_message_id`, or
read an already known request before attempting another action.

Emergency degradation: if flag persistence fails, return HTTP `503` with the
emergency message envelope and an additional `error` object using
`persistence_unavailable`. The safety instruction still reaches the patient;
do not claim that staff were successfully flagged. Log the failure for operators.

## Contract walkthroughs

These are synthetic design examples, not executed endpoint tests. Timestamps use
an illustrative clinic timezone of `Asia/Dubai`; this does not choose the clinic's
production timezone. Short response projections are explicitly labeled; the
field definitions above govern complete responses.

### New and continued conversation

`POST /conversations` with `{}` returns `201`:

```json
{"conversation_id":"conv_demo","created_at":"2026-11-02T09:00:00+04:00"}
```

`POST /conversations/conv_demo/messages`:

```json
{"client_message_id":"00000000-0000-4000-8000-000000000001","text":"When does the clinic open?"}
```

Example `200` response, grounded in a synthetic opening-hours passage:

```json
{"conversation_id":"conv_demo","patient_message_id":"msg_1","reply":{"message_id":"msg_2","role":"assistant","text":"The clinic opens at 09:00. Source: Clinic opening hours.","created_at":"2026-11-02T09:00:01+04:00","citations":[{"source_id":"doc_hours","source_name":"Clinic opening hours","passage_id":"hours_1"}],"request_id":null},"intent":"clinic_question","response_type":"answer","slots":[],"request":null}
```

After a container restart, send another message to the same conversation with a
new `client_message_id`. Storage/checkpoint restoration supplies prior context;
the model receives only the configured recent window. An unclear follow-up
returns `clarification`. A question unsupported by the documents returns
`unsupported`, no citations, and "I do not know from the clinic documents."
A diagnosis/treatment request returns `refusal` without medical recommendations.

### Slot lookup and ordinary booking

`GET /slots?specialty=dermatology&date=2026-11-03` returns `200`:

```json
{"clinic_timezone":"Asia/Dubai","slots":[{"slot_id":"slot_demo_1","doctor_id":"doctor_demo","specialty":"dermatology","starts_at":"2026-11-03T10:00:00+04:00","ends_at":"2026-11-03T10:30:00+04:00"}],"next_cursor":null}
```

On the illustrative current date of November 2, send this to the message endpoint:

```json
{"client_message_id":"00000000-0000-4000-8000-000000000002","text":"Book slot_demo_1."}
```

The API validates; the workflow resolves the slot and date policy; storage tries
the atomic insert. Example `200` response projection (`request` field only):

```json
{"request":{"request_id":"req_book","conversation_id":"conv_demo","action":"book","target":{"slot_id":"slot_demo_1"},"status":"completed","approval_id":null,"patient_message":"Your appointment is confirmed.","decision":null,"outcome":{"code":"appointment_booked","appointment_id":"appt_demo"}}}
```

If another request wins the slot, return `status: failed` and
`outcome.code: slot_unavailable`; never two appointments for one slot.

### Same day booking and staff approval

A separate message requests `slot_today`, whose local date is November 2.
The workflow reaches an interrupt before insertion. Example `202` response
projection (`request` field only):

```json
{"request":{"request_id":"req_today","conversation_id":"conv_demo","action":"book","target":{"slot_id":"slot_today"},"status":"pending_approval","approval_id":"approval_today","patient_message":"Your same-day booking request is waiting for staff approval.","decision":null,"outcome":null}}
```

`GET /staff/approvals` exposes this item and its target for review. Staff submit
`POST /staff/approvals/approval_today/decision`:

```json
{"decision":"approve","reason":"Staff confirmed the requested slot can be booked."}
```

The application resolves the approval to the original request and graph thread,
records the decision, and resumes it. The resumed workflow calls the atomic
booking operation. A terminal `200` decision response is:

```json
{"request_id":"req_today","conversation_id":"conv_demo","action":"book","target":{"slot_id":"slot_today"},"status":"completed","approval_id":"approval_today","patient_message":"Your appointment is confirmed.","decision":{"decision":"approve","reason":"Staff confirmed the requested slot can be booked.","decided_at":"2026-11-02T09:10:00+04:00"},"outcome":{"code":"appointment_booked","appointment_id":"appt_today"}}
```

If continuation is unfinished, return `202` with `processing`. The patient polls
`GET /requests/req_today` for that same resource and receives the final outcome;
`GET /conversations/conv_demo` also includes its assistant outcome message.
A now-unavailable slot produces `failed`, not a false confirmation. Restarting
while paused must preserve the pending item and original target.

### Cancellation and rejection

Send `{"client_message_id":"00000000-0000-4000-8000-000000000003","text":"Cancel appt_demo."}`
to the message endpoint. Return `202`, action `cancel`, target
`{"appointment_id":"appt_demo"}`, status `pending_approval`, and IDs `req_cancel`
and `approval_cancel`. The appointment remains booked.

`POST /staff/approvals/approval_cancel/decision`:

```json
{"decision":"reject","reason":"Please contact the front desk to clarify which appointment should be cancelled."}
```

Return `200` with `status: rejected`, the saved reason, and
`outcome: {"code":"request_rejected"}`. The appointment remains unchanged, and
the patient reads the rejection through `GET /requests/req_cancel` or history.
In a separate approved run, resume and perform the cancellation once; return
`completed` with `appointment_cancelled` and the appointment ID. Repeated identical
decisions return the existing result; competing decisions return `409`.

### Emergency and health

For a synthetic emergency test message, the guard bypasses ordinary classification
and appointment processing, returns `200` with `intent: emergency`,
`response_type: emergency`, empty citations/slots, and null request. Example reply
text for review: "Seek emergency help now. Do not wait for a chat reply."
Persist the message and flag; `GET /staff/flags` returns its identifiers. A paused
appointment request remains paused. Use the defined `503` degradation if the flag
cannot be persisted, rather than falsely claiming staff notification.

`GET /health` returns `200`:

```json
{"status":"ok","api":"reachable","database":"reachable"}
```

With a failed database probe it returns `503` and the unavailable values defined
above. This endpoint does not claim that the model provider or every workflow is
healthy. Model failures are reported by the affected request.

## Research evidence and decisions still open

Evidence refreshed on November 2, 2026 against the merged research on `main` and
the available #4 experiment branch. The research still leaves the team share-out
and agreed ADRs pending; no accepted research ADR is present on `main`.

| Research | Available evidence | What remains open |
| --- | --- | --- |
| [#3](https://github.com/LaAaG21/clinic-assistant/issues/3) checkpoints | [Merged R1 note](../research/r1-postgres-checkpoints.md), from [PR #7](https://github.com/LaAaG21/clinic-assistant/pull/7), reports restored state after container replacement and continuation on the same thread. Its recommendation is explicitly Proposed. | Sync versus async saver, startup/migration lifecycle, public ID/thread mapping, concurrent message handling, retention and state evolution; compare with #4 before acceptance. |
| [#4](https://github.com/LaAaG21/clinic-assistant/issues/4) interrupt and resume | The [unmerged proposed findings](https://github.com/LaAaG21/clinic-assistant/blob/443a89103dbead9cc6085be0ae054498330672cf/docs/research/004-staff-interrupt-resume.md) describe a PostgreSQL-backed interrupt, pending/decision payloads, and approval/rejection assertions. Compilation and Compose configuration checks passed, but the note explicitly reports that end-to-end execution was blocked; no successful pause/resume or persistence result is claimed. | Runtime evidence and comparison with #3 before agreement; production resume shape, replay/duplicate decisions, durable decision-to-resume handoff, mutation/checkpoint reconciliation, pending restart recovery, and emergency handling during a pause. |
| [#5](https://github.com/LaAaG21/clinic-assistant/issues/5) retrieval | The [merged R3 note](../research/clinic-document-retrieval.md), from [PR #9](https://github.com/LaAaG21/clinic-assistant/pull/9), describes splitting four synthetic documents into five passages with source IDs, deterministic fake-model answers naming sources, and unsupported-answer fallbacks. Retrieval results remain 7/8 supported hits for keywords versus 6/8 for PostgreSQL full-text search, with 11 versus 0 irrelevant passages. Embeddings were reviewed in documentation only. The earlier ADR was withdrawn; team agreement and an ADR are deferred to a follow-up PR. | Agree the retrieval method after share-out; production chunk limits/versioned source locations, evidence sufficiency, and unsupported-answer behavior still need decisions. Embedding quality was not measured, and the fake model does not establish real-model answer reliability. |

The PostgreSQL-only requirement and required approval/safety behavior are fixed
by the brief; choosing a specific saver, identity mapping, or retrieval algorithm
is not. The R1 proposal `thread_id = conversation_id` is a candidate, not a decision
made by this document. R3 scores are small-sample retrieval observations; its
fake-model answers demonstrate the evidence/citation interface, not real-model
reliability. Research experiments were not rerun for this documentation change.

Other review questions: clinic timezone and same-day boundary, message/history
window limits, emergency guard rules and wording, staff-route deployment access,
approval expiry, and exact timeout/recovery behavior. A pending booking must not
promise a reserved slot unless a separate reservation policy is agreed.

To finalize #6 after the share-out:

- Review the actual #3/#4/#5 findings together and record agreement, date, and
  accepted ADR links; retain unresolved decisions explicitly.
- Reconcile the API proposals above with the chosen graph/state and retrieval
  contracts, including IDs, retries, and patient outcomes after restart.
- Walk through the six scenarios above with the team: new conversation,
  continuation, ordinary booking, pending same-day booking, pending cancellation,
  and emergency. Confirm each component's input/output and approval/rejection
  results. Record the actual review outcome before marking this document agreed.

Acceptance coverage: the boundary table addresses #6 criterion 1; the endpoint,
validation, error, and walkthrough sections address criterion 2; workflow rules
cover criterion 3. Criterion 4 remains pending the real share-out and agreement.
