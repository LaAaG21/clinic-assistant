# Repository approval policy and setup status

## Project-owner decision

LaAaG21 is the verified lead (GitHub user ID `42642412`, repository administrator). The repository is [LaAaG21/clinic-assistant](https://github.com/LaAaG21/clinic-assistant), with `main` as the protected/default branch. Repository visibility and ownership remain unchanged.

The original challenge and [Codeline contribution guidelines](https://github.com/CodelineAtyab/CodelineLegendsAIWorkflows/blob/main/README.md) require two approvals. For this project, the owner explicitly requires one approving human review from LaAaG21 instead. This is a project-owner decision and a deviation from the original requirement. No trainer approval of an exception has been claimed.

The initial setup uses `chore/repository-setup`, with the explicit branch and PR-title exception: **Initial repository setup — task tracking begins afterward.** No ticket, member ID, or new issue is required for this setup. Future development follows ticket-based naming once tasks exist.

## Intended ongoing policy

For teammate-authored PRs, LaAaG21 owns all files and must approve. Another teammate's approval alone is insufficient once the base branch's CODEOWNERS file and code-owner review requirement are effective together. CI must pass, the branch must be up to date, and review conversations must be resolved. New reviewable changes dismiss stale approvals.

Approval of the most recent reviewable push is disabled: the lead may push a correction to a teammate's PR and then review it. Stale-approval dismissal remains enabled. Merge permissions are separate from approval authority; no rule reserves the final Merge click exclusively for the lead.

Squash is the permitted merge method, with the PR title as the default squash commit title. Main requires a PR and linear history and is protected against deletion and force pushes. Routine bypass actors, update restrictions, creation restrictions, signed-commit requirements, merge queues, and deployment prerequisites are not part of this requested setup.

## Lead-authored PRs and bootstrap

[GitHub prohibits PR authors from approving their own PRs](https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/reviewing-proposed-changes-in-a-pull-request). This includes the setup PR opened through LaAaG21's authenticated account. Native CODEOWNERS does not resolve self-approval. A teammate's review is not an authorized replacement for the lead's human approval.

The lead-authored handling decision remains unresolved. Leave such a PR unmerged until the owner makes a separate, explicit decision about its handling. Do not claim that GitHub necessarily enforces this additional project policy in every lead-authored scenario: its native review counting and author treatment do not establish the missing human authorization. Do not add a bypass, disable reviews, manufacture another identity, or submit a fake review.

[CODEOWNERS is read from the PR base branch](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners). The initial `main` has no CODEOWNERS file. The new ownership file on the setup branch therefore does not enforce sole-lead ownership for this setup PR. Until the file reaches `main`, a generic one-review requirement is not equivalent to the requested lead-only approval policy. The setup must not be pushed directly to `main` to work around this.

## Verification record — 2026-11-02

The following records configuration inspection during setup, not a destructive enforcement test or a submitted review. Recheck GitHub after changes; this document alone is not proof of enforcement.

| Control | Setup evidence/status |
| --- | --- |
| Lead identity and permission | LaAaG21, user ID `42642412`, administrator verified through GitHub API. |
| Existing inherited/classic rules | Initial inspection found no applicable inherited or classic rules in this public personal repository. |
| Main ruleset | [Ruleset `26347955`](https://github.com/LaAaG21/clinic-assistant/rules/26347955) was created active for `refs/heads/main`. |
| PR review configuration | One approval, code-owner review flag, stale-approval dismissal, and conversation resolution read back enabled; most-recent-push approval disabled. |
| Branch protections | Linear history, deletion restriction, and force-push blocking read back enabled. No bypass actors; update/creation restrictions absent. |
| Merge settings | Squash enabled, merge commits/rebase disabled, squash title `PR_TITLE`, squash message `BLANK`; read back from the repository API. |
| Sole-lead code ownership | Pending: `.github/CODEOWNERS` must reach `main`. No later ownership patterns or alternate ownership files are introduced by setup. |
| Required CI checks and up-to-date enforcement | Pending a successful real workflow run and configuration of the actual reported check names. |
| Review dismissal restricted to lead | Not active. REST and GraphQL writes were accepted but did not retain the restriction; a fresh GraphQL read reported `enabled: false` and no allowed actors. No broader bypass was added. |
| Lead-authored setup PR handling | Unresolved project-owner decision. Leave the PR unmerged; do not substitute another teammate's approval. |

The [GitHub rules API](https://docs.github.com/en/rest/repos/rules) documents review dismissal restrictions, but this setup's accepted writes did not persist that setting. Verify the live saved state before claiming it is enabled.

The UI fallback ended before interacting with GitHub because computer use could not verify the current Chrome URL sufficiently to enforce its access policy. This is an unresolved settings limitation, not evidence of a plan restriction. Other rules were verified through fresh API reads. The default workflow token is read-only and cannot approve pull request reviews.

Local validation passed Ruff lint, Ruff formatting, strict Mypy, and all 17 tests with 100% statement/branch coverage of the application. The API image built from source; Compose reported both services healthy and `/health` and `/ready` returned success. Local API testing used port 18000 because another process occupied port 8000; the tracked default remains configurable at 8000.

## CI and course integration

The course [CI workflow](https://github.com/CodelineAtyab/CodelineLegendsAIWorkflows/blob/main/.github/workflows/lint.yml) establishes uv, Ruff, and Mypy conventions. This repository also requires formatting checks, Pytest, and at least 80% application coverage; documentation-only PRs must run the same required checks.

The course [OpenCode review integration](https://github.com/CodelineAtyab/CodelineLegendsAIWorkflows/blob/main/.github/workflows/opencode-review.yml) uses `OPENAI_API_KEY` with `openai/gpt-4.1-mini` and a GitHub token able to comment on PRs. Its availability depends on the required configuration and credential. Its feedback remains advisory and never replaces LaAaG21's human approval. Only the review job may receive the additional permissions needed to post feedback; deterministic CI uses read-only contents access.

The adapted workflow is present but opt-in: the repository currently has no `OPENAI_API_KEY` secret and no `ENABLE_AI_REVIEW` variable. To enable it later, provide the secret through GitHub's secret settings and set `ENABLE_AI_REVIEW=true`. It runs only on same-repository, non-draft PRs, never as a required merge check. Missing credentials do not block deterministic CI. The upstream OpenCode wrapper is pinned to a verified commit; its upstream runtime installation is dynamic, so its result is advisory rather than part of the reproducible CI gate.
