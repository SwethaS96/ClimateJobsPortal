"""Tests for the scheduler wrapper."""

from __future__ import annotations

from unittest.mock import Mock

import pytest

from services.scrape_service import ScrapeSummary
from scheduler.scheduler import ScrapeScheduler


class DummyScheduler:
    def __init__(self) -> None:
        self.jobs: list[tuple[str, dict[str, object]]] = []

    def add_job(self, func, trigger, **kwargs):
        self.jobs.append((trigger, kwargs))

    def start(self) -> None:
        return None

    def shutdown(self, wait: bool = False) -> None:
        return None


def test_run_now_executes_scrape_service_and_returns_summary() -> None:
    scrape_service = Mock()
    scrape_service.run.return_value = ScrapeSummary(
        websites_processed=2,
        successful=1,
        failed=1,
        notifications_added=3,
    )

    scheduler = ScrapeScheduler(scrape_service=scrape_service, interval_hours=12)
    summary = scheduler.run_now()

    assert summary.websites_processed == 2
    assert summary.successful == 1
    assert summary.failed == 1
    assert summary.notifications_added == 3
    scrape_service.run.assert_called_once_with()


def test_start_registers_interval_job() -> None:
    scrape_service = Mock()
    scheduler = ScrapeScheduler(scrape_service=scrape_service, interval_hours=6)
    scheduler.scheduler = DummyScheduler()  # type: ignore[assignment]

    scheduler.start()

    assert scheduler.scheduler is not None
    assert len(scheduler.scheduler.jobs) == 0
