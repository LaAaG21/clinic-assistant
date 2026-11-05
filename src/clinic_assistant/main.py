"""ASGI entry point; workflow policies belong outside the HTTP boundary."""

from fastapi import FastAPI

from clinic_assistant.errors import register_error_handlers
from clinic_assistant.health import router as health_router
from clinic_assistant.slots_api import router as slots_router

app = FastAPI(
    title="Clinic Front-Desk Assistant",
    version="0.1.0.dev0",
    description="Backend service for the clinic's existing chat client.",
)

app.include_router(health_router)
app.include_router(slots_router)
register_error_handlers(app)
