#!/usr/bin/env python3
"""Controlled real-world validation batch for an explicit set of websites.

Exercises the full pipeline — download -> parse -> classify -> deduplicate
-> store -> process PDFs — against REAL websites, but only the ones you
name. It never scrapes all 155 websites on its own; `--website-ids` is
required.

Reuses the existing architecture end to end: `SiteConfigLoader` to load the
requested sites, `ScraperEngine` (real `Downloader` + `ParserRegistry`) to
download and parse, `NotificationValidator`/`DuplicateDetector` (dry-run) or
`NotificationService` (real run, which itself uses the validator, duplicate
detector, and `PDFProcessingService`) to classify/persist. Nothing here
reimplements scraping, parsing, validation, deduplication, or persistence.

Usage:
    # Dry run: download, parse, classify — no database writes at all.
    .venv/bin/python scripts/run_validation_batch.py \\
        --website-ids 1 4 7 10 15 20 25 30 35 40 --dry-run

    # Real run: persists VALID notifications, REVIEW candidates, and PDFs.
    # Requires --confirm as an explicit safety gate.
    .venv/bin/python scripts/run_validation_batch.py \\
        --website-ids 4 7 10 --confirm
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
from database.repositories.scrape_history_repository import insert_scrape_history
from parser.registry import ParserRegistry
from scraper.downloader import Downloader
from scraper.engine import ScraperEngine, ScrapeResult
from scraper.site_config import SiteConfigLoader, WebsiteConfig
from services.duplicate_detector import DuplicateDetector
from services.notification_service import NotificationService
from services.notification_validator import Classification, NotificationValidator, is_recruitment_source_page

HTTP_SUCCESS = "SUCCESS"
HTTP_4XX = "HTTP_4XX"
HTTP_5XX = "HTTP_5XX"
HTTP_TIMEOUT = "TIMEOUT"
HTTP_CONNECTION_ERROR = "CONNECTION_ERROR"
HTTP_OTHER = "OTHER_FAILURE"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--website-ids",
        type=int,
        nargs="+",
        required=True,
        metavar="ID",
        help="Explicit website ids to validate (space-separated). Required — "
        "this script never scrapes every enabled website on its own.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Download, parse, and classify only. No database writes at all.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Required to actually run in real (non-dry-run) mode — an explicit "
        "safety gate since a real run writes to the database.",
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


def classify_http_outcome(result: ScrapeResult) -> str:
    """Coarse-grained bucket for the batch summary's failure breakdown."""
    if result.success:
        return HTTP_SUCCESS

    status_code = result.status_code
    if status_code is not None and 400 <= status_code < 500:
        return HTTP_4XX
    if status_code is not None and 500 <= status_code < 600:
        return HTTP_5XX

    error_lower = (result.error or "").lower()
    if "timeout" in error_lower:
        return HTTP_TIMEOUT
    if "connection error" in error_lower:
        return HTTP_CONNECTION_ERROR
    return HTTP_OTHER


def _organization_name(organization_id: int, organization_lookup) -> str:
    row = organization_lookup(organization_id)
    if row is None:
        return f"Unknown (id={organization_id})"
    return row["name"]


def run(
    args: argparse.Namespace,
    site_loader: SiteConfigLoader | None = None,
    engine: ScraperEngine | None = None,
    notification_service: NotificationService | None = None,
    validator: NotificationValidator | None = None,
    duplicate_detector: DuplicateDetector | None = None,
    organization_lookup=get_organization_by_id,
    scrape_history_writer=insert_scrape_history,
    out=sys.stdout,
) -> int:
    """Run the validation batch. Returns a process exit code."""
    if args.dry_run:
        print("=" * 60, file=out)
        print("DRY RUN — NO DATABASE WRITES", file=out)
        print("=" * 60, file=out)
    else:
        print("=" * 60, file=out)
        print("REAL RUN — DATABASE WILL BE MODIFIED", file=out)
        print("=" * 60, file=out)
        if not args.confirm:
            print(file=out)
            print(
                "Refusing to run: real mode requires --confirm as an explicit safety gate.",
                file=out,
            )
            print("Pass --dry-run to preview instead, or add --confirm to proceed.", file=out)
            return 1

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

    for missing_id in (wid for wid in website_ids if wid not in sites_by_id):
        print(f"WARNING: website id {missing_id} not found in database — skipping", file=out)

    totals = _new_totals()
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
                scrape_history_writer=scrape_history_writer,
                dry_run=args.dry_run,
                totals=totals,
                out=out,
            )
    finally:
        engine.downloader.close()

    total_elapsed = (datetime.now(timezone.utc) - run_started_at).total_seconds()
    _print_summary(totals, total_elapsed, out)
    return 0


