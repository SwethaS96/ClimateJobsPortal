"""Tests for scripts/audit_website_config.py using fake lookups.

Purely in-memory — no real database access, no network. The script must
never import or call any write/insert/update/delete function.
"""

from __future__ import annotations

import inspect
import io

import scripts.audit_website_config as audit


def make_website(id_, organization_id=10, page_name="Careers", url="https://example.org/1",
                  parser_name="generic_html", is_enabled=1):
    return {
        "id": id_,
        "organization_id": organization_id,
        "page_name": page_name,
        "url": url,
        "parser_name": parser_name,
        "is_enabled": is_enabled,
    }


def org_lookup_stub(organization_id):
    return {"name": f"Org {organization_id}"}


# ---------------------------------------------------------------------------
# page_name_flags
# ---------------------------------------------------------------------------


def test_page_name_flags_detects_homepage():
    assert audit.page_name_flags("Announcements / Careers (homepage)") == ["homepage", "careers", "announcements"]


def test_page_name_flags_detects_recruitment():
    assert audit.page_name_flags("Recruitment") == ["recruitment"]


def test_page_name_flags_none_for_specific_page():
    assert audit.page_name_flags("Junior Research Fellow Notification") == []


def test_page_name_flags_is_case_insensitive():
    assert audit.page_name_flags("HOMEPAGE") == ["homepage"]


def test_page_name_flags_handles_none():
    assert audit.page_name_flags(None) == []


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------


def test_run_reports_each_requested_website():
    websites = [make_website(1, page_name="Recruitment"), make_website(4, page_name="Careers")]
    out = io.StringIO()

    args = audit.parse_args(["--website-ids", "1", "4"])
    audit.run(args, website_lookup=lambda ids: websites, organization_lookup=org_lookup_stub, out=out)

    output = out.getvalue()
    assert "Website ID: 1" in output
    assert "Website ID: 4" in output
    assert "Page name: Recruitment" in output
    assert "Page name: Careers" in output


def test_run_reports_enabled_status():
    websites = [make_website(1, is_enabled=1), make_website(2, is_enabled=0)]
    out = io.StringIO()

    args = audit.parse_args(["--website-ids", "1", "2"])
    audit.run(args, website_lookup=lambda ids: websites, organization_lookup=org_lookup_stub, out=out)

    output = out.getvalue()
    assert "Enabled: YES" in output
    assert "Enabled: NO" in output


def test_run_reports_not_found_website():
    out = io.StringIO()

    args = audit.parse_args(["--website-ids", "999"])
    audit.run(args, website_lookup=lambda ids: [], organization_lookup=org_lookup_stub, out=out)

    output = out.getvalue()
    assert "Website ID: 999" in output
    assert "NOT FOUND" in output


def test_run_flags_homepage_careers_recruitment_announcements_in_summary():
    websites = [
        make_website(1, page_name="Recruitment"),
        make_website(4, page_name="Announcements / Careers (homepage)"),
        make_website(7, page_name="Junior Research Fellow Notice"),
    ]
    out = io.StringIO()

    args = audit.parse_args(["--website-ids", "1", "4", "7"])
    audit.run(args, website_lookup=lambda ids: websites, organization_lookup=org_lookup_stub, out=out)

    output = out.getvalue()
    assert "PAGE-NAME FLAG SUMMARY" in output
    assert "Website ID 1: recruitment" in output
    assert "Website ID 4: homepage, careers, announcements" in output
    assert "Website ID 7" not in output.split("PAGE-NAME FLAG SUMMARY")[1]


def test_run_calls_website_lookup_with_requested_ids():
    calls = []

    def lookup(ids):
        calls.append(list(ids))
        return []

    args = audit.parse_args(["--website-ids", "1", "4", "7"])
    audit.run(args, website_lookup=lookup, organization_lookup=org_lookup_stub, out=io.StringIO())

    assert calls == [[1, 4, 7]]


def test_run_ends_with_no_changes_message():
    out = io.StringIO()
    args = audit.parse_args(["--website-ids", "1"])
    exit_code = audit.run(
        args, website_lookup=lambda ids: [make_website(1)], organization_lookup=org_lookup_stub, out=out
    )

    assert exit_code == 0
    assert "No changes were made to the database. URLs and parsers were not modified." in out.getvalue()


def test_field_helper_supports_dataclass_style_objects():
    from scraper.site_config import WebsiteConfig

    site = WebsiteConfig(
        id=4, organization_id=10, page_name="Careers", url="https://example.org/4",
        parser_name="generic_html", parser_metadata=None, user_agent=None,
        timeout_seconds=15, scrape_interval_minutes=60,
    )
    assert audit._field(site, "page_name") == "Careers"


def test_module_has_no_write_functions_imported():
    """Guard against accidental DB mutation."""
    source = inspect.getsource(audit)
    for forbidden in ("insert_", "update_", "delete_", "mark_reviewed"):
        assert forbidden not in source
