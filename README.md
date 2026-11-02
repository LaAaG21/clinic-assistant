# Clinic Front-Desk Assistant

A team project to build an AI-powered REST API for a clinic's front desk.

## Planned Features

- Answer clinic questions using clinic documents and cite the sources.
- Find available appointments and book them without double booking.
- Require staff approval for cancellations and same-day bookings.
- Preserve conversations and pending approvals after a restart.
- Respond immediately to emergency messages and flag them for staff.

The assistant must not provide diagnoses or treatment recommendations.

## Tech Stack

Python, FastAPI, LangGraph, OpenAI SDK, PostgreSQL, psycopg, and Docker Compose.

Database access uses plain SQL without an ORM.

## Status

In development.

## Standalone experiments

Install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run
these commands from the repository root:

```sh
uv sync --locked --group dev
uv run --locked uvicorn clinic_assistant.main:app --host 127.0.0.1 --port 8000
```

uv uses Python 3.12 from `.python-version` and installs the application plus the
locked dependencies into `.venv`. It can download Python if it is not installed.
This foundation starts without a database, `.env`, or model API key.

Open [Swagger UI](http://127.0.0.1:8000/docs) or
[OpenAPI JSON](http://127.0.0.1:8000/openapi.json). No business routes are registered
yet, so the schema has an empty `paths` object and `/` returns `404`. Stop the
server with Ctrl+C. Use another port if 8000 is occupied.

## Package conventions

- Application code lives in `src/clinic_assistant/`; the ASGI entry point is
  `clinic_assistant.main:app`. uv installs this package, so tests do not need
  `PYTHONPATH` changes or path manipulation.
- Application tests live in `tests/` and import the installed package.
- `pyproject.toml` owns the shared dependencies and check settings. `uv.lock`
  records exact resolved versions; `--locked` rejects an outdated lockfile.
  When intentionally changing dependencies, update both files with uv and commit
  them together.
- Standalone research projects in `experiments/` retain their own environments
  and verification commands. Root application checks exclude those projects.

The [service boundaries and API proposal](docs/design/service-boundaries-and-api.md)
from #6 guides future routes and keeps workflow policy outside API handlers.
This foundation establishes package/tool conventions only; it does not finalize
the research-dependent decisions that remain open in that proposal.

## Clinic documents

The [clinic document loader](docs/development/clinic-document-loader.md) reads
complete UTF-8 Markdown files and preserves original filenames for later citations.

## Quality checks

After the locked sync, run:

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy .
uv run --locked pytest --cov --cov-config=pyproject.toml --cov-report=term-missing --cov-fail-under=80
```

These commands match the proposed #13 CI workflow. Coverage measures only
`clinic_assistant`, including branches, with an 80% minimum. The foundation test
runs the ASGI lifecycle, fetches `/openapi.json`, validates it against the OpenAPI
specification, checks package/API version consistency, and checks the Swagger
page's schema link. It requires no real model key or external service.

Verified for #10 on November 2, 2026, using Windows, Python 3.12.15, and uv
0.12.23: a fresh local clone installed successfully with the committed lockfile;
all four commands above passed. Pytest ran one startup/OpenAPI test with 100%
coverage of the current two executable application statements. This measures the
foundation only, not the planned clinic features. The documented Uvicorn command
also served `/openapi.json` and `/docs` successfully on a free localhost port,
without a model key or database URL. GitHub CI execution belongs to #13.

## Research

- [Clinic-document retrieval comparison](docs/research/clinic-document-retrieval.md)
- [Issue #4: staff approval interrupt/resume](experiments/staff_approval/README.md)
- [Research note and proposed recommendation](docs/research/004-staff-interrupt-resume.md)
