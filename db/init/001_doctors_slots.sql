-- Doctors and appointment slots (#19).
-- Design: docs/design/database-diagram.md (#22). Bookings live in a later file (#39).
-- No schema name is hard-coded, so tests can apply this file inside a throwaway schema.

CREATE TABLE doctors (
    doctor_id text PRIMARY KEY,
    full_name text NOT NULL,
    specialty text NOT NULL,
    CONSTRAINT doctors_id_not_blank CHECK (btrim(doctor_id) <> ''),
    CONSTRAINT doctors_full_name_not_blank CHECK (btrim(full_name) <> ''),
    CONSTRAINT doctors_specialty_not_blank CHECK (btrim(specialty) <> '')
);

CREATE TABLE slots (
    slot_id text PRIMARY KEY,
    doctor_id text NOT NULL REFERENCES doctors (doctor_id),
    starts_at timestamptz NOT NULL,
    ends_at timestamptz NOT NULL,
    CONSTRAINT slots_id_not_blank CHECK (btrim(slot_id) <> ''),
    CONSTRAINT slots_starts_before_ends CHECK (starts_at < ends_at),
    -- Also serves as the index for "slots of one doctor ordered by time".
    CONSTRAINT slots_doctor_start_unique UNIQUE (doctor_id, starts_at)
);
