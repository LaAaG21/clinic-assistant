"""Load complete UTF-8 Markdown documents with their original filename identity."""

from dataclasses import dataclass
from pathlib import Path
from stat import S_ISREG
from typing import Literal

LoadFailure = Literal[
    "missing_path",
    "not_a_file",
    "unsupported_format",
    "unreadable_file",
    "invalid_encoding",
    "empty_document",
]


@dataclass(frozen=True, slots=True)
class ClinicDocument:
    source_id: str
    source_name: str
    text: str


class DocumentLoadError(ValueError):
    """An input failure with a stable reason code and the affected path."""

    def __init__(self, path: Path, reason: LoadFailure, explanation: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"Cannot load clinic document '{path}': {explanation}")


def load_document(path: str | Path) -> ClinicDocument:
    """Read one whole .md file, preserving text, line endings, and filename case.

    Filenames identify documents within a corpus, so callers must use unique
    filenames. No chunking, whitespace normalization, or retrieval is performed.
    """
    path = Path(path)
    try:
        if not S_ISREG(path.stat().st_mode):
            raise DocumentLoadError(path, "not_a_file", "expected a regular file")
        if path.suffix.lower() != ".md":
            raise DocumentLoadError(
                path, "unsupported_format", "expected a UTF-8 Markdown (.md) file"
            )
        raw = path.read_bytes()
    except FileNotFoundError:
        raise DocumentLoadError(
            path, "missing_path", "input path does not exist"
        ) from None
    except OSError:
        raise DocumentLoadError(
            path, "unreadable_file", "input file cannot be read"
        ) from None

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise DocumentLoadError(
            path, "invalid_encoding", "input is not valid UTF-8"
        ) from None
    # A UTF-8 BOM alone is not meaningful document content; retain it otherwise.
    if not text.removeprefix("\ufeff").strip():
        raise DocumentLoadError(
            path, "empty_document", "input contains no non-whitespace text"
        )

    return ClinicDocument(source_id=path.name, source_name=path.name, text=text)
