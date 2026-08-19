#!/usr/bin/env python3
"""Controlled real-world end-to-end scrape for a small, explicit set of websites.

Exercises the full pipeline — download -> parse -> validate -> deduplicate ->
store — against REAL websites, but only the ones you name. It never touches
all 155 enabled websites on its own; you must pass `--website-ids` explicitly.

This script does not reimplement scraping, validation, or persistence: it
wires together the existing `SiteConfigLoader`, `ScraperEngine`,
`ParserRegistry`, `NotificationValidator`, `DuplicateDetector`, and
`NotificationService` exactly as `ScrapeService` does for production runs.

Usage:
    .venv/bin/python scripts/test_real_scrape.py --website-ids 1 2 3 4 5
    .venv/bin/python scripts/test_real_scrape.py --website-ids 1 2 3 --dry-run
    .venv/bin/python scripts/test_real_scrape.py --website-ids 1 2 3 4 5 --limit 2

In `--dry-run` mode the page is still downloaded, parsed, and candidates are
still validated and checked against the database for whether they'd be new
or already-known — but nothing is written: no notification rows and no PDF
document rows are created.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.repositories.organization_repository import get_organization_by_id
from parser.registry import ParserRegistry
from scraper.downloader import Downloader
from scraper.engine import ScraperEngine, ScrapeResult
from scraper.site_config import SiteConfigLoader, WebsiteConfig
from services.duplicate_detector import DuplicateDetector
from services.notification_service import NotificationService
from services.notification_validator import Classification, NotificationValidator


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--website-ids",
        type=int,
        nargs="+",
        required=True,
        metavar="ID",
        help="Explicit website ids to scrape (space-separated). Required — this "
        "script never scrapes every enabled website on its own.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Download, parse, and validate, but do not write to the database.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Only process the first N of the given website ids (safety cap).",
    )
    return parser.parse_args(argv)


def build_default_engine() -> ScraperEngine:
    """Build a `ScraperEngine` with a real downloader and every builtin parser registered."""
    registry = ParserRegistry()
    registry.register_builtin_parsers()
    return ScraperEngine(downloader=Downloader(), parser_registry=registry)


def _organization_name(organization_id: int, organization_lookup) -> str:
    row = organization_lookup(organization_id)
    if row is None:
        return f"Unknown (id={organization_id})"
    return row["name"]


def _classify_dry_run_candidates(
    valid_candidates: list,
    duplicate_detector: DuplicateDetector,
) -> tuple[int, int]:
    """Read-only classification of valid candidates as new vs already-known."""
    new_count = 0
    existing_count = 0
    for candidate in valid_candidates:
        title = (candidate.title or "").strip()
        url = (candidate.url or "").strip()
        if duplicate_detector.find_existing(title, url) is not None:
            existing_count += 1
        else:
            new_count += 1
    return new_count, existing_count


def run(
    args: argparse.Namespace,
    site_loader: SiteConfigLoader | None = None,
    engine: ScraperEngine | None = None,
    notification_service: NotificationService | None = None,
    validator: NotificationValidator | None = None,
    duplicate_detector: DuplicateDetector | None = None,
    organization_lookup=get_organization_by_id,
    out=sys.stdout,
) -> int:
    """Run the controlled scrape. Returns a process exit code."""
    site_loader = site_loader or SiteConfigLoader()
    engine = engine or build_default_engine()
    notification_service = notification_service or NotificationService()
    validator = validator or NotificationValidator()
    duplicate_detector = duplicate_detector or DuplicateDetector()

    website_ids = list(args.website_ids)
    if args.limit is not None:
        website_ids = website_ids[: args.limit]

    sites = site_loader.load_websites_by_ids(website_ids)
    sites_by_id = {site.id: site for site in sites}

    missing_ids = [website_id for website_id in website_ids if website_id not in sites_by_id]
    for missing_id in missing_ids:
        print(f"WARNING: website id {missing_id} not found in database — skipping", file=out)

    totals = {
        "websites_processed": 0,
        "successful": 0,
        "failed": 0,
        "candidates_found": 0,
        "invalid_candidates": 0,
        "new_notifications": 0,
        "existing_updated": 0,
        "errors": 0,
    }
    run_started_at = datetime.now(timezone.utc)

    try:
        for website_id in website_ids:
            site = sites_by_id.get(website_id)
            if site is None:
                continue

            _process_site(
                site,
                engine=engine,
                notification_service=notification_service,
                validator=validator,
                duplicate_detector=duplicate_detector,
                organization_lookup=organization_lookup,
                dry_run=args.dry_run,
                totals=totals,
                out=out,
            )
    finally:
        engine.downloader.close()

    total_elapsed = (datetime.now(timezone.utc) - run_started_at).total_seconds()

    print("=" * 60, file=out)
    print("SUMMARY" + (" (dry run)" if args.dry_run else ""), file=out)
    print("=" * 60, file=out)
    print(f"Websites processed: {totals['websites_processed']}", file=out)
    print(f"Successful: {totals['successful']}", file=out)
    print(f"Failed: {totals['failed']}", file=out)
    print(f"Candidates found: {totals['candidates_found']}", file=out)
    print(f"Invalid candidates: {totals['invalid_candidates']}", file=out)
    print(f"New notifications: {totals['new_notifications']}", file=out)
    print(f"Existing notifications updated: {totals['existing_updated']}", file=out)
    print(f"Errors: {totals['errors']}", file=out)
    print(f"Total elapsed time: {total_elapsed:.3f}s", file=out)

    return 0


def _process_site(
    site: WebsiteConfig,
    *,
    engine: ScraperEngine,
    notification_service: NotificationService,
    validator: NotificationValidator,
    duplicate_detector: DuplicateDetector,
    organization_lookup,
    dry_run: bool,
    totals: dict,
    out,
) -> None:
    totals["websites_processed"] += 1

    print("-" * 60, file=out)
    print(f"Organization: {_organization_name(site.organization_id, organization_lookup)}", file=out)
    print(f"Page: {site.page_name}", file=out)
    print(f"URL: {site.url}", file=out)
    print(f"Parser: {site.parser_name}", file=out)
    print(file=out)

    result: ScrapeResult = engine.scrape(site)

    print(f"Download: {'SUCCESS' if result.success else 'FAILED'}", file=out)
    print(f"HTTP status: {result.status_code}", file=out)
    print(f"Elapsed: {result.duration_seconds:.3f}s", file=out)
    print(file=out)

    site_errors: list[str] = []

    if not result.success:
        totals["failed"] += 1
        if result.error:
            site_errors.append(result.error)
        candidates_found = 0
        valid_candidates = 0
        invalid_candidates = 0
        new_notifications = 0
        existing_updated = 0
    else:
        totals["successful"] += 1
        candidates = result.notifications
        candidates_found = len(candidates)

        if dry_run:
            classifications = [(c, validator.classify(c)) for c in candidates]
            valid = [c for c, verdict in classifications if verdict.status == Classification.VALID]
            invalid_candidates = candidates_found - len(valid)
            new_notifications, existing_updated = _classify_dry_run_candidates(valid, duplicate_detector)

            for candidate, verdict in classifications:
                score = candidate.metadata.get("candidate_score", "?")
                print(
                    f"  [{verdict.status.value}] score={score} title={candidate.title!r} url={candidate.url}",
                    file=out,
                )
                print(f"      reason: {verdict.reason}", file=out)
            if candidates:
                print(file=out)
        else:
            persist_result = notification_service.persist(result, site.organization_id)
            new_notifications = persist_result.get("inserted", 0)
            existing_updated = persist_result.get("updated", 0)
            invalid_candidates = persist_result.get("skipped_invalid", 0) + persist_result.get("skipped_review", 0)
            site_errors.extend(persist_result.get("errors", []))

        valid_candidates = candidates_found - invalid_candidates

    print(f"Candidates found: {candidates_found}", file=out)
    print(f"Valid candidates: {valid_candidates}", file=out)
    print(f"New notifications: {new_notifications}", file=out)
    print(f"Existing notifications updated: {existing_updated}", file=out)
    print(f"Invalid candidates: {invalid_candidates}", file=out)
    print(f"Errors: {len(site_errors)}", file=out)
    for error in site_errors:
        print(f"  - {error}", file=out)

    totals["candidates_found"] += candidates_found
    totals["invalid_candidates"] += invalid_candidates
    totals["new_notifications"] += new_notifications
    totals["existing_updated"] += existing_updated
    totals["errors"] += len(site_errors)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