def _new_totals() -> dict:
    return {
        "websites_processed": 0,
        "successful": 0,
        "http_4xx": 0,
        "http_5xx": 0,
        "timeouts": 0,
        "other_failures": 0,
        "valid": 0,
        "invalid": 0,
        "review": 0,
        "new_notifications": 0,
        "existing_updated": 0,
        "pdf_candidates": 0,
        "pdf_downloaded": 0,
        "pdf_download_failed": 0,
        "pdf_extraction_success": 0,
        "pdf_extraction_failed": 0,
    }


def _process_site(
    site: WebsiteConfig,
    *,
    engine: ScraperEngine,
    notification_service: NotificationService,
    validator: NotificationValidator,
    duplicate_detector: DuplicateDetector,
    organization_lookup,
    scrape_history_writer,
    dry_run: bool,
    totals: dict,
    out,
) -> None:
    totals["websites_processed"] += 1

    print("-" * 60, file=out)
    print(f"Organization: {_organization_name(site.organization_id, organization_lookup)}", file=out)
    print(f"Website ID: {site.id}", file=out)
    print(f"Page name: {site.page_name}", file=out)
    print(f"URL: {site.url}", file=out)
    print(f"Parser: {site.parser_name}", file=out)
    print(file=out)

    started_at = datetime.now(timezone.utc)
    result: ScrapeResult = engine.scrape(site)

    print(f"HTTP status: {result.status_code}", file=out)
    print(f"Download: {'SUCCESS' if result.success else 'FAILED'}", file=out)
    print(f"Elapsed time: {result.duration_seconds:.3f}s", file=out)
    print(file=out)

    outcome = classify_http_outcome(result)
    if outcome == HTTP_SUCCESS:
        totals["successful"] += 1
    elif outcome == HTTP_4XX:
        totals["http_4xx"] += 1
    elif outcome == HTTP_5XX:
        totals["http_5xx"] += 1
    elif outcome == HTTP_TIMEOUT:
        totals["timeouts"] += 1
    else:
        totals["other_failures"] += 1

    site_errors: list[str] = []
    candidates_found = 0
    valid_count = invalid_count = review_count = 0
    new_notifications = existing_updated = 0
    pdf_candidates = pdf_processed = 0
    pdf_downloaded = pdf_download_failed = 0
    pdf_extraction_success = pdf_extraction_failed = 0

    if not result.success:
        if result.error:
            site_errors.append(result.error)
    else:
        candidates = result.notifications
        candidates_found = len(candidates)
        pdf_candidates = sum(1 for c in candidates if c.pdf_url)

        if dry_run:
            page_is_recruitment_source = is_recruitment_source_page(site.page_name)
            for candidate in candidates:
                verdict = validator.classify(candidate, page_is_recruitment_source=page_is_recruitment_source)
                if verdict.status == Classification.VALID:
                    valid_count += 1
                elif verdict.status == Classification.INVALID:
                    invalid_count += 1
                else:
                    review_count += 1
        else:
            persist_result = notification_service.persist(result, site.organization_id)
            new_notifications = persist_result.get("inserted", 0)
            existing_updated = persist_result.get("updated", 0)
            invalid_count = persist_result.get("skipped_invalid", 0)
            review_count = persist_result.get("skipped_review", 0)
            valid_count = new_notifications + existing_updated
            pdf_processed = persist_result.get("pdf_processed", 0)
            pdf_downloaded = persist_result.get("pdf_downloaded", 0)
            pdf_download_failed = persist_result.get("pdf_download_failed", 0)
            pdf_extraction_success = persist_result.get("pdf_extraction_success", 0)
            pdf_extraction_failed = persist_result.get("pdf_extraction_failed", 0)
            site_errors.extend(persist_result.get("errors", []))

    print(f"Candidates found: {candidates_found}", file=out)
    print(f"VALID: {valid_count}", file=out)
    print(f"INVALID: {invalid_count}", file=out)
    print(f"REVIEW: {review_count}", file=out)
    print(f"PDF candidates: {pdf_candidates}", file=out)

    if not dry_run:
        print(file=out)
        print(f"New notifications: {new_notifications}", file=out)
        print(f"Existing notifications updated: {existing_updated}", file=out)
        print(f"Review candidates added: {review_count}", file=out)
        print(f"Invalid candidates: {invalid_count}", file=out)
        print(f"PDFs processed: {pdf_processed}", file=out)
        print(f"PDF extraction successes: {pdf_extraction_success}", file=out)
        print(f"PDF extraction failures: {pdf_extraction_failed}", file=out)

    print(f"Errors: {len(site_errors)}", file=out)
    for error in site_errors:
        print(f"  - {error}", file=out)

    totals["valid"] += valid_count
    totals["invalid"] += invalid_count
    totals["review"] += review_count
    totals["new_notifications"] += new_notifications
    totals["existing_updated"] += existing_updated
    totals["pdf_candidates"] += pdf_candidates
    totals["pdf_downloaded"] += pdf_downloaded
    totals["pdf_download_failed"] += pdf_download_failed
    totals["pdf_extraction_success"] += pdf_extraction_success
    totals["pdf_extraction_failed"] += pdf_extraction_failed

    if not dry_run:
        completed_at = datetime.now(timezone.utc)
        try:
            scrape_history_writer(
                website_id=site.id,
                started_at=started_at.isoformat(),
                finished_at=completed_at.isoformat(),
                duration_seconds=int(result.duration_seconds),
                status="SUCCESS" if result.success else "FAILED",
                notifications_found=candidates_found,
                notifications_added=new_notifications,
                notifications_updated=existing_updated,
                error_message="; ".join(site_errors) if site_errors else None,
                status_code=result.status_code,
            )
        except Exception as exc:
            # Recording scrape_history is bookkeeping, not the batch's
            # purpose — a failure here (e.g. schema drift) must not lose
            # notifications/PDFs already persisted for this site, and must
            # never take down the rest of the batch.
            print(f"WARNING: failed to record scrape_history for website {site.id}: {exc}", file=out)


