# Durable same-day booking workflow (#57)

`build_booking_graph(connect, saver, clinic_timezone=...)` compiles the production
booking graph. Use the production PostgreSQL checkpointer context and the shared
connection helper to provide its two durable resources.

`start_booking` accepts a server-owned request ID, conversation ID and selected
slot. It resolves and locks the conversation's internal thread, then prepares
the request and approval in one transaction. The clinic-timezone policy decides
whether to reach a real LangGraph interrupt. Ordinary requests call the shared
atomic booking/outcome operation.

The waiting result includes request, conversation, target and approval identities,
pending state and patient text. Same-request reload preserves the original target
and pending item even after the clinic date changes. A new request is rejected
while that conversation is paused. Retrying an interrupted preparation reconciles
the durable request/approval before producing the waiting response.

The server-derived UUID approval ID, session run lock, and shared-request
coordination are explicit design choices for review. Staff resume and final
outcome/message persistence are supplied by #62.

## Resume and completion (#62)

`resume_booking(graph, connect, approval_id=..., decision=..., reason=...)`
validates the staff fields using the existing SavedDecision constraints. It
resolves the approval to its original request and conversation, serializes the
conversation run, and commits the decision/reason with processing state.
It then invokes the correct paused graph with a real LangGraph resume command.

The shared completion transaction locks the request, reuses any terminal result,
and either applies the existing atomic booking operation or records rejection.
Booking, final request outcome and assistant outcome message commit together.
The assistant message has a stable server-derived ID, so replay preserves one
stored patient-visible outcome.

An identical normalized decision returns the stored outcome and original decision
time. A different decision or reason raises the shared decision_conflict.
Missing approvals raise LookupError. The graph verifies that a matching durable
decision exists before leaving its staff interrupt.

A crash before the completion commit leaves the durable decision in processing
and rolls back booking/message writes. A crash after commit but before graph
checkpointing is reconciled by reading the saved result, without invoking the
mutation again. Retrying an old completed approval preserves a newer pending
request on the same conversation.

Use the shared connection context and keep the saver open for the graph lifecycle.

```python
from uuid import uuid4

from clinic_assistant.booking_workflow import build_booking_graph, start_booking
from clinic_assistant.checkpoints import postgres_checkpointer
from clinic_assistant.database import connection
from clinic_assistant.settings import get_settings

settings = get_settings()
connect = lambda: connection(settings.database)
with postgres_checkpointer(settings.database) as saver:
    graph = build_booking_graph(
        connect, saver, clinic_timezone=settings.clinic_timezone
    )
    waiting = start_booking(
        graph,
        connect,
        conversation_id=existing_conversation_id,
        request_id="request_" + uuid4().hex,
        slot_id=selected_slot_id,
    )
```

The deterministic identities, decision-to-progress transaction and outcome/message
coordination are implementation choices documented for review of #4/#6/#22.
