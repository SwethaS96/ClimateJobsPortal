#!/usr/bin/env python3
"""Seed organizations and websites from CSV files into the SQLite database."""

from __future__ import annotations

import csv
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.connection import get_connection, close_connection
from database.repositories.organization_repository import get_organization_by_name, insert_organization
from database.repositories.website_repository import insert_website
from database.schema import create_schema


class SeedSummary(dict):
    """Simple summary container for seeding results."""


def seed_organizations(csv_path: Path) -> tuple[int, int, list[str]]:
    """Import organizations from a CSV file using the organization repository."""
    inserted = 0
    skipped = 0
    errors: list[str] = []

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for line_number, row in enumerate(reader, start=2):
            try:
                name = (row.get("name") or "").strip()
                if not name:
                    raise ValueError("missing required name")

                if get_organization_by_name(name) is not None:
                    skipped += 1
                    continue

                insert_organization(
                    name=name,
                    short_name=(row.get("short_name") or "").strip() or None,
                    homepage_url=(row.get("homepage_url") or "").strip() or None,
                    country=(row.get("country") or "").strip() or None,
                    state=(row.get("state") or "").strip() or None,
                )
                inserted += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"line {line_number}: {exc}")
                continue

    return inserted, skipped, errors


def seed_websites(csv_path: Path) -> tuple[int, int, list[str]]:
    """Import websites from a CSV file using the website repository."""
    inserted = 0
    skipped = 0
    errors: list[str] = []

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for line_number, row in enumerate(reader, start=2):
            try:
                organization_name = (row.get("organization_name") or "").strip()
                page_name = (row.get("page_name") or "").strip()
                url = (row.get("url") or "").strip()
                if not organization_name or not page_name or not url:
                    raise ValueError("missing required organization_name, page_name, or url")

                organization = get_organization_by_name(organization_name)
                if organization is None:
                    raise ValueError(f"organization '{organization_name}' not found")

                existing_websites = []
                from database.repositories.website_repository import get_all_websites

                for website in get_all_websites():
                    if website["url"] == url and int(website["organization_id"]) == int(organization["id"]):
                        existing_websites.append(website)

                if existing_websites:
                    skipped += 1
                    continue

                insert_website(
                    organization_id=int(organization["id"]),
                    page_name=page_name,
                    url=url,
                    parser_name=(row.get("parser_name") or "").strip() or None,
                    parser_metadata=(row.get("parser_metadata") or "").strip() or None,
                    user_agent=(row.get("user_agent") or "").strip() or None,
                    timeout_seconds=int(row["timeout_seconds"]) if (row.get("timeout_seconds") or "").strip() else None,
                    scrape_interval_minutes=int(row["scrape_interval_minutes"]) if (row.get("scrape_interval_minutes") or "").strip() else None,
                )
                inserted += 1
            except Exception as exc:  # noqa: BLE001
                errors.append(f"line {line_number}: {exc}")
                continue

    return inserted, skipped, errors


def seed_database(organizations_csv: Path, websites_csv: Path) -> SeedSummary:
    """Populate the configured SQLite database from seed CSV files."""
    if not organizations_csv.exists():
        raise FileNotFoundError(f"Organizations CSV not found: {organizations_csv}")
    if not websites_csv.exists():
        raise FileNotFoundError(f"Websites CSV not found: {websites_csv}")

    connection = get_connection()
    try:
        create_schema(connection)
    finally:
        close_connection(connection)

    org_inserted, org_skipped, org_errors = seed_organizations(organizations_csv)
    site_inserted, site_skipped, site_errors = seed_websites(websites_csv)

    return SeedSummary(
        {
            "organizations_inserted": org_inserted,
            "organizations_skipped": org_skipped,
            "websites_inserted": site_inserted,
            "websites_skipped": site_skipped,
            "errors": org_errors + site_errors,
        }
    )


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2:
        print("Usage: python scripts/seed_database.py <organizations.csv> <websites.csv>", file=sys.stderr)
        return 2

    organizations_csv = Path(argv[0]).expanduser().resolve()
    websites_csv = Path(argv[1]).expanduser().resolve()

    try:
        summary = seed_database(organizations_csv, websites_csv)
    except Exception as exc:  # noqa: BLE001
        print(f"Seed failed: {exc}", file=sys.stderr)
        return 1

    print(f"Organizations inserted: {summary['organizations_inserted']}")
    print(f"Organizations skipped: {summary['organizations_skipped']}")
    print(f"Websites inserted: {summary['websites_inserted']}")
    print(f"Websites skipped: {summary['websites_skipped']}")
    print(f"Errors: {len(summary['errors'])}")

    for error in summary["errors"]:
        print(f"ERROR: {error}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
