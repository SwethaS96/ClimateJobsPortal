"""Tests for scripts/audit_validation_candidates.py using fakes/mocks.

No real network access. No real database writes — the JSON snapshot is
written under a pytest tmp_path, never into the real `data/` directory.
"""

from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from unittest.mock import Mock

import scripts.audit_validation_candidates as audit
from parser.models import ParsedNotification
from scraper.engine import ScrapeResult
from scraper.site_config import WebsiteConfig


def make_site(site_id: int = 15, organization_id: int = 10) -> WebsiteConfig:
    return WebsiteConfig(
        id=site_id,
        organization_id=organization_id,
        page_name="Announcements",
        url=f"https://example.org/{site_id}",
        parser_name="generic_html",
        parser_metadata=None,
        user_agent=None,
        timeout_seconds=15,
        scrape_interval_minutes=60,
    )


def make_candidate(title: str, url: str = "https://example.org/notice", pdf_url: str | None = None) -> ParsedNotification:
    return ParsedNotification(
        title=title,
        url=url,
        pdf_url=pdf_url,
        raw_html=f"<a href='{url}'>{title}</a>",
        metadata={
            "parser": "generic_html",
            "candidate_score": "12",
            "source_page": "https://example.org/",
            "is_pdf": "true" if pdf_url else "false",
            "matched_keywords": "recruitment",
        },
    )


def make_result(site: WebsiteConfig, success: bool = True, notifications=None) -> ScrapeResult:
    return ScrapeResult(
        website_id=site.id,
        page_name=site.page_name,
        success=success,
        status_code=200 if success else None,
        notifications=notifications or [],
        error=None if success else "Connection error",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
        duration_seconds=0.1,
    )


def org_lookup_stub(organization_id):
    return {"name": f"Org {organization_id}"}


class FakeEngine:
    def __init__(self, result: ScrapeResult) -> None:
        self.result = result
        self.downloader = Mock()
        self.scrape_calls: list[int] = []

    def scrape(self, site: WebsiteConfig) -> ScrapeResult:
        self.scrape_calls.append(site.id)
        return self.result


def make_site_loader(sites: list[WebsiteConfig]) -> Mock:
    loader = Mock()
    loader.load_websites_by_ids.return_value = sites
    return loader


# ---------------------------------------------------------------------------
# collect_candidates
# ---------------------------------------------------------------------------


def test_collect_candidates_classifies_each_candidate():
    from services.notification_validator import NotificationValidator

    site = make_site()
    candidates = [
        make_candidate("Research Associate Recruitment 2026"),
        make_candidate("Careers"),
        make_candidate("Departmental Update"),
    ]
    engine = FakeEngine(make_result(site, notifications=candidates))
    validator = NotificationValidator()

    records = audit.collect_candidates(site, engine=engine, validator=validator, organization_lookup=org_lookup_stub)

    assert len(records) == 3
    assert records[0]["classification"] == "VALID"
    assert records[1]["classification"] == "INVALID"
    assert records[2]["classification"] == "REVIEW"
    assert records[0]["organization"] == "Org 10"
    assert records[0]["website_id"] == site.id


def test_collect_candidates_returns_empty_list_on_failed_scrape():
    from services.notification_validator import NotificationValidator

    site = make_site()
    engine = FakeEngine(make_result(site, success=False))
    validator = NotificationValidator()

    records = audit.collect_candidates(site, engine=engine, validator=validator, organization_lookup=org_lookup_stub)

    assert records == []


def test_collect_candidates_surfaces_metadata_fields():
    from services.notification_validator import NotificationValidator

    site = make_site()
    candidate = make_candidate("Vacancy Notice", pdf_url="https://example.org/notice.pdf")
    engine = FakeEngine(make_result(site, notifications=[candidate]))
    validator = NotificationValidator()

    records = audit.collect_candidates(site, engine=engine, validator=validator, organization_lookup=org_lookup_stub)

    record = records[0]
    assert record["candidate_score"] == "12"
    assert record["matched_keywords"] == "recruitment"
    assert record["source_page"] == "https://example.org/"
    assert record["pdf_url"] == "https://example.org/notice.pdf"
    assert record["raw_html"] is not None


# ---------------------------------------------------------------------------
# run() — snapshotting, filtering, no DB writes
# ---------------------------------------------------------------------------


