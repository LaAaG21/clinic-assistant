"""Small/long fixture documents against the #21 read-only document contract."""

from dataclasses import dataclass

import pytest

from clinic_assistant.passages import MAX_PASSAGE_CHARS, split_document


@dataclass(frozen=True)
class DocumentFixture:
    text: str
    source_id: str = "hours.md"
    source_name: str = "Clinic hours"


@pytest.mark.parametrize("text", ["", " \t\n\r\n", "\u2003\u00a0"])
def test_empty_document_has_no_passages(text: str) -> None:
    assert split_document(DocumentFixture(text)) == []


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_paragraph_boundaries_and_exact_locations(newline: str) -> None:
    text = (
        "  # Hours"
        + newline
        + "Open Monday."
        + newline
        + " \t"
        + newline
        + "Closed Sunday.  "
    )
    document = DocumentFixture(text)
    passages = split_document(document)
    assert [p.text for p in passages] == [
        "# Hours" + newline + "Open Monday.",
        "Closed Sunday.",
    ]
    for p in passages:
        assert p.text == text[p.start_char : p.end_char]
        assert p.source_id == document.source_id
        assert p.source_name == document.source_name


@pytest.mark.parametrize("length", [1, 1000, 1001, 5001])
def test_short_boundary_and_unbroken_long_text(length: int) -> None:
    text = "🙂" * length
    passages = split_document(DocumentFixture(text))
    assert "".join(p.text for p in passages) == text
    assert all(0 < len(p.text) <= MAX_PASSAGE_CHARS for p in passages)
    assert len(passages) == (length + 999) // 1000


def test_long_document_splits_at_whitespace_without_losing_nonwhitespace() -> None:
    text = ("opening hours " * 300) + "\n\n" + ("parking ramp " * 200)
    document = DocumentFixture(text)
    passages = split_document(document)
    assert all(0 < len(p.text) <= MAX_PASSAGE_CHARS for p in passages)
    assert "".join("".join(p.text.split()) for p in passages) == "".join(text.split())
    for left, right in zip(passages, passages[1:], strict=False):
        assert left.end_char <= right.start_char
        assert not text[left.end_char : right.start_char].strip()
    assert passages[0].end_char < 1000  # Prefer the last whitespace, not mid-word.
    assert all(p.text == text[p.start_char : p.end_char] for p in passages)
    assert split_document(document) == passages
    assert len({p.passage_id for p in passages}) == len(passages)


def test_source_identity_prevents_cross_document_and_delimiter_collisions() -> None:
    documents = [
        DocumentFixture("same text", source_id=s)
        for s in ["hours.md", "access.md", "hours.md:0:9", "9:hours.md", "مواعيد.md"]
    ]
    passages = [split_document(document)[0] for document in documents]
    assert len({p.passage_id for p in passages}) == len(documents)
    assert [p.source_id for p in passages] == [d.source_id for d in documents]
    assert all(p.source_name == "Clinic hours" for p in passages)


def test_whitespace_run_at_size_boundary_is_omitted_without_text_loss() -> None:
    text = "a" * 998 + "   " + "b" * 1000
    passages = split_document(DocumentFixture(text))
    assert [p.text for p in passages] == ["a" * 998, "b" * 1000]
    assert passages[0].end_char == 998
    assert passages[1].start_char == 1001
