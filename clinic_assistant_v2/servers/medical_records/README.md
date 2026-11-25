# Medical Records MCP (item 3, port 8003)

Tools (no user argument; the user is `sub` from the verified Bearer JWT, scope `records:read`):

- `get_my_medical_records()` returns the caller's records, oldest first.
- `get_my_last_medical_record()` returns `{"date", "diagnosis", "notes"}` for the newest one.

Any missing, malformed, expired, wrongly signed or under-scoped token returns
`{"error": "unauthorized"}` and no data. Seed data: `user-a` and `user-b` in `server.py`.
`auth.py` is a copy of `shared/auth.py`; a test fails if they differ.

```sh
uv run pytest tests/test_medical_records.py
docker compose up --build medical-records-mcp
```
