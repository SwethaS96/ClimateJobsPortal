"""Tests for scripts/run_weekly_production.py.

Uses fakes/mocks throughout — no real network access, no real database
writes, no real email. `scripts.run_validation_batch.run` is patched at
module level so these tests never scrape a real website.
"""

from __future__ import annotations

import argparse
import io
import sqlite3
from unittest.mock import Mock

import pytest

import scripts.run_weekly_production as weekly
from scraper.site_config import WebsiteConfig


def make_site(site_id: int) -> WebsiteConfig:
    return WebsiteConfig(
        id=site_id,
        organization_id=10,
        page_name="Recruitment",
        url=f"https://example.org/{site_id}",
        parser_name="generic_html",
        parser_metadata=None,
        user_agent=None,
        timeout_seconds=15,
        scrape_interval_minutes=60,
    )


# ---------------------------------------------------------------------------
# 12. all enabled websites are dynamically selected (never hard-coded)
# ---------------------------------------------------------------------------


def test_load_enabled_website_ids_is_dynamic_not_hardcoded():
    site_loader = Mock()
    site_loader.load_enabled_websites.return_value = [make_site(1), make_site(4), make_site(99)]

    ids = weekly.load_enabled_website_ids(site_loader)

    assert ids == [1, 4, 99]
    site_loader.load_enabled_websites.assert_called_once_with()


def test_run_uses_dynamic_website_ids_when_none_given(monkeypatch):
    site_loader = Mock()
    site_loader.load_enabled_websites.return_value = [make_site(7)]
    monkeypatch.setattr(weekly, "SiteConfigLoader", lambda: site_loader)
    monkeypatch.setattr(weekly, "integrity_check", lambda out: True)

    batch_run = Mock(return_value=0)
    monkeypatch.setattr(weekly.run_validation_batch, "run", batch_run)

    args = argparse.Namespace(dry_run=True, confirm=False, website_ids=None)
    weekly.run(args, out=io.StringIO())

    called_args = batch_run.call_args.args[0]
    assert called_args.website_ids == [7]


# ---------------------------------------------------------------------------
# 13. database integrity failure stops the run
# ---------------------------------------------------------------------------


def test_run_stops_immediately_if_pre_integrity_check_fails(monkeypatch):
    monkeypatch.setattr(weekly, "integrity_check", lambda out: False)
    batch_run = Mock()
    monkeypatch.setattr(weekly.run_validation_batch, "run", batch_run)

    args = argparse.Namespace(dry_run=True, confirm=False, website_ids=[1])
    out = io.StringIO()
    exit_code = weekly.run(args, out=out)

    assert exit_code == 1
    assert "STOP" in out.getvalue()
    batch_run.assert_not_called()


def test_run_reports_failure_and_nonzero_exit_if_post_integrity_check_fails(monkeypatch):
    calls = {"n": 0}

    def fake_integrity_check(out):
        calls["n"] += 1
        return calls["n"] == 1  # pre-check passes, post-check fails

    monkeypatch.setattr(weekly, "integrity_check", fake_integrity_check)
    monkeypatch.setattr(weekly.run_validation_batch, "run", Mock(return_value=0))

    args = argparse.Namespace(dry_run=True, confirm=False, website_ids=[1])
    out = io.StringIO()
    exit_code = weekly.run(args, out=out)

    assert exit_code == 1
    assert "DO NOT COMMIT" in out.getvalue()


# ---------------------------------------------------------------------------
# 6. dry-run never sends email
# ---------------------------------------------------------------------------


def test_dry_run_never_calls_send_weekly_digest(monkeypatch):
    monkeypatch.setattr(weekly, "integrity_check", lambda out: True)
    monkeypatch.setattr(weekly.run_validation_batch, "run", Mock(return_value=0))
    digest_mock = Mock()
    monkeypatch.setattr(weekly, "send_weekly_digest", digest_mock)

    args = argparse.Namespace(dry_run=True, confirm=False, website_ids=[1])
    out = io.StringIO()
    exit_code = weekly.run(args, out=out)

    assert exit_code == 0
    digest_mock.assert_not_called()
    assert "N/A (dry run)" in out.getvalue()


