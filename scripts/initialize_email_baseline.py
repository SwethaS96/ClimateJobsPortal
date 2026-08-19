#!/usr/bin/env python3
"""One-time baseline: mark all EXISTING historical notifications as
email_sent=1, so the first weekly GitHub Actions run doesn't email the
entire historical backlog.

This is a deliberate, one-time, manually-run operation — it is NOT invoked
by the GitHub Actions workflow. Run it once, locally, before ever enabling
the weekly schedule.

Only touches `notifications.email_sent` (and `updated_at`, the same field
`EmailDigestService` itself updates on a successful send). Never deletes
anything, never touches `first_seen`/`last_seen`, never touches
`notification_review_queue` or `pdf_documents`. Notifications created by
future weekly scrapes start at email_sent=0 as usual and are unaffected by
this having run once in the past — this only acts on rows that already
exist at the moment it's run.

Usage:
    .venv/bin/python scripts/initialize_email_baseline.py --dry-run
    .venv/bin/python scripts/initialize_email_baseline.py --confirm
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.connection import close_connection, get_connection


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Show current counts and what would change. Makes no database changes.",
    )
    mode.add_argument(
        "--confirm",
        action="store_true",
        help="Actually mark all currently-unsent notifications as email_sent=1. Required for any mutation.",
    )
    return parser.parse_args(argv)


def _counts(conn) -> dict[str, int]:
    total = conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    sent = conn.execute("SELECT COUNT(*) FROM notifications WHERE email_sent = 1").fetchone()[0]
    return {"total": total, "sent": sent, "unsent": total - sent}


def run(args: argparse.Namespace | None = None, out=sys.stdout) -> int:
    args = args or parse_args([])

    conn = get_connection()
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        print(f"Database integrity check: {integrity}", file=out)
        if integrity != "ok":
            print("STOP: database failed integrity check. No changes made.", file=out)
            return 1

        before = _counts(conn)
        print(file=out)
        print("BEFORE:", file=out)
        print(f"  Total notifications: {before['total']}", file=out)
        print(f"  Already email_sent=1: {before['sent']}", file=out)
        print(f"  Currently email_sent=0 (historical baseline candidates): {before['unsent']}", file=out)

        if args.dry_run:
            print(file=out)
            print(
                f"DRY RUN — no changes made. Re-run with --confirm to mark these "
                f"{before['unsent']} existing notification(s) as the historical baseline "
                "(email_sent=1), so the weekly workflow only emails genuinely new ones.",
                file=out,
            )
            return 0

        if before["unsent"] == 0:
            print(file=out)
            print("Nothing to do — no unsent notifications exist.", file=out)
            return 0

        timestamp = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "UPDATE notifications SET email_sent = 1, updated_at = ? WHERE email_sent = 0",
            (timestamp,),
        )
        conn.commit()

        after = _counts(conn)
        print(file=out)
        print("AFTER:", file=out)
        print(f"  Total notifications: {after['total']}", file=out)
        print(f"  Now email_sent=1: {after['sent']}", file=out)
        print(f"  Now email_sent=0: {after['unsent']}", file=out)

        integrity_after = conn.execute("PRAGMA integrity_check").fetchone()[0]
        print(file=out)
        print(f"Post-change database integrity check: {integrity_after}", file=out)
        if integrity_after != "ok":
            print("WARNING: database failed integrity check after the update. Investigate immediately.", file=out)
            return 1

        print(file=out)
        print(
            "Baseline initialized. Future weekly runs will only email notifications "
            "inserted after this point.",
            file=out,
        )
        return 0
    finally:
        close_connection(conn)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
