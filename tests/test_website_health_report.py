"""Tests for scripts/website_health_report.py using fake lookups.

Purely in-memory — no real database access. The script itself must never
import or call any write/insert/update/delete function.
"""

from __future__ import annotations

import inspect
import io

import scripts.website_health_report as health_report


def make_website(id_, organization_id=10, page_name="Careers", url="https://example.org/1"):
    return {"id": id_, "organization_id": organization_id, "page_name": page_name, "url": url}


def make_history(
    status_code=200,
    status="SUCCESS",
    notifications_found=0,
    error_message=None,
    started_at="2026-08-19T00:00:00+00:00",
):
    return {
        "status_code": status_code,
        "status": status,
        "notifications_found": notifications_found,
        "error_message": error_message,
        "started_at": started_at,
    }


def org_lookup_stub(organization_id):
    return {"name": f"Org {organization_id}"}


# ---------------------------------------------------------------------------
# classify_health
# ---------------------------------------------------------------------------


def test_no_history_is_not_yet_validated():
    assert health_report.classify_health(None) == health_report.NOT_YET_VALIDATED


def test_404_is_classified():
    assert health_report.classify_health(make_history(status_code=404, status="FAILED")) == health_report.HTTP_404


def test_403_is_classified():
    assert health_report.classify_health(make_history(status_code=403, status="FAILED")) == health_report.HTTP_403


def test_5xx_is_classified():
    assert health_report.classify_health(make_history(status_code=503, status="FAILED")) == health_report.HTTP_5XX


def test_timeout_is_classified():
    result = health_report.classify_health(
        make_history(status_code=None, status="FAILED", error_message="Timeout after 15 seconds")
    )
    assert result == health_report.TIMEOUT


def test_connection_error_is_classified():
    result = health_report.classify_health(
        make_history(status_code=None, status="FAILED", error_message="Connection error: refused")
    )
    assert result == health_report.CONNECTION_ERROR


def test_success_with_candidates_is_recruitment_candidates_found():
    result = health_report.classify_health(make_history(status="SUCCESS", notifications_found=5))
    assert result == health_report.RECRUITMENT_CANDIDATES_FOUND


def test_success_with_no_candidates_is_no_candidates():
    result = health_report.classify_health(make_history(status="SUCCESS", notifications_found=0))
    assert result == health_report.NO_CANDIDATES


def test_unclassified_failure_falls_back_to_other_failure():
    result = health_report.classify_health(
        make_history(status_code=200, status="FAILED", error_message="ValueError: parser exploded")
    )
    assert result == health_report.OTHER_FAILURE


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------


def test_website_with_no_history_is_reported_as_not_yet_validated():
    websites = [make_website(1)]
    out = io.StringIO()

    health_report.run(
        website_lookup=lambda: websites,
        history_lookup=lambda _id: [],
        organization_lookup=org_lookup_stub,
        out=out,
    )

    output = out.getvalue()
    assert "Health: NOT_YET_VALIDATED" in output
    assert "NOT_YET_VALIDATED: 1" in output


def test_uses_most_recent_history_row():
    websites = [make_website(1)]
    # get_scrape_history_by_website returns rows ordered started_at DESC — first is most recent.
    history_rows = [
        make_history(status="SUCCESS", notifications_found=3, started_at="2026-08-19T00:00:00+00:00"),
        make_history(status_code=404, status="FAILED", started_at="2026-08-01T00:00:00+00:00"),
    ]
    out = io.StringIO()

    health_report.run(
        website_lookup=lambda: websites,
        history_lookup=lambda _id: history_rows,
        organization_lookup=org_lookup_stub,
        out=out,
    )

    assert "Health: RECRUITMENT_CANDIDATES_FOUND" in out.getvalue()


def test_summary_counts_multiple_websites_by_category():
    websites = [make_website(1), make_website(2), make_website(3)]
    histories = {
        1: [make_history(status="SUCCESS", notifications_found=2)],
        2: [make_history(status_code=404, status="FAILED")],
        3: [],
    }
    out = io.StringIO()

    health_report.run(
        website_lookup=lambda: websites,
        history_lookup=lambda wid: histories[wid],
        organization_lookup=org_lookup_stub,
        out=out,
    )

    output = out.getvalue()
    assert "RECRUITMENT_CANDIDATES_FOUND: 1" in output
    assert "HTTP_404: 1" in output
    assert "NOT_YET_VALIDATED: 1" in output
    assert "Websites reported: 3" in output


def test_website_ids_filter_uses_site_config_loader():
    from unittest.mock import Mock

    from scraper.site_config import WebsiteConfig

    # A real WebsiteConfig dataclass — unlike a dict/sqlite3.Row it is not
    # subscriptable, which is exactly what `load_websites_by_ids` returns.
    site = WebsiteConfig(
        id=4,
        organization_id=10,
        page_name="Careers",
        url="https://example.org/4",
        parser_name="generic_html",
        parser_metadata=None,
        user_agent=None,
        timeout_seconds=15,
        scrape_interval_minutes=60,
    )
    loader = Mock()
    loader.load_websites_by_ids.return_value = [site]
    args = health_report.parse_args(["--website-ids", "4"])
    out = io.StringIO()

    health_report.run(
        args,
        site_id_lookup=loader,
        history_lookup=lambda _id: [],
        organization_lookup=org_lookup_stub,
        out=out,
    )

    loader.load_websites_by_ids.assert_called_once_with([4])
    output = out.getvalue()
    assert "Website ID: 4" in output
    assert "URL: https://example.org/4" in output


def test_report_ends_with_no_changes_message():
    out = io.StringIO()

    exit_code = health_report.run(
        website_lookup=lambda: [], history_lookup=lambda _id: [], organization_lookup=org_lookup_stub, out=out
    )

    assert exit_code == 0
    assert "No changes were made to the database." in out.getvalue()


def test_health_report_module_has_no_write_functions_imported():
    """Guard against accidental DB mutation."""
    source = inspect.getsource(health_report)
    for forbidden in ("insert_", "update_", "delete_", "mark_reviewed", "touch_last_seen"):
        assert forbidden not in source
