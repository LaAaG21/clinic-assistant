# ADR 0001: Start with PostgreSQL full-text retrieval

Status: **Proposed — awaiting team agreement**

Date: 2026-11-02

## Context

Clinic answers need passages with auditable source names. The planned application
already uses PostgreSQL and plain SQL. We need a small initial option without an
extra database or vector service. [The experiment and research note](../research/clinic-document-retrieval.md)
compare keyword overlap and PostgreSQL English full-text search on identical
synthetic inputs, including unsupported questions.

## Proposed decision

Use explicit English `to_tsvector` / `plainto_tsquery` matching with `@@`, rank by
`ts_rank_cd` and a stable passage-ID tie break, and return at most three candidate
passages. Carry passage ID, original source ID, and text together throughout the
answer workflow. Keep the simple keyword implementation as an evaluation baseline.
Add a GIN index only when implementing and measuring the actual persisted corpus.

No candidate is an answerability guarantee. Abstain or refer to staff when evidence
is absent or does not support the requested fact. Do not broaden queries through
an automatic keyword fallback. Apply emergency and medical-advice policies
independently of retrieval. Production implementation remains separate work.

## Evidence and consequences

On PostgreSQL 18.6, full-text search retrieved expected evidence for 6/8 supported
questions versus 7/8 for keyword overlap, with 0 versus 11 irrelevant passages and
0/4 versus 2/4 unsupported questions returning candidates. Different conjunction
and stop-word rules are part of this comparison, so these figures do not prove
that normalization alone improves quality.

The proposed option reuses the database and reduces noisy candidates in this
sample, but loses a parking-cost question due to strict conjunction. Both options
miss a car/parking paraphrase. Neither has been evaluated for multilingual input,
typos, stale/conflicting documents, production scale, or answer generation. A
larger reviewed question set and explicit unsupported-answer validation are
required before treating it as a production design.

## Alternatives

Keyword overlap has no database dependency and found one extra supported question,
but also returned misleading evidence for unsupported entities/services. Additional
vector services are outside this issue's scope; the experiment does not establish
their relative quality.

## Acceptance

This ADR records a proposal only. Record team agreement and its date here before
changing the status to Accepted. Revisit the choice if a broader evaluation shows
unacceptable recall or unsupported-answer behavior.
