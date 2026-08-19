#!/usr/bin/env python3
"""Validate the scraper end to end against enabled websites."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scraper.engine import ScrapeEngine
from scraper.site_config import SiteConfigLoader


def get_organization_by_id(organization_id: int):
    try:
        from database.repositories.organization_repository import get_organization_by_id as repository_lookup
    except Exception:  # pragma: no cover - defensive fallback
        return None

    return repository_lookup(organization_id)


def _organization_name(organization_id: int) -> str:
    row = get_organization_by_id(organization_id)
    if row is None:
        return "Unknown"

    if isinstance(row, dict):
        name = row.get("name")
    else:
        name = getattr(row, "name", None)

    return str(name) if name is not None else "Unknown"


def main() -> int:
    loader = SiteConfigLoader()
    engine = ScrapeEngine(site_config_loader=loader)
    sites = loader.load_enabled_websites()

    if not sites:
        print("No enabled websites found.")
        return 0

    successful = 0
    failed = 0
    notifications_found = 0

    for index, site in enumerate(sites, start=1):
        print("-" * 50)
        print(f"[{index}/{len(sites)}]")
        print(f"Organization: {_organization_name(site.organization_id)}")
        print(f"Page: {site.page_name}")
        print(f"URL: {site.url}")

        result = engine.scrape(site)
        status = "SUCCESS" if result.success else "FAILED"
        print(f"Download {status}")
        print(f"Parser {site.parser_name}")
        print(f"Notifications Found {len(result.notifications)}")
        print(f"Elapsed {result.duration_seconds:.2f} seconds")

        if result.success:
            successful += 1
            notifications_found += len(result.notifications)
        else:
            failed += 1

    print("-" * 50)
    print("Websites processed")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Notifications Found: {notifications_found}")
    print("Elapsed Time")
    print("Completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
