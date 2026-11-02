FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
# Dev group included so pytest can run against the real database in this container.
RUN uv sync --frozen --no-install-project

COPY fake_llm.py spike.py ./
COPY tests/ ./tests/
RUN useradd --create-home spike
USER spike

# Stay alive so we can `exec` commands into it and then restart the container.
CMD ["sleep", "infinity"]
