"""Configurable recruitment-relevance keyword lists.

`GenericHTMLParser` (and any parser built on `RecruitmentRelevanceScorer`)
uses these keyword lists to decide which hyperlinks on a page are plausible
recruitment/job notification candidates. Callers may override either list
per-parser instead of relying on these defaults, e.g. to tune a specific
site once its real HTML has been inspected.
"""

from __future__ import annotations

DEFAULT_POSITIVE_KEYWORDS: tuple[str, ...] = (
    "recruitment",
    "recruitment notice",
    "vacancy",
    "vacancies",
    "career",
    "careers",
    "job",
    "jobs",
    "advertisement",
    "employment",
    "engagement",
    "walk-in",
    "walk in",
    "jrf",
    "srf",
    "research associate",
    "project associate",
    "project assistant",
    "project scientist",
    "scientist",
    "postdoctoral",
    "post-doctoral",
    "fellowship",
    "apprentice",
    "young professional",
    "consultant",
    "technical assistant",
    "project staff",
)

DEFAULT_NEGATIVE_KEYWORDS: tuple[str, ...] = (
    "tender",
    "procurement",
    "auction",
    "login",
    "contact",
    "privacy",
    "gallery",
    "about us",
    "annual report",
    "press release",
)
