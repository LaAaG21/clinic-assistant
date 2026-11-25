import hashlib

import pytest
from qdrant_client import QdrantClient

from ingestion import ingest
from ingestion.ingest import (
    COLLECTION,
    DOCS_DIR,
    EMBEDDING_SIZE,
    chunk_text,
    ensure_collection,
    extract_text,
    ingest_file,
)
from ingestion.make_sample_pdfs import write_pdf

SAMPLE_PDFS = ["doctors.pdf", "facilities.pdf", "policies.pdf"]


def fake_embed(texts: list[str]) -> list[list[float]]:
    """Deterministic stand-in for OpenAI: no network, no key."""
    vectors = []
    for text in texts:
        seed = hashlib.sha256(text.encode()).digest()
        vectors.append(
            [seed[i % len(seed)] / 255 + 0.01 for i in range(EMBEDDING_SIZE)]
        )
    return vectors


@pytest.fixture
def client():
    qdrant = QdrantClient(":memory:")
    ensure_collection(qdrant)
    return qdrant


def stored(client, source=None):
    points, _ = client.scroll(COLLECTION, limit=1000, with_payload=True)
    return [p for p in points if source is None or p.payload["source"] == source]


def test_chunks_overlap_and_respect_size():
    text = " ".join(f"word{i}" for i in range(200))
    chunks = chunk_text(text, size=100, overlap=20)
    assert len(chunks) > 1
    assert all(len(chunk) <= 100 for chunk in chunks)
    assert chunks[0][-10:] in chunks[1]  # neighbouring chunks share text
    assert " ".join(chunks).count("word199") >= 1


def test_short_and_empty_text():
    assert chunk_text("short text") == ["short text"]
    assert chunk_text("") == []


@pytest.mark.parametrize("name", SAMPLE_PDFS)
def test_sample_pdfs_have_text(name):
    assert len(extract_text(DOCS_DIR / name)) > 200


def test_doctors_pdf_mentions_skin_doctor():
    text = extract_text(DOCS_DIR / "doctors.pdf")
    assert "dermatologist" in text and "skin" in text


def test_ingest_stores_source_and_text(client):
    count = ingest_file(client, DOCS_DIR / "doctors.pdf", fake_embed)
    points = stored(client, "doctors.pdf")
    assert count == len(points) > 0
    assert all(
        p.payload["text"] and p.payload["source"] == "doctors.pdf" for p in points
    )


def test_rerun_does_not_duplicate_points(client):
    for name in SAMPLE_PDFS:
        ingest_file(client, DOCS_DIR / name, fake_embed)
    first = sorted(p.id for p in stored(client))
    for name in SAMPLE_PDFS:
        ingest_file(client, DOCS_DIR / name, fake_embed)
    assert sorted(p.id for p in stored(client)) == first


def test_shorter_file_removes_stale_chunks_of_that_source_only(client, tmp_path):
    long_pdf = tmp_path / "policies.pdf"
    write_pdf(long_pdf, "Policies", ["word " * 150] * 4)
    ingest_file(client, DOCS_DIR / "doctors.pdf", fake_embed)
    before_long = ingest_file(client, long_pdf, fake_embed)
    doctors_count = len(stored(client, "doctors.pdf"))

    write_pdf(long_pdf, "Policies", ["word " * 20])
    after_short = ingest_file(client, long_pdf, fake_embed)

    assert after_short < before_long
    assert len(stored(client, "policies.pdf")) == after_short
    assert len(stored(client, "doctors.pdf")) == doctors_count


def test_main_prints_one_line_per_pdf(monkeypatch, capsys):
    memory = QdrantClient(":memory:")
    monkeypatch.setattr(ingest, "QdrantClient", lambda url: memory)
    monkeypatch.setattr(ingest, "openai_embedder", fake_embed)
    ingest.main()
    lines = capsys.readouterr().out.splitlines()
    assert [line.split(":")[0] for line in lines] == SAMPLE_PDFS
    assert all(line.endswith("chunks stored") for line in lines)