def test_dry_run_never_creates_a_backup(monkeypatch):
    monkeypatch.setattr(weekly, "integrity_check", lambda out: True)
    monkeypatch.setattr(weekly.run_validation_batch, "run", Mock(return_value=0))
    backup_mock = Mock()
    monkeypatch.setattr(weekly, "backup_database", backup_mock)

    args = argparse.Namespace(dry_run=True, confirm=False, website_ids=[1])
    weekly.run(args, out=io.StringIO())

    backup_mock.assert_not_called()


def test_real_run_creates_a_backup_before_scraping(monkeypatch):
    monkeypatch.setattr(weekly, "integrity_check", lambda out: True)
    monkeypatch.setattr(weekly.run_validation_batch, "run", Mock(return_value=0))
    monkeypatch.setattr(weekly, "send_weekly_digest", Mock(return_value={"sent": False, "message": "x"}))
    backup_mock = Mock()
    monkeypatch.setattr(weekly, "backup_database", backup_mock)

    args = argparse.Namespace(dry_run=False, confirm=True, website_ids=[1])
    weekly.run(args, out=io.StringIO())

    backup_mock.assert_called_once()


# ---------------------------------------------------------------------------
# 11. website failure does not stop the run (delegated to run_validation_batch,
# already covered by its own Phase 30 regression tests — this confirms the
# orchestration script doesn't swallow/short-circuit that behavior).
# ---------------------------------------------------------------------------


def test_run_continues_to_email_even_if_batch_reports_website_failures(monkeypatch):
    monkeypatch.setattr(weekly, "integrity_check", lambda out: True)
    monkeypatch.setattr(weekly, "backup_database", Mock())
    # run_validation_batch.run() always returns 0 even with per-site failures
    # (Phase 30) — the orchestration script must not treat that as fatal.
    monkeypatch.setattr(weekly.run_validation_batch, "run", Mock(return_value=0))
    digest_mock = Mock(return_value={"sent": True, "notifications_included": 2, "organizations_included": 1, "notifications_excluded": 0})
    monkeypatch.setattr(weekly, "send_weekly_digest", digest_mock)

    args = argparse.Namespace(dry_run=False, confirm=True, website_ids=[1, 2, 3])
    exit_code = weekly.run(args, out=io.StringIO())

    assert exit_code == 0
    digest_mock.assert_called_once()


# ---------------------------------------------------------------------------
# 14. required SMTP environment variables are handled safely
# ---------------------------------------------------------------------------


def test_send_weekly_digest_with_missing_config_does_not_crash(monkeypatch):
    monkeypatch.setattr(weekly.settings, "SMTP_HOST", None)
    monkeypatch.setattr(weekly.settings, "SMTP_USERNAME", None)
    monkeypatch.setattr(weekly.settings, "SMTP_PASSWORD", None)
    monkeypatch.setattr(weekly.settings, "EMAIL_FROM", None)
    monkeypatch.setattr(weekly.settings, "EMAIL_TO", [])

    out = io.StringIO()
    result = weekly.send_weekly_digest(out)

    assert result["sent"] is False
    # Naming a missing variable is fine and helpful; only its *value* must
    # never be printed (covered by the dedicated "never prints password"
    # test below).
    assert "EMAIL SKIPPED" in out.getvalue()
    assert "SMTP_PASSWORD" in out.getvalue()


