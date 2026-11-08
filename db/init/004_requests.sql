-- Appointment requests (#52), following the fields proposed in #22.
-- Applied after bookings and before messages/request FKs and approvals.
-- A booking request targets a slot before a resulting booking exists.

-- Composite keys let request FKs preserve the booking's conversation and slot.
-- booking_id is already unique, so existing bookings satisfy both keys.
ALTER TABLE bookings
    ADD CONSTRAINT bookings_request_conversation_key
        UNIQUE (booking_id, conversation_id),
    ADD CONSTRAINT bookings_request_slot_key UNIQUE (booking_id, slot_id);

CREATE TABLE requests (
    request_id text PRIMARY KEY,
    conversation_id text NOT NULL REFERENCES conversations (conversation_id),
    action text NOT NULL,
    slot_id text REFERENCES slots (slot_id),
    booking_id text,
    status text NOT NULL DEFAULT 'pending_approval',
    outcome_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT requests_booking_conversation_fkey
        FOREIGN KEY (booking_id, conversation_id)
        REFERENCES bookings (booking_id, conversation_id),
    CONSTRAINT requests_booking_slot_fkey
        FOREIGN KEY (booking_id, slot_id) REFERENCES bookings (booking_id, slot_id),
    CONSTRAINT requests_id_not_blank CHECK (btrim(request_id) <> ''),
    CONSTRAINT requests_action_valid CHECK (action IN ('book', 'cancel')),
    CONSTRAINT requests_status_valid CHECK (
        status IN ('pending_approval', 'processing', 'completed', 'rejected', 'failed')
    ),
    CONSTRAINT requests_target_matches_action CHECK (
        (action = 'book' AND slot_id IS NOT NULL)
        OR (action = 'cancel' AND booking_id IS NOT NULL AND slot_id IS NULL)
    ),
    CONSTRAINT requests_completed_has_booking CHECK (
        status <> 'completed' OR booking_id IS NOT NULL
    ),
    CONSTRAINT requests_booking_result_matches_status CHECK (
        action <> 'book' OR booking_id IS NULL OR status IN ('processing', 'completed')
    ),
    CONSTRAINT requests_outcome_matches_status CHECK (
        (status IN ('pending_approval', 'processing') AND outcome_code IS NULL)
        OR (
            status IN ('completed', 'rejected', 'failed')
            AND outcome_code IS NOT NULL AND btrim(outcome_code) <> ''
        )
    ),
    CONSTRAINT requests_updated_at_valid CHECK (updated_at >= created_at)
);
