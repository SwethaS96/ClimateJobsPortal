"""Relevance scoring for candidate recruitment-notification links.

`RecruitmentRelevanceScorer` replaces a simple keyword yes/no filter with a
weighted score, combining signals from the anchor text, its surrounding
page context, the href itself, and whether the link points at a PDF. Only
candidates whose score crosses a configurable threshold should be treated
as notifications — a link is never excluded purely for lacking a keyword,
it simply fails to accumulate enough signal to cross the threshold.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse

from parser.keywords import DEFAULT_NEGATIVE_KEYWORDS, DEFAULT_POSITIVE_KEYWORDS

# Anchor text is the strongest signal, followed by the href slug, then the
# looser surrounding page context. PDFs get a flat bonus since recruitment
# advertisements in this domain are very commonly published as PDFs.
TEXT_POSITIVE_WEIGHT = 3
HREF_POSITIVE_WEIGHT = 1
SURROUNDING_POSITIVE_WEIGHT = 1
PDF_WEIGHT = 2

TEXT_NEGATIVE_WEIGHT = 4
HREF_NEGATIVE_WEIGHT = 2
SURROUNDING_NEGATIVE_WEIGHT = 1

DEFAULT_SCORE_THRESHOLD = 3


@dataclass(frozen=True)
class CandidateScore:
    """Result of scoring a single candidate link."""

    score: int
    is_pdf: bool
    matched_positive_keywords: tuple[str, ...] = field(default_factory=tuple)
    matched_negative_keywords: tuple[str, ...] = field(default_factory=tuple)


class RecruitmentRelevanceScorer:
    """Scores candidate links for recruitment-notification relevance.

    Configurable: callers may supply custom positive/negative keyword
    lists instead of the module defaults in `parser.keywords`.
    """

    def __init__(
        self,
        positive_keywords: tuple[str, ...] | None = None,
        negative_keywords: tuple[str, ...] | None = None,
    ) -> None:
        self.positive_keywords = tuple(
            keyword.lower() for keyword in (positive_keywords or DEFAULT_POSITIVE_KEYWORDS)
        )
        self.negative_keywords = tuple(
            keyword.lower() for keyword in (negative_keywords or DEFAULT_NEGATIVE_KEYWORDS)
        )

    def score(
        self,
        *,
        anchor_text: str,
        surrounding_text: str,
        href: str,
        absolute_url: str,
    ) -> CandidateScore:
        """Score one candidate link.

        Args:
            anchor_text: Visible, whitespace-normalized anchor text.
            surrounding_text: Text of the anchor's containing element,
                used as looser contextual evidence.
            href: The raw href attribute value.
            absolute_url: The href resolved against the page URL.

        Returns:
            A `CandidateScore` with the total score, PDF flag, and the
            keywords that contributed to the score.
        """
        anchor_text_lower = anchor_text.lower()
        surrounding_lower = surrounding_text.lower()
        href_lower = href.lower()

        is_pdf = self._is_pdf(href_lower) or self._is_pdf(absolute_url.lower())

        text_pos, text_pos_matched = self._count_matches(anchor_text_lower, self.positive_keywords)
        href_pos, href_pos_matched = self._count_matches(href_lower, self.positive_keywords)
        surrounding_pos, surrounding_pos_matched = self._count_matches(surrounding_lower, self.positive_keywords)

        text_neg, text_neg_matched = self._count_matches(anchor_text_lower, self.negative_keywords)
        href_neg, href_neg_matched = self._count_matches(href_lower, self.negative_keywords)
        surrounding_neg, surrounding_neg_matched = self._count_matches(surrounding_lower, self.negative_keywords)

        score = (
            text_pos * TEXT_POSITIVE_WEIGHT
            + href_pos * HREF_POSITIVE_WEIGHT
            + surrounding_pos * SURROUNDING_POSITIVE_WEIGHT
            + (PDF_WEIGHT if is_pdf else 0)
            - text_neg * TEXT_NEGATIVE_WEIGHT
            - href_neg * HREF_NEGATIVE_WEIGHT
            - surrounding_neg * SURROUNDING_NEGATIVE_WEIGHT
        )

        matched_positive = tuple(
            sorted(set(text_pos_matched) | set(href_pos_matched) | set(surrounding_pos_matched))
        )
        matched_negative = tuple(
            sorted(set(text_neg_matched) | set(href_neg_matched) | set(surrounding_neg_matched))
        )

        return CandidateScore(
            score=score,
            is_pdf=is_pdf,
            matched_positive_keywords=matched_positive,
            matched_negative_keywords=matched_negative,
        )

    @staticmethod
    def _is_pdf(value: str) -> bool:
        return urlparse(value).path.lower().endswith(".pdf")

    @staticmethod
    def _count_matches(haystack: str, keywords: tuple[str, ...]) -> tuple[int, list[str]]:
        matched: list[str] = []
        count = 0
        for keyword in keywords:
            occurrences = haystack.count(keyword)
            if occurrences:
                matched.append(keyword)
                count += occurrences
        return count, matched
