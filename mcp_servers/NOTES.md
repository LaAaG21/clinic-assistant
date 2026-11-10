# Notes: Clinic MCP Servers

An MCP server is a program that offers tools to AI agents through a standard protocol, so a client can list its tools and call them by name. The server also enforces the rules, for example checking that a patient is registered or that a doctor is free before booking.

A tool is a normal Python function that is registered on the server with `@mcp.tool`, so a client can call it by name; its docstring becomes the tool's description and its type hints become its input schema.

From the Clinic diagram I built the three MCP servers (Booking on port 8001 with `register_patient` and `book_appointment`, Pharmacy on 8002 with `view_inventory` and `add_inventory`, and Medical Reports on 8003 with `get_patient_medical_records` and `get_opd_records`) and one async client that plays the role of the agents' MCP Client, plus a small hello warm-up. I skipped the agents, UI, API gateway, auth, Temporal, Redis, Postgres, Qdrant and monitoring, and kept all data in memory with plain dicts and lists instead of a database.
