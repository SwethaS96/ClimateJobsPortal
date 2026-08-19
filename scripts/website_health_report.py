#!/usr/bin/env python3
"""Read-only website health report, built from `scrape_history`.

`scrape_history` is the existing "results from the validation batch" store
(see `database/repositories/scrape_history_repository.py`); this script
only reads it — via `get_scrape_history_by_website` — plus `websites` /
`organizations` for display context. No new table, and nothing is written.

Each website's most recent `scrape_history` row (if any) is classified
into one of:

    WORKING, HTTP_404, HTTP_403, HTTP_5XX, TIMEOUT, CONNECTION_ERROR,
    NO_CANDIDATES, RECRUITMENT_CANDIDATES_FOUND, NOT_YET_VALIDATED

`NOT_YET_VALIDATED` covers a website with no `scrape_history` row yet
(e.g. before its first `run_validation_batch.py --confirm` run) — the
required category list assumes at least one prior run, so this is an
explicit addition for that gap rather than misclassifying it as failing.

Usage:
    .venv/bin/python scripts/website_health_report.py
    .venv/bin/python scripts/website_health_report.py --website-ids 1 4 7
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.repositories.organization_repository import get_organization_by_id
from database.repositories.scrape_history_repository import get_scrape_history_by_website
from database.repositories.website_repository import get_all_websites
from scraper.site_config import SiteConfigLoader

WORKING = "WORKING"
HTTP_404 = "HTTP_404"
HTTP_403 = "HTTP_403"
HTTP_5XX = "HTTP_5XX"
TIMEOUT = "TIMEOUT"
CONNECTION_ERROR = "CONNECTION_ERROR"
NO_CANDIDATES = "NO_CANDIDATES"
RECRUITMENT_CANDIDATES_FOUND = "RECRUITMENT_CANDIDATES_FOUND"
NOT_YET_VALIDATED = "NOT_YET_VALIDATED"
OTHER_FAILURE = "OTHER_FAILURE"

ALL_CATEGORIES = (
    WORKING,
    HTTP_404,
    HTTP_403,
    HTTP_5XX,
    TIMEOUT,
    CONNECTION_ERROR,
    NO_CANDIDATES,
    RECRUITMENT_CANDIDATES_FOUND,
    NOT_YET_VALIDATED,
    OTHER_FAILURE,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--website-ids",
        type=int,
        nargs="+",
        default=None,
        metavar="ID",
        help="Only report on these website ids. Default: every enabled website.",
    )
    return parser.parse_args(argv)


def classify_health(latest_history: dict | None) -> str:
    """Classify a website's health from its most recent scrape_history row."""
    if latest_history is None:
        return NOT_YET_VALIDATED

    status_code = latest_history["status_code"]
    if status_code == 404:
        return HTTP_404
    if status_code == 403:
        return HTTP_403
    if status_code is not None and 500 <= status_code < 600:
        return HTTP_5XX

    error_message = (latest_history["error_message"] or "").lower()
    if "timeout" in error_message:
        return TIMEOUT
    if "connection error" in error_message:
        return CONNECTION_ERROR

    if latest_history["status"] == "SUCCESS":
        notifications_found = latest_history["notifications_found"]
        if notifications_found is None:
            return WORKING
        return RECRUITMENT_CANDIDATES_FOUND if notifications_found > 0 else NO_CANDIDATES

    return OTHER_FAILURE


def run(
    args: argparse.Namespace | None = None,
    website_lookup=None,
    site_id_lookup=None,
    history_lookup=get_scrape_history_by_website,
    organization_lookup=get_organization_by_id,
    out=sys.stdout,
) -> int:
    """Run the report. Returns 0 always — this is a report, not a pass/fail check."""
    args = args or parse_args([])

    if args.website_ids:
        loader = site_id_lookup or SiteConfigLoader()
        websites = loader.load_websites_by_ids(args.website_ids)
    else:
        websites = (website_lookup or get_all_websites)()

    print("WEBSITE HEALTH REPORT", file=out)
    print("=" * 60, file=out)
    print(f"Websites reported: {len(websites)}", file=out)
    print(file=out)

    counts = {category: 0 for category in ALL_CATEGORIES}

    for website in websites:
        website_id = _field(website, "id")
        history_rows = history_lookup(website_id)
        latest = history_rows[0] if history_rows else None
        health = classify_health(latest)
        counts[health] += 1

        print(f"Website ID: {website_id}", file=out)
        print(f"Organization: {_organization_name(_field(website, 'organization_id'), organization_lookup)}", file=out)
        print(f"Page: {_field(website, 'page_name')}", file=out)
        print(f"URL: {_field(website, 'url')}", file=out)
        print(f"Health: {health}", file=out)
        if latest is not None:
            print(f"Last checked: {latest['started_at']}", file=out)
            print(
                f"Details: status_code={latest['status_code']}, "
                f"notifications_found={latest['notifications_found']}, "
                f"error={latest['error_message']}",
                file=out,
            )
        print("-" * 60, file=out)

    print(file=out)
    print("=" * 60, file=out)
    print("SUMMARY", file=out)
    print("=" * 60, file=out)
    for category in ALL_CATEGORIES:
        print(f"{category}: {counts[category]}", file=out)

    print(file=out)
    print("No changes were made to the database.", file=out)
    return 0


def _field(obj, name):
    """Read `name` off either a sqlite3.Row/dict or a `WebsiteConfig` dataclass."""
    try:
        return obj[name]
    except TypeError:
        return getattr(obj, name)


def _organization_name(organization_id: int, organization_lookup) -> str:
    row = organization_lookup(organization_id)
    if row is None:
        return f"Unknown (id={organization_id})"
    return row["name"]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
