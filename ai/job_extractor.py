"""Extract structured job metadata from PDF text for a parsed notification."""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from parser.models import ParsedNotification


class JobExtractorBackend(Protocol):
    """Protocol for future LLM or heuristic backends."""

    def extract(self, notification: ParsedNotification, pdf_text: str) -> dict[str, Any]:
        """Return structured job fields for the provided input."""
        ...


class RuleBasedJobExtractor:
    """Simple deterministic extractor for job metadata from PDF text."""

    def extract(self, notification: ParsedNotification, pdf_text: str) -> dict[str, Any]:
        text = (pdf_text or "").strip()
        lower_text = text.lower()

        def find_field(patterns: list[str]) -> str | None:
            for pattern in patterns:
                match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
                if match:
                    value = match.group(1).strip() if match.lastindex else match.group(0).strip()
                    return value
            return None

        title = notification.title or find_field([r"job title\s*[:\-]\s*(.+)", r"position\s*[:\-]\s*(.+)"])
        organization = find_field([r"organization\s*[:\-]\s*(.+)", r"institute\s*[:\-]\s*(.+)"])
        salary = find_field([r"salary\s*[:\-]\s*(.+)", r"pay\s*[:\-]\s*(.+)"])
        qualification = find_field([r"qualification\s*[:\-]\s*(.+)", r"educational qualification\s*[:\-]\s*(.+)"])
        experience = find_field([r"experience\s*[:\-]\s*(.+)", r"years of experience\s*[:\-]\s*(.+)"])
        age_limit = find_field([r"age limit\s*[:\-]\s*(.+)", r"age\s*[:\-]\s*(.+)"])
        last_date = find_field([r"last date\s*[:\-]\s*(.+)", r"deadline\s*[:\-]\s*(.+)"])
        application_link = find_field([r"application link\s*[:\-]\s*(.+)", r"apply at\s*[:\-]\s*(.+)"])

        return {
            "job_title": title,
            "organization": organization,
            "salary": salary,
            "qualification": qualification,
            "experience": experience,
            "age_limit": age_limit,
            "last_date": last_date,
            "application_link": application_link,
        }


class JobExtractor:
    """Facade that can use a pluggable backend for extraction."""

    def __init__(self, backend: JobExtractorBackend | None = None) -> None:
        self.backend = backend or RuleBasedJobExtractor()

    def extract(self, notification: ParsedNotification, pdf_text: str) -> dict[str, Any]:
        """Return structured JSON-ready metadata for the provided notification."""
        result = self.backend.extract(notification, pdf_text)
        return result

    def extract_json(self, notification: ParsedNotification, pdf_text: str) -> str:
        """Return the extracted fields as JSON."""
        return json.dumps(self.extract(notification, pdf_text), indent=2, ensure_ascii=False)
