# Clinic Assistant v2 (#314)

Per-domain FastMCP servers in Docker, Qdrant for clinic documents, Google sign-in
and a signed JWT passed from FastAPI to the servers. Architecture:
[docs/architecture.md](../docs/architecture.md).

## 1. Google OAuth client

In your GCP project: APIs & Services > Credentials > Create credentials > OAuth
client ID, type **Web application**, authorized redirect URI
`http://localhost:8000/auth/callback`. Keep the client ID and secret for `.env`.

## 2. Configure `.env`

```sh
cp .env.example .env
```

Fill in `OPENAI_API_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and a long
random `JWT_SECRET` (`python -c "import secrets; print(secrets.token_urlsafe(48))"`).
`.env` is gitignored. Never commit a real value.

## 3. Start everything

```sh
docker compose up --build
```

## 4. Ingest the clinic PDFs

With Qdrant running (see [ingestion/README.md](ingestion/README.md) once item 4 is merged):

```sh
uv run --env-file .env python -m ingestion.ingest
```

## 5. Log in

Open <http://localhost:8000/auth/login> (item 6) and sign in with Google.

## 6. Tests

```sh
uv run pytest
```

Run from this folder. Servers that need extra packages use `uv run --group <name>`.

## Status

| Item | Deliverable | Status |
|---|---|---|
| 1 | Appointments MCP | see its PR |
| 2 | Pharmacy Inventory MCP | open |
| 3 | Medical Records MCP | see its PR |
| 4 | PDF ingestion | see its PR |
| 5 | Knowledge retrieval MCP | open |
| 6 | FastAPI + Google OAuth + agent | open |
| 7 | Tests and compose | open (skeleton in `docker-compose.yml`) |
