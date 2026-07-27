"""A simple generic HTML parser that extracts links as notifications.

This parser finds all <a> anchors with both visible text and an href,
converts relative URLs to absolute using `urllib.parse.urljoin`, and
returns a list of `ParsedNotification` objects.
"""
from __future__ import annotations


from urllib.parse import urljoin

from bs4 import BeautifulSoup

from parser.base_parser import BaseParser
from parser.models import ParsedNotification


class GenericHTMLParser(BaseParser):
    """Generic HTML parser extracting anchors as notifications.

    The parser is intentionally simple: it maps each anchor with visible
    text and an href into a `ParsedNotification` where the anchor text
    becomes the `title` and the resolved absolute URL becomes `url`.
    """

    def parse(self, html: str, page_url: str) -> list[ParsedNotification]:
        """Parse HTML and extract notifications from anchors.

        Args:
            html: Raw HTML content to parse.
            page_url: Base URL used to resolve relative links.

        Returns:
            List of ParsedNotification instances. Returns an empty list
            if no anchors with visible text and hrefs are found or if
            the input cannot be parsed.
        """
        try:
            if not html:
                return []

            soup = BeautifulSoup(html, "html.parser")
            results: list[ParsedNotification] = []

            for a in soup.find_all("a"):
                # href must exist
                href = a.get("href")
                if not href:
                    continue

                # normalize href and ignore invalid values/schemes
                href = href.strip()
                if href == "" or href == "#":
                    continue
                href_lower = href.lower()
                if href_lower.startswith(("javascript:", "mailto:", "tel:")):
                    continue

                # visible text (trimmed) must be present
                text = a.get_text(strip=True)
                if not text:
                    continue

                absolute = urljoin(page_url, href)
                results.append(
                    ParsedNotification(
                        title=text,
                        url=absolute,
                        summary=None,
                        published_date=None,
                        deadline=None,
                        pdf_url=None,
                        category=None,
                        reference_number=None,
                        raw_html=str(a),
                        metadata={"parser": "generic_html"},
                    )
                )

            return results
        except Exception:
            # Be defensive: do not raise on bad/malformed HTML
            return []
