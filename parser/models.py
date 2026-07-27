"""Data models for parsed notifications."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ParsedNotification:
    """Represents a parsed notification extracted from a website."""

    title: str
    url: str
    summary: str | None = None
    published_date: str | None = None
    deadline: str | None = None
    pdf_url: str | None = None
    category: str | None = None
    reference_number: str | None = None
    raw_html: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)
