-- Synthetic doctor and slot seed data (#29). Development and demonstration only.
-- Docs: docs/development/seed-data.md. Schema: 001_doctors_slots.sql (#19).
--
-- Numbered 900 so it runs after every schema file on a fresh volume. Seeds only
-- doctors and slots: no bookings, approvals, conversations, documents or messages.
-- No schema name is hard-coded, so tests can apply this file inside a throwaway schema.
--
-- Configuration (session settings, e.g. from PGOPTIONS in compose.yaml):
--   clinic.seed_timezone   required IANA timezone; slot wall-clock times use it.
--   clinic.seed_base_date  optional YYYY-MM-DD; empty means today in that timezone.
--
-- Safe to load repeatedly: rows are only inserted, never updated or deleted.
-- IDs are derived from the inputs, so the same input yields the same rows, and
-- ON CONFLICT DO NOTHING skips any row that already exists (by ID or by
-- doctor and start time). Everything runs in one DO block, so a failed load
-- inserts nothing.

DO $seed$
DECLARE
    clinic_timezone text := nullif(btrim(current_setting('clinic.seed_timezone', true)), '');
    base_date_text text := nullif(btrim(current_setting('clinic.seed_base_date', true)), '');
    base_date date;
BEGIN
    IF clinic_timezone IS NULL THEN
        RAISE EXCEPTION 'clinic.seed_timezone is required (an IANA timezone name)';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_timezone_names WHERE name = clinic_timezone) THEN
        RAISE EXCEPTION 'clinic.seed_timezone must be an available IANA timezone';
    END IF;

    IF base_date_text IS NULL THEN
        base_date := (now() AT TIME ZONE clinic_timezone)::date;
    ELSE
        IF base_date_text !~ '^\d{4}-\d{2}-\d{2}$' THEN
            RAISE EXCEPTION 'clinic.seed_base_date must be a YYYY-MM-DD date';
        END IF;
        BEGIN
            base_date := base_date_text::date;
        EXCEPTION
            WHEN datetime_field_overflow OR invalid_datetime_format THEN
                RAISE EXCEPTION 'clinic.seed_base_date must be a YYYY-MM-DD date';
        END;
    END IF;

    -- Synthetic names only; no real people.
    INSERT INTO doctors (doctor_id, full_name, specialty)
    VALUES
        ('doctor_seed_gp', 'Dr. Amal Synthetic', 'general practice'),
        ('doctor_seed_derm', 'Dr. Badr Synthetic', 'dermatology'),
        ('doctor_seed_peds', 'Dr. Huda Synthetic', 'pediatrics')
    ON CONFLICT DO NOTHING;

    -- 3 days from the base date x 4 consecutive 30-minute slots per doctor,
    -- in clinic wall-clock time, converted to absolute instants.
    INSERT INTO slots (slot_id, doctor_id, starts_at, ends_at)
    SELECT
        'slot_seed_' || schedule.doctor_key || '_'
            || to_char(local_start, 'YYYYMMDD"T"HH24MI'),
        'doctor_seed_' || schedule.doctor_key,
        local_start AT TIME ZONE clinic_timezone,
        (local_start + interval '30 minutes') AT TIME ZONE clinic_timezone
    FROM (
        VALUES
            ('gp', time '09:00'),
            ('derm', time '10:00'),
            ('peds', time '14:00')
    ) AS schedule (doctor_key, first_start)
    CROSS JOIN generate_series(0, 2) AS day_offset
    CROSS JOIN generate_series(0, 3) AS slot_index
    CROSS JOIN LATERAL (
        SELECT (base_date + day_offset) + schedule.first_start
            + slot_index * interval '30 minutes' AS local_start
    ) AS computed
    ORDER BY 2, 3
    ON CONFLICT DO NOTHING;
END
$seed$;
