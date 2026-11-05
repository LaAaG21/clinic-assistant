-- Bookings (#39).
-- Design: docs/design/database-diagram.md (#22). Q6: the key is booking_id; the API
-- (#6) may expose the same value as appointment_id. Booking/cancelling logic is #61.
-- No schema name is hard-coded, so tests can apply this file inside a throwaway schema.

CREATE TABLE bookings (
    booking_id text PRIMARY KEY,
    slot_id text NOT NULL REFERENCES slots (slot_id),
    conversation_id text NOT NULL REFERENCES conversations (conversation_id),
    status text NOT NULL DEFAULT 'booked',
    created_at timestamptz NOT NULL DEFAULT now(),
    cancelled_at timestamptz,
    CONSTRAINT bookings_id_not_blank CHECK (btrim(booking_id) <> ''),
    CONSTRAINT bookings_status_valid CHECK (status IN ('booked', 'cancelled')),
    -- cancelled_at is set exactly when the booking is cancelled.
    CONSTRAINT bookings_cancelled_at_matches_status
        CHECK ((status = 'cancelled') = (cancelled_at IS NOT NULL))
);

-- At most one active booking per slot, enforced by PostgreSQL even when requests
-- race. Cancelled rows are ignored, so a cancelled slot can be booked again.
CREATE UNIQUE INDEX bookings_one_active_per_slot
    ON bookings (slot_id)
    WHERE status = 'booked';
