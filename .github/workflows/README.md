# Quality checks (#13)

`quality.yml` runs on all pull requests targeting `main`, including documentation
changes, on pushes to `main`, and on manual dispatch. It does not change branch
protection. The single check is named **Quality checks**, with separately named
Ruff lint, Ruff format, Mypy, and Pytest/coverage steps. Any nonzero command exit
fails the job; there are no ignored failures or successful fallback commands.

## Integration requirements

This workflow must remain a draft until #10 and #12 are available:

- #10 supplies the root `pyproject.toml`, committed `uv.lock`, application package,
  development dependency group (Ruff, Mypy, Pytest, pytest-cov), and meaningful
  application startup/OpenAPI tests. Shared Ruff/Mypy/Pytest settings must target
  the application and its tests rather than standalone research environments.
- Shared `[tool.coverage.run]` configuration must set `source` or `source_pkgs` to
  the actual application. CI refuses an absent source or a scope consisting of
  the repository, tests, or experiments. `--cov-fail-under=80` is explicit; no
  exclusions are added here to improve coverage artificially.
- #11's PR #16 proposes PostgreSQL 17.6 and `POSTGRES_DB`, `POSTGRES_USER`,
  `POSTGRES_PASSWORD`, `POSTGRES_PORT`, and `DATABASE_URL`. CI uses the same names,
  with a health-checked ephemeral service on localhost and a public CI-only
  password. It does not load a developer `.env` or touch persistent local data.
- #12 supplies meaningful real-PostgreSQL helper/probe tests using that connection
  configuration. Include successful connectivity, cleanup/failure handling, and
  a bounded unavailable-database case. Do not skip these tests in CI.

No model API key is supplied and no health endpoint is invoked. Neither #14 nor
the standalone research tests substitute for the required application tests.

## Verification record

Prepared from `origin/main` at `2f6452c` on 2026-11-02. At that revision there is
no root Python configuration/lockfile or application package/tests; only the #3
standalone experiment exists. #10 and #12 had no open implementation PRs. #11
was available as PR #16. The CI scope and exact foundation commands must be
reconciled with the merged dependencies before this issue can be completed.

- `actionlint` v1.7.12: passed against `quality.yml`.
- `git diff --check`: passed.
- Successful application workflow run: **pending #10/#12**.
- Measured application coverage: **not available**.
- Failure propagation in a real workflow: **pending**; no claim of execution.

After integration, record the actual GitHub Actions run URL, commit, step names,
results, test count, and measured coverage here. Verify documentation-only PRs
trigger the same check. In disposable test commits, independently introduce a
lint violation, formatting violation, type mismatch, failing behavioral test,
and an actual application coverage drop below 80%; record each failed run and
restore the changes. Do not merge those deliberate faults. A successful command
list alone is not evidence that application behavior or failure gates work.

## Why test real behavior?

Commands can finish successfully while checking the wrong files or an empty
test set. Application startup/OpenAPI and real database tests exercise contracts,
transactions, cleanup, and failure outcomes. Coverage of the application reveals
untested runtime paths; covering test helpers or research code cannot provide
that evidence.

References: [uv and GitHub Actions](https://docs.astral.sh/uv/guides/integration/github/),
[GitHub PostgreSQL services](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers),
[pytest-cov configuration](https://pytest-cov.readthedocs.io/en/latest/config.html).
