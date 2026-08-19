"""Unit tests for the parser framework."""

from __future__ import annotations

import pytest

from parser.base_parser import BaseParser
from parser.csir import CSIRParser
from parser.exceptions import ParserNotFoundError, ParserRegistrationError
from parser.generic_html import GenericHTMLParser
from parser.iitm import IITMParser
from parser.imd import IMDParser
from parser.models import ParsedNotification
from parser.niot import NIOTParser
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


def test_register_builtin_parsers_registers_all_expected_names():
    registry = ParserRegistry()
    registry.register_builtin_parsers()

    assert registry.list_parsers() == [
        "csir",
        "generic_html",
        "iitm",
        "imd",
        "niot",
    ]


def test_register_builtin_parsers_maps_names_to_expected_classes():
    registry = ParserRegistry()
    registry.register_builtin_parsers()

    assert registry.get("generic_html") is GenericHTMLParser
    assert registry.get("iitm") is IITMParser
    assert registry.get("imd") is IMDParser
    assert registry.get("niot") is NIOTParser
    assert registry.get("csir") is CSIRParser


def test_parser_registry_lookup_is_case_insensitive_for_builtins():
    registry = ParserRegistry()
    registry.register_builtin_parsers()

    assert registry.get("IITM") is IITMParser
    assert registry.get("Csir") is CSIRParser


@pytest.mark.parametrize("parser_class", [IMDParser, IITMParser, NIOTParser, CSIRParser])
def test_specialized_parsers_inherit_generic_html_parser(parser_class):
    assert issubclass(parser_class, GenericHTMLParser)
    assert issubclass(parser_class, BaseParser)


@pytest.mark.parametrize("parser_class", [IMDParser, IITMParser, NIOTParser, CSIRParser])
def test_specialized_parsers_behave_like_generic_html_parser(parser_class):
    html = '<a href="/jobs/1">Vacancy Notice</a>'
    parser = parser_class()

    result = parser.parse(html, "https://example.org")

    assert result == GenericHTMLParser().parse(html, "https://example.org")


def test_get_or_default_returns_registered_parser_when_known():
    registry = ParserRegistry()
    registry.register_builtin_parsers()

    assert registry.get_or_default("imd") is IMDParser


def test_get_or_default_falls_back_to_generic_html_for_unknown_name():
    registry = ParserRegistry()
    registry.register_builtin_parsers()

    assert registry.get_or_default("some_unregistered_site") is GenericHTMLParser


def test_get_or_default_falls_back_when_registry_has_no_generic_html_registered():
    registry = ParserRegistry()

    assert registry.get_or_default("anything") is GenericHTMLParser


def test_get_or_default_never_raises():
    registry = ParserRegistry()
    registry.register_builtin_parsers()

    try:
        registry.get_or_default("totally-unknown-parser")
    except ParserNotFoundError:
        pytest.fail("get_or_default should never raise ParserNotFoundError")