def test_run_writes_json_snapshot(tmp_path):
    from services.notification_validator import NotificationValidator

    site = make_site()
    candidates = [make_candidate("Research Associate Recruitment")]
    engine = FakeEngine(make_result(site, notifications=candidates))
    loader = make_site_loader([site])
    out = io.StringIO()

    args = audit.parse_args(["--website-id", str(site.id)])
    audit.run(
        args,
        site_loader=loader,
        engine=engine,
        validator=NotificationValidator(),
        organization_lookup=org_lookup_stub,
        audit_dir=tmp_path,
        out=out,
    )

    snapshot_path = tmp_path / f"website_{site.id}.json"
    assert snapshot_path.exists()
    data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["classification"] == "VALID"
    assert engine.scrape_calls == [site.id]


def test_run_uses_cached_snapshot_and_does_not_rescrape(tmp_path):
    from services.notification_validator import NotificationValidator

    site = make_site()
    snapshot_path = tmp_path / f"website_{site.id}.json"
    snapshot_path.write_text(
        json.dumps([{"website_id": site.id, "organization": "Org 10", "title": "Cached", "url": "x",
                     "classification": "VALID", "classification_reason": "r", "candidate_score": "1",
                     "matched_keywords": "recruitment", "pdf_url": None, "source_page": "x", "raw_html": None}]),
        encoding="utf-8",
    )
    engine = FakeEngine(make_result(site, notifications=[]))
    loader = make_site_loader([site])
    out = io.StringIO()

    args = audit.parse_args(["--website-id", str(site.id)])
    audit.run(
        args,
        site_loader=loader,
        engine=engine,
        validator=NotificationValidator(),
        organization_lookup=org_lookup_stub,
        audit_dir=tmp_path,
        out=out,
    )

    assert engine.scrape_calls == []
    assert "Cached" in out.getvalue()


def test_run_refresh_forces_rescrape_even_with_cache(tmp_path):
    from services.notification_validator import NotificationValidator

    site = make_site()
    snapshot_path = tmp_path / f"website_{site.id}.json"
    snapshot_path.write_text(json.dumps([]), encoding="utf-8")
    candidates = [make_candidate("Vacancy Notice")]
    engine = FakeEngine(make_result(site, notifications=candidates))
    loader = make_site_loader([site])
    out = io.StringIO()

    args = audit.parse_args(["--website-id", str(site.id), "--refresh"])
    audit.run(
        args,
        site_loader=loader,
        engine=engine,
        validator=NotificationValidator(),
        organization_lookup=org_lookup_stub,
        audit_dir=tmp_path,
        out=out,
    )

    assert engine.scrape_calls == [site.id]
    data = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert len(data) == 1


def test_run_filters_by_classification(tmp_path):
    from services.notification_validator import NotificationValidator

    site = make_site()
    candidates = [
        make_candidate("Research Associate Recruitment"),
        make_candidate("Careers"),
        make_candidate("Departmental Update"),
    ]
    engine = FakeEngine(make_result(site, notifications=candidates))
    loader = make_site_loader([site])
    out = io.StringIO()

    args = audit.parse_args(["--website-id", str(site.id), "--classification", "REVIEW"])
    audit.run(
        args,
        site_loader=loader,
        engine=engine,
        validator=NotificationValidator(),
        organization_lookup=org_lookup_stub,
        audit_dir=tmp_path,
        out=out,
    )

    output = out.getvalue()
    assert "Candidates: 1" in output
    assert "Departmental Update" in output
    assert "Research Associate Recruitment" not in output


def test_run_website_not_found_writes_no_snapshot(tmp_path):
    loader = Mock()
    loader.load_websites_by_ids.return_value = []
    engine = FakeEngine(make_result(make_site()))
    out = io.StringIO()

    args = audit.parse_args(["--website-id", "999"])
    audit.run(
        args,
        site_loader=loader,
        engine=engine,
        organization_lookup=org_lookup_stub,
        audit_dir=tmp_path,
        out=out,
    )

    assert not (tmp_path / "website_999.json").exists()
    assert "not found" in out.getvalue()


def test_run_ends_with_no_database_changes_message(tmp_path):
    loader = make_site_loader([make_site()])
    engine = FakeEngine(make_result(make_site()))
    out = io.StringIO()

    args = audit.parse_args(["--website-id", "15"])
    exit_code = audit.run(
        args,
        site_loader=loader,
        engine=engine,
        organization_lookup=org_lookup_stub,
        audit_dir=tmp_path,
        out=out,
    )

    assert exit_code == 0
    assert "No database changes were made." in out.getvalue()


def test_module_has_no_write_functions_imported():
    """Guard against accidental DB mutation."""
    import inspect

    source = inspect.getsource(audit)
    for forbidden in ("insert_", "update_", "delete_", "mark_reviewed"):
        assert forbidden not in source
