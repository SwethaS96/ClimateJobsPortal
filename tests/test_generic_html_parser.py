"""End-to-end tests for parser.generic_html.GenericHTMLParser."""
from __future__ import annotations

from parser.generic_html import GenericHTMLParser
from parser.scoring import DEFAULT_SCORE_THRESHOLD


def test_recruitment_keyword_in_text_is_extracted():
    html = '<a href="/notices/45">Recruitment Notice for Scientist Posts</a>'
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")

    assert len(result) == 1
    notification = result[0]
    assert notification.title == "Recruitment Notice for Scientist Posts"
    assert notification.url == "https://example.org/notices/45"
    assert notification.raw_html.startswith("<a")


def test_plain_navigation_link_is_not_extracted():
    html = '<a href="/about-us">About Us</a>'
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")

    assert result == []


def test_negative_keyword_link_is_filtered_even_with_href_pdf():
    html = '<a href="/downloads/tender_notice.pdf">Tender Notice</a>'
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")

    assert result == []


def test_common_non_recruitment_links_are_filtered():
    html = (
        '<a href="/login">Login</a>'
        '<a href="/contact">Contact</a>'
        '<a href="/gallery">Gallery</a>'
        '<a href="/privacy">Privacy Policy</a>'
        '<a href="/annual-report">Annual Report</a>'
        '<a href="/press">Press Release</a>'
    )
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")

    assert result == []


def test_pdf_link_is_detected_and_populates_pdf_url():
    html = '<a href="advertisement_12.pdf">Advertisement for Project Associate</a>'
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org/careers/")

    assert len(result) == 1
    notification = result[0]
    assert notification.url == "https://example.org/careers/advertisement_12.pdf"
    assert notification.pdf_url == "https://example.org/careers/advertisement_12.pdf"
    assert notification.metadata["is_pdf"] == "true"


def test_non_pdf_link_leaves_pdf_url_none():
    html = '<a href="/careers/vacancy-45">Vacancy Notice 45</a>'
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")

    assert len(result) == 1
    notification = result[0]
    assert notification.pdf_url is None
    assert notification.metadata["is_pdf"] == "false"


def test_relative_url_is_resolved_to_absolute():
    html = '<a href="/careers/jobs-2026">Jobs 2026</a>'
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org/base/")

    assert len(result) == 1
    assert result[0].url == "https://example.org/careers/jobs-2026"


def test_absolute_url_is_preserved():
    html = '<a href="https://other.example/vacancy/1">Vacancy</a>'
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")

    assert len(result) == 1
    assert result[0].url == "https://other.example/vacancy/1"


def test_surrounding_text_can_push_borderline_candidate_over_threshold():
    html = '<li>Latest Recruitment Update <a href="/notice/45.pdf">View details</a></li>'
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")

    # Anchor text alone ("View details") carries no keyword signal; the
    # surrounding <li> text ("Recruitment") plus the PDF bonus is what
    # crosses the default threshold.
    assert len(result) == 1
    assert result[0].url == "https://example.org/notice/45.pdf"


def test_generic_click_here_link_without_context_is_not_extracted():
    html = '<a href="/notice/45">View details</a>'
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")

    assert result == []


def test_metadata_contains_parser_score_and_source_page():
    html = '<a href="/careers/vacancy-45">Vacancy Notice 45</a>'
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org/page")

    assert len(result) == 1
    metadata = result[0].metadata
    assert metadata["parser"] == "generic_html"
    assert metadata["source_page"] == "https://example.org/page"
    assert int(metadata["candidate_score"]) >= DEFAULT_SCORE_THRESHOLD
    assert "vacancy" in metadata["matched_keywords"]


def test_empty_html():
    parser = GenericHTMLParser()
    result = parser.parse("", "https://example.org")
    assert result == []


def test_malformed_html_does_not_crash():
    # Missing closing tags anywhere in the document; the parser must not
    # raise and must still surface the recruitment-relevant candidate.
    html = '<div><a href="/jobs/open.pdf">Jobs Open <p>Read more'
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")

    assert len(result) == 1
    assert result[0].url == "https://example.org/jobs/open.pdf"


def test_link_without_href_is_skipped():
    html = '<a>Recruitment Notice</a>'
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")
    assert result == []


def test_link_without_text_is_skipped():
    html = '<a href="/jobs"><img src="pic.png"/></a>'
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")
    assert result == []


def test_ignored_href_schemes_are_skipped():
    html = (
        '<a href="#">Recruitment</a>'
        '<a href="javascript:void(0)">Recruitment</a>'
        '<a href="mailto:jobs@example.org">Recruitment</a>'
        '<a href="tel:+911234567890">Recruitment</a>'
        '<a href="/careers/good-notice">Recruitment Notice</a>'
    )
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")

    assert len(result) == 1
    assert result[0].url == "https://example.org/careers/good-notice"


def test_trimmed_href_is_resolved():
    html = '<a href="   /careers/jobs   ">Jobs</a>'
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")

    assert len(result) == 1
    assert result[0].url == "https://example.org/careers/jobs"


def test_duplicate_links_are_deduplicated():
    html = (
        '<nav><a href="/careers/notice-1">Recruitment Notice 1</a></nav>'
        '<main><a href="/careers/notice-1">Recruitment Notice 1</a></main>'
    )
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")

    assert len(result) == 1
    assert result[0].url == "https://example.org/careers/notice-1"


def test_distinct_links_with_same_title_are_both_kept():
    html = (
        '<a href="/careers/notice-1">Recruitment Notice</a>'
        '<a href="/careers/notice-2">Recruitment Notice</a>'
    )
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")

    assert len(result) == 2
    assert {n.url for n in result} == {
        "https://example.org/careers/notice-1",
        "https://example.org/careers/notice-2",
    }


def test_custom_keywords_and_threshold_are_configurable():
    html = '<a href="/openings/42">Openings for Analysts</a>'

    default_parser = GenericHTMLParser()
    assert default_parser.parse(html, "https://example.org") == []

    custom_parser = GenericHTMLParser(
        positive_keywords=("openings", "analyst"),
        score_threshold=2,
    )
    result = custom_parser.parse(html, "https://example.org")

    assert len(result) == 1
    assert result[0].url == "https://example.org/openings/42"
