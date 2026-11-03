# Clinic passage retrieval (#41)

Policy confirmed by the issue assignee on 2026-11-03: PostgreSQL English
`plainto_tsquery` matching, descending `ts_rank_cd`, deterministic passage-ID
tie break, default 3 results, hard maximum 10, no broad keyword fallback.
This records an implementation decision, not an invented research share-out.

`retrieve(question, passages, settings, limit=3)` returns the original passage
objects in rank order, preserving their IDs, text, source ID/name, and any offsets.
It consumes #28's metadata contract structurally without duplicating the splitter.
Duplicate passage IDs and limits outside integer 1..10 are rejected. Empty input,
blank questions, and unmatched/stop-word-only queries return an empty list.
Full-text conjunction may miss paraphrases or extra query terms; a match is not
proof of answerability. No unrelated passage is substituted.

The existing #12 helper owns finite connection/query timeouts, transaction
commit/rollback, and connection cleanup. Values are bound through psycopg.
The small supplied corpus is inserted into a connection-local temporary table
with a generated English vector and `ON COMMIT DROP`; no permanent schema or
extra service is added. IDs use PostgreSQL `C` collation for repeatable ties
independent of database locale. No index is needed for this initial small corpus.
This per-call staging approach is not a scale/latency claim. Database exceptions
propagate honestly, rather than becoming empty successful evidence.

Set `TEST_DATABASE_URL` to an isolated PostgreSQL test database (the CI service
can use `DATABASE_URL`). Run `uv run --locked pytest tests/test_retrieval.py -q`,
then the shared Ruff, format, strict Mypy, and coverage commands. Tests use actual
PostgreSQL for query/ranking behavior, including quotes, empty matches, bounds,
repeated ties, preserved objects, and connection failure.

Draft pending #28's merge and final suite integration with its actual Passage
type. No model calls, embeddings, answers, permanent corpus storage, or extra
retrieval interface is introduced.

Verified 2026-11-03: 14 focused cases and 78 total application tests passed with
real PostgreSQL enabled; retrieval coverage 100%, overall application coverage
96%. Ruff lint/format and strict Mypy passed. An isolated run using the actual
pending #21 loader and #28 splitter returned, in order:

| Passage ID | Source ID/name | Complete matched text |
| --- | --- | --- |
| `10:parking.md:0:27` | `parking.md` | Free parking behind clinic. |
| `10:parking.md:31:63` | `parking.md` | Clinic parking permit available. |

The broad `clinic` query returned 3 by default and 1 with `limit=1`; `astronomy`
returned `[]`. Objects/metadata were preserved, including original offsets.
Dependency code was loaded only in the isolated verification process, not copied
into this PR. Add that integration case to the shared suite once #28 merges.
