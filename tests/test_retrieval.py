"""Real PostgreSQL ranking, bounds, no-match behavior, and provenance checks."""

import os
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest

from clinic_assistant.database import DatabaseSettings
from clinic_assistant.documents import load_document
from clinic_assistant.passages import split_document
from clinic_assistant.retrieval import retrieve


@dataclass(frozen=True)
class PassageFixture:
    passage_id: str
    text: str
    source_id: str = "access.md"
    source_name: str = "Clinic access"


@pytest.fixture
def settings() -> DatabaseSettings:
    url = os.getenv("TEST_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL (or CI DATABASE_URL) for real PostgreSQL")
    return DatabaseSettings(url)


def test_known_match_ranking_ties_and_unchanged_sources(
    settings: DatabaseSettings,
) -> None:
    passages = [
        PassageFixture("z", "parking parking", "parking.md", "Parking policy"),
        PassageFixture("b", "parking available"),
        PassageFixture("a", "parking available"),
        PassageFixture(
            "insurance", "Cedar insurance accepted", "billing.md", "Billing"
        ),
    ]
    result = retrieve("parking", passages, settings)
    assert [p.passage_id for p in result] == ["z", "a", "b"]
    assert result[0] is passages[0]
    assert (result[0].source_id, result[0].source_name, result[0].text) == (
        "parking.md",
        "Parking policy",
        "parking parking",
    )
    assert retrieve("parking", passages, settings) == result
    assert retrieve("insurance", passages, settings) == [passages[3]]


@pytest.mark.parametrize("question", ["astronomy", "the and is", "parking surgery"])
def test_no_match_never_substitutes_passages(
    question: str, settings: DatabaseSettings
) -> None:
    assert (
        retrieve(question, [PassageFixture("p", "parking available")], settings) == []
    )


@pytest.mark.parametrize("limit", [1, 3, 10])
def test_bounded_counts_and_stable_ties(limit: int, settings: DatabaseSettings) -> None:
    passages = [PassageFixture(f"p{i}", "clinic") for i in range(5, -1, -1)]
    assert [
        p.passage_id for p in retrieve("clinic", passages, settings, limit=limit)
    ] == [f"p{i}" for i in range(min(limit, 6))]
    assert len(retrieve("clinic", passages, settings)) == 3


@pytest.mark.parametrize("limit", [0, -1, 11, True])
def test_invalid_limit_rejected_without_database(limit: int) -> None:
    with pytest.raises(ValueError, match="1 to 10"):
        retrieve("clinic", [], DatabaseSettings("not-used"), limit=limit)


def test_empty_inputs_and_duplicate_ids_do_not_need_database() -> None:
    settings = DatabaseSettings("not-used")
    assert retrieve("clinic", [], settings) == []
    passage = PassageFixture("p", "clinic")
    assert retrieve(" \t", [passage], settings) == []
    with pytest.raises(ValueError, match="unique"):
        retrieve("clinic", [passage, passage], settings)


def test_values_are_bound_and_metadata_is_not_reconstructed(
    settings: DatabaseSettings,
) -> None:
    passage = PassageFixture(
        "quote'\\", "Clinic's parking", "clinic's.md", "Original name"
    )
    assert retrieve("parking", [passage], settings)[0] is passage
    assert (
        retrieve("'; DROP TABLE clinic_retrieval_passages; --", [passage], settings)
        == []
    )
    assert retrieve("parking", [passage], settings) == [passage]


def test_unavailable_database_is_not_a_successful_empty_result() -> None:
    settings = DatabaseSettings("postgresql://postgres@127.0.0.1:1/postgres")
    with pytest.raises(psycopg.OperationalError):
        retrieve("clinic", [PassageFixture("p", "clinic")], settings)


def test_real_document_pipeline_preserves_passages_and_bounds(
    tmp_path: Path, settings: DatabaseSettings
) -> None:
    corpus = []
    for name, text in {
        "parking.md": (
            "Free parking behind clinic.\r\n\r\nClinic parking permit available."
        ),
        "hours.md": "Clinic opens Monday.",
        "billing.md": "Clinic accepts Cedar insurance.",
    }.items():
        path = tmp_path / name
        path.write_bytes(text.encode("utf-8"))
        corpus.extend(split_document(load_document(path)))
    results = retrieve("parking", corpus, settings)
    assert [p.passage_id for p in results] == [
        "10:parking.md:0:27",
        "10:parking.md:31:63",
    ]
    assert [p.text for p in results] == [
        "Free parking behind clinic.",
        "Clinic parking permit available.",
    ]
    assert all(p.source_id == p.source_name == "parking.md" for p in results)
    assert all(any(p is original for original in corpus) for p in results)
    assert retrieve("parking", corpus, settings) == results
    assert len(retrieve("clinic", corpus, settings)) == 3
    assert len(retrieve("clinic", corpus, settings, limit=1)) == 1
    assert retrieve("astronomy", corpus, settings) == []
