"""Actionability classification for parser-produced notification candidates.

`GenericHTMLParser`'s relevance scoring answers "is this link plausibly
about recruitment?" This module answers the narrower question the project
actually cares about: "is this a *specific, open* opportunity someone could
act on?" A "Careers" landing page or a "Retired Scientist" listing is
recruitment-*related* but not actionable — there's nothing to apply to.

`classify()` returns one of three deterministic outcomes:

- VALID   — a specific, open opportunity (an advertisement, a JRF/SRF
            notice, an invitation for applications, ...).
- INVALID — a concluded process (results/selections/shortlists) or a
            non-specific page (a directory, a landing page, a tender).
- REVIEW  — neither a recognized positive nor negative pattern matched;
            the classifier has no basis to decide either way, so the
            candidate is flagged for manual review rather than guessed at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import unquote, urlsplit

from parser.models import ParsedNotification
from services.notification_patterns import (
    DEFAULT_HARD_NEGATIVE_PATTERNS,
    DEFAULT_HARD_NEGATIVE_TITLE_ONLY_PATTERNS,
    DEFAULT_POSITIVE_PATTERNS,
    DEFAULT_SOFT_NEGATIVE_PATTERNS,
    FELLOWSHIP_CONTEXT_WORDS,
    RECRUITMENT_CONTEXT_WORDS,
    RECRUITMENT_SOURCE_PAGE_KEYWORDS,
    SHORT_RECRUITMENT_LABELS,
    PatternReason,
)

_SEPARATOR_PATTERN = re.compile(r"[-_–—]+")  # hyphen, underscore, en dash, em dash
_WHITESPACE_PATTERN = re.compile(r"\s+")
_FILE_EXTENSION_PATTERN = re.compile(r"\.[a-z0-9]{1,5}$")


def _year_adjacent_pattern(keyword: str) -> re.Pattern:
    escaped = re.escape(keyword)
    return re.compile(rf"\b{escaped}\s+(?:19|20)\d{{2}}\b|\b(?:19|20)\d{{2}}\s+{escaped}\b")


# A bare-but-otherwise-unqualified keyword ("recruitment", "fellowship")
# only counts as actionable when it co-occurs with a concrete
# opportunity/action word, or with a year directly adjacent to it (a dated
# cycle, e.g. "Recruitment 2026") — not when another word sits between
# them ("Recruitment Handbook 2025", "Fellowship Schemes 2026").
_RECRUITMENT_YEAR_ADJACENT_PATTERN = _year_adjacent_pattern("recruitment")
_FELLOWSHIP_YEAR_ADJACENT_PATTERN = _year_adjacent_pattern("fellowship")


def normalize_for_matching(text: str | None) -> str:
    """Normalize text for substring pattern matching.

    URL-decodes percent-encoded sequences (so a URL containing
    "Selected%20Candidates" matches the same as literal "Selected
    Candidates"), lowercases, and collapses hyphens/underscores/dashes and
    repeated whitespace to single spaces. This only affects the
    representation used internally for matching — the original
    `ParsedNotification.title`/`.url` are never modified.
    """
    if not text:
        return ""
    decoded = unquote(text)
    decoded = decoded.lower()
    decoded = _SEPARATOR_PATTERN.sub(" ", decoded)
    decoded = _WHITESPACE_PATTERN.sub(" ", decoded).strip()
    return decoded


def _recruitment_is_actionable(combined_text: str) -> bool:
    """Whether "recruitment" in `combined_text` is backed by a real signal.

    True when co-occurring with a concrete opportunity/action word (see
    `RECRUITMENT_CONTEXT_WORDS`) or a year directly adjacent to
    "recruitment" (a dated cycle, e.g. "Recruitment 2026"). False for bare
    process/policy mentions like "Recruitment Assessment and Promotion
    Rules" or "Recruitment Handbook 2025" — a year elsewhere in the text
    does not, by itself, make "recruitment" actionable.
    """
    if "recruitment" not in combined_text:
        return False
    if any(word in combined_text for word in RECRUITMENT_CONTEXT_WORDS):
        return True
    return bool(_RECRUITMENT_YEAR_ADJACENT_PATTERN.search(combined_text))


def _fellowship_is_actionable(combined_text: str) -> bool:
    """Same idea as `_recruitment_is_actionable`, for bare "fellowship".

    True when co-occurring with a concrete opportunity/action word (see
    `FELLOWSHIP_CONTEXT_WORDS` — deliberately excludes "fellow", which is
    a substring of "fellowship" itself) or a year directly adjacent to
    "fellowship". False for informational scheme/portal mentions like
    "Fellowship Schemes" or "Scholarships and Fellowships".
    """
    if "fellowship" not in combined_text:
        return False
    if any(word in combined_text for word in FELLOWSHIP_CONTEXT_WORDS):
        return True
    return bool(_FELLOWSHIP_YEAR_ADJACENT_PATTERN.search(combined_text))


def _url_path_segments(url: str | None) -> list[str]:
    """Normalized path segments of `url`, each with a trailing file
    extension stripped (so "/recruitment.html" still yields "recruitment").
    """
    if not url:
        return []
    path = urlsplit(url).path
    segments = []
    for raw_segment in path.split("/"):
        if not raw_segment:
            continue
        without_extension = _FILE_EXTENSION_PATTERN.sub("", raw_segment)
        segments.append(normalize_for_matching(without_extension))
    return segments


def _url_has_matching_segment(url: str | None, normalized_pattern: str) -> bool:
    """Whether `normalized_pattern` is an entire URL path segment.

    A clean path segment ("/recruitment/", "/vacancies/45") is meaningful
    context and counts. A pattern that only appears as a substring *inside*
    a longer segment — most commonly a static PDF filename like
    "advertisement_scst_cell.pdf" — does not: on its own, a filename token
    must not be enough to make an otherwise unrelated candidate VALID.
    """
    return normalized_pattern in _url_path_segments(url)


def is_recruitment_source_page(page_name: str | None) -> bool:
    """Whether a website's configured page is itself a dedicated
    recruitment/careers/jobs source, as opposed to a generic homepage that
    merely mentions careers/announcements in its own description (e.g.
    "Announcements / Careers (homepage — no dedicated page confirmed)").
    """
    if not page_name:
        return False
    normalized = page_name.lower()
    if "homepage" in normalized:
        return False
    return any(keyword in normalized for keyword in RECRUITMENT_SOURCE_PAGE_KEYWORDS)


_NORMALIZED_SHORT_RECRUITMENT_LABELS = frozenset(normalize_for_matching(label) for label in SHORT_RECRUITMENT_LABELS)


class Classification(str, Enum):
    """Outcome of classifying a notification candidate."""

    VALID = "VALID"
    INVALID = "INVALID"
    REVIEW = "REVIEW"


@dataclass(frozen=True)
class ClassificationResult:
    """A classification outcome paired with the reason it was reached."""

    status: Classification
    reason: str


class NotificationValidator:
    """Classifies candidates as VALID / INVALID / REVIEW.

    Configurable: callers may supply custom pattern lists instead of the
    module defaults in `services.notification_patterns`.
    """

    def __init__(
        self,
        hard_negative_patterns: tuple[PatternReason, ...] | None = None,
        soft_negative_patterns: tuple[PatternReason, ...] | None = None,
        positive_patterns: tuple[PatternReason, ...] | None = None,
        hard_negative_title_only_patterns: tuple[PatternReason, ...] | None = None,
    ) -> None:
        self.hard_negative_patterns = hard_negative_patterns or DEFAULT_HARD_NEGATIVE_PATTERNS
        self.soft_negative_patterns = soft_negative_patterns or DEFAULT_SOFT_NEGATIVE_PATTERNS
        self.positive_patterns = positive_patterns or DEFAULT_POSITIVE_PATTERNS
        self.hard_negative_title_only_patterns = (
            hard_negative_title_only_patterns
            if hard_negative_title_only_patterns is not None
            else DEFAULT_HARD_NEGATIVE_TITLE_ONLY_PATTERNS
        )

    def classify(
        self,
        parsed_notification: ParsedNotification,
        *,
        page_is_recruitment_source: bool = False,
    ) -> ClassificationResult:
        """Classify a candidate as VALID, INVALID, or REVIEW, with a reason.

        `page_is_recruitment_source` is an optional, opt-in signal from the
        caller (see `is_recruitment_source_page`) that the website's
        configured page is itself a dedicated recruitment/careers/jobs
        page rather than a generic homepage. It only affects short, bare
        labels like "Recruitment" or "Jobs" that would otherwise have no
        basis for a decision — every other rule is unchanged, and omitting
        it (the default) reproduces prior behavior exactly.
        """
        title = (parsed_notification.title or "").strip()
        if not title:
            return ClassificationResult(Classification.INVALID, "Empty title.")

        title_normalized = normalize_for_matching(title)
        url_normalized = normalize_for_matching(parsed_notification.url)

        def matches(pattern_reason: PatternReason) -> bool:
            normalized_pattern = normalize_for_matching(pattern_reason.pattern)
            return normalized_pattern in title_normalized or normalized_pattern in url_normalized

        def title_only_matches(pattern_reason: PatternReason) -> bool:
            normalized_pattern = normalize_for_matching(pattern_reason.pattern)
            return normalized_pattern in title_normalized

        def positive_matches(pattern_reason: PatternReason) -> bool:
            """Positive patterns require a stronger URL signal than
            negatives: the title alone is always sufficient (it's the
            visible, strongest signal), but a URL match only counts when
            the pattern is a whole path segment — see
            `_url_has_matching_segment`. A generic filename token can
            support an already-positive title, but must not create a
            VALID classification on its own."""
            normalized_pattern = normalize_for_matching(pattern_reason.pattern)
            if normalized_pattern in title_normalized:
                return True
            return _url_has_matching_segment(parsed_notification.url, normalized_pattern)

        hard_hit = next((p for p in self.hard_negative_patterns if matches(p)), None)
        if hard_hit is not None:
            return ClassificationResult(Classification.INVALID, hard_hit.reason)

        title_only_hard_hit = next(
            (p for p in self.hard_negative_title_only_patterns if title_only_matches(p)), None
        )
        if title_only_hard_hit is not None:
            return ClassificationResult(Classification.INVALID, title_only_hard_hit.reason)

        if page_is_recruitment_source and title_normalized in _NORMALIZED_SHORT_RECRUITMENT_LABELS:
            return ClassificationResult(
                Classification.VALID,
                "Short recruitment-section label on a page configured as a recruitment/careers/jobs source.",
            )

        positive_hit = next((p for p in self.positive_patterns if positive_matches(p)), None)
        if positive_hit is not None:
            return ClassificationResult(Classification.VALID, positive_hit.reason)

        combined_text = f"{title_normalized} {url_normalized}"
        if _recruitment_is_actionable(combined_text):
            return ClassificationResult(
                Classification.VALID,
                "Recruitment mentioned alongside a specific opportunity/action word or a dated cycle.",
            )

        if _fellowship_is_actionable(combined_text):
            return ClassificationResult(
                Classification.VALID,
                "Fellowship mentioned alongside a specific opportunity/action word or a dated cycle.",
            )

        soft_hit = next((p for p in self.soft_negative_patterns if matches(p)), None)
        if soft_hit is not None:
            return ClassificationResult(Classification.INVALID, soft_hit.reason)

        return ClassificationResult(
            Classification.REVIEW,
            "No clear actionable recruitment signal found; needs manual review.",
        )

    def is_valid(self, parsed_notification: ParsedNotification) -> bool:
        """Return True only for candidates classified VALID."""
        return self.classify(parsed_notification).status == Classification.VALID
