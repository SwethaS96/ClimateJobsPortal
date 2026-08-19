"""Canonical generic HTML parser and default fallback.

Extracts candidate recruitment-notification links from arbitrary HTML,
scores each candidate for relevance with `RecruitmentRelevanceScorer`, and
returns `ParsedNotification` objects only for candidates whose score
crosses a configurable threshold. Not every hyperlink on a page is treated
as a notification — plain navigation, tenders, and other non-recruitment
links are filtered out by score rather than by a hardcoded allow/deny list.
"""

from __future__ import annotations

from urllib.parse import urljoin

from bs4 import BeautifulSoup

from parser.base_parser import BaseParser
from parser.keywords import DEFAULT_NEGATIVE_KEYWORDS, DEFAULT_POSITIVE_KEYWORDS
from parser.models import ParsedNotification
from parser.scoring import DEFAULT_SCORE_THRESHOLD, RecruitmentRelevanceScorer

IGNORED_HREF_SCHEMES = ("javascript:", "mailto:", "tel:")


class GenericHTMLParser(BaseParser):
    """Generic HTML parser that extracts recruitment-notification candidates.

    Every anchor with visible text and a usable href is scored for
    recruitment relevance using its text, href, surrounding page context,
    and whether it points at a PDF. Positive and negative keyword lists and
    the score threshold are all configurable per instance.
    """

    def __init__(
        self,
        positive_keywords: tuple[str, ...] | None = None,
        negative_keywords: tuple[str, ...] | None = None,
        score_threshold: int = DEFAULT_SCORE_THRESHOLD,
    ) -> None:
        self.scorer = RecruitmentRelevanceScorer(
            positive_keywords=positive_keywords or DEFAULT_POSITIVE_KEYWORDS,
            negative_keywords=negative_keywords or DEFAULT_NEGATIVE_KEYWORDS,
        )
        self.score_threshold = score_threshold

    def parse(self, html: str, page_url: str) -> list[ParsedNotification]:
        """Parse HTML and extract recruitment-notification candidates.

        Args:
            html: Raw HTML content to parse.
            page_url: URL of the page being parsed, used to resolve
                relative links and recorded as `source_page` metadata.

        Returns:
            List of `ParsedNotification` instances that crossed the score
            threshold. Returns an empty list for empty/unparsable input,
            and never raises.
        """
        try:
            if not html:
                return []

            soup = BeautifulSoup(html, "html.parser")
            results: list[ParsedNotification] = []
            seen: set[tuple[str, str]] = set()

            for anchor in soup.find_all("a"):
                candidate = self._build_candidate(anchor, page_url)
                if candidate is None:
                    continue

                dedupe_key = (candidate.title.lower(), candidate.url.lower())
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)
                results.append(candidate)

            return results
        except Exception:
            # Be defensive: do not raise on bad/malformed HTML.
            return []

    def _build_candidate(self, anchor, page_url: str) -> ParsedNotification | None:
        href = anchor.get("href")
        if not href:
            return None

        href = href.strip()
        if href in ("", "#"):
            return None
        if href.lower().startswith(IGNORED_HREF_SCHEMES):
            return None

        text = " ".join(anchor.get_text(strip=True).split())
        if not text:
            return None

        absolute_url = urljoin(page_url, href)
        surrounding_text = self._surrounding_text(anchor)

        candidate_score = self.scorer.score(
            anchor_text=text,
            surrounding_text=surrounding_text,
            href=href,
            absolute_url=absolute_url,
        )

        if candidate_score.score < self.score_threshold:
            return None

        pdf_url = absolute_url if candidate_score.is_pdf else None

        return ParsedNotification(
            title=text,
            url=absolute_url,
            summary=None,
            published_date=None,
            deadline=None,
            pdf_url=pdf_url,
            category=None,
            reference_number=None,
            raw_html=str(anchor),
            metadata={
                "parser": "generic_html",
                "candidate_score": str(candidate_score.score),
                "source_page": page_url,
                "is_pdf": "true" if candidate_score.is_pdf else "false",
                "matched_keywords": ",".join(candidate_score.matched_positive_keywords),
            },
        )

    @staticmethod
    def _surrounding_text(anchor) -> str:
        parent = anchor.parent
        if parent is None:
            return ""
        return " ".join(parent.get_text(strip=True, separator=" ").split())
