#!/usr/bin/env python3
"""Read-only dry-run diagnostic for the production email digest.

Shows exactly what `EmailDigestService.send_digest()` would send — without
sending anything, without configuring SMTP, and without modifying any
`email_sent` flag. Safe to run against the real production database at any
time.

Usage:
    .venv/bin/python scripts/test_email_digest.py
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.repositories.notification_repository import close_connection, get_connection
from services.email_service import EmailDigestService


def run(service: EmailDigestService | None = None, out=sys.stdout) -> int:
    service = service or EmailDigestService()
    digest = service.build_pending_digest()

    conn = get_connection()
    try:
        review_pending = conn.execute(
            "SELECT COUNT(*) FROM notification_review_queue WHERE review_status = 'PENDING'"
        ).fetchone()[0]
    finally:
        close_connection(conn)

    print("=" * 60, file=out)
    print("EMAIL DIGEST DRY RUN — NOTHING WILL BE SENT", file=out)
    print("=" * 60, file=out)
    print(f"UNSENT VALID NOTIFICATIONS: {digest.total_unsent}", file=out)
    print(f"GROUPS: {len(digest.grouped)} organizations", file=out)

    if digest.included_count:
        sample_html = service.render_digest_html(digest.grouped, "<dry-run>")
        print(f"ESTIMATED EMAIL SIZE: {len(sample_html):,} bytes of HTML "
              f"({digest.included_count} notification(s) in this digest)", file=out)
    else:
        print("ESTIMATED EMAIL SIZE: 0 bytes (no digest would be sent)", file=out)

    if digest.excluded_count:
        print(
            f"NOTE: {digest.excluded_count} additional unsent notification(s) exist beyond the "
            f"EMAIL_MAX_NOTIFICATIONS limit ({service.max_notifications}) — they remain unsent "
            "and will be included in a future digest, not discarded.",
            file=out,
        )

    print(file=out)
    print("TOP ORGANIZATIONS:", file=out)
    top_organizations = sorted(digest.grouped.items(), key=lambda kv: -len(kv[1]))[:10]
    if not top_organizations:
        print("  (none)", file=out)
    for organization_name, notifications in top_organizations:
        print(f"  {len(notifications):>4}  {organization_name}", file=out)

    print(file=out)
    print(f"REVIEW NOTIFICATIONS EXCLUDED (pending manual review, never emailed): {review_pending}", file=out)
    print(
        "INVALID NOTIFICATIONS EXCLUDED: not tracked — INVALID candidates are discarded "
        "during scraping and never persisted to any table",
        file=out,
    )

    print(file=out)
    if digest.included_count == 0:
        print("Result: No new recruitment notifications.", file=out)
    else:
        print("Sample of the generated digest (first organization, up to 3 notices):", file=out)
        print("-" * 60, file=out)
        first_organization, first_notifications = next(iter(sorted(digest.grouped.items())))
        print(f"Organization: {first_organization}", file=out)
        for notification in first_notifications[:3]:
            print(f"  - {notification['title']}", file=out)
            print(f"    {notification['page_url']}", file=out)
            if notification.get("pdf_url"):
                print(f"    PDF: {notification['pdf_url']}", file=out)

    print(file=out)
    print("DRY RUN COMPLETE — no email was sent, no email_sent flags were modified.", file=out)
    return 0


def main(argv: list[str] | None = None) -> int:
    return run()


if __name__ == "__main__":
    sys.exit(main())
