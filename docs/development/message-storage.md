# Message storage (#26)

`005_messages.sql` follows requests and precedes approvals. It completes the
conversation/message schema while preserving the request-to-conversation foreign
key. Patient retry IDs are UUIDs unique within a conversation. Assistant messages
have null client retry IDs. Text is required, and patient text is limited to 4,000
Unicode code points.

The implementation stores citations as a JSONB array, following the existing
message response shape. This is an explicit choice for review of #22's open
citation-storage question. Application code remains responsible for citation
object validation through the existing Pydantic message models.

Later completion code stores its assistant outcome in this table in the same
transaction as request and booking updates. An outcome message uses a stable
server-generated ID to make a replay return the existing message.
