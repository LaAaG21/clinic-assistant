-- Emergency flags (#55), read by staff through #60.
-- Design: docs/design/database-diagram.md (#22). Numbered 010 so the agreed order
-- (004 requests #52, 005 messages #26 second portion, 006 approvals #40) keeps its
-- slots; the message foreign key is added once the messages table exists.
-- No schema name is hard-coded, so tests can apply this file inside a throwaway schema.

CREATE TABLE emergency_flags (
    flag_id text PRIMARY KEY,
    conversation_id text NOT NULL REFERENCES conversations (conversation_id),
    -- Identity of the flagged patient message; one flag per message.
    message_id text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT emergency_flags_id_not_blank CHECK (btrim(flag_id) <> ''),
    CONSTRAINT emergency_flags_message_id_not_blank CHECK (btrim(message_id) <> '')
);

-- Staff list newest first (#60); also serves "flags of one conversation".
CREATE INDEX emergency_flags_created_at ON emergency_flags (created_at DESC, flag_id);
CREATE INDEX emergency_flags_conversation ON emergency_flags (conversation_id);
