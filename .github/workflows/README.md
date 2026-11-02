# Quality checks (#13)

`quality.yml` runs on all pull requests targeting `main`, including documentation
changes, on pushes to `main`, and on manual dispatch. It does not change branch
protection. The single check is named **Quality checks**, with separately named
Ruff lint, Ruff format, Mypy, and Pytest/coverage steps. Any nonzero command exit
fails the job; there are no ignored failures or successful fallback commands.

## Integration requirements

The workflow now runs against merged #10/#11. Final acceptance of #13 still
requires #12's database-helper implementation and tests:

- Merged #10 supplies the root `pyproject.toml`, committed `uv.lock`, application package,
  development dependency group (Ruff, Mypy, Pytest, pytest-cov), and meaningful
  application startup/OpenAPI tests. Shared Ruff/Mypy/Pytest settings must target
  the application and its tests rather than standalone research environments.
- Shared `[tool.coverage.run]` configuration must set `source` or `source_pkgs` to
  the actual application. CI refuses an absent source or a scope consisting of
  the repository, tests, or experiments. `--cov-fail-under=80` is explicit; no
  exclusions are added here to improve coverage artificially.
- Merged #11 / PR #16 supplies PostgreSQL 17.6 and `POSTGRES_DB`, `POSTGRES_USER`,
  `POSTGRES_PASSWORD`, `POSTGRES_PORT`, and `DATABASE_URL`. CI uses the same names,
  with a health-checked ephemeral service on localhost and a public CI-only
  password. It does not load a developer `.env` or touch persistent local data.
- #12 supplies meaningful real-PostgreSQL helper/probe tests using that connection
  configuration. Include successful connectivity, cleanup/failure handling, and
  a bounded unavailable-database case. Do not skip these tests in CI.

No model API key is supplied and no health endpoint is invoked. Neither #14 nor
the standalone research tests substitute for the required application tests.

## Verification record

Prepared from `origin/main` at `2f6452c`, then integrated with main at `82a09bb`
(merged #10 and #11) on 2026-11-02. The shared tool configuration excludes research
experiments, Mypy checks `src`/`tests`, and coverage targets `clinic_assistant`.

- `actionlint` v1.7.12: passed against `quality.yml`.
- `git diff --check`: passed.
- Successful foundation application workflow run: **passed**, linked below.
- Measured application coverage: **100% of the current two statements**.
- Lint/format/type/test/coverage failure propagation: **verified**, table below.

First real run: [41437693661](https://github.com/LaAaG21/clinic-assistant/actions/runs/41437693661),
commit `6332a44`, draft PR #17. Check **Quality checks**: **failed**.
PostgreSQL container initialization, checkout, and uv installation succeeded.
**Install locked project and development tools** failed against the current
dependency-incomplete tree at that time. Ruff lint, Ruff format, Mypy, coverage-scope validation,
and Pytest/coverage were skipped as a consequence, not passed. This demonstrates
that installation failure fails the workflow, but does not establish successful
application behavior or lint/format/type/test/coverage failure propagation.

Successful integrated run:
[41442384018](https://github.com/LaAaG21/clinic-assistant/actions/runs/41442384018),
commit `8427b02`. **Quality checks** passed, including PostgreSQL initialization,
locked dependency installation, **Ruff lint**, **Ruff format**, **Mypy**,
**Verify application coverage scope**, and **Pytest and application coverage
(minimum 80%)**. The real foundation startup/OpenAPI test passed: **1 test**,
**100% coverage of 2 application statements**. This is foundation coverage only;
it is not database-helper or planned clinical-workflow coverage. No health endpoint
or model API key was used.

Documentation-only commit `b849fde` triggered
[41437881219](https://github.com/LaAaG21/clinic-assistant/actions/runs/41437881219).
It failed before the foundation was merged, demonstrating that documentation
changes are not filtered out; it is not successful application-test evidence.

### Verified failure gates

Disposable [PR #32](https://github.com/LaAaG21/clinic-assistant/pull/32) used the
same workflow and locked application configuration, with one deliberate defect
per commit. It was closed without merging. None of its application/test changes
is included in PR #17. Earlier checks passed before each expected failing step.

| Deliberate defect | Real failed run | Failed step |
| --- | --- | --- |
| Unused import | [41442743836](https://github.com/LaAaG21/clinic-assistant/actions/runs/41442743836) | Ruff lint |
| Unformatted list | [41442818823](https://github.com/LaAaG21/clinic-assistant/actions/runs/41442818823) | Ruff format |
| String assigned to an integer annotation | [41442900403](https://github.com/LaAaG21/clinic-assistant/actions/runs/41442900403) | Mypy |
| Wrong expected OpenAPI title in the real startup test | [41442996220](https://github.com/LaAaG21/clinic-assistant/actions/runs/41442996220) | Pytest and application coverage (minimum 80%) |
| Test accidentally constructs its own FastAPI app instead of importing the application | [41443097436](https://github.com/LaAaG21/clinic-assistant/actions/runs/41443097436) | Pytest and application coverage (minimum 80%) |

The final fault is intentionally a test-wiring defect: **1 test passed**, while
coverage of the actual application was **0%**, below 80%, and the workflow failed.
It demonstrates why a passing assertion alone cannot substitute for measuring
the application. No coverage exclusions or ignored failures were introduced.

Remaining acceptance: merge #12, reconcile its connection configuration and test
collection, verify that its real-PostgreSQL success/failure/cleanup cases execute
without skips, and record the successful run and measured application coverage.
Do not mark #13 complete solely because the foundation-only run is green.

## Why test real behavior?

Commands can finish successfully while checking the wrong files or an empty
test set. Application startup/OpenAPI and real database tests exercise contracts,
transactions, cleanup, and failure outcomes. Coverage of the application reveals
untested runtime paths; covering test helpers or research code cannot provide
that evidence.

References: [uv and GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/),
[GitHub PostgreSQL services](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers),
[pytest-cov configuration](https://pytest-cov.readthedocs.io/en/latest/config.html).
