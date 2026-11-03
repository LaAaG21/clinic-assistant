# Traceable clinic passages (#28)

Splitting policy confirmed by the issue assignee in Codex on 2026-11-03:
blank-line paragraphs, at most 1,000 Unicode characters per passage, prefer
whitespace when a paragraph is too long, hard-split unbroken text, no overlap,
and keep original character locations with deterministic source-based IDs.
This is the approved implementation policy, not a claim that a research
share-out or architecture ADR has taken place.

`split_document(document)` consumes #21's read-only `source_id`, `source_name`,
and `text` attributes. The structural `DocumentSource` protocol permits the real
immutable `ClinicDocument` without importing/copying its loader or research code.
Empty/whitespace-only text returns no passages. Paragraph/chunk edge whitespace
is omitted; internal text and original line endings are unchanged.

Each immutable `Passage` retains the source fields, text, and zero-based,
end-exclusive `start_char` / `end_char`. Always
`passage.text == document.text[start_char:end_char]`. Locations count Unicode
characters, not bytes or model tokens. Blank lines support LF, CRLF, and CR.
Passage IDs are `source-length:source-id:start:end`; the length prefix disambiguates
source IDs containing delimiters. They are distinct within/across unique sources
and deterministic for identical input. Offsets/IDs can change after edits; these
are locations, not document-version hashes. #21's unique-source-ID requirement
still applies when assembling a corpus.

No retrieval, embeddings, model calls, database, or answer generation is added.
Source metadata travels with every passage because recovering it from text later
is ambiguous when different documents contain identical wording.

Verification: `uv run --locked pytest tests/test_passages.py -q`, plus the shared
Ruff, format, strict Mypy, and full coverage commands. Tests include empty input,
short paragraphs, line endings, exact size boundaries, long words, long documents,
non-overlap, exact text locations, stable IDs, and delimiter/Unicode source IDs.

Integration with the real loader remains pending PR #34's merge. This PR stays
draft until the loader integration check can live in the shared test suite.
An isolated check against PR #34's actual loader (without copying it into this
branch) returned `8:hours.md:0:21` and `8:hours.md:25:39` for the two CRLF
paragraphs, each with source ID/name `hours.md` and exact source slices.
A 3,150-character long sample produced sizes 994, 999, 994, and 159.
Verified 2026-11-03: 13 focused cases and 77 total application tests passed with
real PostgreSQL tests enabled; passage coverage 100%, overall coverage 96.81%.
Ruff lint/format and strict Mypy passed. Full-suite loader integration remains
pending the dependency merge; the fixture tests do not claim that merge occurred.
