"""Scheduler for running the scrape service on a recurring interval."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

try:
    from apscheduler.schedulers.blocking import BlockingScheduler
except ImportError:  # pragma: no cover - handled in tests
    BlockingScheduler = None  # type: ignore[assignment]

from services.scrape_service import ScrapeService, ScrapeSummary

logger = logging.getLogger(__name__)


class ScrapeScheduler:
    """Run the scrape service on a configurable interval."""

    def __init__(self, scrape_service: Optional[ScrapeService] = None, interval_hours: int = 24) -> None:
        self.scrape_service = scrape_service or ScrapeService()
        self.interval_hours = interval_hours
        self.scheduler: Optional[BlockingScheduler] = None

    def start(self) -> None:
        """Start the scheduler and begin recurring execution."""
        if self.scheduler is not None:
            return

        if BlockingScheduler is None:
            raise RuntimeError("APScheduler is not installed")

        self.scheduler = BlockingScheduler()
        self.scheduler.add_job(
            self._run_job,
            "interval",
            hours=self.interval_hours,
            next_run_time=datetime.now(timezone.utc),
        )
        self.scheduler.start()

    def stop(self) -> None:
        """Stop the scheduler if it is running."""
        if self.scheduler is None:
            return
        self.scheduler.shutdown(wait=False)
        self.scheduler = None

    def run_now(self) -> ScrapeSummary:
        """Execute the scrape service immediately and return the summary."""
        return self._run_job()

    def _run_job(self) -> ScrapeSummary:
        """Execute the scrape service and log the outcome."""
        started_at = datetime.now(timezone.utc)
        logger.info("Starting scrape job at %s", started_at.isoformat())
        try:
            summary = self.scrape_service.run()
        except Exception as exc:  # pragma: no cover - defensive logging path
            logger.exception("Scrape job failed: %s", exc)
            return ScrapeSummary(
                websites_processed=0,
                successful=0,
                failed=0,
                notifications_added=0,
            )

        logger.info(
            "Scrape job completed at %s with %s websites processed, %s successful, %s failed, %s notifications added",
            datetime.now(timezone.utc).isoformat(),
            summary.websites_processed,
            summary.successful,
            summary.failed,
            summary.notifications_added,
        )
        return summary
