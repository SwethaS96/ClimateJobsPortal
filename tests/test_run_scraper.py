from __future__ import annotations

from types import SimpleNamespace

from scripts.run_scraper import main


class FakeResult:
    def __init__(self, success: bool, notifications: list[object], duration_seconds: float) -> None:
        self.success = success
        self.notifications = notifications
        self.duration_seconds = duration_seconds


class FakeScrapeEngine:
    def __init__(self, site_config_loader=None, **kwargs) -> None:
        self.site_config_loader = site_config_loader
        self.scraped_sites = []
        self.downloader = SimpleNamespace(close=lambda: None)

    def scrape(self, site):
        self.scraped_sites.append(site)
        if site.page_name == "Jobs":
            return FakeResult(True, [object()], 0.25)
        return FakeResult(False, [], 0.10)


class FakeLoader:
    def __init__(self) -> None:
        self.sites = [
            SimpleNamespace(
                id=1,
                organization_id=1,
                page_name="Jobs",
                url="https://example.org/jobs",
                parser_name="generic_html",
            ),
            SimpleNamespace(
                id=2,
                organization_id=2,
                page_name="Careers",
                url="https://example.org/careers",
                parser_name="generic_html",
            ),
        ]

    def load_enabled_websites(self):
        return self.sites


def test_main_prints_progress_and_summary(monkeypatch, capsys) -> None:
    monkeypatch.setattr("scripts.run_scraper.SiteConfigLoader", FakeLoader)
    monkeypatch.setattr("scripts.run_scraper.ScrapeEngine", FakeScrapeEngine)
    monkeypatch.setattr("scripts.run_scraper.get_organization_by_id", lambda organization_id: SimpleNamespace(name=f"Org {organization_id}"))

    exit_code = main()

    captured = capsys.readouterr().out
    assert exit_code == 0
    assert "[1/2]" in captured
    assert "Organization:" in captured
    assert "Websites processed" in captured
    assert "Successful" in captured
    assert "Failed" in captured
    assert "Notifications Found" in captured
