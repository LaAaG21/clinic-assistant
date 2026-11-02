"""Container entry point: validate shared settings before accepting requests."""

import uvicorn

from clinic_assistant.settings import SettingsError, get_settings


def main() -> None:
    try:
        get_settings()
    except SettingsError as exc:
        raise SystemExit(f"Configuration error: {exc}") from None
    uvicorn.run("clinic_assistant.main:app", host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
