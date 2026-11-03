"""Bounded paragraph passages with exact source-text character locations."""

import re
from dataclasses import dataclass
from typing import Protocol

MAX_PASSAGE_CHARS = 1000
# Atomic line endings prevent one CRLF from backtracking into a false blank line.
_BLANK_LINE = re.compile(r"(?>\r\n|\r|\n)[^\S\r\n]*(?>\r\n|\r|\n)")


class DocumentSource(Protocol):
    """Read-only view of #21's ClinicDocument; no duplicate loader implementation."""

    @property
    def source_id(self) -> str: ...

    @property
    def source_name(self) -> str: ...

    @property
    def text(self) -> str: ...


@dataclass(frozen=True, slots=True)
class Passage:
    passage_id: str
    source_id: str
    source_name: str
    text: str
    start_char: int
    end_char: int


def split_document(document: DocumentSource) -> list[Passage]:
    """Trim paragraph/chunk edges, preserve internal text, and never overlap.

    Offsets are zero-based Unicode character positions, end-exclusive, in the
    unchanged loaded text. Source IDs must be unique within the caller's corpus.
    """
    text = document.text
    boundaries = [(match.start(), match.end()) for match in _BLANK_LINE.finditer(text)]
    passages = []
    start = 0
    for paragraph_end, next_start in [*boundaries, (len(text), len(text))]:
        end = paragraph_end
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        while start < end:
            stop = min(start + MAX_PASSAGE_CHARS, end)
            if stop < end:
                whitespace = stop
                while whitespace > start and not text[whitespace].isspace():
                    whitespace -= 1
                if whitespace > start:
                    stop = whitespace
            chunk_end = stop
            while chunk_end > start and text[chunk_end - 1].isspace():
                chunk_end -= 1
            # Length-prefix the source ID so delimiters inside filenames cannot
            # collide with the source/offset separators of a different document.
            identity = (
                f"{len(document.source_id)}:{document.source_id}:{start}:{chunk_end}"
            )
            passages.append(
                Passage(
                    identity,
                    document.source_id,
                    document.source_name,
                    text[start:chunk_end],
                    start,
                    chunk_end,
                )
            )
            start = stop
            while start < end and text[start].isspace():
                start += 1
        start = next_start
    return passages
