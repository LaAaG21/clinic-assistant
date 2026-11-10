# Team working guide

How this team plans, builds, reviews and records its work. Conventions for
code and PRs are in [AGENTS.md](../../AGENTS.md); the system picture is the
[system view](../design/system-view.md). Everything below records facts from
the repository; items marked **pending** have no evidence yet and must not be
treated as done.

## Ready and Done

An issue is **Ready** when it has:

1. a Goal and a Scope that say what is in and out;
2. numbered Acceptance criteria that a reviewer can check one by one;
3. a Verification section naming the commands or checks to run;
4. its dependencies listed, with blockers labelled as blockers (a missing
   agreement is a blocker, not permission to drop a requirement);
5. an estimate in effort units and one assignee.

A PR is **Done** when:

1. every acceptance criterion is met or the PR says which one is not and uses
   `Refs #N` instead of `Closes #N`;
2. the four required checks pass in CI on an up-to-date branch;
3. the PR body records the verification actually run, with real results, and
   its limitations;
4. the lead's approving review is recorded (one teammate review for
   lead-authored PRs) and conversations are resolved;
5. it is squash-merged and the issue is closed only when all criteria are met.

Documentation that proposes a design labels unresolved decisions instead of
claiming agreement; accepted decisions go to [`docs/adr/`](../adr/README.md).

## Sprint and story records

Work is issued in numbered **rounds** (issue labels `round:1` … `round:14`),
each round being the sprint-like batch the lead publishes together. Each issue
carries its story acceptance (the criteria above) and its effort estimate
("N effort units from Lxx/Rxx/Dxx/Axx/Uxx"), so the round label, the issue text
and the merged PR are the sprint goal, story acceptance and effort record.

| Record | Where it is kept | Status |
| --- | --- | --- |
| Sprint goal and backlog | GitHub issues with `round:N` labels; the lead writes them | In use |
| Story acceptance and effort | Acceptance criteria and estimate in each issue; verification in the PR body | In use |
| Daily standup, mid-day sync | **Pending**: no written record in the repository. Proposal: one `docs/team/standups/YYYY-MM-DD.md` note per day with three lines per member (done, next, blocked); the team must confirm where it meets | Pending |
| Sprint planning, review, retrospective | **Pending**: no written record in the repository. Proposal: `docs/team/rounds/round-NN.md` with goal, accepted stories, review outcome and retrospective actions | Pending |
| Owned actions from retrospectives | **Pending** until the first retrospective note exists | Pending |

Nothing here records a meeting that did not happen.

## Contribution evidence

Counted from the repository's pull requests on 2026-11-05 (merged unless
stated). "Application-code PR" means a merged PR that changes `src/`, `tests/`
or `db/init/`. "Substantive review" means a review on a teammate's PR that
reads as a judgement against the issue's criteria; only review *existence* is
counted here from the GitHub search (`reviewed-by:<user>`), and the team should
confirm substance. "Explained another member's work" needs a written note
(for example a review comment or a `docs/team` note that explains a teammate's
PR) and is **pending** for everyone until such a note exists.

| Member | Application-code PRs (≥ 2 needed) | Reviews given (≥ 2 substantive needed) | Explained another member's work |
| --- | --- | --- | --- |
| LaAaG21 (lead) | #24 (#10 foundation), #48 (#14 health), #49 (#18 settings); open: #108 (#25 Docker), #110 (#65 logging), #111 (#55 emergency guard) | 27 PRs reviewed, including #7, #9, #16, #17, #30, #31, #33, #34, #35, #37, #90–#102 | **Pending** |
| HAFISAALBAHRI | #30 (#8 models), #34 (#21 loader), #91 (#46 fake adapter), #92/#94 (#28 passages), #93/#95 (#41 retrieval), #97 (#53 OpenAI adapter), #98 (#43 errors), #99 (#58 failures), #100 (#63 classification), #101 (#68 clarification) | 6 PRs reviewed: #15, #23, #24, #48, #49, #90 | **Pending** |
| Louai1999 | #90 (#19 doctors/slots tables), #96 (#26 conversations), #102 (#39 bookings); #16 (#11 Compose service) is infrastructure | 2 PRs reviewed: #2, #36 (both documentation/ownership PRs); substantive code reviews **pending** | **Pending** |
| Hidaya21 | #35 (#12 database helper), #37 (#20 same-day policy); #31 is the #4 experiment; open: #103, #104, #105, #107 | 0 reviews found; **pending** | **Pending** |
| yarubalshabibi-hub | Open: #109 (#29 seed data); merged application-code PRs **pending** | 0 reviews found; **pending** | **Pending** |

Research PRs (#7, #9, #31) and documentation PRs (#15, #23, #33, #36) count as
contributions but not as application-code PRs. Update this table when PRs merge;
do not add rows for work that is not visible on GitHub.

## Recorded project decisions

- One approving review from the lead instead of two approvals (project-owner
  decision, 2026-11-02, recorded in the closed setup PR #1).
- Lead-authored PRs merge on one teammate review (practice since PR #15; #15,
  #23, #24, #48 and #49 were each reviewed by a teammate).
- GitHub issues are the only tracker; ClickUp is not used.
