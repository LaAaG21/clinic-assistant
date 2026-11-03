# Local PostgreSQL (development)

Issue: #11. One `db` service in [`compose.yaml`](../../compose.yaml): PostgreSQL 17.6, named volume `postgres-data`, `pg_isready` health check, port bound to `127.0.0.1` only.
API packaging and seed data are separate issues.

## Schema initialisation

Plain SQL files in [`db/init/`](../../db/init/) are mounted read-only into `/docker-entrypoint-initdb.d` and run once, in name order, when the volume is first created. Files never name a schema, so tests can apply them inside a throwaway schema.

| File | Issue | Tables |
|---|---|---|
| `001_doctors_slots.sql` | #19 | `doctors`, `slots` |

An existing volume is **not** re-initialised. To add new files to it, apply them once:

```bash
docker compose exec -T db sh -c 'psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < db/init/001_doctors_slots.sql
```

(`docker compose down -v` followed by `up` also re-runs them, but deletes all local data.)

`timestamptz` stores absolute instants; requiring an explicit offset in input (#6, RFC 3339) is the API's job, because PostgreSQL accepts offset-less text using the session timezone.

### Schema tests (#19)

```bash
export TEST_DATABASE_URL=postgresql://clinic:<your-password>@127.0.0.1:5432/clinic
uv run --locked pytest tests/test_doctors_slots_schema.py -v
```

Each test creates `test_schema_<uuid>`, applies the SQL file there and drops it, so `public` data stays intact. Result (2026-11-02): 15 passed in 2.4s; full suite 79 passed, coverage 95%. A fresh volume (`docker compose -p clinic-init-check up`) logged `running /docker-entrypoint-initdb.d/001_doctors_slots.sql` and created both tables.

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
