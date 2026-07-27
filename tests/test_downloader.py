"""Tests for scraper.downloader using mocking to avoid network access."""
from __future__ import annotations

import pytest
from unittest.mock import Mock, patch
import requests

from scraper.downloader import Downloader, DownloadResult


class DummySite:
    def __init__(self, url: str, timeout_seconds: int = 5, user_agent: str | None = None):
        self.url = url
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent


def make_response(status_code=200, text="ok", headers=None):
    resp = Mock()
    resp.status_code = status_code
    resp.text = text
    resp.headers = headers or {"Content-Type": "text/html"}
    return resp


@patch("time.sleep", lambda s: None)
def test_successful_download():
    site = DummySite("https://example.org/test")
    mock_session = Mock()
    mock_session.get.return_value = make_response(200, "hello world")

    dl = Downloader(session=mock_session)
    result = dl.download(site)

    assert isinstance(result, DownloadResult)
    assert result.url == site.url
    assert result.status_code == 200
    assert result.success is True
    assert result.content == "hello world"
    assert result.error is None


@patch("time.sleep", lambda s: None)
def test_404_not_retried():
    site = DummySite("https://example.org/missing")
    mock_session = Mock()
    mock_session.get.return_value = make_response(404, "Not Found")

    dl = Downloader(session=mock_session)
    result = dl.download(site)

    assert result.status_code == 404
    assert result.success is False
    assert result.error == "HTTP 404 Not Found"
    # Ensure only one request was performed (no retries)
    assert mock_session.get.call_count == 1


@patch("time.sleep", lambda s: None)
def test_timeout_retries_and_failure():
    site = DummySite("https://example.org/slow")
    mock_session = Mock()
    # Make the session.get raise Timeout each time
    mock_session.get.side_effect = requests.exceptions.Timeout("timed out")

    dl = Downloader(session=mock_session, max_retries=3)
    result = dl.download(site)

    assert result.success is False
    assert result.status_code is None
    assert "Timeout" in (result.error or "")
    # retried max_retries times
    assert mock_session.get.call_count == 3


@patch("time.sleep", lambda s: None)
def test_retry_on_503_then_success():
    site = DummySite("https://example.org/flaky")
    mock_session = Mock()
    # Two 503 responses, then 200
    resp_503 = make_response(503, "Service Unavailable")
    resp_503.reason = "Service Unavailable"
    resp_ok = make_response(200, "recovered")
    mock_session.get.side_effect = [resp_503, resp_503, resp_ok]

    dl = Downloader(session=mock_session, max_retries=3)
    result = dl.download(site)

    assert result.success is True
    assert result.status_code == 200
    assert result.content == "recovered"
    assert mock_session.get.call_count == 3


@patch("time.sleep", lambda s: None)
def test_connection_error_retries():
    site = DummySite("https://example.org/conn")
    mock_session = Mock()
    # First two attempts raise ConnectionError, final attempt returns 200
    mock_session.get.side_effect = [
        requests.exceptions.ConnectionError("conn lost"),
        requests.exceptions.ConnectionError("conn lost"),
        make_response(200, "ok after retry"),
    ]

    dl = Downloader(session=mock_session, max_retries=3)
    result = dl.download(site)

    assert result.success is True
    assert result.status_code == 200
    assert result.content == "ok after retry"
    assert mock_session.get.call_count == 3
