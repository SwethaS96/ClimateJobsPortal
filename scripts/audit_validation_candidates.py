#!/usr/bin/env python3
"""Read-only candidate audit: inspect the raw candidates a website's page
produces, classified VALID/INVALID/REVIEW, without persisting anything.

`run_validation_batch.py --dry-run` classifies candidates but never writes
them anywhere, so there is nothing left to inspect after the fact. This
script closes that gap by re-running the same download -> parse -> classify
steps for one website — reusing `SiteConfigLoader`, `ScraperEngine`, and
`NotificationValidator` (no reimplementation) — and caching the result as a
local JSON snapshot under `data/validation_audit/`, not in any production
table.

Usage:
    .venv/bin/python scripts/audit_validation_candidates.py --website-id 15
    .venv/bin/python scripts/audit_validation_candidates.py --website-id 15 --classification REVIEW
    .venv/bin/python scripts/audit_validation_candidates.py --website-id 15 --refresh
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.repositories.organization_repository import get_organization_by_id
from parser.registry import ParserRegistry
from scraper.downloader import Downloader
from scraper.engine import ScraperEngine
from scraper.site_config import SiteConfigLoader, WebsiteConfig
from services.notification_validator import NotificationValidator, is_recruitment_source_page

DEFAULT_AUDIT_DIR = PROJECT_ROOT / "data" / "validation_audit"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--website-id", type=int, required=True, metavar="ID")
    parser.add_argument(
        "--classification",
        choices=["VALID", "INVALID", "REVIEW"],
        default=None,
        help="Only show candidates with this classification.",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Re-scrape even if a cached snapshot already exists for this website.",
    )
    return parser.parse_args(argv)


def build_default_engine() -> ScraperEngine:
    registry = ParserRegistry()
    registry.register_builtin_parsers()
    return ScraperEngine(downloader=Downloader(), parser_registry=registry)


def _organization_name(organization_id: int, organization_lookup) -> str:
    row = organization_lookup(organization_id)
    if row is None:
        return f"Unknown (id={organization_id})"
    return row["name"]


def collect_candidates(site: WebsiteConfig, *, engine, validator, organization_lookup) -> list[dict]:
    """Scrape and classify one site's candidates. Nothing is persisted."""
    result = engine.scrape(site)
    if not result.success:
        return []

    org_name = _organization_name(site.organization_id, organization_lookup)
    page_is_recruitment_source = is_recruitment_source_page(site.page_name)
    records = []
    for candidate in result.notifications:
        verdict = validator.classify(candidate, page_is_recruitment_source=page_is_recruitment_source)
        metadata = candidate.metadata or {}
        records.append(
            {
                "website_id": site.id,
                "organization": org_name,
                "title": candidate.title,
                "url": candidate.url,
                "classification": verdict.status.value,
                "classification_reason": verdict.reason,
                "candidate_score": metadata.get("candidate_score"),
                "matched_keywords": metadata.get("matched_keywords"),
                "pdf_url": candidate.pdf_url,
                "source_page": metadata.get("source_page"),
                "raw_html": candidate.raw_html,
            }
        )
    return records


def _snapshot_path(website_id: int, audit_dir: Path) -> Path:
    return audit_dir / f"website_{website_id}.json"


def load_or_collect(
    website_id: int,
    *,
    site_loader,
    engine,
    validator,
    organization_lookup,
    audit_dir: Path,
    refresh: bool,
    out,
) -> list[dict]:
    snapshot_path = _snapshot_path(website_id, audit_dir)
    if snapshot_path.exists() and not refresh:
        print(f"Loaded cached snapshot: {snapshot_path}", file=out)
        return json.loads(snapshot_path.read_text(encoding="utf-8"))

    sites = site_loader.load_websites_by_ids([website_id])
    if not sites:
        print(f"WARNING: website id {website_id} not found — no snapshot written", file=out)
        return []

    records = collect_candidates(sites[0], engine=engine, validator=validator, organization_lookup=organization_lookup)

    audit_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(records, indent=2), encoding="utf-8")
    print(f"Wrote snapshot: {snapshot_path} ({len(records)} candidates)", file=out)
    return records


def _print_candidate(record: dict, out) -> None:
    print(f"Website ID: {record['website_id']}", file=out)
    print(f"Organization: {record['organization']}", file=out)
    print(f"Title: {record['title']}", file=out)
    print(f"URL: {record['url']}", file=out)
    print(f"Classification: {record['classification']}", file=out)
    print(f"Classification reason: {record['classification_reason']}", file=out)
    print(f"Candidate score: {record['candidate_score']}", file=out)
    print(f"Matched keywords: {record['matched_keywords']}", file=out)
    print(f"PDF URL: {record['pdf_url']}", file=out)
    print(f"Source page: {record['source_page']}", file=out)
    print(f"Raw HTML: {record['raw_html']}", file=out)
    print("-" * 60, file=out)


def run(
    args: argparse.Namespace | None = None,
    site_loader: SiteConfigLoader | None = None,
    engine: ScraperEngine | None = None,
    validator: NotificationValidator | None = None,
    organization_lookup=get_organization_by_id,
    audit_dir: Path | None = None,
    out=sys.stdout,
) -> int:
    """Run the audit. Returns 0 always — this is a report, not a pass/fail check."""
    args = args or parse_args([])
    site_loader = site_loader or SiteConfigLoader()
    engine = engine or build_default_engine()
    validator = validator or NotificationValidator()
    audit_dir = audit_dir or DEFAULT_AUDIT_DIR

    try:
        records = load_or_collect(
            args.website_id,
            site_loader=site_loader,
            engine=engine,
            validator=validator,
            organization_lookup=organization_lookup,
            audit_dir=audit_dir,
            refresh=args.refresh,
            out=out,
        )
    finally:
        downloader = getattr(engine, "downloader", None)
        if downloader is not None:
            downloader.close()

    if args.classification is not None:
        records = [record for record in records if record["classification"] == args.classification]

    print(file=out)
    print("=" * 60, file=out)
    print(f"Candidates: {len(records)}", file=out)
    print("=" * 60, file=out)
    for record in records:
        _print_candidate(record, out)

    print(file=out)
    print("No database changes were made.", file=out)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
