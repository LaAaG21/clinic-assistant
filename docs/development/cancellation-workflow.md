# Durable cancellation pause (#72)

`build_cancellation_graph(connect, saver)` uses the production PostgreSQL saver,
shared conversation/thread identity, request storage and approval storage.
`pause_cancellation` starts or recovers the request for an already accepted
patient message belonging to that conversation.

The application validates the booking/conversation relationship and active state
through #67's non-mutating target validator. It commits the cancellation request,
pending approval, patient-message link and assistant waiting reply together.
The graph then reaches a real LangGraph interrupt before the waiting result is
returned. Today's and future-date appointments follow the same path.

The result is the existing `PatientMessageResponse` envelope with intent
`cancel`, response type `action`, a cancellation request with
`pending_approval`, and its approval ID. The request target exposes the stored
booking ID as `appointment_id`. IDs, reply timestamps and the original target
survive reconnect/retry. Changed retry targets raise idempotency_conflict, and a
different request on the paused conversation raises conversation_busy.

Invalid targets raise `InvalidCancellationTarget` with the safe outcome
`target_not_found` or `ineligible_target` and create no pending work.
Missing or mismatched accepted patient messages raise LookupError.

The checkpoint is reconciled from durable application records if preparation
commits before checkpointing fails. A failure within that transaction rolls back
the request, approval and message writes together. The validator and pause leave
the booking unchanged.

Use the library entry points with the shared connection factory and production
checkpointer context.

```python
from clinic_assistant.cancellation_workflow import (
    build_cancellation_graph,
    pause_cancellation,
)
from clinic_assistant.checkpoints import postgres_checkpointer
from clinic_assistant.database import connection
from clinic_assistant.settings import get_settings

settings = get_settings()
connect = lambda: connection(settings.database)
with postgres_checkpointer(settings.database) as saver:
    graph = build_cancellation_graph(connect, saver)
    waiting = pause_cancellation(
        graph, connect, conversation_id=conversation_id, request_id=request_id,
        booking_id=booking_id, patient_message_id=accepted_patient_message_id,
    )
```

Request IDs and the accepted message are supplied by the application layer.
Approval/reply IDs use the documented deterministic server identity convention.
The current phase guards the resume boundary. #77 supplies the separate
decision/completion operation.

Run the CI-collected application tests with a disposable PostgreSQL database and
`TEST_DATABASE_URL` set.

```powershell
uv run --locked pytest tests/test_cancellation_workflow.py tests/test_bookings_schema.py -q
```
