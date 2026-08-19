"""Tests for services.pdf_text_extractor.extract_text.

Uses small, locally generated PDF fixtures (via pypdf itself) — no real
network access and no external fixture files.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from pypdf import PdfWriter

from services.pdf_text_extractor import PDFExtractionError, extract_text

# A minimal, hand-written single-page PDF with a real text content stream.
# pypdf can recover it even though the xref/trailer offsets are bogus,
# which is common enough in the wild that it's worth covering directly.
_MINIMAL_TEXT_PDF = b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 58 >>
stream
BT /F1 24 Tf 20 100 Td (Hello Recruitment) Tj ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
trailer
<< /Size 6 /Root 1 0 R >>
startxref
0
%%EOF
"""


def write_pdf(tmp_path: Path, name: str, content: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(content)
    return path


def test_extracts_text_from_a_valid_pdf(tmp_path: Path) -> None:
    path = write_pdf(tmp_path, "notice.pdf", _MINIMAL_TEXT_PDF)

    text = extract_text(path)

    assert "Hello Recruitment" in text


def test_accepts_string_path_as_well_as_path_object(tmp_path: Path) -> None:
    path = write_pdf(tmp_path, "notice.pdf", _MINIMAL_TEXT_PDF)

    text = extract_text(str(path))

    assert "Hello Recruitment" in text


def test_empty_pdf_returns_empty_string_not_an_error(tmp_path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)

    path = write_pdf(tmp_path, "blank.pdf", buf.getvalue())

    assert extract_text(path) == ""


def test_invalid_pdf_raises_extraction_error(tmp_path: Path) -> None:
    path = write_pdf(tmp_path, "not_a_pdf.pdf", b"this is not a pdf file at all")

    with pytest.raises(PDFExtractionError):
        extract_text(path)


def test_zero_byte_file_raises_extraction_error(tmp_path: Path) -> None:
    path = write_pdf(tmp_path, "empty_file.pdf", b"")

    with pytest.raises(PDFExtractionError):
        extract_text(path)


def test_missing_file_raises_extraction_error(tmp_path: Path) -> None:
    with pytest.raises(PDFExtractionError):
        extract_text(tmp_path / "does_not_exist.pdf")


def test_encrypted_pdf_without_a_usable_password_raises_extraction_error(tmp_path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt(user_password="secret123", owner_password="ownersecret")

    buf = io.BytesIO()
    writer.write(buf)
    path = write_pdf(tmp_path, "encrypted.pdf", buf.getvalue())

    with pytest.raises(PDFExtractionError):
        extract_text(path)


def test_encrypted_pdf_with_empty_password_is_readable(tmp_path: Path) -> None:
    """Some real-world PDFs are 'encrypted' only for permissions, with an
    empty user password — those should still extract successfully."""
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    writer.encrypt(user_password="", owner_password="ownersecret")

    buf = io.BytesIO()
    writer.write(buf)
    path = write_pdf(tmp_path, "soft_encrypted.pdf", buf.getvalue())

    # A blank page has no text, but this must not raise.
    assert extract_text(path) == ""
