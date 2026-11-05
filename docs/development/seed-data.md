# Synthetic doctor and slot seed data

Issue: #29. File: [`db/init/900_seed_doctors_slots.sql`](../../db/init/900_seed_doctors_slots.sql).
Schema: `doctors` and `slots` from #19 ([database diagram](../design/database-diagram.md)).

A small, repeatable, synthetic dataset for development and demonstrations. It seeds
**only** doctors and appointment slots: no bookings, approvals, conversations, clinic
documents or sample messages. All names are invented.

| Doctor ID | Name | Specialty | Daily slots (clinic time) |
|---|---|---|---|
| `doctor_seed_gp` | Dr. Amal Synthetic | general practice | 09:00–11:00 |
| `doctor_seed_derm` | Dr. Badr Synthetic | dermatology | 10:00–12:00 |
| `doctor_seed_peds` | Dr. Huda Synthetic | pediatrics | 14:00–16:00 |

Each doctor gets four consecutive 30-minute slots on each of three days, starting at
the base date: 3 doctors, 36 slots. Slot IDs encode the doctor and local start, e.g.
`slot_seed_gp_20261110T0900`. Days are consecutive; no weekend or holiday rules are
applied because none have been agreed yet.

## Configuration

The file reads two PostgreSQL session settings. `compose.yaml` sets them for the
`db` container through `PGOPTIONS`, from `.env`:

| `.env` variable | Setting | Rule |
|---|---|---|
| `CLINIC_TIMEZONE` | `clinic.seed_timezone` | Required IANA timezone. Slot wall-clock times are in this zone and stored as absolute `timestamptz` instants (#6, #20). No machine-timezone default. |
| `SEED_BASE_DATE` | `clinic.seed_base_date` | Optional `YYYY-MM-DD`. Empty means today in the clinic timezone, so a new volume always has current availability. Set a fixed date for reproducible checks. |

A missing or unknown timezone, or a base date that is not a valid `YYYY-MM-DD`, stops
the load with a clear error and inserts nothing (the whole load is one `DO` block).

## Loading

**Automatically:** the file sits in `db/init/` and is numbered `900`, so the postgres
image runs it after every schema file when the volume is first created (#11, #22
order). `docker compose up -d --wait` on a fresh clone is enough.

**Again, on an existing volume** (e.g. to add days for a new base date):

```bash
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/init/900_seed_doctors_slots.sql
```

To override the base date for one run only, pass a different `PGOPTIONS`:

```bash
docker compose exec -T -e PGOPTIONS="-c clinic.seed_timezone=Asia/Dubai -c clinic.seed_base_date=2026-11-10" db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/init/900_seed_doctors_slots.sql
```

(`Asia/Dubai` is an example, as in `.env.example`, not a clinic-policy decision.)

## Why repeated loading is safe

The seed only ever runs `INSERT ... ON CONFLICT DO NOTHING`. It never updates,
truncates or deletes.

- **No duplicates:** IDs are derived from the inputs, so the same base date and
  timezone produce the same rows; the primary keys and the
  `UNIQUE (doctor_id, starts_at)` constraint make the second insert a no-op. A
  different base date only adds slots for days not already present.
- **No deletion of someone else's data:** rows the seed did not create, and seed rows
  someone has since edited, are left as they are. If a slot already exists for a seed
  doctor at the same start time (under any ID), the seed skips it.

## Tests

```bash
export TEST_DATABASE_URL=postgresql://clinic:<your-password>@127.0.0.1:5432/clinic
uv run --locked pytest tests/test_seed_doctors_slots.py -v
```

`schema_db` (`tests/conftest.py`) skips `*_seed_*.sql` files, so schema tests keep
starting from empty tables; the seed tests load the file explicitly in their own
throwaway schema. They check counts, that every slot references an existing doctor,
30-minute slots at the expected clinic wall-clock times from a fixed base date,
stable rows after loading the same input twice, preservation of an unrelated
synthetic doctor and slot, the today default, and rejection of bad configuration.

## Verification

2026-11-05, PostgreSQL 17.6, Docker 29.9.1:

- `tests/test_seed_doctors_slots.py` plus the doctors/slots, conversations and
  bookings schema tests: 47 passed against a disposable container. Full suite:
  308 passed, coverage 98%; `ruff check`, `ruff format --check` and `mypy` clean.
- Fresh Compose volume in a throwaway project
  (`POSTGRES_PORT=55434 CLINIC_TIMEZONE=Asia/Dubai SEED_BASE_DATE=2026-11-10 docker compose -p clinic-seed-check up -d --wait db`):
  3 doctors, 36 slots, 0 slots without a doctor; first slot
  `slot_seed_gp_20261110T0900` at `2026-11-10 09:00` Asia/Dubai. After inserting an
  unrelated synthetic doctor and slot and loading the seed file twice more: 4 doctors,
  37 slots, unrelated slot still present. Removed with
  `docker compose -p clinic-seed-check down -v`.
