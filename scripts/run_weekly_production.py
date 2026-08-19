#!/usr/bin/env python3
"""Weekly production orchestration: scrape -> classify -> dedupe -> persist
-> PDFs -> email, for every currently ENABLED website.

This is the script GitHub Actions' weekly workflow invokes. It is a thin
orchestration layer over two already-existing, already-tested components —
it reuses them, it does not reimplement them:

- `scripts/run_validation_batch.run()` does the scrape -> parse -> classify
  -> deduplicate -> persist -> review-queue -> PDF pipeline (real mode
  when `--confirm` is passed, dry-run/no-writes otherwise). Its own report
  (per-site detail, HTTP failure breakdown, VALID/INVALID/REVIEW counts,
  PDF stats) is reused as-is here, not re-derived.
- `services.email_service.EmailDigestService` sends the one consolidated
  digest of newly-VALID unsent notifications, exactly as validated in
  Phases 31-34.

The website list is never hard-coded: it's fetched fresh from the database
via `SiteConfigLoader.load_enabled_websites()` on every run, so a newly
enabled website is picked up automatically and a disabled one is skipped
automatically.

Safety:
- A `PRAGMA integrity_check` runs before and after. If the *before* check
  fails, the script stops immediately — no scrape, no email, no backup
  needed since nothing was going to be written anyway. If the *after*
  check fails, the script exits non-zero specifically so the calling
  workflow does not commit a corrupt database.
- A local, uncommitted (gitignored) backup of the database is taken right
  before any write, purely as an in-workflow safety net.
- Email is only ever attempted in real (`--confirm`) mode, and only after
  the scrape/persist step completes — a failed email delivery is reported
  but does not block the database commit (the newly scraped/classified
  data is still real and still worth keeping; `email_sent` simply stays
  0 for those notifications, exactly as designed, so the next run retries
  them).
- In `--dry-run` mode, nothing is persisted (scripts/run_validation_batch.py
  itself already guarantees that) and email is never attempted at all.

Usage:
    .venv/bin/python scripts/run_weekly_production.py --dry-run
    .venv/bin/python scripts/run_weekly_production.py --confirm
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import scripts.run_validation_batch as run_validation_batch
from config import settings
from database.connection import get_connection, close_connection
from scraper.site_config import SiteConfigLoader
from services.email_service import EmailDigestService, SMTPEmailProvider

DEFAULT_BACKUP_DIR = PROJECT_ROOT / "data" / "database" / "backups"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape and classify every enabled website, but write nothing and send no email.",
    )
    mode.add_argument(
        "--confirm",
        action="store_true",
        help="Real run: scrape, persist, process PDFs, and send the email digest.",
    )
    parser.add_argument(
        "--website-ids",
        type=int,
        nargs="+",
        default=None,
        metavar="ID",
        help="Override the enabled-website list with explicit ids (local testing only). "
        "Default: every currently enabled website, loaded fresh from the database.",
    )
    return parser.parse_args(argv)


def integrity_check(out) -> bool:
    """Run PRAGMA integrity_check. Prints and returns whether it passed."""
    conn = get_connection()
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        close_connection(conn)
    print(f"Database integrity check: {result}", file=out)
    return result == "ok"


def backup_database(out, backup_dir: Path = DEFAULT_BACKUP_DIR) -> Path:
    """Create a local, gitignored backup of the production database before
    any write. Uses sqlite3's own backup API for a consistent copy."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_path = backup_dir / f"climate_jobs_pre_weekly_run_{timestamp}.db"

    src = get_connection()
    dst = sqlite3.connect(backup_path)
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        close_connection(src)

    print(f"Backup written (not committed): {backup_path}", file=out)
    return backup_path


def load_enabled_website_ids(site_loader: SiteConfigLoader) -> list[int]:
    """Fresh, dynamic list of every currently enabled website id. Never
    hard-coded — a newly enabled website is picked up automatically."""
    return [site.id for site in site_loader.load_enabled_websites()]


