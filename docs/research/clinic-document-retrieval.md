# Clinic-document retrieval: research note

2026-11-02 | [Refs #5](https://github.com/LaAaG21/clinic-assistant/issues/5)

**Question:** Which small retrieval approach finds clinic evidence with traceable
sources? **Recommendation for share-out:** start conservatively with PostgreSQL
full-text search; evaluate recall further. Team agreement and the ADR belong in
a follow-up PR. This experiment does not close #5.

**Splitting:** four synthetic files in `experiments/retrieval/documents/` produce
five passages at blank lines. Normalize internal whitespace; retain filename as
`source_id` and filename plus `#pN` as passage ID. Paragraphs keep short policies
intact while separating booking/cancellation. No overlap is needed here. Production
needs size limits and versioned locations: paragraph reordering changes ordinals.
Carry source metadata through context assembly and citation rendering for auditing.

**Measured options:** keyword overlap (lowercase whole words, fixed stop words,
any overlap) and PostgreSQL English `to_tsvector`/`plainto_tsquery`, `@@`,
`ts_rank_cd`. Same questions/top-3; descending score, then passage-ID tie break.
Full-text requires all remaining lexemes; stop-word lists also differ. This compares
recipes, not stemming alone. psycopg binds inputs with parameters/`executemany`;
temporary tables roll back. No real-model calls or API keys.

**Embeddings: documentation only, not measured.** Vectors support similarity search
and may improve car/parking paraphrases; that is untested here. They add model
selection/versioning, inference cost, re-embedding, vector storage, and threshold
calibration. Similarity cannot establish factual support. No vector service was
added; evaluate the same unsupported inputs and provenance before choosing it.

## Reproduce

Python 3.12+, uv, Docker Compose. From the repository root:

```sh
cd experiments/retrieval
# Copy .env.example to .env; choose a URL-safe POSTGRES_PASSWORD.
uv sync --group dev --locked
docker compose -p clinic-retrieval up -d --wait
```

Set `DATABASE_URL=postgresql://postgres:YOUR_PASSWORD@127.0.0.1:55435/postgres`
(bash: `export DATABASE_URL='...'`; PowerShell: `$env:DATABASE_URL='...'`), then:

```sh
uv run compare.py --output results.json
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy compare.py fake_llm.py test_compare.py
docker compose -p clinic-retrieval down -v
```

An existing test database also works via `DATABASE_URL`; no psql/container ID.
`uv run compare.py --keyword-only` runs the baseline. Connection failure exits
nonzero without overwriting a report.

## Findings

Full questions/expected labels: `fixtures.json`; passages, source names, scores,
misses, irrelevant hits, and answers: `results.json`. Aliases: H=`clinic-hours.md#p1`,
B=`appointments.md#p1`, C=`appointments.md#p2`, P=`access.md#p1`, I=`billing.md#p1`.
Results are ranked; IDs absent from Expected are irrelevant; `-` means no hits.

| Question | Expected | Keyword | PostgreSQL |
| --- | --- | --- | --- |
| q1 Opening hours | H | P,I,H | H |
| q2 Book appointments | B | B | B |
| q3 Free parking | P | P | P |
| q4 Cancellation approval | C | C,B | C |
| q5 Accepted insurance | I | I,P,H | I |
| q6 Leave my car | P | - | - |
| q7 Parking cost | P | P | - |
| q8 Maple insurance | - | I,P,H | - |
| q9 Surgery bookings | - | B | - |
| q10 Antibiotic advice | - | - | - |
| q11 Open Sunday | H | H,P,I | H |
| q12 Stop words | - | - | - |

Keyword: **7/8** supported hits, **2/4** unsupported inputs with hits, **11** irrelevant
passages; PostgreSQL: **6/8, 0/4, 0**. Both miss car/parking; conjunction misses
parking cost. Maple/surgery keyword hits are insufficient. q11 must preserve “closed”.

**Fake model:** only the question and retrieved IDs/source names/text cross its
boundary; no corpus or expected labels. Fixed replies require the supporting
source/text substring. Recorded examples for both methods:

- q1: `The clinic opens Monday to Friday from 09:00 to 17:00. Source: clinic-hours.md`
- q10, empty retrieval: `I do not know from the clinic documents`

q8/q9 also abstain despite keyword noise. The fake demonstrates the interface,
not general answerability. Unsupported evidence needs abstention/staff referral;
avoid automatic keyword fallback. Emergency/medical-advice policies remain separate.

**Verified:** psycopg 3.3.6, PostgreSQL 18.6, Python 3.14.8; two identical reports,
eight pytest checks including real SQL/quotes/source preservation, Ruff, strict
mypy. Revised Compose was not run here; the reviewer's earlier Compose verification
covered the psql version. Tiny English fixtures establish neither scale nor
robustness to typos, stale/conflicting policies, or other languages. Align the
PostgreSQL major with the checkpoint experiment (17.6) at share-out.

**Official sources:** [PostgreSQL search](https://www.postgresql.org/docs/18/textsearch-controls.html)
(normalization/conjunction/ranking), [GIN indexes](https://www.postgresql.org/docs/18/textsearch-indexes.html)
(consider at scale), [psycopg parameters](https://www.psycopg.org/psycopg3/docs/basic/params.html)
(bind data separately), [OpenAI embeddings](https://developers.openai.com/api/docs/guides/embeddings)
(vector similarity; documentation only).
