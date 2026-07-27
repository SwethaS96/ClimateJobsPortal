"""Unit tests for the parser framework."""

from __future__ import annotations

import pytest

from parser.base_parser import BaseParser
from parser.exceptions import ParserNotFoundError, ParserRegistrationError
from parser.models import ParsedNotification
from parser.registry import ParserRegistry


class DummyParser(BaseParser):
    def parse(self, html: str, page_url: str) -> list[ParsedNotification]:
        return [ParsedNotification(title="Dummy", url=page_url)]


def test_parsed_notification_fields():
    notification = ParsedNotification(
        title="Title",
        url="https://example.org",
        summary="Summary",
        published_date="2026-07-27",
        deadline="2026-08-01",
        pdf_url="https://example.org/doc.pdf",
        category="Research",
        reference_number="REF-1",
        raw_html="<p>Test</p>",
        metadata={"source": "example"},
    )

    assert notification.title == "Title"
    assert notification.url == "https://example.org"
    assert notification.summary == "Summary"
    assert notification.metadata["source"] == "example"


def test_base_parser_requires_parse_implementation():
    with pytest.raises(TypeError):
        class InvalidParser(BaseParser):
            pass

        InvalidParser()


def test_parser_registry_register_and_get():
    registry = ParserRegistry()
    registry.register("dummy", DummyParser)

    parser_class = registry.get("dummy")
    assert parser_class is DummyParser
    assert registry.list_parsers() == ["dummy"]


def test_parser_registry_register_is_case_insensitive():
    registry = ParserRegistry()
    registry.register("Dummy", DummyParser)

    parser_class = registry.get("dummy")
    assert parser_class is DummyParser
    assert registry.get("DUMMY") is DummyParser


def test_parser_registry_prevents_duplicate_registration():
    registry = ParserRegistry()
    registry.register("dummy", DummyParser)

    with pytest.raises(ParserRegistrationError):
        registry.register("dummy", DummyParser)


def test_parser_registry_raises_not_found():
    registry = ParserRegistry()

    with pytest.raises(ParserNotFoundError):
        registry.get("missing")