def _print_summary(totals: dict, total_elapsed: float, out) -> None:
    print(file=out)
    print("=" * 60, file=out)
    print("VALIDATION SUMMARY", file=out)
    print("=" * 60, file=out)
    print(f"Websites processed: {totals['websites_processed']}", file=out)
    print(f"Successful: {totals['successful']}", file=out)
    print(f"HTTP 4xx: {totals['http_4xx']}", file=out)
    print(f"HTTP 5xx: {totals['http_5xx']}", file=out)
    print(f"Timeouts: {totals['timeouts']}", file=out)
    print(f"Other failures: {totals['other_failures']}", file=out)
    print(file=out)
    print("Candidates:", file=out)
    print(f"  VALID: {totals['valid']}", file=out)
    print(f"  INVALID: {totals['invalid']}", file=out)
    print(f"  REVIEW: {totals['review']}", file=out)
    print(file=out)
    print(f"New notifications: {totals['new_notifications']}", file=out)
    print(f"Existing notifications updated: {totals['existing_updated']}", file=out)
    print(file=out)
    print("PDF candidates:", totals["pdf_candidates"], file=out)
    print(f"PDF downloads successful: {totals['pdf_downloaded']}", file=out)
    print(f"PDF downloads failed: {totals['pdf_download_failed']}", file=out)
    print(f"PDF extraction successful: {totals['pdf_extraction_success']}", file=out)
    print(f"PDF extraction failed: {totals['pdf_extraction_failed']}", file=out)
    print(file=out)
    print(f"Total elapsed time: {total_elapsed:.3f}s", file=out)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
