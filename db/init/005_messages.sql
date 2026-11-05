-- Message/request-FK portion of #26. Conversations are in 002; requests in 004.
ALTER TABLE requests ADD CONSTRAINT requests_message_conversation_key
    UNIQUE (request_id, conversation_id);

CREATE TABLE messages (
    message_id text PRIMARY KEY,
    conversation_id text NOT NULL REFERENCES conversations (conversation_id),
    role text NOT NULL CHECK (role IN ('patient', 'assistant')),
    text text NOT NULL CHECK (btrim(text) <> ''),
    client_message_id uuid,
    request_id text,
    created_at timestamptz NOT NULL DEFAULT now(),
    citations jsonb NOT NULL DEFAULT '[]'::jsonb,
    CONSTRAINT messages_id_not_blank CHECK (btrim(message_id) <> ''),
    CONSTRAINT messages_client_identity CHECK (
        (role = 'patient' AND client_message_id IS NOT NULL)
        OR (role = 'assistant' AND client_message_id IS NULL)
    ),
    CONSTRAINT messages_patient_text_limit CHECK (
        role <> 'patient' OR char_length(text) <= 4000
    ),
    CONSTRAINT messages_citations_array CHECK (jsonb_typeof(citations) = 'array'),
    CONSTRAINT messages_client_retry_key UNIQUE (conversation_id, client_message_id),
    CONSTRAINT messages_request_conversation_fkey
        FOREIGN KEY (request_id, conversation_id)
        REFERENCES requests (request_id, conversation_id)
);