def test_send_weekly_digest_never_prints_password_even_when_configured(monkeypatch):
    monkeypatch.setattr(weekly.settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(weekly.settings, "SMTP_PORT", 587)
    monkeypatch.setattr(weekly.settings, "SMTP_USERNAME", "user@example.com")
    monkeypatch.setattr(weekly.settings, "SMTP_PASSWORD", "super-secret-value")
    monkeypatch.setattr(weekly.settings, "EMAIL_FROM", "user@example.com")
    monkeypatch.setattr(weekly.settings, "EMAIL_TO", ["dest@example.com"])

    fake_provider_cls = Mock()
    fake_service_instance = Mock()
    fake_service_instance.send_digest.return_value = {
        "sent": False, "message": "No new recruitment notifications.",
        "notifications_included": 0, "notifications_excluded": 0, "organizations_included": 0,
    }
    monkeypatch.setattr(weekly, "SMTPEmailProvider", fake_provider_cls)
    monkeypatch.setattr(weekly, "EmailDigestService", lambda email_provider: fake_service_instance)

    out = io.StringIO()
    weekly.send_weekly_digest(out)

    assert "super-secret-value" not in out.getvalue()


# ---------------------------------------------------------------------------
# 9 & 10. email success/failure marking (delegated to EmailDigestService,
# already exhaustively covered in tests/test_email_service.py — this
# confirms the orchestration wrapper reports correctly either way).
# ---------------------------------------------------------------------------


def test_send_weekly_digest_reports_success(monkeypatch):
    monkeypatch.setattr(weekly.settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(weekly.settings, "SMTP_USERNAME", "u")
    monkeypatch.setattr(weekly.settings, "SMTP_PASSWORD", "p")
    monkeypatch.setattr(weekly.settings, "EMAIL_FROM", "from@example.com")
    monkeypatch.setattr(weekly.settings, "EMAIL_TO", ["to@example.com"])

    fake_service_instance = Mock()
    fake_service_instance.send_digest.return_value = {
        "sent": True, "message": None,
        "notifications_included": 3, "notifications_excluded": 0, "organizations_included": 2,
    }
    monkeypatch.setattr(weekly, "SMTPEmailProvider", Mock())
    monkeypatch.setattr(weekly, "EmailDigestService", lambda email_provider: fake_service_instance)

    out = io.StringIO()
    result = weekly.send_weekly_digest(out)

    assert result["sent"] is True
    assert "EMAIL SENT" in out.getvalue()
    assert "3 notification(s)" in out.getvalue()


def test_send_weekly_digest_reports_failure_without_crashing(monkeypatch):
    monkeypatch.setattr(weekly.settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(weekly.settings, "SMTP_USERNAME", "u")
    monkeypatch.setattr(weekly.settings, "SMTP_PASSWORD", "p")
    monkeypatch.setattr(weekly.settings, "EMAIL_FROM", "from@example.com")
    monkeypatch.setattr(weekly.settings, "EMAIL_TO", ["to@example.com"])

    fake_service_instance = Mock()
    fake_service_instance.send_digest.return_value = {
        "sent": False, "message": "Email delivery failed; no notifications marked as sent.",
        "notifications_included": 0, "notifications_excluded": 5, "organizations_included": 0,
    }
    monkeypatch.setattr(weekly, "SMTPEmailProvider", Mock())
    monkeypatch.setattr(weekly, "EmailDigestService", lambda email_provider: fake_service_instance)

    out = io.StringIO()
    result = weekly.send_weekly_digest(out)

    assert result["sent"] is False
    assert "EMAIL NOT SENT" in out.getvalue()
    assert "remain eligible for the next run" in out.getvalue()


# ---------------------------------------------------------------------------
# misc
# ---------------------------------------------------------------------------


def test_no_enabled_websites_is_a_clean_no_op(monkeypatch):
    monkeypatch.setattr(weekly, "integrity_check", lambda out: True)
    site_loader = Mock()
    site_loader.load_enabled_websites.return_value = []
    monkeypatch.setattr(weekly, "SiteConfigLoader", lambda: site_loader)
    batch_run = Mock()
    monkeypatch.setattr(weekly.run_validation_batch, "run", batch_run)

    args = argparse.Namespace(dry_run=True, confirm=False, website_ids=None)
    exit_code = weekly.run(args, out=io.StringIO())

    assert exit_code == 0
    batch_run.assert_not_called()


def test_parse_args_requires_either_dry_run_or_confirm():
    with pytest.raises(SystemExit):
        weekly.parse_args([])


def test_parse_args_rejects_both_dry_run_and_confirm():
    with pytest.raises(SystemExit):
        weekly.parse_args(["--dry-run", "--confirm"])


def test_backup_database_writes_a_readable_sqlite_file(tmp_path, monkeypatch):
    src_path = tmp_path / "source.db"
    conn = sqlite3.connect(src_path)
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()

    def fake_get_connection():
        c = sqlite3.connect(src_path)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(weekly, "get_connection", fake_get_connection)
    monkeypatch.setattr(weekly, "close_connection", lambda c: c.close())

    backup_dir = tmp_path / "backups"
    backup_path = weekly.backup_database(io.StringIO(), backup_dir=backup_dir)

    assert backup_path.exists()
    verify = sqlite3.connect(backup_path)
    assert verify.execute("SELECT id FROM t").fetchone()[0] == 1
    verify.close()
