"""Tests for services.pdf_processing_service.PDFProcessingService.

Uses a real `PDFDownloader` backed by a mocked `requests` session (no real
network) against an isolated temp database, so both the download and the
extraction step exercise their real code paths.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import requests

import database.connection as connection_module
from database.repositories.pdf_repository import get_pdf_document_by_id
from database.schema import create_schema
from parser.models import ParsedNotification
from pdf.pdf_downloader import PDFDownloader
from services import pdf_processing_service as pdf_processing_service_module
from services.pdf_processing_service import PDFProcessingService

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


@pytest.fixture()
def isolated_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "climate_jobs.db"
    monkeypatch.setattr(connection_module, "DATABASE_PATH", db_path)

    conn = connection_module.get_connection()
    try:
        create_schema(conn)
        conn.execute(
            """
            INSERT INTO organizations (name, short_name, homepage_url, country, state, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("Test Org", "TST", "https://example.org", "India", "Tamil Nadu",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            """
            INSERT INTO websites (organization_id, page_name, url, parser_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (1, "Jobs", "https://example.org/jobs", "generic_html",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.execute(
            """
            INSERT INTO notifications (organization_id, website_id, title, page_url, hash, first_seen, last_seen, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (1, 1, "Test Role", "https://example.org/jobs/1", "hash-1",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00",
             "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()
    finally:
        connection_module.close_connection(conn)

    return db_path


def make_response(content: bytes, status_code: int = 200) -> Mock:
    response = Mock()
    response.content = content
    response.status_code = status_code
    response.headers = {"Content-Type": "application/pdf"}
    response.raise_for_status.return_value = None
    return response


def make_notification(pdf_url: str | None = "https://example.org/files/notice.pdf") -> ParsedNotification:
    return ParsedNotification(title="Test Role", url="https://example.org/jobs/1", pdf_url=pdf_url)


def test_downloads_and_extracts_text_successfully(isolated_db: Path, tmp_path: Path) -> None:
    session = Mock()
    session.get.return_value = make_response(_MINIMAL_TEXT_PDF)
    downloader = PDFDownloader(download_dir=tmp_path / "downloads", session=session)
    service = PDFProcessingService(pdf_downloader=downloader)

    result = service.process(make_notification(), notification_id=1)

    assert result["downloaded"] is True
    assert result["extraction_status"] == "SUCCESS"
    assert "Hello Recruitment" in result["extracted_text"]

    row = get_pdf_document_by_id(result["id"])
    assert row["extraction_status"] == "SUCCESS"
    assert "Hello Recruitment" in row["extracted_text"]


def test_no_pdf_url_skips_download_and_extraction(isolated_db: Path, tmp_path: Path) -> None:
    session = Mock()
    downloader = PDFDownloader(download_dir=tmp_path / "downloads", session=session)
    service = PDFProcessingService(pdf_downloader=downloader)

    result = service.process(make_notification(pdf_url=None), notification_id=1)

    assert result["extraction_status"] is None
    assert result["extracted_text"] is None
    session.get.assert_not_called()


def test_download_failure_leaves_extraction_untouched(isolated_db: Path, tmp_path: Path) -> None:
    session = Mock()
    response = Mock()
    response.status_code = 404
    response.headers = {}
    response.raise_for_status.side_effect = requests.HTTPError("404 Client Error")
    session.get.return_value = response

    downloader = PDFDownloader(download_dir=tmp_path / "downloads", session=session)
    service = PDFProcessingService(pdf_downloader=downloader)

    result = service.process(make_notification(), notification_id=1)

    assert result["downloaded"] is False
    assert result["extraction_status"] is None
    assert result["extracted_text"] is None


def test_invalid_pdf_content_is_recorded_as_failed_without_raising(isolated_db: Path, tmp_path: Path) -> None:
    session = Mock()
    session.get.return_value = make_response(b"this is not a real pdf file")
    downloader = PDFDownloader(download_dir=tmp_path / "downloads", session=session)
    service = PDFProcessingService(pdf_downloader=downloader)

    result = service.process(make_notification(), notification_id=1)

    assert result["downloaded"] is True  # the bytes downloaded fine, they just aren't a valid PDF
    assert result["extraction_status"] == "FAILED"
    assert result["extracted_text"] is None
    assert "extraction_error" in result

    row = get_pdf_document_by_id(result["id"])
    assert row["extraction_status"] == "FAILED"


def test_empty_pdf_is_recorded_as_empty_not_failed(isolated_db: Path, tmp_path: Path) -> None:
    from pypdf import PdfWriter
    import io

    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)

    session = Mock()
    session.get.return_value = make_response(buf.getvalue())
    downloader = PDFDownloader(download_dir=tmp_path / "downloads", session=session)
    service = PDFProcessingService(pdf_downloader=downloader)

    result = service.process(make_notification(), notification_id=1)

    assert result["extraction_status"] == "EMPTY"
    assert result["extracted_text"] == ""


def test_repeated_processing_does_not_redo_extraction(isolated_db: Path, tmp_path: Path) -> None:
    session = Mock()
    session.get.return_value = make_response(_MINIMAL_TEXT_PDF)
    downloader = PDFDownloader(download_dir=tmp_path / "downloads", session=session)
    service = PDFProcessingService(pdf_downloader=downloader)
    notification = make_notification()

    with patch.object(
        pdf_processing_service_module, "extract_text", wraps=pdf_processing_service_module.extract_text
    ) as spy:
        first = service.process(notification, notification_id=1)
        second = service.process(notification, notification_id=1)

    assert spy.call_count == 1
    assert first["extraction_status"] == "SUCCESS"
    assert second["extraction_status"] == "SUCCESS"
    assert second["extracted_text"] == first["extracted_text"]
    # The second call hit the "already downloaded" branch, so no new HTTP call either.
    assert session.get.call_count == 1
