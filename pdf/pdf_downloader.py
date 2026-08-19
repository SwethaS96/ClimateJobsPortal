"""Download and persist PDF files for parsed notifications."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from database.repositories.pdf_repository import (
    get_pdf_documents_by_notification,
    insert_pdf_document,
    update_pdf_document,
)
from parser.models import ParsedNotification


class PDFDownloader:
    """Download PDF documents referenced by ParsedNotification objects.

    A `pdf_documents` row is always created up front (association), before
    any network call — so a notification's PDF is linked even if the
    download itself later fails. The download attempt then updates that
    same row rather than ever crashing: a bad PDF (network error, 404,
    5xx, ...) is recorded via `downloaded=False` / `http_status`, and the
    caller gets a result dict describing what happened instead of an
    exception.
    """

    def __init__(self, download_dir: Optional[Path] = None, session: Optional[requests.Session] = None) -> None:
        self.download_dir = download_dir or Path("data/downloads")
        self.session = session or requests.Session()

    def download_for_notification(self, notification: ParsedNotification, notification_id: int) -> dict[str, object]:
        """Ensure the notification's PDF is associated and, if possible, downloaded.

        Returns a dict with `downloaded`, `skipped`, `path`, `checksum`,
        `id` (the `pdf_documents` row id, or None if there was no
        `pdf_url`), `http_status`, and — on failure — an `error` message.
        Never raises.
        """
        pdf_url = notification.pdf_url
        if not pdf_url:
            return {
                "downloaded": False,
                "skipped": True,
                "path": None,
                "checksum": None,
                "id": None,
                "http_status": None,
            }

        self.download_dir.mkdir(parents=True, exist_ok=True)

        existing_documents = get_pdf_documents_by_notification(notification_id)
        existing_row = next((row for row in existing_documents if row["pdf_url"] == pdf_url), None)

        if existing_row is not None and existing_row["downloaded"]:
            return {
                "downloaded": False,
                "skipped": True,
                "path": existing_row["local_file"],
                "checksum": existing_row["checksum"],
                "id": existing_row["id"],
                "http_status": existing_row["http_status"],
            }

        pdf_document_id = (
            existing_row["id"]
            if existing_row is not None
            else insert_pdf_document(
                notification_id=notification_id,
                document_type=None,
                pdf_url=pdf_url,
                local_file=None,
                checksum=None,
                downloaded=False,
                downloaded_at=None,
                file_size=None,
            )
        )

        try:
            response = self.session.get(pdf_url, timeout=10)
        except requests.RequestException as exc:
            return {
                "downloaded": False,
                "skipped": False,
                "path": None,
                "checksum": None,
                "id": pdf_document_id,
                "http_status": None,
                "error": str(exc),
            }

        http_status = response.status_code

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            update_pdf_document(pdf_document_id=pdf_document_id, downloaded=False, http_status=http_status)
            return {
                "downloaded": False,
                "skipped": False,
                "path": None,
                "checksum": None,
                "id": pdf_document_id,
                "http_status": http_status,
                "error": str(exc),
            }

        file_bytes = response.content
        checksum = hashlib.sha256(file_bytes).hexdigest()
        file_name = f"{checksum}.pdf"
        local_path = self.download_dir / file_name

        if not local_path.exists():
            local_path.write_bytes(file_bytes)

        file_size = local_path.stat().st_size
        downloaded_at = datetime.now(timezone.utc).isoformat()
        headers = response.headers or {}
        content_type = headers.get("Content-Type", "application/pdf")

        update_pdf_document(
            pdf_document_id=pdf_document_id,
            document_type=content_type,
            local_file=str(local_path),
            checksum=checksum,
            downloaded=True,
            downloaded_at=downloaded_at,
            file_size=file_size,
            http_status=http_status,
        )

        return {
            "downloaded": True,
            "skipped": False,
            "path": str(local_path),
            "checksum": checksum,
            "id": pdf_document_id,
            "http_status": http_status,
        }
