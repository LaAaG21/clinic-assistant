# Contributing

Keep changes focused and preserve unrelated work. The clinic's full product workflows are separate development tasks; the repository foundation does not implement them.

## Branches and pull requests

All changes to `main` go through a pull request. Update your local view of `main` before starting work, then create a branch. For future development, once tasks exist, use:

```text
feature/<ticket-id>-<member-id>-<short-title>
```

Use the actual ClickUp ticket ID and member ID. The PR title begins with the ticket ID, followed by a concise description, for example `<ticket-id>: <purpose>`. Fill in the PR template with the ticket, purpose, testing, and limitations. Do not invent a task ID.

The project owner explicitly chose `chore/repository-setup` for the initial setup, with this branch and PR-title exception:

> Initial repository setup — task tracking begins afterward.

No ClickUp ticket, member ID, or newly created issue is required for this initial setup. Ticket-based naming applies to future development after tasks exist.

## Human review and merging

LaAaG21 is the sole code owner of every file, including `.github/CODEOWNERS` and workflows. For teammate-authored PRs, one approving human review from LaAaG21 is required. Another teammate's approval and any AI review do not replace it. New reviewable changes dismiss stale approvals, and review conversations must be resolved.

Required CI must pass against an up-to-date branch. Merge using squash so the PR title, including its ticket ID where applicable, becomes the default commit title. Approval authority is distinct from permission to click Merge: this policy does not restrict that final action to LaAaG21 once every applicable requirement is satisfied.

The [course contribution guidelines](https://github.com/CodelineAtyab/CodelineLegendsAIWorkflows/blob/main/README.md) and original challenge call for two approvals. LaAaG21, as project owner, explicitly chose one required approval from the lead instead. This is a recorded deviation from the original requirement, not a trainer-approved exception.

GitHub does not permit PR authors to approve their own PRs. A PR authored by LaAaG21 therefore requires a separate, explicit handling decision before it may be merged under this project's policy. Another teammate's approval is not an authorized substitute. Do not manufacture an identity, submit a review as the lead, add a bypass, or disable review requirements to get around this limitation. See [repository policy and bootstrap status](docs/repository-policy.md).

## Development and checks

Use `uv` with the committed `uv.lock`. Run the commands in the [README](README.md) before requesting review. CI runs Ruff lint, Ruff formatting, Mypy, and Pytest with at least 80% coverage of actual application code. These checks also run for documentation-only PRs.

Application tests use a deterministic fake LLM and require no model API key. Tests that access a database use PostgreSQL, including the PostgreSQL service in CI. Use parameterized SQL through psycopg; do not add SQLite, an in-memory database, SQLAlchemy, or another ORM. Do not suppress failures or exclude substantial application code merely to meet coverage.

Keep `.env` and local secret variants out of Git. Commit only safe placeholders in `.env.example`. SQL schemas, safe seed data, clinic documents, sample messages, and `uv.lock` belong in version control. Do not commit real patient data or credentials.

## AI review

The course's [OpenCode workflow](https://github.com/CodelineAtyab/CodelineLegendsAIWorkflows/blob/main/.github/workflows/opencode-review.yml) provides advisory feedback using `OPENAI_API_KEY`. Missing configuration or credentials do not replace or weaken deterministic CI or human review. AI feedback is not an approving human review and is not a required merge check.
