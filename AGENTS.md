# Working guide

Read this, the [README](README.md) and the [team working guide](docs/team/working-guide.md)
before changing the repository. Design proposals live in
[`docs/design/`](docs/design/); the current system picture is the
[system view](docs/design/system-view.md). Do not describe planned clinic
workflows as implemented.

## Package and test conventions

- Application code is in `src/clinic_assistant/`; the ASGI entry point is
  `clinic_assistant.main:app`. Tests are in `tests/` and import the installed
  package. Research spikes stay under `experiments/` with their own environments.
- Use `uv` with the committed `uv.lock` (`uv sync --locked --group dev`); change
  `pyproject.toml` and `uv.lock` together.
- Required checks, locally and in CI: `ruff check .`, `ruff format --check .`,
  `mypy .` (strict) and `pytest --cov --cov-fail-under=80` of application code.
  Do not suppress failures, skip tests to pass, or exclude application code from
  coverage.
- PostgreSQL only, through parameterized SQL with psycopg; no ORM, SQLite or
  in-memory substitute. Schema files live in `db/init/`; database tests run on a
  real PostgreSQL (`TEST_DATABASE_URL`, provided by CI).
- Tests use the deterministic fake model adapter; no real model key is ever
  required. Keep `.env` ignored and `.env.example` free of secrets.
- Keep changes small and the code easy to read; prefer fewer lines that say
  exactly what happens.

## GitHub issue-based work

- Every task is a GitHub issue with Goal, Scope, Acceptance criteria,
  Verification and a Learning question. Work only on an issue that is Ready
  (see the working guide) and assigned to you; do not invent task IDs.
- Branches: `feature/<issue>-<member>-<short-title>`. PR titles:
  `#<issue>: <purpose>`. The PR body states ticket, purpose, testing and
  limitations, and uses `Closes #N` only when every acceptance criterion is met;
  otherwise `Refs #N`.
- One PR per issue; squash merge with the PR title as the commit title.

## Review policy

- All changes to `main` go through a pull request. One approving review from the
  lead, LaAaG21 (sole code owner), is required for teammate PRs; CI must pass and
  review conversations must be resolved. There is no second required approval
  and no ClickUp or other tracker.
- Lead-authored PRs are merged on one teammate review, as the recorded project
  decision in [docs/team/working-guide.md](docs/team/working-guide.md).
- Never approve on someone else's behalf, bypass protections or claim checks
  that did not run. AI feedback is advisory only.
