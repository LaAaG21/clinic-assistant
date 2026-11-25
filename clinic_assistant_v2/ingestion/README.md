# PDF ingestion (item 4)

`ingest.py` reads every PDF in `ingestion/docs/`, splits the text into overlapping
chunks (600 characters, 100 overlap), embeds them with `text-embedding-3-small`
and upserts them into the Qdrant collection `clinic_docs` with `source` (the file
name) and `text` in the payload.

Sample PDFs with made-up data: `doctors.pdf`, `facilities.pdf`, `policies.pdf`
(regenerate with `uv run python -m ingestion.make_sample_pdfs`).

## Run

Start Qdrant, then run from `clinic_assistant_v2/` with your `.env` filled in:

```sh
docker compose up -d qdrant
uv run --env-file .env python -m ingestion.ingest
```

Expected output, one line per file:

```text
doctors.pdf: 2 chunks stored
facilities.pdf: 2 chunks stored
policies.pdf: 2 chunks stored
```

The script is safe to re-run: point ids are derived from `(source, chunk index)`,
so a second run overwrites the same points, and chunks left over from a shorter
version of a file are deleted.

Configuration (environment variables): `QDRANT_URL` (default
`http://localhost:6333`), `QDRANT_COLLECTION` (default `clinic_docs`),
`OPENAI_API_KEY`. Inside Docker use `QDRANT_URL=http://qdrant:6333`.

## Tests

```sh
uv run pytest tests/test_ingest.py
```

They use an in-memory Qdrant and a fake embedder, so they need no key or Docker.
