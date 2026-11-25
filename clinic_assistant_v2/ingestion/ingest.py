"""PDF ingestion workflow (item 4): PDF text -> chunks -> embeddings -> Qdrant.

Safe to re-run: point ids are derived from (source, chunk index), so a second run
overwrites the same points, and chunks left over from a shorter file are removed.

Run: uv run python -m ingestion.ingest
"""

import os
import uuid
from collections.abc import Callable
from pathlib import Path

from openai import OpenAI
from pypdf import PdfReader
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    HasIdCondition,
    MatchValue,
    PointStruct,
    VectorParams,
)

COLLECTION = os.environ.get("QDRANT_COLLECTION", "clinic_docs")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_SIZE = 1536
CHUNK_CHARS = 600
CHUNK_OVERLAP = 100
DOCS_DIR = Path(__file__).parent / "docs"

Embedder = Callable[[list[str]], list[list[float]]]


def extract_text(pdf_path: Path) -> str:
    """Return the text of every page, with whitespace collapsed."""
    pages = (page.extract_text() or "" for page in PdfReader(pdf_path).pages)
    return " ".join(" ".join(pages).split())


def chunk_text(
    text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP
) -> list[str]:
    """Split text into overlapping windows, cutting at a space when possible."""
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            end = text.rfind(" ", start + overlap + 1, end) + 1 or end
        chunks.append(text[start:end].strip())
        if end == len(text):
            break
        start = end - overlap
    return chunks


def openai_embedder(texts: list[str]) -> list[list[float]]:
    """Embed texts with OpenAI. The key is read from OPENAI_API_KEY."""
    response = OpenAI().embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [item.embedding for item in response.data]


def point_id(source: str, index: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{source}#{index}"))


def ensure_collection(client: QdrantClient) -> None:
    if not client.collection_exists(COLLECTION):
        client.create_collection(
            COLLECTION,
            vectors_config=VectorParams(size=EMBEDDING_SIZE, distance=Distance.COSINE),
        )


def ingest_file(client: QdrantClient, pdf_path: Path, embed: Embedder) -> int:
    """Store one PDF's chunks in Qdrant and return how many chunks it has."""
    source = pdf_path.name
    chunks = chunk_text(extract_text(pdf_path))
    ids = [point_id(source, index) for index in range(len(chunks))]
    if chunks:
        client.upsert(
            COLLECTION,
            points=[
                PointStruct(
                    id=chunk_id,
                    vector=vector,
                    payload={"source": source, "text": chunk},
                )
                for chunk_id, vector, chunk in zip(
                    ids, embed(chunks), chunks, strict=True
                )
            ],
        )
    client.delete(
        COLLECTION,
        points_selector=Filter(
            must=[FieldCondition(key="source", match=MatchValue(value=source))],
            must_not=[HasIdCondition(has_id=ids)],
        ),
    )
    return len(chunks)


def main() -> None:
    client = QdrantClient(url=QDRANT_URL)
    ensure_collection(client)
    for pdf_path in sorted(DOCS_DIR.glob("*.pdf")):
        count = ingest_file(client, pdf_path, openai_embedder)
        print(f"{pdf_path.name}: {count} chunks stored")


if __name__ == "__main__":
    main()
