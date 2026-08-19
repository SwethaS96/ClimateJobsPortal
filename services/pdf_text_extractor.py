"""Local PDF text extraction — no OCR.

A single function, `extract_text(pdf_path) -> str`, wrapping `pypdf`. Any
failure (missing file, corrupt/invalid PDF, encrypted PDF that cannot be
opened, a page that fails to parse) is normalized into `PDFExtractionError`
so callers have one exception type to handle, rather than needing to know
`pypdf`'s internal exception hierarchy.

A PDF with no extractable text (e.g. a scanned/image-only PDF) is not a
failure here — `extract_text` returns `""` for it. Distinguishing "no text
found" from "extraction failed" is the caller's job (see
`services/pdf_processing_service.py`), since only the caller knows what to
do with that distinction (e.g. record it as EMPTY vs FAILED).
"""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


class PDFExtractionError(Exception):
    """Raised when text cannot be extracted from a PDF."""


def extract_text(pdf_path: str | Path) -> str:
    """Extract all text from a local PDF file.

    Args:
        pdf_path: Path to a PDF file already downloaded to local disk.

    Returns:
        The concatenated text of every page, whitespace-trimmed. An empty
        string means the PDF opened fine but had no extractable text.

    Raises:
        PDFExtractionError: if the file is missing, not a valid PDF, or is
            encrypted with a password this function cannot supply.
    """
    path = Path(pdf_path)
    if not path.exists():
        raise PDFExtractionError(f"PDF file not found: {path}")

    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        raise PDFExtractionError(f"Could not read PDF: {exc}") from exc

    if reader.is_encrypted:
        try:
            # Many published government PDFs are "encrypted" only with an
            # empty owner password (permissions-only, not access-restricted)
            # and are effectively still readable once that's supplied.
            decrypt_result = reader.decrypt("")
        except Exception as exc:
            raise PDFExtractionError(f"Encrypted PDF could not be decrypted: {exc}") from exc
        if not decrypt_result:
            raise PDFExtractionError("Encrypted PDF requires a password.")

    try:
        pages_text = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise PDFExtractionError(f"Failed to extract text from PDF: {exc}") from exc

    return "\n".join(pages_text).strip()
