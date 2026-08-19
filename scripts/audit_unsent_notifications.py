#!/usr/bin/env python3
"""Read-only production audit of unsent VALID notifications.

The `notifications` table only ever contains candidates the existing
`NotificationValidator` classified VALID — but Phases 26-29 already showed
that "VALID" doesn't always mean "genuine open recruitment opportunity":
award/achievement news, tenders misfiled as "Advertisement", admission
notices, and similar patterns can slip through the same positive keywords
that catch real recruitment. This script does NOT change that classifier —
it re-runs it (unchanged) against each unsent notification's stored title
and URL purely to recover *why* it was called VALID, then applies a
separate, additional keyword layer specifically to flag likely
false-positive *categories* for human review.

This is read-only: no network requests, no writes, no email, no scheduler.
Every row it reads already exists in the production database.

Usage:
    .venv/bin/python scripts/audit_unsent_notifications.py
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database.repositories.notification_repository import get_unsent_notifications
from parser.models import ParsedNotification
from services.notification_validator import NotificationValidator

HIGH_CONFIDENCE_RECRUITMENT = "HIGH_CONFIDENCE_RECRUITMENT"
LIKELY_FALSE_POSITIVE = "LIKELY_FALSE_POSITIVE"
NEEDS_REVIEW = "NEEDS_REVIEW"

# Suspicious categories, checked in priority order (most specific / least
# ambiguous first) against the notification title. First match wins for
# the "primary category" label used in the per-category breakdown — a
# title can plausibly match more than one, but only needs a name to sort
# under.
SUSPICIOUS_CATEGORIES: tuple[tuple[str, re.Pattern], ...] = (
    ("RESULTS_OR_SELECTED_CANDIDATES", re.compile(
        r"\b(result|results|selected candidates?|selection list|shortlist|shortlisted|"
        r"merit list|answer key|cut[- ]?off)\b", re.IGNORECASE)),
    ("TENDER_PROCUREMENT", re.compile(
        r"\b(tenders?|e-?tender|expression of interest|\beoi\b|procurement|quotations?|"
        r"empanelment|request for proposal|\brfp\b)\b", re.IGNORECASE)),
    ("AWARDS_ACHIEVEMENTS", re.compile(
        r"\b(award|awards|awarded|medal|prize|felicitat\w*|honou?red|honou?rs?|conferred|"
        r"best paper|gold medal|academician of the year)\b"
        r"|\b(receives?|bags?|wins?)\b[^.]{0,40}\b(award|medal|prize|honou?r|recognition|trophy)\b",
        re.IGNORECASE)),
    ("FELLOWSHIP_SCHEME_NOT_RECRUITMENT", re.compile(
        r"\bfellowships? (and|&) scholarships?\b|\bfellowship schemes?\b|national fellowship",
        re.IGNORECASE)),
    ("SCHOLARSHIP", re.compile(r"\bscholarships?\b", re.IGNORECASE)),
    ("ADMISSION", re.compile(r"\badmissions?\b|\bentrance\b|\bcounsel(l)?ing\b", re.IGNORECASE)),
    ("CONFERENCE_SEMINAR", re.compile(
        r"\b(conference|seminar|symposium|webinar|colloquium)\b", re.IGNORECASE)),
    ("TRAINING_WORKSHOP", re.compile(
        r"\btraining (program|programme)\b|\bworkshop\b|capacity building|skill development|"
        r"refresher course", re.IGNORECASE)),
    ("EVENT_CEREMONY", re.compile(
        r"\binauguration\b|\binaugurat\w*|foundation day|celebrat\w*|\bceremony\b|"
        r"felicitation function|\bconvocation\b", re.IGNORECASE)),
    ("CIRCULAR_OFFICE_ORDER", re.compile(
        r"\bcircular\b|office order|office memorandum|\bmemorandum\b", re.IGNORECASE)),
    ("POLICY_RULES_REPORT", re.compile(
        r"\bpolicy\b|\bpolicies\b|\brules\b|\bhandbook\b|annual report|\bguidelines?\b",
        re.IGNORECASE)),
    ("STAFF_FACULTY_DIRECTORY", re.compile(
        r"\bdirectory\b|\bbiodata\b|profile of|list of (faculty|staff|employees)",
        re.IGNORECASE)),
)

# URL folder/path signals that catch cases where the *title* is a generic
# word like "Advertisement" but the URL reveals its true nature — e.g.
# NIT Nagaland's tender/conference PDFs filed under generic "Advertisement"
# anchor text (Phase 28/29 finding).
SUSPICIOUS_URL_CATEGORIES: tuple[tuple[str, re.Pattern], ...] = (
    ("TENDER_PROCUREMENT", re.compile(r"tender|tander|procurement|purchase", re.IGNORECASE)),
    ("CONFERENCE_SEMINAR", re.compile(r"conference|seminar|symposium", re.IGNORECASE)),
)

# Unambiguous recruitment-specific signals. When a title matches BOTH a
# suspicious category AND one of these, the case is genuinely ambiguous
# (e.g. an award named after a fellowship) — flagged NEEDS_REVIEW rather
# than confidently bucketed either way.
STRONG_RECRUITMENT_SIGNAL = re.compile(
    r"\b(walk-in interview|walk in interview|jrf|srf|jpf|research associate|project associate|"
    r"project assistant|project staff|technical assistant|young professional|postdoctoral|"
    r"post-doctoral|junior research fellow|senior research fellow|apprentice(ship)?|"
    r"advt\.?\s*no\.?\s*\d|advertisement no\.?\s*\d)\b",
    re.IGNORECASE,
)


def categorize(title: str, url: str | None) -> tuple[str, str | None]:
    """Return (bucket, primary_suspicious_category_or_None).

    bucket is one of HIGH_CONFIDENCE_RECRUITMENT / LIKELY_FALSE_POSITIVE /
    NEEDS_REVIEW. Pure function — no I/O, easy to unit test directly.
    """
    title = title or ""
    url = url or ""

    primary_category = None
    for category_name, pattern in SUSPICIOUS_CATEGORIES:
        if pattern.search(title):
            primary_category = category_name
            break

    if primary_category is None:
        path = urlsplit(url).path
        for category_name, pattern in SUSPICIOUS_URL_CATEGORIES:
            if pattern.search(path):
                primary_category = category_name
                break

    if primary_category is None:
        return HIGH_CONFIDENCE_RECRUITMENT, None

    if STRONG_RECRUITMENT_SIGNAL.search(title):
        return NEEDS_REVIEW, primary_category

    return LIKELY_FALSE_POSITIVE, primary_category


def audit_notifications(rows, validator: NotificationValidator | None = None) -> list[dict]:
    """Classify+categorize each row. `rows` are sqlite3.Row/dict-like
    objects from `get_unsent_notifications()`. Read-only, no DB access."""
    validator = validator or NotificationValidator()
    audited = []
    for row in rows:
        title = row["title"]
        url = row["page_url"]
        pdf_url = row["pdf_url"] if "pdf_url" in row.keys() else None

        classification_result = validator.classify(ParsedNotification(title=title or "", url=url or ""))
        bucket, category = categorize(title, url)

        audited.append(
            {
                "id": row["id"],
                "organization": row["organization_name"],
                "title": title,
                "page_url": url,
                "pdf_url": pdf_url,
                "bucket": bucket,
                "category": category,
                "classifier_reason": classification_result.reason,
                "classifier_status": classification_result.status.value,
                "still_valid_under_classifier": classification_result.status.value == "VALID",
            }
        )
    return audited


def _print_report(audited: list[dict], out) -> None:
    total = len(audited)
    print("=" * 70, file=out)
    print("UNSENT NOTIFICATION AUDIT — READ-ONLY", file=out)
    print("=" * 70, file=out)
    print(f"Total unsent VALID notifications: {total}", file=out)
    print(file=out)

    reclassification_counts = Counter(a["classifier_status"] for a in audited)
    print("RE-CLASSIFICATION UNDER THE CURRENT NotificationValidator:", file=out)
    print(
        "  (each row was originally persisted as VALID; this shows what the "
        "classifier says about it right now — same title/url, re-evaluated)",
        file=out,
    )
    for status in ("VALID", "INVALID", "REVIEW"):
        count = reclassification_counts.get(status, 0)
        pct = (count / total * 100) if total else 0.0
        print(f"  {status:10s} {count:6d}  ({pct:5.1f}%)", file=out)
    print(file=out)

    bucket_counts = Counter(a["bucket"] for a in audited)
    print("BUCKETS:", file=out)
    for bucket in (HIGH_CONFIDENCE_RECRUITMENT, LIKELY_FALSE_POSITIVE, NEEDS_REVIEW):
        count = bucket_counts.get(bucket, 0)
        pct = (count / total * 100) if total else 0.0
        print(f"  {bucket:28s} {count:6d}  ({pct:5.1f}%)", file=out)
    print(file=out)

    category_counts = Counter(a["category"] for a in audited if a["category"] is not None)
    print("COUNTS BY DETECTED CATEGORY:", file=out)
    for category, count in category_counts.most_common():
        pct = (count / total * 100) if total else 0.0
        print(f"  {category:32s} {count:6d}  ({pct:5.1f}%)", file=out)
    if not category_counts:
        print("  (none)", file=out)
    print(file=out)

    org_flagged = Counter()
    org_total = Counter()
    for a in audited:
        org_total[a["organization"]] += 1
        if a["bucket"] in (LIKELY_FALSE_POSITIVE, NEEDS_REVIEW):
            org_flagged[a["organization"]] += 1

    print("ORGANIZATION-WISE FALSE-POSITIVE CONCENTRATION (top 15):", file=out)
    ranked_orgs = sorted(org_flagged.items(), key=lambda kv: -kv[1])[:15]
    if not ranked_orgs:
        print("  (none flagged)", file=out)
    for org_name, flagged_count in ranked_orgs:
        total_for_org = org_total[org_name]
        pct = (flagged_count / total_for_org * 100) if total_for_org else 0.0
        print(f"  {flagged_count:4d}/{total_for_org:<4d} ({pct:5.1f}%)  {org_name}", file=out)
    print(file=out)

    no_longer_valid = [a for a in audited if not a["still_valid_under_classifier"]]
    print(
        f"NOTIFICATIONS NO LONGER VALID UNDER THE UPDATED CLASSIFIER "
        f"({len(no_longer_valid)} of {total}, up to 50 shown):",
        file=out,
    )
    print("-" * 70, file=out)
    for a in no_longer_valid[:50]:
        print(f"[now {a['classifier_status']} / heuristic: {a['bucket']} / {a['category']}] {a['organization']}", file=out)
        print(f"  Title: {a['title']}", file=out)
        print(f"  URL: {a['page_url']}", file=out)
        if a["pdf_url"]:
            print(f"  PDF: {a['pdf_url']}", file=out)
        print(f"  Classifier reason: {a['classifier_reason']}", file=out)
        print("-" * 70, file=out)
    print(file=out)

    suspicious = [a for a in audited if a["bucket"] in (LIKELY_FALSE_POSITIVE, NEEDS_REVIEW)]
    top_50 = suspicious[:50]
    print(f"TOP {len(top_50)} HEURISTIC-SUSPICIOUS NOTIFICATIONS (of {len(suspicious)} flagged):", file=out)
    print("(these are the audit's own regex-based signals — informational; some may already "
          "be correctly rejected above, others remain VALID and are residual risk)", file=out)
    print("-" * 70, file=out)
    for a in top_50:
        print(f"[{a['bucket']} / {a['category']} / classifier says {a['classifier_status']}] {a['organization']}", file=out)
        print(f"  Title: {a['title']}", file=out)
        print(f"  URL: {a['page_url']}", file=out)
        if a["pdf_url"]:
            print(f"  PDF: {a['pdf_url']}", file=out)
        print(f"  Classifier reason: {a['classifier_reason']}", file=out)
        print("-" * 70, file=out)

    genuine_count = bucket_counts.get(HIGH_CONFIDENCE_RECRUITMENT, 0)
    print(file=out)
    print(f"Likely genuine recruitment notifications (HIGH_CONFIDENCE_RECRUITMENT): {genuine_count}", file=out)
    print(f"Likely false positives (LIKELY_FALSE_POSITIVE): {bucket_counts.get(LIKELY_FALSE_POSITIVE, 0)}", file=out)
    print(f"Ambiguous, needs human review (NEEDS_REVIEW): {bucket_counts.get(NEEDS_REVIEW, 0)}", file=out)
    print(file=out)
    print("No database changes were made. No email was sent.", file=out)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    return parser.parse_args(argv)


def run(
    args: argparse.Namespace | None = None,
    notification_lookup=get_unsent_notifications,
    validator: NotificationValidator | None = None,
    out=sys.stdout,
) -> int:
    args = args or parse_args([])
    rows = notification_lookup()
    audited = audit_notifications(rows, validator=validator)
    _print_report(audited, out)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
