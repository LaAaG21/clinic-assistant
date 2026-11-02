# Clinic Front-Desk Assistant

A team project to build an AI-powered REST API for a clinic's front desk.

## Current foundation

This repository provides a small, tested FastAPI foundation, a PostgreSQL
development service, and repeatable quality checks. It is not the complete clinic
assistant and is not ready for production use.

- `GET /health`: process liveness.
- `GET /ready`: database readiness using psycopg and a real PostgreSQL connection.
- `POST /draft`: an injectable model-adapter boundary, returning `503` until a
  real adapter is implemented. Tests inject a deterministic fake LLM; no model
  API key is needed. This endpoint does not implement a clinic workflow.
- Interactive API documentation: <http://localhost:8000/docs> when running.

## Local setup

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Docker
with Compose. The project uses Python 3.12, pinned in `.python-version`, and
commits `uv.lock`. In PowerShell, from the repository root:

```powershell
uv python install 3.12
uv sync --locked
Copy-Item .env.example .env
docker compose config --quiet
docker compose up -d --wait db
uv run --env-file .env uvicorn clinic_assistant.api:app --reload
```

On Linux/macOS, use `cp .env.example .env` for the copy step. Preserve an existing
`.env` rather than overwriting it. The example contains local development values
only. Keep passwords URL-safe when using the example connection strings; if
changing the database credentials or port, update both host-side URLs in `.env`.
PostgreSQL initializes its credentials only when its data volume is first created.

To build and run the entire foundation from source instead of running uvicorn on
the host:

```sh
docker compose up --build -d --wait
docker compose ps
docker compose logs api
docker compose down
```

Stop host uvicorn before starting the containerized API on the same port.
Both services publish ports only on localhost. PostgreSQL data remains in the
named `postgres_data` volume when `docker compose down` stops the services.
The API container has a readiness health check and waits for healthy PostgreSQL.
No application image is published to a registry.

## Checks

Start the database with `docker compose up -d --wait db`, then run:

```sh
uv sync --locked
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy src tests
uv run --locked --env-file .env pytest
```

Pytest enforces at least 80% coverage of the entire application source, including
branches. Database integration tests require `TEST_DATABASE_URL`; missing
configuration fails the tests instead of silently skipping them. They connect
to PostgreSQL, not an in-memory substitute. Model tests inject a deterministic
fake and never call a model provider.

CI runs these checks on every pull request targeting `main`, including
documentation-only changes, and on pushes to `main`. CI supplies a PostgreSQL
service container and installs the committed dependency lockfile. AI review is
advisory and separate from these checks; see [repository policy](docs/repository-policy.md)
for its configuration and bootstrap limitations.

## Collaboration

Read [CONTRIBUTING.md](CONTRIBUTING.md) before changing the repository.
Changes to `main` go through a PR, must pass required CI, and use squash merging.
The intended approval gate is one human approval from lead **@LaAaG21**, the sole
code owner. Another teammate's approval cannot substitute for the lead's approval
once ownership is effective on `main`. Eligible collaborators may merge after all
requirements are satisfied; approval authority is separate from merge permissions.

The lead explicitly chose one lead approval instead of the challenge's original
two approvals. This is a project-owner decision and deviation, not a trainer-approved
exception. CODEOWNERS is read from the PR's base branch, so the setup branch's new
file does not enforce lead ownership until it reaches `main`.

Initial repository setup uses `chore/repository-setup`, without a ticket or member
ID: **Initial repository setup — task tracking begins afterward.** Future
development uses `feature/<ticket-id>-<member-id>-<short-title>` and PR titles
beginning with the ticket ID after tasks exist.

GitHub forbids PR authors from approving their own PRs. A lead-authored PR,
including this setup when opened through @LaAaG21, remains blocked pending a
separate handling decision. No substitute approval, automatic approval, or bypass
is authorized. See [repository policy](docs/repository-policy.md).

## Planned product work

- Answer clinic questions using clinic documents and cite the sources.
- Find available appointments and book them without double booking.
- Require staff approval for cancellations and same-day bookings.
- Preserve conversations and pending approvals after a restart.
- Respond immediately to emergency messages and flag them for staff.

The assistant must not provide diagnoses or treatment recommendations.

The foundation uses Python, FastAPI, PostgreSQL, psycopg, and Docker Compose.
LangGraph, an OpenAI SDK adapter, application schemas, migrations, and clinical
documents remain future work. Database access must use plain, parameterized SQL
through psycopg, without an ORM or SQLite.

Release automation, versioned releases, production deployment, authentication,
backup/restore procedures, and rollback procedures are not implemented. They
require later tasks; the Compose setup above is for local development.
