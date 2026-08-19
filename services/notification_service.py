"""Notification persistence service for scraped results.

Pipeline for each `ParsedNotification` produced by a scrape:

    classify -> duplicate-detect (by title+url hash) -> insert/touch -> process PDF

Classification decides the destination:

    VALID   -> the existing notification persistence flow (insert or
               touch `last_seen`), then its PDF (if any) is downloaded and
               its text extracted.
    INVALID -> discarded entirely.
    REVIEW  -> stored in the review queue instead of `notifications` — no
               notification row is created and no PDF is downloaded, so a
               REVIEW candidate can never end up in the email digest.

A notification (or review candidate) already seen on a prior run is never
re-inserted — for notifications only `last_seen` is refreshed; a review
candidate already queued (by the same stable title+url hash) is simply
left alone. One notification failing classification or persistence never
stops the rest of the batch — the failure is counted and recorded, and
processing continues.
"""

from __future__ import annotations

import json

from database.repositories.notification_repository import insert_notification, touch_last_seen
from database.repositories.notification_review_queue_repository import (
    get_review_candidate_by_hash,
    insert_review_candidate,
)
from parser.models import ParsedNotification
from scraper.engine import ScrapeResult
from services.duplicate_detector import DuplicateDetector
from services.notification_validator import Classification, NotificationValidator, is_recruitment_source_page
from services.pdf_processing_service import PDFProcessingService


class NotificationService:
    """Persist parsed notifications into the SQLite database."""

    def __init__(
        self,
        validator: NotificationValidator | None = None,
        duplicate_detector: DuplicateDetector | None = None,
        pdf_processing_service: PDFProcessingService | None = None,
    ) -> None:
        self.validator = validator or NotificationValidator()
        self.duplicate_detector = duplicate_detector or DuplicateDetector()
        self.pdf_processing_service = pdf_processing_service or PDFProcessingService()

    def persist(self, scrape_result: ScrapeResult, organization_id: int) -> dict[str, object]:
        """Save parsed notifications for one scrape result.

        Returns a summary dict with `inserted`, `updated` (existing
        notifications whose `last_seen` was refreshed), `skipped_invalid`
        (classified INVALID), `skipped_review` (classified REVIEW — queued
        for manual review), `failed` counts, an `errors` list of failure
        messages, and PDF pipeline stats: `pdf_processed` (PDFs a VALID
        candidate pointed at), `pdf_downloaded`/`pdf_download_failed`, and
        `pdf_extraction_success`/`pdf_extraction_failed`.
        """
        inserted = 0
        updated = 0
        skipped_invalid = 0
        skipped_review = 0
        failed = 0
        errors: list[str] = []
        pdf_processed = 0
        pdf_downloaded = 0
        pdf_download_failed = 0
        pdf_extraction_success = 0
        pdf_extraction_failed = 0
        page_is_recruitment_source = is_recruitment_source_page(scrape_result.page_name)

        for notification in scrape_result.notifications:
            try:
                outcome, pdf_result = self._persist_one(
                    notification, scrape_result.website_id, organization_id, page_is_recruitment_source
                )
            except Exception as exc:
                failed += 1
                errors.append(str(exc))
                continue

            if outcome == "inserted":
                inserted += 1
            elif outcome == "updated":
                updated += 1
            elif outcome == "skipped_invalid":
                skipped_invalid += 1
            elif outcome == "skipped_review":
                skipped_review += 1

            if pdf_result is not None:
                pdf_processed += 1
                if pdf_result.get("path") is not None:
                    pdf_downloaded += 1
                elif pdf_result.get("id") is not None:
                    pdf_download_failed += 1

                extraction_status = pdf_result.get("extraction_status")
                if extraction_status in ("SUCCESS", "EMPTY"):
                    pdf_extraction_success += 1
                elif extraction_status == "FAILED":
                    pdf_extraction_failed += 1

        return {
            "inserted": inserted,
            "updated": updated,
            "skipped_invalid": skipped_invalid,
            "skipped_review": skipped_review,
            "failed": failed,
            "errors": errors,
            "pdf_processed": pdf_processed,
            "pdf_downloaded": pdf_downloaded,
            "pdf_download_failed": pdf_download_failed,
            "pdf_extraction_success": pdf_extraction_success,
            "pdf_extraction_failed": pdf_extraction_failed,
        }

    def _persist_one(
        self,
        parsed_notification: ParsedNotification,
        website_id: int,
        organization_id: int,
        page_is_recruitment_source: bool = False,
    ) -> tuple[str, dict | None]:
        classification = self.validator.classify(
            parsed_notification, page_is_recruitment_source=page_is_recruitment_source
        )
        parsed_notification.metadata["classification"] = classification.status.value
        parsed_notification.metadata["classification_reason"] = classification.reason

        if classification.status == Classification.REVIEW:
            self._enqueue_for_review(parsed_notification, website_id, organization_id, classification)
            return "skipped_review", None
        if classification.status != Classification.VALID:
            return "skipped_invalid", None

        title = parsed_notification.title.strip()
        url = parsed_notification.url.strip() if parsed_notification.url else ""

        existing = self.duplicate_detector.find_existing(title, url, website_id)
        if existing is not None:
            touch_last_seen(existing["id"])
            pdf_result = self._process_pdf(existing["id"], parsed_notification)
            return "updated", pdf_result

        hash_value = self.duplicate_detector.build_hash(title, url)
        notification_id = insert_notification(
            organization_id=organization_id,
            website_id=website_id,
            title=title,
            notification_number=parsed_notification.reference_number,
            category=parsed_notification.category,
            notification_date=parsed_notification.published_date,
            application_deadline=parsed_notification.deadline,
            page_url=url or None,
            hash=hash_value,
        )
        pdf_result = self._process_pdf(notification_id, parsed_notification)
        return "inserted", pdf_result

    def _process_pdf(self, notification_id: int, parsed_notification: ParsedNotification) -> dict | None:
        """Download and extract text for a VALID notification's PDF, if any.

        Delegates entirely to `PDFProcessingService` (association, download,
        and extraction). Never invoked for INVALID/REVIEW candidates.
        Returns the processing result dict, or None if there was no
        `pdf_url` to begin with.
        """
        if not parsed_notification.pdf_url:
            return None
        return self.pdf_processing_service.process(parsed_notification, notification_id)

    def _enqueue_for_review(
        self,
        parsed_notification: ParsedNotification,
        website_id: int,
        organization_id: int,
        classification,
    ) -> None:
        title = parsed_notification.title.strip()
        url = parsed_notification.url.strip() if parsed_notification.url else ""
        hash_value = self.duplicate_detector.build_hash(title, url)

        if get_review_candidate_by_hash(hash_value) is not None:
            return  # already queued — never create unlimited review rows

        insert_review_candidate(
            organization_id=organization_id,
            website_id=website_id,
            title=title,
            url=url or None,
            reason=classification.reason,
            classification=classification.status.value,
            raw_html=parsed_notification.raw_html,
            metadata=json.dumps(parsed_notification.metadata),
            hash=hash_value,
        )
