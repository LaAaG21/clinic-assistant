"""Exercise application startup and the public API documentation contract."""

from importlib.metadata import version

from fastapi.testclient import TestClient
from openapi_spec_validator import validate

from clinic_assistant.main import app


def test_application_starts_and_serves_valid_openapi() -> None:
    # The context manager runs the ASGI startup and shutdown lifecycle.
    with TestClient(app) as client:
        response = client.get("/openapi.json")

        assert response.status_code == 200
        assert response.headers["content-type"] == "application/json"
        specification = response.json()
        validate(specification)
        assert specification["info"]["title"] == "Clinic Front-Desk Assistant"
        assert specification["info"]["version"] == version("clinic-assistant")

        # The served Swagger page must point at the working schema URL.
        documentation = client.get("/docs")
        assert documentation.status_code == 200
        assert "/openapi.json" in documentation.text