def send_weekly_digest(out) -> dict:
    """Send the one consolidated digest via the existing EmailDigestService.
    Only called in real (--confirm) mode, after persistence completes."""
    missing = [
        name
        for name, value in (
            ("SMTP_HOST", settings.SMTP_HOST),
            ("SMTP_USERNAME", settings.SMTP_USERNAME),
            ("SMTP_PASSWORD", settings.SMTP_PASSWORD),
            ("EMAIL_FROM", settings.EMAIL_FROM),
        )
        if not value
    ]
    if missing or not settings.EMAIL_TO:
        if not settings.EMAIL_TO:
            missing.append("EMAIL_TO")
        print(
            f"EMAIL SKIPPED: missing required configuration: {', '.join(missing)}. "
            "Notifications remain unsent (email_sent=0) and will be retried next run.",
            file=out,
        )
        return {"sent": False, "message": f"Missing configuration: {', '.join(missing)}"}

    provider = SMTPEmailProvider(
        host=settings.SMTP_HOST,
        port=settings.SMTP_PORT,
        username=settings.SMTP_USERNAME,
        password=settings.SMTP_PASSWORD,
        sender=settings.EMAIL_FROM,
    )
    service = EmailDigestService(email_provider=provider)
    result = service.send_digest(recipients=settings.EMAIL_TO)

    if result["sent"]:
        print(
            f"EMAIL SENT: 1 consolidated digest, {result['notifications_included']} notification(s), "
            f"{result['organizations_included']} organization(s). "
            f"{result['notifications_excluded']} additional unsent notification(s) remain for next run.",
            file=out,
        )
    else:
        print(
            f"EMAIL NOT SENT: {result['message']} "
            "No notification was marked email_sent — all remain eligible for the next run.",
            file=out,
        )
    return result


def run(args: argparse.Namespace | None = None, out=sys.stdout) -> int:
    args = args or parse_args([])

    print("=" * 70, file=out)
    print("WEEKLY CLIMATE JOB RADAR — PRODUCTION RUN", file=out)
    print("MODE:", "DRY RUN (no writes, no email)" if args.dry_run else "REAL RUN (writes + email)", file=out)
    print("=" * 70, file=out)

    print(file=out)
    print("--- Pre-run database integrity check ---", file=out)
    if not integrity_check(out):
        print("STOP: database failed integrity check before any work began. Not scraping, not sending email.", file=out)
        return 1

    if not args.dry_run:
        backup_database(out)

    site_loader = SiteConfigLoader()
    website_ids = args.website_ids if args.website_ids is not None else load_enabled_website_ids(site_loader)
    print(file=out)
    print(f"Enabled websites to process: {len(website_ids)}", file=out)

    if not website_ids:
        print("No enabled websites found — nothing to do.", file=out)
        return 0

    batch_args = argparse.Namespace(
        website_ids=website_ids,
        dry_run=args.dry_run,
        confirm=args.confirm,
        limit=None,
    )

    print(file=out)
    print("--- Scrape / classify / deduplicate / persist / PDFs (scripts/run_validation_batch.py) ---", file=out)
    run_validation_batch.run(batch_args, site_loader=site_loader, out=out)

    email_result = None
    if not args.dry_run:
        print(file=out)
        print("--- Email digest ---", file=out)
        email_result = send_weekly_digest(out)

    print(file=out)
    print("--- Post-run database integrity check ---", file=out)
    post_ok = integrity_check(out)

    print(file=out)
    print("=" * 70, file=out)
    print("WEEKLY RUN SUMMARY", file=out)
    print("=" * 70, file=out)
    print(f"Mode: {'DRY RUN' if args.dry_run else 'REAL RUN'}", file=out)
    print(f"Websites attempted: {len(website_ids)}", file=out)
    if email_result is not None:
        print(f"Email sent: {'YES' if email_result['sent'] else 'NO'}", file=out)
    else:
        print("Email sent: N/A (dry run)", file=out)
    print(f"Final database integrity: {'OK' if post_ok else 'FAILED'}", file=out)

    if not post_ok:
        print(file=out)
        print("STOP: database failed integrity check after the run. DO NOT COMMIT this database.", file=out)
        return 1

    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
