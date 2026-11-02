# Clinic-document retrieval comparison

Date: 2026-11-02. Resolves the research scope of [issue #5](https://github.com/LaAaG21/clinic-assistant/issues/5).

## Question and scope

What small retrieval approach can return clinic passages with reliable source
identifiers, using the project's existing PostgreSQL stack?

This standalone experiment uses five explicitly synthetic English passages and
twelve fixed questions. There are no real patient records, model calls, production
adapters, or additional database/vector services. The fixtures include eight
supported questions and four unsupported inputs. Expected matches were specified
in `experiments/retrieval/fixtures.json`; an empty expected list means no passage
answers the question. It does not mean that every such question is suitable for
the assistant to answer.

## Options and method

1. **Keyword baseline:** lowercase ASCII whole-word sets, a fixed small stop-word
   list, and overlap count. Return any positive overlap, ordered by count descending
   and passage ID ascending, capped at three. No stemming or synonyms.
2. **PostgreSQL full-text search:** `to_tsvector('english', body)` and
   `plainto_tsquery('english', question)`, filtered using `@@`, ranked by
   `ts_rank_cd` descending, then passage ID ascending, capped at three. The text
   search configuration is explicit. Only passage text is searched; source names
   are metadata, not extra search terms.

Both use identical passages, full unmodified questions, expected labels, and top-k.
The comparison intentionally measures two simple end-to-end retrieval recipes:
the baseline matches **any** remaining word, while `plainto_tsquery` requires
**all** remaining lexemes. Their stop-word lists also differ. Thus the result
does not isolate stemming, ranking, or PostgreSQL itself as the cause of quality
differences. No threshold tuning or performance benchmark was performed.

The SQL runs in a transaction using a temporary table, then rolls back; no
application tables are changed. No index is needed for five rows. The output
retains passage ID, original source ID, complete text, and score for every hit,
plus per-question misses and irrelevant hits. Scores across methods are not
comparable probabilities.

## Reproduction

From the repository root, with Python 3.10+ and Docker Compose available:

```sh
docker compose -p clinic-retrieval -f experiments/retrieval/compose.yaml up -d --wait
docker compose -p clinic-retrieval -f experiments/retrieval/compose.yaml ps -q postgres
```

Copy the container ID printed by the second command into `CONTAINER_ID` below:

```sh
python experiments/retrieval/compare.py --container CONTAINER_ID --output experiments/retrieval/results.json
python -m unittest discover -s experiments/retrieval -p test_compare.py -v
docker compose -p clinic-retrieval -f experiments/retrieval/compose.yaml down -v
```

Alternatively, use an existing PostgreSQL server and a local `psql` executable.
Set libpq's `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER` and authentication as needed,
then run:

```sh
python experiments/retrieval/compare.py --psql /path/to/psql --output experiments/retrieval/results.json
```

The connection role needs permission to create temporary tables. Use a test
database. Connection settings stay outside the report. Missing PostgreSQL or a
failed SQL command exits nonzero without writing a new report; an existing report
is not evidence of a successful rerun. For baseline debugging only:

```sh
python experiments/retrieval/compare.py --keyword-only
```

The checked-in full report was measured using PostgreSQL **18.6**, Python 3.14.8,
and portable Windows `psql`, with an isolated local database. Docker was unavailable
on the authoring machine, so the Compose path was supplied but not executed there.
The same SQL is used by both invocation paths. The four harness unit tests passed.

## Actual findings

IDs below are in returned rank order. `—` means no hits. These are retrieval
results, not generated answers; inspect `experiments/retrieval/results.json` for
the actual passages, original source names, scores, misses, and irrelevant hits.

| Question | Expected passage | Keyword actual | PostgreSQL actual |
| --- | --- | --- | --- |
| q1: When does the clinic open? | hours-1 | hours-1, insurance-1, parking-1 | hours-1 |
| q2: How do I book appointments? | booking-1 | booking-1 | booking-1 |
| q3: Is parking free? | parking-1 | parking-1 | parking-1 |
| q4: Do cancellations require approval? | cancel-1 | cancel-1, booking-1 | cancel-1 |
| q5: Which insurance does the clinic accept? | insurance-1 | insurance-1, hours-1, parking-1 | insurance-1 |
| q6: Where can I leave my car? | parking-1 | — | — |
| q7: How much does parking cost? | parking-1 | parking-1 | — |
| q8: Does the clinic accept Maple insurance? | — | insurance-1, hours-1, parking-1 | — |
| q9: Can I book surgery appointments? | — | booking-1 | — |
| q10: What antibiotic should I take? | — | — | — |
| q11: Is the clinic open on Sunday? | hours-1 | hours-1, insurance-1, parking-1 | hours-1 |
| q12: the and is | — | — | — |

| Metric | Keyword | PostgreSQL |
| --- | --- | --- |
| Supported questions with at least one expected hit in top 3 | 7/8 | 6/8 |
| Unsupported questions with any hit (lower is better) | 2/4 | 0/4 |
| Total irrelevant passages across all questions | 11 | 0 |

Passage/source mapping: hours-1 → `clinic-hours.md`; booking-1 and cancel-1 →
`appointments.md`; parking-1 → `access.md`; insurance-1 → `billing.md`.
Distinct passage IDs prevent two chunks from the same document being conflated.

The keyword method retrieves noise from generic words such as “clinic” and
“approval”, including booking evidence for a cancellation question. It returns
Cedar insurance evidence for a Maple question and general booking evidence for
surgery. Neither supports those questions. PostgreSQL handles open/opens and
accept/accepts, while its conjunction excludes those unsupported inputs. Both
methods miss the car/parking paraphrase. PostgreSQL misses q7 because “cost” is
absent, even though “Free parking” answers it. q11 retrieves a passage that says
Sunday is closed; retrieval must preserve that negation when answering.

## Recommendation and risks

Propose PostgreSQL English full-text search as the first conservative retrieval
candidate, keeping keyword search as an experiment baseline. It produces cleaner
candidate sets here and fits the planned database without another service. This
is a small-sample engineering recommendation, not proof of production quality.
The proposed ADR remains pending team agreement.

Strict conjunction loses recall on natural questions; neither recipe handles
synonyms reliably. English stemming is unsuitable as an untested multilingual
strategy. Typos, abbreviations, conflicting policies, stale documents, longer
chunks, and multiple sources per answer need a larger, independently reviewed
evaluation. Consider controlled query normalization and reviewed synonyms in a
follow-up experiment; measure their unsupported-hit rate before enabling them.
Do not silently fall back to broad keyword matches when full-text search is empty.
If the corpus grows, evaluate a GIN index and actual latency; these five rows say
nothing about scale.

Unsupported-answer handling must be separate from retrieval: no hits should lead
to an explicit lack-of-evidence response and referral to clinic staff. A hit is
only a candidate: verify that its text supports the specific entity, requested
fact, and polarity before answering; otherwise abstain. Never infer Maple coverage
from Cedar coverage or surgery availability from general booking instructions.
No rank threshold in this experiment establishes answerability. Emergency handling
and the prohibition on diagnosis/treatment advice must apply independently of
search results; q10 is not a medical-safety implementation.

**Learning check:** source identifiers must travel with passage text through
retrieval, context assembly, answer generation, and citation rendering. Otherwise
an answer can lose its provenance or cite the wrong document. Preserve both a
stable passage ID and original source name, and plan document versions/locations
so staff can audit the exact evidence even after a document changes.

## Official sources

- [PostgreSQL 18: Controlling Text Search](https://www.postgresql.org/docs/18/textsearch-controls.html):
  vector construction, query conversion, conjunction in `plainto_tsquery`, and
  cover-density ranking.
- [PostgreSQL 18: Dictionaries](https://www.postgresql.org/docs/18/textsearch-dictionaries.html):
  stop words and normalization; synonym handling needs configuration.
- [PostgreSQL 18: Preferred Index Types](https://www.postgresql.org/docs/18/textsearch-indexes.html):
  indexes are optional, with GIN preferred for regular text-search workloads.
- [Python: Regular expressions](https://docs.python.org/3/library/re.html):
  the standard-library token matching used in the baseline.
