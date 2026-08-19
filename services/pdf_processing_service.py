"""Orchestrates PDF download + text extraction for a notification's PDF.

Ties together the existing `PDFDownloader` (association + download) and
`extract_text` (local text extraction) into one call. A PDF failure of any
kind — download failure, invalid/empty/encrypted PDF, extraction error —
is recorded on the `pdf_documents` row and returned in the result dict; it
never raises, so a single bad PDF can never fail the surrounding website
scrape.
"""

from __future__ import annotations

from database.repositories.pdf_repository import get_pdf_document_by_id, update_pdf_document
from parser.models import ParsedNotification
from pdf.pdf_downloader import PDFDownloader
from services.pdf_text_extractor import PDFExtractionError, extract_text

EXTRACTION_SUCCESS = "SUCCESS"
EXTRACTION_EMPTY = "EMPTY"
EXTRACTION_FAILED = "FAILED"


class PDFProcessingService:
    """Downloads a notification's PDF (if any) and extracts its text."""

    def __init__(self, pdf_downloader: PDFDownloader | None = None) -> None:
        self.pdf_downloader = pdf_downloader or PDFDownloader()

    def process(self, notification: ParsedNotification, notification_id: int) -> dict[str, object]:
        """Download the notification's PDF (if any) and extract its text.

        Returns the downloader's result dict extended with
        `extraction_status` (None/"SUCCESS"/"EMPTY"/"FAILED"),
        `extracted_text`, and — on extraction failure — `extraction_error`.
        """
        download_result = self.pdf_downloader.download_for_notification(notification, notification_id)

        local_path = download_result.get("path")
        pdf_document_id = download_result.get("id")

        if local_path is None or pdf_document_id is None:
            # No pdf_url, or the download never produced a local file.
            return {**download_result, "extraction_status": None, "extracted_text": None}

        existing_row = get_pdf_document_by_id(pdf_document_id)
        if existing_row is not None and existing_row["extraction_status"]:
            # Already extracted on a prior run — don't redo the work.
            return {
                **download_result,
                "extraction_status": existing_row["extraction_status"],
                "extracted_text": existing_row["extracted_text"],
            }

        try:
            text = extract_text(local_path)
        except PDFExtractionError as exc:
            update_pdf_document(pdf_document_id=pdf_document_id, extraction_status=EXTRACTION_FAILED)
            return {
                **download_result,
                "extraction_status": EXTRACTION_FAILED,
                "extracted_text": None,
                "extraction_error": str(exc),
            }

        status = EXTRACTION_SUCCESS if text.strip() else EXTRACTION_EMPTY
        update_pdf_document(pdf_document_id=pdf_document_id, extracted_text=text, extraction_status=status)
        return {**download_result, "extraction_status": status, "extracted_text": text}
