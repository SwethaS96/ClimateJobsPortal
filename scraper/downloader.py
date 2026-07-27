"""HTTP downloader for scraping websites.

Provides a reusable `Downloader` that uses a persistent
`requests.Session` and returns `DownloadResult` dataclasses.

Retry policy: up to 3 attempts for connection errors, timeouts,
and 5xx responses with exponential backoff (1s, 2s, 4s).
404 responses are not retried. The `download` method never raises;
it always returns a `DownloadResult`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict
from scraper.site_config import WebsiteConfig
import time

import requests
from requests import Session
from requests.exceptions import ConnectionError, Timeout, RequestException


@dataclass
class DownloadResult:
    """Result of a download attempt.

    Attributes:
        url: URL that was requested.
        status_code: HTTP status code if available, otherwise None.
        headers: Response headers (string keys/values).
        content: Response text content if available, otherwise None.
        elapsed_seconds: Wall-clock seconds spent for the successful request
            or last failed attempt.
        success: True when the response status indicates success (2xx).
        error: Error message when not successful, otherwise None.
    """

    url: str
    status_code: Optional[int]
    headers: Dict[str, str]
    content: Optional[str]
    elapsed_seconds: float
    success: bool
    error: Optional[str]


class Downloader:
    """HTTP downloader that reuses a requests.Session for multiple requests.

    Example:
        loader = Downloader()
        result = loader.download(website_config)
    """

    DEFAULT_USER_AGENT = "ClimateJobsPortal/1.0"
    RETRY_STATUS_CODES = {
        500,
        502,
        503,
        504,
    }

    def __init__(self, session: Optional[Session] = None, max_retries: int = 3):
        self.session = session if session is not None else requests.Session()
        self.max_retries = max_retries

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def download(self, site: WebsiteConfig) -> DownloadResult:
        """Download the page for a `WebsiteConfig`.

        The `site` object is expected to have at least the attributes
        `url`, `timeout_seconds`, and `user_agent` (user_agent may be None).

        This method will never raise; it returns a `DownloadResult` indicating
        success or failure and any error message.
        """
        url = site.url
        timeout = site.timeout_seconds
        user_agent = site.user_agent or self.DEFAULT_USER_AGENT

        headers = {"User-Agent": user_agent}

        last_error = None
        last_status = None
        last_headers = {}
        last_content = None
        elapsed = 0.0

        for attempt in range(self.max_retries):
            start = time.monotonic()
            try:
                resp = self.session.get(url, headers=headers, timeout=timeout)
                elapsed = time.monotonic() - start
                last_status = resp.status_code
                # normalize headers to plain dict[str,str]
                last_headers = {k: str(v) for k, v in resp.headers.items()} if resp.headers else {}
                last_content = resp.text if resp.text is not None else None

                # Do not retry on 404
                if resp.status_code == 404:
                    last_error = "HTTP 404 Not Found"
                    break

                # Retry on server errors
                if resp.status_code in self.RETRY_STATUS_CODES:
                    # Use a readable error message when available
                    reason = resp.reason
                    if reason:
                        last_error = f"HTTP {resp.status_code} {reason}"
                    else:
                        last_error = f"HTTP {resp.status_code} Server Error"
                    # will retry if attempts remain
                else:
                    # Successful or client error (other than 404)
                    success = 200 <= resp.status_code < 400
                    return DownloadResult(
                        url=url,
                        status_code=resp.status_code,
                        headers=last_headers,
                        content=last_content,
                        elapsed_seconds=elapsed,
                        success=success,
                        error=None if success else f"HTTP {resp.status_code}",
                    )

            except Timeout as ex:
                elapsed = time.monotonic() - start
                last_error = f"Timeout after {timeout} seconds"
            except ConnectionError as ex:
                elapsed = time.monotonic() - start
                last_error = f"Connection error: {str(ex)}"
            except RequestException as ex:
                elapsed = time.monotonic() - start
                last_error = f"RequestException: {str(ex)}"
                # For unknown request exceptions, do not retry
                break

            # If we get here, we will retry unless this was the last attempt
            if attempt < self.max_retries - 1:
                backoff = 1 << attempt  # 1, 2, 4 ...
                time.sleep(backoff)
                continue
            else:
                # last attempt exhausted
                break

        # Build final DownloadResult from last known values
        success_flag = last_status is not None and 200 <= last_status < 400
        return DownloadResult(
            url=url,
            status_code=last_status,
            headers=last_headers,
            content=last_content,
            elapsed_seconds=elapsed,
            success=success_flag,
            error=last_error,
        )

    def close(self) -> None:
        """Close the underlying requests session."""
        self.session.close()