# Clinic Front-Desk Assistant

A team project to build an AI-powered REST API for a clinic's front desk.
The assistant must not provide diagnoses or treatment recommendations.

**Tech stack:** Python 3.12, FastAPI, OpenAI SDK, PostgreSQL 17, psycopg 3 (plain
SQL, no ORM), Docker Compose, and uv. LangGraph is planned for the conversation
workflow but is not a dependency yet.

## Project status

In development. This section describes what the code on `main` does today.

**Working now**

- The FastAPI app serves OpenAPI (`/openapi.json`) and Swagger UI (`/docs`).
- `GET /health` is the only HTTP route. It reports whether PostgreSQL is
  reachable. See [API and database health](docs/development/health.md).
- Shared JSON error responses are registered on the app. See
  [shared API errors](docs/development/api-errors.md).
- Local PostgreSQL runs through Compose. Schema files create the `doctors`,
  `slots`, `conversations` and `bookings` tables. See
  [local PostgreSQL](docs/development/database.md).
- Library code that has tests but no HTTP route yet: settings, the database
  helper, patient-message models, the clinic document loader, passages and
  retrieval, the model adapters (fake and OpenAI), intent classification,
  clarification, and the same-day booking policy.

**Planned, not implemented**

- Conversation and message endpoints. `POST /conversations/...` does not exist yet.
- Answering questions from clinic documents, with citations, over HTTP.
- Finding and booking appointments through the API.
- Staff approval for cancellations and same-day bookings.
- Conversations and pending approvals that survive a restart (LangGraph checkpoints).
- An end-to-end emergency response that flags messages for staff.
- A Docker image for the API, plus deployment and rollback docs (#59).

The [service boundaries and API proposal](docs/design/service-boundaries-and-api.md)
describes the planned routes. It is still a proposal: if a route is not listed
under **Working now**, it does not exist yet.

## Local development

Run every command from the repository root. The PowerShell and Bash versions do
the same thing.

### 1. Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/). CI pins 0.12.23.
  uv uses Python 3.12 from `.python-version` and downloads it if needed.
- [Docker](https://docs.docker.com/get-docker/) with Compose v2. You need it for
  PostgreSQL. The API itself runs on your machine, not in a container.

### 2. Install locked dependencies

```sh
uv sync --locked --group dev
```

This installs the `clinic_assistant` package and the exact versions from
`uv.lock` into `.venv`. `--locked` fails if `uv.lock` does not match
`pyproject.toml`; it does not quietly re-resolve.

### 3. Configure the environment

```sh
cp .env.example .env
```

Edit `.env` and replace `change-me` **in both places** (`POSTGRES_PASSWORD` and
`DATABASE_URL`) with your own local password. Use only letters, digits, `-` and
`_`. If port 5432 is taken, change `POSTGRES_PORT` and the port in `DATABASE_URL`
together. Keep the host as `127.0.0.1`: Compose publishes the port on IPv4 only.
Never commit `.env`.

**How variables are loaded:**

- Docker Compose reads `.env` automatically.
- Python does **not**. The app, its tests and `clinic_assistant.settings` read
  only the process environment, so export the variables into your shell
  (step 5) before you start the API or run the database tests.

`MODEL_BACKEND=fake` needs no OpenAI key. For every variable and its validation
rules, see [shared application settings](docs/development/settings.md).

### 4. Start PostgreSQL

```sh
docker compose config -q
docker compose up -d --wait db
docker compose ps
```

`ps` should show `db` as `(healthy)`. When the data volume is first created,
the files in `db/init/` run in name order. Later schema files must be applied by
hand; see [local PostgreSQL](docs/development/database.md). To stop the database,
run `docker compose down`. **`down -v` deletes all local data.**

### 5. Export variables into your shell

PowerShell:

```powershell
Get-Content .env | Where-Object { $_ -match '^\s*[^#\s][^=]*=' } | ForEach-Object {
    $name, $value = $_ -split '=', 2
    Set-Item -Path "Env:$($name.Trim())" -Value $value.Trim()
}
$env:TEST_DATABASE_URL = $env:DATABASE_URL
```

Bash (including Git Bash):

```sh
set -a; . ./.env; set +a
export TEST_DATABASE_URL="$DATABASE_URL"
```

The variables last only for that terminal session. `TEST_DATABASE_URL` is what
enables the real-PostgreSQL tests. Point it at a local database you can safely
modify: tests create and drop uniquely named schemas and test-only tables in it.

### 6. Start the API

```sh
uv run --locked uvicorn clinic_assistant.main:app --host 127.0.0.1 --port 8000
```

- [Swagger UI](http://127.0.0.1:8000/docs) and
  [OpenAPI JSON](http://127.0.0.1:8000/openapi.json) work without a database,
  `.env` or model key.
- `curl http://127.0.0.1:8000/health` returns HTTP 200
  `{"status":"ok","api":"reachable","database":"reachable"}` when the database
  is reachable. It returns HTTP 503 with `"database":"unreachable"` when the
  database is down or `DATABASE_URL` is missing from the shell.
- `/` returns 404. No other routes exist yet.

Stop the server with Ctrl+C. Use another port if 8000 is taken. Restart the
server after changing environment variables.

### 7. Run the quality checks

These are the same commands as the CI workflow
([`.github/workflows/quality.yml`](.github/workflows/quality.yml), described in
[its README](.github/workflows/README.md)):

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy .
uv run --locked pytest --cov --cov-config=pyproject.toml --cov-report=term-missing --cov-fail-under=80
```

Coverage measures only `clinic_assistant`, including branches; the minimum is
80%. No model API key is needed. CI provides an ephemeral PostgreSQL 17.6
service and sets both `DATABASE_URL` and `TEST_DATABASE_URL`.

**Without the database variables**, schema, database-helper and retrieval tests
are **skipped**, and `tests/test_health.py::test_health_with_real_postgresql`
**fails** on purpose, so that a missing database is never reported as a passing
health check. A full local pass needs steps 4 and 5.

### Verification record (#47)

On November 5, 2026, this guide was followed from a fresh clone of `main`
(`7075cc2`) on Windows 11 with uv 0.12.23, Python 3.12.15, Docker 29.9.1,
Compose v5.6.0 and PostgreSQL 17.6. The clone used a throwaway Compose project
on a non-default port, removed afterwards with `down -v`.

| Step | Result |
| --- | --- |
| `uv sync --locked --group dev` | Passed. Installed FastAPI 0.162.0, psycopg 3.3.6, Pydantic 2.14.2, Uvicorn 0.54.0. |
| `docker compose config -q`, `up -d --wait db` | Passed; `db` reported healthy. |
| Pytest with no database variables | 247 passed, 48 skipped, 1 failed (`test_health_with_real_postgresql`, as described above). |
| Ruff lint, Ruff format, Mypy (strict) | All passed. |
| Full pytest with coverage, variables exported (Bash) | 296 passed, 0 skipped; 98.27% coverage. |
| `tests/test_health.py` and `tests/test_database.py`, variables exported (PowerShell) | 12 passed. |
| `get_settings()` with the exported `.env` | Loaded and validated (`fake` backend). |
| Uvicorn, variables not exported | `/openapi.json` 200, `/docs` 200, `/health` 503, `/` 404. Only `/health` appears in OpenAPI. |
| Uvicorn, variables exported | `/health` 200, `database: reachable`. |

**Not verified:** the real OpenAI backend (no key was used), macOS and Linux
shells other than Git Bash, and GitHub CI for this change (check it on the PR).

## Package conventions

- Application code lives in `src/clinic_assistant/`. The ASGI entry point is
  `clinic_assistant.main:app`. uv installs the package, so tests need no
  `PYTHONPATH` changes or path tricks.
- Application tests live in `tests/` and import the installed package. The
  `schema_db` fixture in `tests/conftest.py` applies `db/init/*.sql` inside a
  throwaway schema.
- `pyproject.toml` owns the shared dependencies and check settings. `uv.lock`
  records exact resolved versions. When you change dependencies on purpose,
  update both files with uv and commit them together.
- Schema changes are new numbered plain-SQL files in `db/init/`; see
  [local PostgreSQL](docs/development/database.md) for the agreed order.
- Workflow policy stays outside API handlers, as described in the
  [service boundaries proposal](docs/design/service-boundaries-and-api.md).
- Standalone research projects in `experiments/` keep their own environments and
  verification commands. The root checks exclude them.

## Developer guides

Each guide records its own verification results.

| Area | Guide |
| --- | --- |
| Settings and environment variables | [settings.md](docs/development/settings.md) |
| Local PostgreSQL, schema files, persistence | [database.md](docs/development/database.md) |
| Database helper and connectivity probe | [database-access.md](docs/database-access.md) |
| Health endpoint | [health.md](docs/development/health.md) |
| Shared API errors | [api-errors.md](docs/development/api-errors.md) |
| Patient-message models | [patient-message-models.md](docs/development/patient-message-models.md) |
| Clinic document loader | [clinic-document-loader.md](docs/development/clinic-document-loader.md) |
| Traceable clinic passages | [clinic-passages.md](docs/development/clinic-passages.md) |
| Passage retrieval | [passage-retrieval.md](docs/development/passage-retrieval.md) |
| Shared model adapter | [model-adapter.md](docs/development/model-adapter.md) |
| Real OpenAI adapter | [openai-model-adapter.md](docs/development/openai-model-adapter.md) |
| Intent classification | [intent-classification.md](docs/development/intent-classification.md) |
| Clarification | [clarification.md](docs/development/clarification.md) |
| Same-day booking policy | [same-day-booking.md](docs/development/same-day-booking.md) |
| Database diagram | [database-diagram.md](docs/design/database-diagram.md) |
| Architecture decisions | [docs/adr](docs/adr/README.md) |

## Research and experiments

- [Clinic-document retrieval comparison](docs/research/clinic-document-retrieval.md)
- [R1: PostgreSQL checkpoint persistence](docs/research/r1-postgres-checkpoints.md)
- [Issue #4: staff approval interrupt/resume](docs/research/004-staff-interrupt-resume.md),
  with its [standalone experiment](experiments/staff_approval/README.md)
