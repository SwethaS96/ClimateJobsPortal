#!/usr/bin/env python3
"""Read-only website configuration audit.

Reports each selected website's current configuration (organization, page
name, URL, parser, enabled status) and flags websites whose page name
suggests they are pointed at a homepage/careers/announcements landing page
rather than a dedicated recruitment page. Makes no network requests and no
database writes — URL corrections and parser changes are made separately,
by hand, after reviewing this report.

Usage:
    .venv/bin/python scripts/audit_website_config.py --website-ids 1 4 7 10 15 20 25 30 35 40
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.repositories.organization_repository import get_organization_by_id
from database.repositories.website_repository import get_websites_by_ids

PAGE_NAME_FLAGS = ("homepage", "careers", "recruitment", "announcements")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--website-ids",
        type=int,
        nargs="+",
        required=True,
        metavar="ID",
        help="Explicit website ids to audit (space-separated).",
    )
    return parser.parse_args(argv)


def _field(obj, name):
    """Read `name` off either a sqlite3.Row/dict or an object with attributes."""
    try:
        return obj[name]
    except TypeError:
        return getattr(obj, name)


def page_name_flags(page_name: str) -> list[str]:
    """Which of PAGE_NAME_FLAGS appear in this page name, case-insensitively."""
    page_name_lower = (page_name or "").lower()
    return [flag for flag in PAGE_NAME_FLAGS if flag in page_name_lower]


def _organization_name(organization_id: int, organization_lookup) -> str:
    row = organization_lookup(organization_id)
    if row is None:
        return f"Unknown (id={organization_id})"
    return row["name"]


def run(
    args: argparse.Namespace | None = None,
    website_lookup=get_websites_by_ids,
    organization_lookup=get_organization_by_id,
    out=sys.stdout,
) -> int:
    """Run the audit. Returns 0 always — this is a report, not a pass/fail check."""
    args = args or parse_args([])

    websites = website_lookup(args.website_ids)
    websites_by_id = {int(_field(w, "id")): w for w in websites}

    print("WEBSITE CONFIGURATION AUDIT", file=out)
    print("=" * 60, file=out)
    print(f"Websites requested: {len(args.website_ids)}", file=out)
    print(f"Websites found: {len(websites_by_id)}", file=out)
    print(file=out)

    flagged: list[tuple[int, list[str]]] = []

    for website_id in args.website_ids:
        website = websites_by_id.get(website_id)
        if website is None:
            print(f"Website ID: {website_id}", file=out)
            print("NOT FOUND in database.", file=out)
            print("-" * 60, file=out)
            continue

        page_name = _field(website, "page_name")
        flags = page_name_flags(page_name)
        if flags:
            flagged.append((website_id, flags))

        print(f"Website ID: {website_id}", file=out)
        print(f"Organization: {_organization_name(_field(website, 'organization_id'), organization_lookup)}", file=out)
        print(f"Page name: {page_name}", file=out)
        print(f"Current URL: {_field(website, 'url')}", file=out)
        print(f"Parser: {_field(website, 'parser_name')}", file=out)
        print(f"Enabled: {'YES' if _field(website, 'is_enabled') else 'NO'}", file=out)
        if flags:
            print(f"Page-name flags: {', '.join(flags)}", file=out)
        print("-" * 60, file=out)

    print(file=out)
    print("=" * 60, file=out)
    print("PAGE-NAME FLAG SUMMARY", file=out)
    print("=" * 60, file=out)
    print(
        "Websites whose page name suggests a homepage/careers/announcements "
        "landing page rather than a dedicated recruitment page:",
        file=out,
    )
    if flagged:
        for website_id, flags in flagged:
            print(f"  Website ID {website_id}: {', '.join(flags)}", file=out)
    else:
        print("  (none)", file=out)

    print(file=out)
    print("No changes were made to the database. URLs and parsers were not modified.", file=out)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
