"""Parser registry for dynamic parser lookup and registration."""

from __future__ import annotations

from typing import Type

from parser.base_parser import BaseParser
from parser.exceptions import ParserRegistrationError, ParserNotFoundError


class ParserRegistry:
    """Registry for parser classes used by the scraper framework."""

    def __init__(self) -> None:
        self._parsers: dict[str, Type[BaseParser]] = {}

    def register(self, name: str, parser_class: Type[BaseParser]) -> None:
        """Register a parser class under a unique name.

        Args:
            name: Unique parser name.
            parser_class: Parser class implementing BaseParser.

        Raises:
            ParserRegistrationError: When the parser name is already registered.
        """
        normalized_name = name.lower()
        if normalized_name in self._parsers:
            raise ParserRegistrationError(
                f"Parser '{name}' is already registered"
            )
        self._parsers[normalized_name] = parser_class

    def get(self, name: str) -> Type[BaseParser]:
        """Retrieve a parser class by name.

        Args:
            name: The parser name to lookup.

        Returns:
            The registered parser class.

        Raises:
            ParserNotFoundError: When no parser exists for the given name.
        """
        normalized_name = name.lower()
        parser_class = self._parsers.get(normalized_name)
        if parser_class is None:
            raise ParserNotFoundError(f"Parser '{name}' not found")
        return parser_class

    def list_parsers(self) -> list[str]:
        """Return all registered parser names."""
        return sorted(self._parsers.keys())
