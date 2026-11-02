"""Harness, fake-model boundary, failure behavior, and optional real SQL checks."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import cast

import pytest

import compare
from compare import (
    Hit,
    Question,
    evaluate,
    keyword_search,
    postgres_search,
    split_documents,
)
from fake_llm import FALLBACK, Evidence, fake_answer


def test_split_preserves_sources_and_paragraphs(tmp_path: Path) -> None:
    (tmp_path / "clinic.md").write_text(
        " First line\nwrapped line.\n\n\nSecond paragraph.\n", encoding="utf-8"
    )
    (tmp_path / "empty.md").write_text("\n\n", encoding="utf-8")
    assert split_documents(tmp_path) == [
        {
            "passage_id": "clinic.md#p1",
            "source_id": "clinic.md",
            "text": "First line wrapped line.",
        },
        {
            "passage_id": "clinic.md#p2",
            "source_id": "clinic.md",
            "text": "Second paragraph.",
        },
    ]


def test_empty_document_directory_fails(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="No passages"):
        split_documents(tmp_path)


def test_keyword_whole_words_empty_query_and_deterministic_limit() -> None:
    passages = [
        Evidence(passage_id=str(i), source_id="original.md", text="Parking")
        for i in range(5, 0, -1)
    ]
    assert keyword_search(passages, "park") == []
    assert keyword_search(passages, "the and is") == []
    hits = keyword_search(passages, "Is parking available?")
    assert [p["passage_id"] for p in hits] == ["1", "2", "3"]
    assert all(p["source_id"] == "original.md" for p in hits)


def test_metrics_distinguish_misses_and_unsupported_hits() -> None:
    questions: list[Question] = [
        {"id": "a", "text": "Unknown", "expected": ["p1"]},
        {"id": "b", "text": "Unknown", "expected": []},
    ]
    hit = Hit(passage_id="p2", source_id="other.md", text="irrelevant", score=1)
    report = evaluate(questions, {"a": [], "b": [hit]})
    assert report["supported_hit_at_3"] == 0
    assert report["unsupported_with_hits"] == 1
    assert report["questions"][0]["missed"] == ["p1"]
    assert report["questions"][1]["irrelevant"] == ["p2"]
    assert report["questions"][1]["answer"] == FALLBACK


def test_only_retrieved_evidence_reaches_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    received: list[list[Evidence]] = []

    def spy(question: str, evidence: list[Evidence]) -> str:
        assert question == "Is parking free?"
        received.append(evidence)
        return FALLBACK

    monkeypatch.setattr(compare, "fake_answer", spy)
    question: Question = {"id": "q", "text": "Is parking free?", "expected": ["hidden"]}
    hit = Hit(passage_id="retrieved", source_id="other.md", text="Only this", score=1)
    evaluate([question], {"q": [hit]})
    assert received == [
        [{"passage_id": "retrieved", "source_id": "other.md", "text": "Only this"}]
    ]


def test_fake_requires_retrieved_text_and_source_and_preserves_negation() -> None:
    passages = split_documents(compare.ROOT / "documents")
    hours = [p for p in passages if p["source_id"] == "clinic-hours.md"]
    assert fake_answer("When does the clinic open?", hours) == (
        "The clinic opens Monday to Friday from 09:00 to 17:00. Source: clinic-hours.md"
    )
    assert fake_answer("Is the clinic open on Sunday?", hours).startswith("No.")
    assert fake_answer("When does the clinic open?", []) == FALLBACK
    assert fake_answer("Does the clinic accept Maple insurance?", passages) == FALLBACK
    changed_source = Evidence(**hours[0])
    changed_source["source_id"] = "wrong.md"
    assert fake_answer("When does the clinic open?", [changed_source]) == FALLBACK
    changed_text = Evidence(**hours[0])
    changed_text["text"] = "No opening hours here"
    assert fake_answer("When does the clinic open?", [changed_text]) == FALLBACK


def test_failed_connection_never_overwrites_report(tmp_path: Path) -> None:
    output = tmp_path / "report.json"
    output.write_text("previous report", encoding="utf-8")
    env = dict(os.environ, DATABASE_URL="postgresql://postgres@127.0.0.1:1/postgres")
    result = subprocess.run(
        [sys.executable, str(compare.ROOT / "compare.py"), "--output", str(output)],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 1
    assert "No report written" in result.stderr
    assert output.read_text(encoding="utf-8") == "previous report"


@pytest.mark.postgres
def test_real_parameterized_search_and_repeatability() -> None:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("Set DATABASE_URL to run the real PostgreSQL integration check")
    passages = split_documents(compare.ROOT / "documents")
    questions = cast(
        list[Question],
        json.loads((compare.ROOT / "fixtures.json").read_text(encoding="utf-8"))[
            "questions"
        ],
    )
    version, first = postgres_search(passages, questions, database_url)
    assert version
    assert first == postgres_search(passages, questions, database_url)[1]
    report = evaluate(questions, first)
    assert report["supported_hit_at_3"] == 6
    assert report["unsupported_with_hits"] == 0
    assert report["irrelevant_passages"] == 0
    originals = {p["passage_id"]: p for p in passages}
    for hits in first.values():
        for hit in hits:
            assert hit["source_id"] == originals[hit["passage_id"]]["source_id"]
            assert hit["text"] == originals[hit["passage_id"]]["text"]
    assert report["questions"][0]["answer"].endswith("Source: clinic-hours.md")
    assert report["questions"][9]["answer"] == FALLBACK

    # Quotes, backslashes and SQL-looking text must remain bound data.
    unusual = Evidence(
        passage_id="quote'\\",
        source_id="clinic's.md",
        text="O'Reilly's clinic has parking \\ behind reception.",
    )
    special: list[Question] = [
        {"id": "quote", "text": "parking", "expected": [unusual["passage_id"]]},
        {"id": "sql", "text": "'; DROP TABLE retrieval_passages; --", "expected": []},
    ]
    bound = postgres_search([unusual], special, database_url)[1]
    assert bound["quote"][0]["text"] == unusual["text"]
    assert bound["quote"][0]["source_id"] == "clinic's.md"
