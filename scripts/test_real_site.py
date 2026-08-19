#!/usr/bin/env python3
"""Diagnostic tool: run GenericHTMLParser against one real website URL.

Downloads a single page and prints the recruitment-notification candidates
`GenericHTMLParser` extracts from it, along with their relevance scores.
This script never touches the database and never sends email — it exists
purely to eyeball parser behavior against real HTML while tuning keywords
and scoring.

Usage:
    python scripts/test_real_site.py https://example.org/recruitment
    python scripts/test_real_site.py https://example.org/recruitment --threshold 2
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from parser.generic_html import GenericHTMLParser
from scraper.downloader import Downloader
from scraper.site_config import WebsiteConfig


def _build_diagnostic_site(url: str, timeout_seconds: int) -> WebsiteConfig:
    return WebsiteConfig(
        id=0,
        organization_id=0,
        page_name="diagnostic",
        url=url,
        parser_name="generic_html",
        parser_metadata=None,
        user_agent=None,
        timeout_seconds=timeout_seconds,
        scrape_interval_minutes=0,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Website URL to download and parse")
    parser.add_argument(
        "--threshold",
        type=int,
        default=None,
        help="Override the default candidate score threshold",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="Request timeout in seconds (default: 15)",
    )
    args = parser.parse_args()

    site = _build_diagnostic_site(args.url, args.timeout)

    downloader = Downloader()
    try:
        download_result = downloader.download(site)
    finally:
        downloader.close()

    print(f"URL: {args.url}")
    print(f"Status code: {download_result.status_code}")
    print(f"Download success: {download_result.success}")
    if not download_result.success:
        print(f"Error: {download_result.error}")
        return 1

    html_parser = GenericHTMLParser(score_threshold=args.threshold) if args.threshold is not None else GenericHTMLParser()
    notifications = html_parser.parse(download_result.content or "", args.url)

    print(f"Threshold: {html_parser.score_threshold}")
    print(f"Candidates found: {len(notifications)}")
    print("-" * 60)

    for index, notification in enumerate(
        sorted(notifications, key=lambda n: int(n.metadata.get("candidate_score", 0)), reverse=True),
        start=1,
    ):
        print(f"[{index}] score={notification.metadata.get('candidate_score')}")
        print(f"    title: {notification.title}")
        print(f"    url:   {notification.url}")
        if notification.pdf_url:
            print(f"    pdf:   {notification.pdf_url}")
        matched = notification.metadata.get("matched_keywords") or ""
        if matched:
            print(f"    matched keywords: {matched}")
        print("-" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
