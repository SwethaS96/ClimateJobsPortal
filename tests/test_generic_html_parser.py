"""Tests for parser.generic_html_parser.GenericHTMLParser."""
from __future__ import annotations

from parser.generic_html_parser import GenericHTMLParser
from parser.models import ParsedNotification


def test_absolute_url():
    html = '<a href="https://example.org/doc">Document</a>'
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")

    assert len(result) == 1
    pn = result[0]
    assert pn.title == "Document"
    assert pn.url == "https://example.org/doc"
    assert pn.raw_html.startswith("<a")


def test_relative_url():
    html = '<a href="/docs/1">Doc1</a>'
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org/base/")

    assert len(result) == 1
    assert result[0].url == "https://example.org/docs/1"


def test_empty_html():
    parser = GenericHTMLParser()
    result = parser.parse("", "https://example.org")
    assert result == []


def test_malformed_html():
    # missing closing tags, etc.
    html = '<a href="/a">A<a href="/b">B'
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")

    # Ensure parser does not crash and returns two notifications
    assert len(result) == 2


def test_link_without_href():
    html = '<a>no href</a>'
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")
    assert result == []


def test_link_without_text():
    html = '<a href="/img"><img src="pic.png"/></a>'
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")
    assert result == []


def test_multiple_links():
    html = '<a href="/one">One</a><a href="/two">Two</a>'
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")
    assert len(result) == 2
    assert {p.title for p in result} == {"One", "Two"}


def test_ignore_invalid_links():
    html = (
        '<a href="#">hash</a>'
        '<a href="javascript:void(0)">js</a>'
        '<a href="mailto:test@example.com">mail</a>'
        '<a href="tel:+911234567890">phone</a>'
        '<a href="/good">Good</a>'
    )
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")

    # Only the valid /good link should be returned
    assert len(result) == 1
    assert result[0].url == "https://example.org/good"


def test_trimmed_href():
    html = '<a href="   /jobs   ">Jobs</a>'
    parser = GenericHTMLParser()
    result = parser.parse(html, "https://example.org")

    assert len(result) == 1
    assert result[0].url == "https://example.org/jobs"
