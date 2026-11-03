-- Conversations (#26, first portion).
-- Design: docs/design/database-diagram.md (#22). Messages follow in a later file,
-- after the requests table (#52), because each message may reference a request.
-- No schema name is hard-coded, so tests can apply this file inside a throwaway schema.

CREATE TABLE conversations (
    conversation_id text PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT conversations_id_not_blank CHECK (btrim(conversation_id) <> '')
);
