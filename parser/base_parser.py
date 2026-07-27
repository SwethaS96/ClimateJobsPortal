"""Base parser abstraction for notification parsers."""

from __future__ import annotations

from abc import ABC, abstractmethod

from parser.models import ParsedNotification


class BaseParser(ABC):
    """Abstract base class for all parser implementations."""

    @abstractmethod
    def parse(self, html: str, page_url: str) -> list[ParsedNotification]:
        """Parse HTML and return a list of notifications.

        Args:
            html: The raw HTML content of the page.
            page_url: The URL of the page being parsed.

        Returns:
            A list of `ParsedNotification` objects extracted from the HTML.
        """
        raise NotImplementedError
