"""Tests for scripts/test_pdf_pipeline.py using mocked collaborators.

No real network or database access — the PDF processing service,
notification/pdf lookups, and HTTP session are all mocked/faked.
"""

from __future__ import annotations

import io
from unittest.mock import Mock

import pytest
import requests

import scripts.test_pdf_pipeline as pipeline


def test_parse_args_requires_one_of_notification_id_or_pdf_url():
    with pytest.raises(SystemExit):
        pipeline.parse_args([])


def test_parse_args_rejects_both_together():
    with pytest.raises(SystemExit):
        pipeline.parse_args(["--notification-id", "1", "--pdf-url", "https://example.org/a.pdf"])


def test_parse_args_notification_id():
    args = pipeline.parse_args(["--notification-id", "5"])
    assert args.notification_id == 5
    assert args.pdf_url is None


def test_parse_args_pdf_url():
    args = pipeline.parse_args(["--pdf-url", "https://example.org/a.pdf"])
    assert args.pdf_url == "https://example.org/a.pdf"
    assert args.notification_id is None


def test_unknown_notification_id_reports_failure():
    args = pipeline.parse_args(["--notification-id", "999"])
    out = io.StringIO()

    exit_code = pipeline.run(args, notification_lookup=lambda _id: None, out=out)

    assert exit_code == 1
    assert "not found" in out.getvalue()


def test_notification_without_pdf_reports_failure():
    args = pipeline.parse_args(["--notification-id", "5"])
    out = io.StringIO()

    row = {"id": 5, "title": "Some Notice", "page_url": "https://example.org/notice"}
    exit_code = pipeline.run(
        args,
        notification_lookup=lambda _id: row,
        pdf_lookup=lambda _id: [],
        out=out,
    )

    assert exit_code == 1
    assert "No PDF associated" in out.getvalue()


def test_notification_with_pdf_runs_pipeline_and_prints_preview():
    args = pipeline.parse_args(["--notification-id", "5"])
    out = io.StringIO()

    row = {"id": 5, "title": "RA Advertisement", "page_url": "https://example.org/notice"}
    pdf_rows = [{"pdf_url": "https://example.org/notice.pdf"}]

    fake_service = Mock()
    fake_service.process.return_value = {
        "downloaded": True,
        "skipped": False,
        "path": "/tmp/x.pdf",
        "http_status": 200,
        "extraction_status": "SUCCESS",
        "extracted_text": "Applications are invited for Research Associate positions." * 3,
    }

    exit_code = pipeline.run(
        args,
        pdf_processing_service=fake_service,
        notification_lookup=lambda _id: row,
        pdf_lookup=lambda _id: pdf_rows,
        out=out,
    )

    assert exit_code == 0
    fake_service.process.assert_called_once()
    called_notification, called_id = fake_service.process.call_args[0]
    assert called_notification.pdf_url == "https://example.org/notice.pdf"
    assert called_id == 5

    output = out.getvalue()
    assert "Title: RA Advertisement" in output
    assert "PDF URL: https://example.org/notice.pdf" in output
    assert "Extraction: SUCCESS" in output
    assert "Applications are invited" in output


def test_notification_with_pdf_download_failure_reports_failure():
    args = pipeline.parse_args(["--notification-id", "5"])
    out = io.StringIO()

    row = {"id": 5, "title": "RA Advertisement", "page_url": "https://example.org/notice"}
    pdf_rows = [{"pdf_url": "https://example.org/notice.pdf"}]

    fake_service = Mock()
    fake_service.process.return_value = {
        "downloaded": False,
        "skipped": False,
        "path": None,
        "http_status": 404,
        "error": "404 Client Error",
        "extraction_status": None,
        "extracted_text": None,
    }

    exit_code = pipeline.run(
        args,
        pdf_processing_service=fake_service,
        notification_lookup=lambda _id: row,
        pdf_lookup=lambda _id: pdf_rows,
        out=out,
    )

    assert exit_code == 1
    assert "Download error: 404 Client Error" in out.getvalue()


def test_bare_pdf_url_downloads_and_extracts_without_db(monkeypatch):
    args = pipeline.parse_args(["--pdf-url", "https://example.org/standalone.pdf"])
    out = io.StringIO()

    session = Mock()
    response = Mock()
    response.content = b"%PDF-1.4\n%not extractable by our fake reader\n"
    response.status_code = 200
    response.raise_for_status.return_value = None
    session.get.return_value = response

    # extract_text will fail on this fake content — verify it's handled, not crashed.
    exit_code = pipeline.run(args, session=session, out=out)

    assert exit_code == 1
    output = out.getvalue()
    assert "PDF URL: https://example.org/standalone.pdf" in output
    assert "Download: SUCCESS" in output
    assert "Extraction: FAILED" in output


def test_bare_pdf_url_download_failure_is_handled():
    args = pipeline.parse_args(["--pdf-url", "https://example.org/missing.pdf"])
    out = io.StringIO()

    session = Mock()
    session.get.side_effect = requests.ConnectionError("refused")

    exit_code = pipeline.run(args, session=session, out=out)

    assert exit_code == 1
    assert "Download: FAILED" in out.getvalue()
