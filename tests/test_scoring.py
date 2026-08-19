"""Tests for parser.scoring.RecruitmentRelevanceScorer."""
from __future__ import annotations

from parser.scoring import (
    DEFAULT_SCORE_THRESHOLD,
    HREF_POSITIVE_WEIGHT,
    PDF_WEIGHT,
    SURROUNDING_POSITIVE_WEIGHT,
    TEXT_NEGATIVE_WEIGHT,
    TEXT_POSITIVE_WEIGHT,
    RecruitmentRelevanceScorer,
)


def _score(scorer, text="", surrounding="", href="", absolute_url=""):
    return scorer.score(
        anchor_text=text,
        surrounding_text=surrounding,
        href=href,
        absolute_url=absolute_url,
    )


def test_no_signal_scores_zero():
    scorer = RecruitmentRelevanceScorer()
    result = _score(scorer, text="Home", surrounding="Home", href="/home", absolute_url="https://example.org/home")

    assert result.score == 0
    assert result.is_pdf is False
    assert result.matched_positive_keywords == ()
    assert result.matched_negative_keywords == ()


def test_positive_keyword_in_anchor_text_increases_score():
    scorer = RecruitmentRelevanceScorer()
    result = _score(scorer, text="Recruitment", href="/x", absolute_url="https://example.org/x")

    assert result.score == TEXT_POSITIVE_WEIGHT
    assert result.matched_positive_keywords == ("recruitment",)


def test_positive_keyword_in_href_increases_score_less_than_text():
    scorer = RecruitmentRelevanceScorer()
    result = _score(scorer, text="Details", href="/recruitment/45", absolute_url="https://example.org/recruitment/45")

    assert result.score == HREF_POSITIVE_WEIGHT
    assert HREF_POSITIVE_WEIGHT < TEXT_POSITIVE_WEIGHT


def test_positive_keyword_in_surrounding_text_contributes_lightly():
    scorer = RecruitmentRelevanceScorer()
    result = _score(
        scorer,
        text="Details",
        surrounding="Recruitment update: Details",
        href="/x",
        absolute_url="https://example.org/x",
    )

    assert result.score == SURROUNDING_POSITIVE_WEIGHT
    assert SURROUNDING_POSITIVE_WEIGHT < TEXT_POSITIVE_WEIGHT


def test_pdf_extension_adds_bonus():
    scorer = RecruitmentRelevanceScorer()
    result = _score(scorer, text="Notice", href="/notice.pdf", absolute_url="https://example.org/notice.pdf")

    assert result.is_pdf is True
    assert result.score == PDF_WEIGHT


def test_pdf_detection_uses_resolved_absolute_url_when_href_is_relative():
    scorer = RecruitmentRelevanceScorer()
    result = _score(scorer, text="Notice", href="notice.pdf", absolute_url="https://example.org/careers/notice.pdf")

    assert result.is_pdf is True


def test_non_pdf_extension_is_not_flagged():
    scorer = RecruitmentRelevanceScorer()
    result = _score(scorer, text="Notice", href="/notice.html", absolute_url="https://example.org/notice.html")

    assert result.is_pdf is False


def test_negative_keyword_in_anchor_text_decreases_score_more_than_positive_increases_it():
    scorer = RecruitmentRelevanceScorer()
    result = _score(scorer, text="Tender", href="/x", absolute_url="https://example.org/x")

    assert result.score == -TEXT_NEGATIVE_WEIGHT
    assert result.matched_negative_keywords == ("tender",)
    assert TEXT_NEGATIVE_WEIGHT > TEXT_POSITIVE_WEIGHT


def test_combined_signals_accumulate():
    scorer = RecruitmentRelevanceScorer()
    result = _score(
        scorer,
        text="Advertisement for Project Associate",
        surrounding="New Advertisement for Project Associate posted",
        href="advertisement.pdf",
        absolute_url="https://example.org/careers/advertisement.pdf",
    )

    assert result.score > DEFAULT_SCORE_THRESHOLD
    assert "advertisement" in result.matched_positive_keywords
    assert "project associate" in result.matched_positive_keywords


def test_negative_signal_can_outweigh_positive_and_pdf_bonus():
    scorer = RecruitmentRelevanceScorer()
    result = _score(
        scorer,
        text="Tender for Career Development Equipment",
        href="/tender/45.pdf",
        absolute_url="https://example.org/tender/45.pdf",
    )

    assert result.score < DEFAULT_SCORE_THRESHOLD


def test_custom_keyword_lists_override_defaults():
    scorer = RecruitmentRelevanceScorer(
        positive_keywords=("openings",),
        negative_keywords=("archive",),
    )

    positive = _score(scorer, text="Openings", href="/x", absolute_url="https://example.org/x")
    assert positive.matched_positive_keywords == ("openings",)

    # "recruitment" is not in the custom positive list, so it no longer scores.
    unrecognized = _score(scorer, text="Recruitment", href="/x", absolute_url="https://example.org/x")
    assert unrecognized.score == 0

    negative = _score(scorer, text="Archive", href="/x", absolute_url="https://example.org/x")
    assert negative.matched_negative_keywords == ("archive",)


def test_matched_keywords_are_deduplicated_across_sources():
    scorer = RecruitmentRelevanceScorer()
    result = _score(
        scorer,
        text="Vacancy",
        surrounding="Vacancy Vacancy Vacancy",
        href="/vacancy",
        absolute_url="https://example.org/vacancy",
    )

    assert result.matched_positive_keywords == ("vacancy",)
