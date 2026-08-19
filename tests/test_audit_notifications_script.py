"""Tests for scripts/audit_notifications.py using mocked/fake lookups.

Purely in-memory — no real database access, and the script itself must
never call any write/insert/update/delete function.
"""

from __future__ import annotations

import io

import scripts.audit_notifications as audit


def row(id_, title, page_url, status="ACTIVE"):
    return {"id": id_, "title": title, "page_url": page_url, "status": status}


def test_valid_notification_is_not_flagged():
    rows = [row(1, "RA Advertisement", "https://example.org/1")]
    out = io.StringIO()

    audit.run(out=out, notifications_lookup=lambda: rows)

    output = out.getvalue()
    assert "Would now classify INVALID: 0" in output
    assert "notification_id: 1" not in output


def test_now_invalid_notification_is_flagged_with_reason():
    rows = [row(2, "Careers", "https://example.org/careers")]
    out = io.StringIO()

    audit.run(out=out, notifications_lookup=lambda: rows)

    output = out.getvalue()
    assert "Would now classify INVALID: 1" in output
    assert "notification_id: 2" in output
    assert "title: Careers" in output
    assert "new classification: INVALID" in output
    assert "reason:" in output


def test_review_notification_is_reported_separately_from_invalid():
    rows = [row(3, "Departmental Update", "https://example.org/3")]
    out = io.StringIO()

    audit.run(out=out, notifications_lookup=lambda: rows)

    output = out.getvalue()
    assert "Would now classify REVIEW:  1" in output
    assert "new classification: REVIEW" in output


def test_real_world_false_positives_are_all_flagged_invalid():
    rows = [
        row(1, "Careers", "https://example.org/careers"),
        row(2, "Retired Scientist", "https://example.org/retired_scientists.php"),
        row(3, "RA Advertisement - Results (August 2026 Quarter)", "https://example.org/463"),
        row(4, "RA Advertisement", "https://example.org/ra-advertisement"),
    ]
    out = io.StringIO()

    audit.run(out=out, notifications_lookup=lambda: rows)

    output = out.getvalue()
    assert "Would now classify INVALID: 3" in output
    for flagged_id in (1, 2, 3):
        assert f"notification_id: {flagged_id}" in output


def test_empty_database_reports_zero_and_no_changes_made():
    out = io.StringIO()

    exit_code = audit.run(out=out, notifications_lookup=lambda: [])

    assert exit_code == 0
    output = out.getvalue()
    assert "Total ACTIVE notifications: 0" in output
    assert "No changes were made to the database." in output


def test_audit_module_has_no_write_functions_imported():
    """Guard against accidental DB mutation: the module must not import any
    insert/update/delete/mark_reviewed function."""
    import inspect

    source = inspect.getsource(audit)
    for forbidden in ("insert_", "update_", "delete_", "mark_reviewed", "touch_last_seen"):
        assert forbidden not in source
