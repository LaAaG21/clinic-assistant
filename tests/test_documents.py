"""Complete-document loading and input failures using tiny temporary files."""

from pathlib import Path

import pytest

from clinic_assistant.documents import DocumentLoadError, load_document


def test_two_documents_keep_complete_text_and_original_names(tmp_path: Path) -> None:
    samples = {
        "clinic-hours.md": (
            "# Clinic hours\r\n\r\nOpen 09:00-17:00.\r\n\r\nClosed Sunday.\r\n"
        ),
        "Access.MD": "  # Access\n\nFree parking.\n\nمدخل العيادة ♿\n  ",
    }
    for filename, text in samples.items():
        path = tmp_path / filename
        path.write_bytes(text.encode("utf-8"))
        document = load_document(path)
        assert document.text == text
        assert document.source_id == filename
        assert document.source_name == filename
        assert load_document(str(path)) == document


def test_identity_survives_relative_paths_and_content_updates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "hours.md"
    path.write_text("Original policy", encoding="utf-8")
    first = load_document(path)
    monkeypatch.chdir(tmp_path)
    assert load_document("hours.md") == first
    path.write_text("Updated policy", encoding="utf-8")
    updated = load_document(path)
    assert updated.source_id == first.source_id
    assert updated.source_name == first.source_name
    assert updated.text == "Updated policy"


@pytest.mark.parametrize(
    "content", [b"", b" \r\n\t", "\u2003\u00a0".encode(), b"\xef\xbb\xbf\n"]
)
def test_empty_content_has_clear_error(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "empty.md"
    path.write_bytes(content)
    with pytest.raises(DocumentLoadError, match="no non-whitespace text") as error:
        load_document(path)
    assert error.value.reason == "empty_document"
    assert error.value.path == path


def test_missing_input_path(tmp_path: Path) -> None:
    path = tmp_path / "missing.md"
    with pytest.raises(DocumentLoadError, match="does not exist") as error:
        load_document(path)
    assert error.value.reason == "missing_path"
    assert str(path) in str(error.value)


def test_directory_is_not_a_document(tmp_path: Path) -> None:
    with pytest.raises(DocumentLoadError, match="regular file") as error:
        load_document(tmp_path)
    assert error.value.reason == "not_a_file"


def test_unsupported_format(tmp_path: Path) -> None:
    path = tmp_path / "clinic.pdf"
    path.write_bytes(b"not Markdown")
    with pytest.raises(DocumentLoadError, match=r"Markdown \(\.md\)") as error:
        load_document(path)
    assert error.value.reason == "unsupported_format"


def test_invalid_encoding_identifies_path_without_echoing_content(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invalid.md"
    path.write_bytes(b"private example \xff")
    with pytest.raises(DocumentLoadError, match="not valid UTF-8") as error:
        load_document(path)
    assert error.value.reason == "invalid_encoding"
    assert str(path) in str(error.value)
    assert "private example" not in str(error.value)


def test_unreadable_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "unreadable.md"
    path.write_text("Policy", encoding="utf-8")

    def denied(_path: Path) -> bytes:
        raise PermissionError("Access denied")

    # Permission bits behave differently on Windows/root; inject the OS error.
    monkeypatch.setattr(Path, "read_bytes", denied)
    with pytest.raises(DocumentLoadError, match="cannot be read") as error:
        load_document(path)
    assert error.value.reason == "unreadable_file"
    assert error.value.path == path


def test_file_removed_between_stat_and_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "removed.md"
    path.write_text("Policy", encoding="utf-8")

    def removed(_path: Path) -> bytes:
        raise FileNotFoundError("File disappeared")

    monkeypatch.setattr(Path, "read_bytes", removed)
    with pytest.raises(DocumentLoadError) as error:
        load_document(path)
    assert error.value.reason == "missing_path"


def test_bom_is_preserved_with_document_text(tmp_path: Path) -> None:
    path = tmp_path / "bom.md"
    text = "\ufeff# Hours\nOpen Monday.\n"
    path.write_bytes(text.encode("utf-8"))
    assert load_document(path).text == text
