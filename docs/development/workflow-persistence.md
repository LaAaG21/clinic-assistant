# Production workflow persistence

The #51 factory uses the synchronous PostgreSQL saver, matching the application's
synchronous database boundary. `postgres_checkpointer(settings)` sets bounded
connection and query timeouts, creates a dedicated `workflow_checkpoints` schema,
serializes library setup with a session advisory lock, and closes the connection
on normal exit or failure. The library owns its checkpoint tables and migrations.

Applications keep the context open while compiling and running a graph. Setup is
idempotent and runs when the context opens. Tests override the schema with a
unique disposable name and verify reconnect/continuation using the shared fake.

Saver mode, dedicated schema, and this initialization lifecycle are explicit
implementation choices for review of #3/#4/#6/#22. Configuration uses the shared
database settings. Application code accesses saved state through LangGraph APIs.

The implementation follows the official [PostgreSQL saver guidance](https://docs.langchain.com/oss/python/langgraph/add-memory)
and [interrupt/resume guidance](https://docs.langchain.com/oss/python/langgraph/interrupts).

## Conversation identity (#56)

The internal thread is a version-stable UUID5 derived from the public conversation
ID using the project namespace string. The conversation must exist in PostgreSQL.
Callers supply a conversation ID to the application service, which derives the
internal thread. A missing conversation raises LookupError.

`conversation_run` holds a session advisory lock on a dedicated connection for
the duration of a graph invocation. Concurrent attempts return conversation_busy.
Business nodes use separate connections so their transactions can commit before
checkpointing. The shared connection context releases session locks on connection
failure. This deterministic mapping is an explicit choice for design review.
