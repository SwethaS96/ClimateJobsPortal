#!/usr/bin/env python3
"""Diagnostic tool: audit stored notifications against the current classifier.

Read-only. Re-classifies every stored (ACTIVE) notification with today's
`NotificationValidator` and reports any that would now be rejected —
without touching the database. Older rows (e.g. the "Careers" / "Retired
Scientist" / results-page false positives from an earlier, less strict
validator) never get retroactively cleaned up automatically; this script
only tells you which rows those are, so a human can decide what to do.

Usage:
    .venv/bin/python scripts/audit_notifications.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.repositories.notification_repository import get_all_notifications
from parser.models import ParsedNotification
from services.notification_validator import Classification, NotificationValidator


def run(
    out=sys.stdout,
    notifications_lookup=get_all_notifications,
    validator: NotificationValidator | None = None,
) -> int:
    """Run the audit. Returns 0 always — this is a report, not a pass/fail check."""
    validator = validator or NotificationValidator()
    rows = notifications_lookup()

    would_be_invalid = []
    would_be_review = []

    for row in rows:
        candidate = ParsedNotification(title=row["title"] or "", url=row["page_url"] or "")
        result = validator.classify(candidate)
        if result.status == Classification.INVALID:
            would_be_invalid.append((row, result))
        elif result.status == Classification.REVIEW:
            would_be_review.append((row, result))

    print(f"Total ACTIVE notifications: {len(rows)}", file=out)
    print(f"Would now classify INVALID: {len(would_be_invalid)}", file=out)
    print(f"Would now classify REVIEW:  {len(would_be_review)}", file=out)
    print(file=out)

    _print_section("NOTIFICATIONS THAT WOULD NOW BE CLASSIFIED INVALID", would_be_invalid, out)
    _print_section("NOTIFICATIONS THAT WOULD NOW BE CLASSIFIED REVIEW", would_be_review, out)

    print("No changes were made to the database.", file=out)
    return 0


def _print_section(heading: str, entries: list, out) -> None:
    print("=" * 70, file=out)
    print(heading, file=out)
    print("=" * 70, file=out)

    if not entries:
        print("(none)", file=out)
        print(file=out)
        return

    for row, result in entries:
        print(f"notification_id: {row['id']}", file=out)
        print(f"title: {row['title']}", file=out)
        print(f"url: {row['page_url']}", file=out)
        print(f"current status: {row['status']}", file=out)
        print(f"new classification: {result.status.value}", file=out)
        print(f"reason: {result.reason}", file=out)
        print("-" * 70, file=out)
    print(file=out)


def main() -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
