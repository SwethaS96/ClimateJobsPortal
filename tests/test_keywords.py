"""Tests for the default recruitment keyword lists."""
from __future__ import annotations

from parser.keywords import DEFAULT_NEGATIVE_KEYWORDS, DEFAULT_POSITIVE_KEYWORDS


def test_default_positive_keywords_cover_expected_recruitment_terms():
    expected = {
        "recruitment",
        "vacancy",
        "vacancies",
        "career",
        "careers",
        "job",
        "jobs",
        "advertisement",
        "employment",
        "walk-in",
        "jrf",
        "srf",
        "research associate",
        "project associate",
        "scientist",
        "postdoctoral",
        "fellowship",
    }
    assert expected.issubset(set(DEFAULT_POSITIVE_KEYWORDS))


def test_default_negative_keywords_cover_expected_non_recruitment_terms():
    expected = {
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
    }
    assert expected.issubset(set(DEFAULT_NEGATIVE_KEYWORDS))


def test_positive_and_negative_keyword_lists_are_disjoint():
    assert set(DEFAULT_POSITIVE_KEYWORDS).isdisjoint(set(DEFAULT_NEGATIVE_KEYWORDS))


def test_keyword_lists_have_no_duplicates():
    assert len(DEFAULT_POSITIVE_KEYWORDS) == len(set(DEFAULT_POSITIVE_KEYWORDS))
    assert len(DEFAULT_NEGATIVE_KEYWORDS) == len(set(DEFAULT_NEGATIVE_KEYWORDS))
