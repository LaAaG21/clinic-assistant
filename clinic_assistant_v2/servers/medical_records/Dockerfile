FROM python:3.14-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
COPY servers/__init__.py servers/__init__.py
COPY servers/medical_records servers/medical_records
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8003
CMD ["python", "-m", "servers.medical_records.server"]
