# Quality checks (#13)

`quality.yml` runs on every PR targeting `main` (including docs-only changes),
pushes to `main`, and manual dispatch. It uses the committed uv lockfile, uv
0.12.23, and a health-checked PostgreSQL 17.6 service with the shared #11 variables.
No model API key or health endpoint is required; branch protection is unchanged.

The **Quality checks** job runs Ruff lint/format, strict Mypy, and Pytest.
Shared `pyproject.toml` settings measure `clinic_assistant`; coverage below 80%
fails the job. Command failures are not ignored.

After `uv sync --locked --group dev`, run locally from the repository root:

```sh
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy .
uv run --locked pytest --cov --cov-config=pyproject.toml --cov-report=term-missing --cov-fail-under=80
```

Verified run links (full narrative is in PR #17):

- [Foundation success](https://github.com/LaAaG21/clinic-assistant/actions/runs/41442384018): 1 startup/OpenAPI test, 100% of 2 application statements.
- [Docs-only success](https://github.com/LaAaG21/clinic-assistant/actions/runs/41443465247).
- Failures: [lint](https://github.com/LaAaG21/clinic-assistant/actions/runs/41442743836), [format](https://github.com/LaAaG21/clinic-assistant/actions/runs/41442818823), [typing](https://github.com/LaAaG21/clinic-assistant/actions/runs/41442900403), [test](https://github.com/LaAaG21/clinic-assistant/actions/runs/41442996220), [coverage](https://github.com/LaAaG21/clinic-assistant/actions/runs/41443097436).

Deliberate faults were isolated in closed, unmerged PR #32. Those historical
runs used uv 0.13.6 and the earlier workflow. #13 remains open until #12's real
database-helper tests run in CI; PostgreSQL service health alone is insufficient.
