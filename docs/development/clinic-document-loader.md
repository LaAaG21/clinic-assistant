# Clinic document loader (#21)

`clinic_assistant.documents.load_document(path)` reads one complete UTF-8 Markdown
file and returns an immutable `ClinicDocument` with `source_id`, `source_name`,
and `text`. Both source fields are the original filename, including its case.
This follows the input demonstrated in the merged [#5 research](../research/clinic-document-retrieval.md):
UTF-8 `.md` files and filename source IDs. It does not change the proposed
retrieval recommendation or claim an accepted research ADR.

## Input and identity contract

- Accept a `str` or `pathlib.Path` naming a regular `.md` file. The extension
  check is case-insensitive; the returned source name is never lowercased.
- Decode UTF-8 strictly and retain the entire text, including headings, all
  paragraphs, leading/trailing whitespace, Unicode, original line endings,
  and a UTF-8 BOM if present. A BOM alone is not meaningful content.
- Repeated loads, relative/absolute paths, and content edits preserve filename
  identity. A rename changes identity. IDs are not content hashes or versions.
- Filenames must be unique within the caller's document corpus. Two paths with
  the same filename have the same source ID; callers must not combine colliding
  names from different directories as distinct documents. This single-file
  loader neither recursively discovers documents nor manages a corpus registry.

Source identity is attached before any future passage creation so every passage
can carry provenance back to the original document. Normalizing or splitting
text here could lose evidence or formatting needed by later stages. The loader
performs no chunking, retrieval, embeddings, or answer generation, and imports no
research code. No database or model key is needed.

## Errors

All expected input failures raise `DocumentLoadError`, a `ValueError` subclass.
It exposes `path` and a stable `reason` code; the message identifies the path and
problem without echoing document contents. Loading fails rather than returning
an empty/partial document.

| Reason | Input problem |
| --- | --- |
| `missing_path` | Path does not exist, including removal before reading. |
| `not_a_file` | Path refers to a directory or another non-regular file. |
| `unsupported_format` | Existing file does not have a `.md` extension. |
| `unreadable_file` | Metadata/read operation fails with an OS error, such as permission denied. |
| `invalid_encoding` | File cannot be decoded as UTF-8. |
| `empty_document` | Content is empty or whitespace-only (optionally with a leading BOM). |

## Reproduce the two-document demonstration

After `uv sync --locked --group dev`, save and run this with `uv run --locked python demo.py`:

```python
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
import json

from clinic_assistant.documents import load_document

samples = {
    "clinic-hours.md": "# Hours\nOpen Monday.\n\nClosed Sunday.\n",
    "access.md": "Free parking.\nWheelchair ramp.\n",
}
with TemporaryDirectory() as directory:
    documents = []
    for name, text in samples.items():
        path = Path(directory) / name
        path.write_bytes(text.encode("utf-8"))
        document = load_document(path)
        assert load_document(path) == document
        documents.append(asdict(document))
    print(json.dumps(documents, indent=2))
```

Actual complete returned values (escaped newlines represent the retained text):

```json
[
  {
    "source_id": "clinic-hours.md",
    "source_name": "clinic-hours.md",
    "text": "# Hours\nOpen Monday.\n\nClosed Sunday.\n"
  },
  {
    "source_id": "access.md",
    "source_name": "access.md",
    "text": "Free parking.\nWheelchair ramp.\n"
  }
]
```

## Verification

From the repository root:

```sh
uv sync --locked --group dev
uv run --locked pytest tests/test_documents.py -q
uv run --locked pytest --cov --cov-report=term-missing
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked mypy .
```

Verified on 2026-11-02 with Python 3.12.15 and the existing committed lockfile:
**13 loader cases + 1 foundation startup/OpenAPI case passed (14 total)**;
**100% application statement/branch coverage**; Ruff lint/format and strict Mypy
passed. The two-document demonstration above ran successfully and repeated loads
were identical. Permission failures are injected in a focused test because real
permission-bit behavior differs across Windows and privileged test runners.
