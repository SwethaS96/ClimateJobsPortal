"""Tests for the PDF downloader."""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

import database.connection as connection_module
from database.repositories.pdf_repository import get_pdf_documents_by_notification
from database.schema import create_schema
from parser.models import ParsedNotification
from pdf.pdf_downloader import PDFDownloader


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
            (
                "Test Org",
                "TST",
                "https://example.org",
                "India",
                "Tamil Nadu",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO websites (organization_id, page_name, url, parser_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                "Jobs",
                "https://example.org/jobs",
                "generic_html",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.execute(
            """
            INSERT INTO notifications (organization_id, website_id, title, page_url, hash, first_seen, last_seen, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1,
                1,
                "Test Role",
                "https://example.org/jobs/1",
                "hash-1",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.commit()
    finally:
        connection_module.close_connection(conn)

    return db_path


def make_success_response(content: bytes = b"%PDF-1.4\n%hello\n") -> Mock:
    response = Mock()
    response.content = content
    response.status_code = 200
    response.headers = {"Content-Type": "application/pdf"}
    response.raise_for_status.return_value = None
    return response


def test_downloads_pdf_and_records_checksum(isolated_db: Path, tmp_path: Path) -> None:
    session = Mock()
    response = make_success_response()
    session.get.return_value = response

    downloader = PDFDownloader(download_dir=tmp_path / "downloads", session=session)
    notification = ParsedNotification(
        title="Test Role",
        url="https://example.org/jobs/1",
        pdf_url="https://example.org/files/test.pdf",
    )

    result = downloader.download_for_notification(notification, notification_id=1)

    expected_checksum = hashlib.sha256(response.content).hexdigest()

    assert result["downloaded"] is True
    assert result["skipped"] is False
    assert result["checksum"] == expected_checksum
    assert result["http_status"] == 200
    assert result["id"] is not None
    assert Path(result["path"]).exists()


def test_skips_download_when_pdf_already_exists(isolated_db: Path, tmp_path: Path) -> None:
    session = Mock()
    session.get.return_value = make_success_response()

    downloader = PDFDownloader(download_dir=tmp_path / "downloads", session=session)
    notification = ParsedNotification(
        title="Test Role",
        url="https://example.org/jobs/1",
        pdf_url="https://example.org/files/test.pdf",
    )

    first = downloader.download_for_notification(notification, notification_id=1)
    second = downloader.download_for_notification(notification, notification_id=1)

    assert first["downloaded"] is True
    assert second["downloaded"] is False
    assert second["skipped"] is True
    assert second["id"] == first["id"]
    assert session.get.call_count == 1


def test_no_pdf_url_is_a_no_op() -> None:
    downloader = PDFDownloader(download_dir=Path("/tmp/unused"), session=Mock())
    notification = ParsedNotification(title="Test Role", url="https://example.org/jobs/1")

    result = downloader.download_for_notification(notification, notification_id=1)

    assert result == {
        "downloaded": False,
        "skipped": True,
        "path": None,
        "checksum": None,
        "id": None,
        "http_status": None,
    }


def test_pdf_document_is_associated_even_when_download_fails(isolated_db: Path, tmp_path: Path) -> None:
    """A 404 must not crash the caller — the association row must still
    exist so the failure is visible, but nothing is written to disk."""
    session = Mock()
    response = Mock()
    response.status_code = 404
    response.headers = {}
    response.raise_for_status.side_effect = requests.HTTPError("404 Client Error")
    session.get.return_value = response

    downloader = PDFDownloader(download_dir=tmp_path / "downloads", session=session)
    notification = ParsedNotification(
        title="Test Role",
        url="https://example.org/jobs/1",
        pdf_url="https://example.org/files/missing.pdf",
    )

    result = downloader.download_for_notification(notification, notification_id=1)

    assert result["downloaded"] is False
    assert result["skipped"] is False
    assert result["path"] is None
    assert result["http_status"] == 404
    assert "error" in result
    assert result["id"] is not None

    rows = get_pdf_documents_by_notification(1)
    assert len(rows) == 1
    assert rows[0]["downloaded"] == 0
    assert rows[0]["http_status"] == 404
    assert rows[0]["pdf_url"] == "https://example.org/files/missing.pdf"


def test_connection_error_does_not_raise(isolated_db: Path, tmp_path: Path) -> None:
    session = Mock()
    session.get.side_effect = requests.ConnectionError("connection refused")

    downloader = PDFDownloader(download_dir=tmp_path / "downloads", session=session)
    notification = ParsedNotification(
        title="Test Role",
        url="https://example.org/jobs/1",
        pdf_url="https://example.org/files/test.pdf",
    )

    result = downloader.download_for_notification(notification, notification_id=1)

    assert result["downloaded"] is False
    assert result["path"] is None
    assert result["http_status"] is None
    assert "connection refused" in result["error"]
