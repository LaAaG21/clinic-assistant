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
