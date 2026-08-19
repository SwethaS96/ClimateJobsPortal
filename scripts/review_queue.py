#!/usr/bin/env python3
"""CLI to inspect and resolve REVIEW-queue candidates.

Thin wrapper around `notification_review_queue_repository` — all queries
and mutations go through the existing repository functions; this script
only formats output. It never touches `notifications` or `pdf_documents`,
and never sends email.

Usage:
    .venv/bin/python scripts/review_queue.py                # list PENDING (default)
    .venv/bin/python scripts/review_queue.py --pending       # same, explicit
    .venv/bin/python scripts/review_queue.py --all           # list every candidate, any status
    .venv/bin/python scripts/review_queue.py --show 12       # full detail for one candidate
    .venv/bin/python scripts/review_queue.py --resolve 12    # mark candidate 12 RESOLVED
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.repositories.notification_review_queue_repository import (
    get_all_review_candidates,
    get_review_candidate_by_id,
    list_pending_reviews,
    mark_reviewed,
)
from database.repositories.organization_repository import get_organization_by_id


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--pending", action="store_true", help="List only PENDING candidates (default).")
    group.add_argument("--all", action="store_true", help="List every candidate, including RESOLVED.")
    group.add_argument("--resolve", type=int, metavar="ID", help="Mark candidate ID as RESOLVED.")
    group.add_argument("--show", type=int, metavar="ID", help="Show full detail for candidate ID.")
    return parser.parse_args(argv)


def _organization_label(organization_id: int, organization_lookup) -> str:
    row = organization_lookup(organization_id)
    if row is None:
        return f"Unknown (id={organization_id})"
    return row["name"]


def run(
    args: argparse.Namespace,
    list_pending=list_pending_reviews,
    list_all=get_all_review_candidates,
    get_by_id=get_review_candidate_by_id,
    resolve=mark_reviewed,
    organization_lookup=get_organization_by_id,
    out=sys.stdout,
) -> int:
    """Dispatch to the requested action. Returns a process exit code."""
    if args.resolve is not None:
        return _resolve(args.resolve, get_by_id=get_by_id, resolve=resolve, out=out)
    if args.show is not None:
        return _show(args.show, get_by_id=get_by_id, organization_lookup=organization_lookup, out=out)
    if args.all:
        return _list(list_all(), heading="ALL REVIEW CANDIDATES", organization_lookup=organization_lookup, out=out)
    return _list(list_pending(), heading="PENDING REVIEW CANDIDATES", organization_lookup=organization_lookup, out=out)


def _list(rows, *, heading: str, organization_lookup, out) -> int:
    print(f"{heading} ({len(rows)})", file=out)
    print("=" * 60, file=out)

    if not rows:
        print("(none)", file=out)
        return 0

    for row in rows:
        print(f"ID: {row['id']}", file=out)
        print(f"Organization: {_organization_label(row['organization_id'], organization_lookup)}", file=out)
        print(f"Website ID: {row['website_id']}", file=out)
        print(f"Title: {row['title']}", file=out)
        print(f"URL: {row['url']}", file=out)
        print(f"Classification: {row['classification']}", file=out)
        print(f"Reason: {row['reason']}", file=out)
        print(f"Created At: {row['created_at']}", file=out)
        print(f"Status: {row['review_status']}", file=out)
        print("-" * 60, file=out)

    return 0


def _show(review_id: int, *, get_by_id, organization_lookup, out) -> int:
    row = get_by_id(review_id)
    if row is None:
        print(f"Review candidate {review_id} not found.", file=out)
        return 1

    print(f"ID: {row['id']}", file=out)
    print(f"Organization: {_organization_label(row['organization_id'], organization_lookup)}", file=out)
    print(f"Website ID: {row['website_id']}", file=out)
    print(f"Title: {row['title']}", file=out)
    print(f"URL: {row['url']}", file=out)
    print(f"Classification: {row['classification']}", file=out)
    print(f"Reason: {row['reason']}", file=out)
    print(f"Raw HTML: {row['raw_html'] if row['raw_html'] else '(none)'}", file=out)
    print(f"Metadata: {row['metadata'] if row['metadata'] else '(none)'}", file=out)
    print(f"Created At: {row['created_at']}", file=out)
    print(f"Reviewed At: {row['reviewed_at'] if row['reviewed_at'] else '(not reviewed yet)'}", file=out)
    print(f"Review Status: {row['review_status']}", file=out)
    return 0


def _resolve(review_id: int, *, get_by_id, resolve, out) -> int:
    row = get_by_id(review_id)
    if row is None:
        print(f"Review candidate {review_id} not found.", file=out)
        return 1

    if row["review_status"] != "PENDING":
        print(f"Review candidate {review_id} is already {row['review_status']} — nothing to do.", file=out)
        return 1

    resolve(review_id)
    print(f"Review candidate {review_id} marked RESOLVED.", file=out)
    print(f"  Title: {row['title']}", file=out)
    print(f"  URL: {row['url']}", file=out)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
