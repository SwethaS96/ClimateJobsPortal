#!/usr/bin/env python3
"""Safe, read-only-by-default import for the expanded institutions seed
data — TWO files, matching the exact column layout already used by the
existing `data/seeds/organizations.csv` / `data/seeds/websites.csv` (and
read the same way `scripts/seed_database.py` does):

    data/seeds/organisation_expanded.csv   (name, short_name, homepage_url,
                                             country, state, is_active)
    data/seeds/websites_expanded.csv        (organization_name, page_name,
                                             url, parser_name,
                                             parser_metadata, user_agent,
                                             timeout_seconds,
                                             scrape_interval_minutes,
                                             is_enabled)

Never blindly inserts rows. Every row is categorized before anything is
written:

    EXISTING              — organization (by name) or website (by URL)
                            already in the database. Never touched.
    NEW                   — genuinely new. Inserted. A new website is
                            ALWAYS inserted with is_enabled=0, regardless
                            of what the CSV's own is_enabled column says
                            (Phase 37 found every row in
                            websites_expanded.csv has is_enabled=1 — that
                            value is never trusted for a new site).
    DUPLICATE             — the website URL already exists (either as an
                            existing site, or repeated within this same
                            batch). Never inserted twice.
    INVALID_URL           — url isn't a well-formed http(s) URL.
    MISSING_URL           — url is blank.
    ORPHAN_ORGANIZATION   — a website row's organization_name doesn't
                            match any organization, existing or in the
                            expanded organizations CSV. Flagged, never
                            guessed/merged, never inserted.

`--confirm` is required for ANY database write; the default is a
read-only report. Existing organizations/websites are never modified —
only INSERT for genuinely new rows, never UPDATE. Running the importer
twice is idempotent: the second run finds everything already present and
inserts nothing further.

Usage:
    .venv/bin/python scripts/import_expanded_institutions.py \\
        data/seeds/organisation_expanded.csv data/seeds/websites_expanded.csv

    .venv/bin/python scripts/import_expanded_institutions.py \\
        data/seeds/organisation_expanded.csv data/seeds/websites_expanded.csv --confirm
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.connection import close_connection, get_connection
from database.repositories.organization_repository import get_organization_by_name, insert_organization
from database.repositories.website_repository import insert_website, update_website

EXISTING = "EXISTING"
NEW = "NEW"
DUPLICATE = "DUPLICATE"
INVALID_URL = "INVALID_URL"
MISSING_URL = "MISSING_URL"
ORPHAN_ORGANIZATION = "ORPHAN_ORGANIZATION"

DEFAULT_PARSER_NAME = "generic_html"
# insert_website() requires these explicitly — passing None inserts a
# literal NULL rather than falling back to the column's schema DEFAULT
# (same quirk noted in Phase 36; matches the existing 155's own convention
# in data/seeds/websites.csv).
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_SCRAPE_INTERVAL_MINUTES = 1440


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("organizations_csv", type=Path, help="Path to the expanded organizations CSV.")
    parser.add_argument("websites_csv", type=Path, help="Path to the expanded websites CSV.")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Actually insert NEW organizations/websites (websites always is_enabled=0). "
        "Without this flag, the script only reports — no database writes.",
    )
    return parser.parse_args(argv)


def _is_valid_url(url: str) -> bool:
    if not url:
        return False
    parts = urlsplit(url)
    return parts.scheme in ("http", "https") and bool(parts.netloc)


def load_rows(csv_path: Path) -> list[dict]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _existing_organization_names(conn) -> set[str]:
    rows = conn.execute("SELECT name FROM organizations").fetchall()
    return {row["name"].strip().lower() for row in rows}


def _existing_website_urls(conn) -> set[str]:
    rows = conn.execute("SELECT url FROM websites").fetchall()
    return {row["url"].strip().lower() for row in rows if row["url"]}


def categorize_organizations(org_rows: list[dict], existing_org_names: set[str]) -> list[dict]:
    """Pure classification — no database access, no side effects."""
    results = []
    seen_this_batch: set[str] = set()
    for line_number, row in enumerate(org_rows, start=2):
        name = (row.get("name") or "").strip()
        entry = {
            "line_number": line_number,
            "name": name,
            "short_name": (row.get("short_name") or "").strip(),
            "homepage_url": (row.get("homepage_url") or "").strip(),
            "country": (row.get("country") or "").strip() or "India",
            "state": (row.get("state") or "").strip(),
        }
        key = name.strip().lower()
        if not name:
            entry["category"] = MISSING_URL  # no name at all — can't identify the org
        elif key in existing_org_names or key in seen_this_batch:
            entry["category"] = EXISTING
        else:
            entry["category"] = NEW
            seen_this_batch.add(key)
        results.append(entry)
    return results


def categorize_websites(
    site_rows: list[dict], existing_website_urls: set[str], all_known_org_names: set[str]
) -> list[dict]:
    """Pure classification — no database access, no side effects."""
    results = []
    seen_urls_this_batch: set[str] = set()

    for line_number, row in enumerate(site_rows, start=2):
        organization_name = (row.get("organization_name") or "").strip()
        url = (row.get("url") or "").strip()
        page_name = (row.get("page_name") or "").strip()
        parser_name = (row.get("parser_name") or "").strip() or DEFAULT_PARSER_NAME
        parser_metadata = (row.get("parser_metadata") or "").strip() or None
        user_agent = (row.get("user_agent") or "").strip() or None

        entry = {
            "line_number": line_number,
            "organization_name": organization_name,
            "page_name": page_name,
            "url": url,
            "parser_name": parser_name,
            "parser_metadata": parser_metadata,
            "user_agent": user_agent,
        }

        if not url:
            entry["category"] = MISSING_URL
            results.append(entry)
            continue
        if not _is_valid_url(url):
            entry["category"] = INVALID_URL
            results.append(entry)
            continue
        if organization_name.strip().lower() not in all_known_org_names:
            entry["category"] = ORPHAN_ORGANIZATION
            results.append(entry)
            continue

        key = url.strip().lower()
        if key in existing_website_urls or key in seen_urls_this_batch:
            entry["category"] = DUPLICATE
            results.append(entry)
            continue

        seen_urls_this_batch.add(key)
        entry["category"] = NEW
        results.append(entry)

    return results


def apply_confirmed_inserts(org_entries: list[dict], site_entries: list[dict], out) -> dict[str, int]:
    """Insert NEW organizations, then NEW websites. Every inserted website
    is forced to is_enabled=0. Never touches an existing row."""
    inserted_orgs = 0
    for entry in org_entries:
        if entry["category"] != NEW:
            continue
        insert_organization(
            name=entry["name"],
            short_name=entry["short_name"] or None,
            homepage_url=entry["homepage_url"] or None,
            country=entry["country"] or None,
            state=entry["state"] or None,
        )
        inserted_orgs += 1
        print(f"  inserted organization: {entry['name']}", file=out)

    inserted_sites = 0
    for entry in site_entries:
        if entry["category"] != NEW:
            continue
        organization = get_organization_by_name(entry["organization_name"])
        if organization is None:
            # Should not happen — categorize_websites() already checked
            # against all_known_org_names — but never guess/create here.
            print(f"  SKIPPED (organization not found at insert time): {entry['organization_name']}", file=out)
            continue

        website_id = insert_website(
            organization_id=organization["id"],
            page_name=entry["page_name"],
            url=entry["url"],
            parser_name=entry["parser_name"],
            parser_metadata=entry["parser_metadata"],
            user_agent=entry["user_agent"],
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
            scrape_interval_minutes=DEFAULT_SCRAPE_INTERVAL_MINUTES,
        )
        update_website(website_id, is_enabled=False)
        inserted_sites += 1
        print(f"  inserted (disabled): {entry['organization_name']} -> {entry['url']}", file=out)

    return {"organizations_inserted": inserted_orgs, "websites_inserted": inserted_sites}


def _print_report(org_entries: list[dict], site_entries: list[dict], out) -> None:
    org_counts = Counter(e["category"] for e in org_entries)
    site_counts = Counter(e["category"] for e in site_entries)

    print("=" * 70, file=out)
    print("EXPANDED INSTITUTIONS IMPORT REPORT", file=out)
    print("=" * 70, file=out)
    print(f"Organization rows read: {len(org_entries)}", file=out)
    for category in (EXISTING, NEW, MISSING_URL):
        if category in org_counts:
            print(f"  {category:20s} {org_counts.get(category, 0)}", file=out)
    print(file=out)
    print(f"Website rows read: {len(site_entries)}", file=out)
    for category in (EXISTING, NEW, DUPLICATE, INVALID_URL, MISSING_URL, ORPHAN_ORGANIZATION):
        print(f"  {category:20s} {site_counts.get(category, 0)}", file=out)
    print(file=out)

    for category in (ORPHAN_ORGANIZATION, DUPLICATE, INVALID_URL, MISSING_URL):
        matching = [e for e in site_entries if e["category"] == category]
        if not matching:
            continue
        print(f"--- website {category} ({len(matching)}) ---", file=out)
        for entry in matching[:20]:
            print(
                f"  line {entry['line_number']}: {entry['organization_name'] or '(no name)'} "
                f"| url={entry['url'] or '(missing)'}",
                file=out,
            )
        if len(matching) > 20:
            print(f"  ... and {len(matching) - 20} more", file=out)
        print(file=out)


def run(args: argparse.Namespace | None = None, out=sys.stdout) -> int:
    args = args or parse_args([])

    if not args.organizations_csv.exists():
        print(f"STOP: organizations CSV not found: {args.organizations_csv}", file=out)
        return 1
    if not args.websites_csv.exists():
        print(f"STOP: websites CSV not found: {args.websites_csv}", file=out)
        return 1

    conn = get_connection()
    try:
        existing_org_names = _existing_organization_names(conn)
        existing_website_urls = _existing_website_urls(conn)
    finally:
        close_connection(conn)

    org_rows = load_rows(args.organizations_csv)
    site_rows = load_rows(args.websites_csv)

    org_entries = categorize_organizations(org_rows, existing_org_names)
    csv_org_names = {e["name"].strip().lower() for e in org_entries if e["name"]}
    all_known_org_names = existing_org_names | csv_org_names

    site_entries = categorize_websites(site_rows, existing_website_urls, all_known_org_names)

    _print_report(org_entries, site_entries, out)

    if not args.confirm:
        print("DRY RUN — no database changes made. Re-run with --confirm to insert NEW organizations/websites (websites disabled).", file=out)
        return 0

    print(file=out)
    print("--- Applying confirmed inserts (new websites always is_enabled=0) ---", file=out)
    summary = apply_confirmed_inserts(org_entries, site_entries, out)
    print(file=out)
    print(f"Organizations inserted: {summary['organizations_inserted']}", file=out)
    print(f"Websites inserted (all disabled): {summary['websites_inserted']}", file=out)
    print("No existing organization or website was modified. No website was enabled.", file=out)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
