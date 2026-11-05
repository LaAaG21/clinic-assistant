# Local PostgreSQL (development)

Issue: #11. One `db` service in [`compose.yaml`](../../compose.yaml): PostgreSQL 17.6, named volume `postgres-data`, `pg_isready` health check, port bound to `127.0.0.1` only.
API packaging and seed data are separate issues.

## Schema initialisation

Plain SQL files in [`db/init/`](../../db/init/) are mounted read-only into `/docker-entrypoint-initdb.d` and run once, in name order, when the volume is first created. Files never name a schema, so tests can apply them inside a throwaway schema.

| File | Issue | Tables |
|---|---|---|
| `001_doctors_slots.sql` | #19 | `doctors`, `slots` |
| `002_conversations.sql` | #26 (first portion) | `conversations` |
| `003_bookings.sql` | #39 | `bookings` + partial unique index `bookings_one_active_per_slot` |
| `900_seed_doctors_slots.sql` | #29 | synthetic `doctors`/`slots` rows; see [seed data](seed-data.md) |

Seed files are numbered `9xx` so they run after every schema file.

Agreed order (#52): doctors/slots → conversations → bookings (#39) → requests (#52) → messages (#26, second portion) → approvals (#40). Each file may only reference tables created by earlier files.

An existing volume is **not** re-initialised. To add a new file to it, apply that file once:

```bash
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/init/003_bookings.sql
```

(`docker compose down -v` followed by `up` also re-runs them, but deletes all local data.)

`timestamptz` stores absolute instants; requiring an explicit offset in input (#6, RFC 3339) is the API's job, because PostgreSQL accepts offset-less text using the session timezone.

### Schema tests

```bash
export TEST_DATABASE_URL=postgresql://clinic:<your-password>@127.0.0.1:5432/clinic
uv run --locked pytest tests/test_doctors_slots_schema.py tests/test_conversations_schema.py tests/test_bookings_schema.py -v
```

The shared `schema_db` fixture in `tests/conftest.py` creates `test_schema_<uuid>`, applies every `db/init/*.sql` schema file there in name order (as on a fresh volume, skipping `*_seed_*.sql` files) and drops it, so `public` data stays intact.

| Date | Result |
|---|---|
| 2026-11-02 (#19) | doctors/slots 15 passed in 2.4s; full suite 79 passed, coverage 95% |
| 2026-11-03 (#26) | conversations 6 passed, doctors/slots 15 passed; full suite 98 passed, coverage 96% |
| 2026-11-03 (#39) | bookings 14 passed (4 runs in a row), including a two-connection race for one slot; full suite 234 passed |

A fresh volume (`POSTGRES_PORT=55432 docker compose -p clinic-init-check up -d --wait db`) ran `001`, `002` and `003` in order and created `bookings`, `conversations`, `doctors`, `slots` plus `bookings_one_active_per_slot`; the throwaway project was then removed with `docker compose -p clinic-init-check down -v`.

### Why PostgreSQL, not Python, rejects a second active booking

A Python "is this slot free?" check followed by an insert lets two concurrent requests both read "free" and both insert. The partial unique index is checked inside PostgreSQL: the second transaction waits for the first, then fails with `UniqueViolation` on `bookings_one_active_per_slot` once the first commits. `test_concurrent_bookings_for_one_slot_have_one_winner` shows this with two real connections.

## Setup

```bash
cp .env.example .env    # then replace change-me (in both places) with your own password
docker compose config -q
docker compose up -d --wait
docker compose ps       # db should show (healthy)
```

Without `POSTGRES_PASSWORD`, Compose stops with: `Set POSTGRES_PASSWORD in .env (copy .env.example)`.

## Variables

| Variable | Default in `.env.example` | Used by |
|---|---|---|
| `POSTGRES_DB` | `clinic` | postgres image, health check |
| `POSTGRES_USER` | `clinic` | postgres image, health check |
| `POSTGRES_PASSWORD` | placeholder `change-me`, required | postgres image |
| `POSTGRES_PORT` | `5432` | host port (127.0.0.1 only) |
| `CLINIC_TIMEZONE` | `Asia/Dubai` (example) | required by Compose; seed slot times ([seed data](seed-data.md)) and app settings |
| `SEED_BASE_DATE` | empty (today in clinic timezone) | first day of seed slots ([seed data](seed-data.md)) |
| `DATABASE_URL` | `postgresql://clinic:change-me@127.0.0.1:5432/clinic` | application code and tests on your machine (#12) |

Use `127.0.0.1`, not `localhost`: the port is bound to IPv4 only, and `localhost` may try IPv6 first and wait for the connect timeout. Code running inside Compose later should reach the database at host `db`.

## Check connectivity

```bash
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "select current_user, current_database()"'
```

## Persistence check (repeatable)

```bash
# 1. write synthetic probe data
docker compose exec -T db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<'SQL'
CREATE TABLE persistence_probe (id int PRIMARY KEY, note text NOT NULL);
INSERT INTO persistence_probe VALUES (1, 'synthetic probe for #11');
SQL

# 2. recreate the container, keeping the volume (never add -v here)
docker compose up -d --force-recreate --wait
docker compose down && docker compose up -d --wait

# 3. data is still there
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT * FROM persistence_probe"'

# 4. clean up the probe data only
docker compose exec db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "DROP TABLE persistence_probe"'
```

### Result (2026-11-02, Docker 29.9.1, Compose v5.6.0)

| Step | Container ID | `persistence_probe` |
|---|---|---|
| Probe written | `31088be812e8` | `1 \| synthetic probe for #11` |
| `up --force-recreate` | `2d8a4df091e3` (new) | row present |
| `down` + `up` | `dc4d0f1718ff` (new) | row present |
| `DROP TABLE` | `dc4d0f1718ff` | table gone; volume `clinic-assistant_postgres-data` kept; db healthy |

Host connection with psycopg and `DATABASE_URL` (`connect_timeout=5`) returned `('clinic', 'clinic', 5432)`.

## Why the data survives

The container is disposable; the database files live in the named volume `postgres-data`, which Docker manages separately. A recreated container mounts the same volume and finds the same files. Only `docker compose down -v` or `docker volume rm` deletes it, and that wipes the local database.
