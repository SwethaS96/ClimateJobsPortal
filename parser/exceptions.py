"""Parser-related exceptions for the ClimateJobsPortal scraper framework."""

from __future__ import annotations


class ParserError(Exception):
    """Base exception for parser failures."""


class ParserRegistrationError(ParserError):
    """Raised when parser registration fails."""


class ParserNotFoundError(ParserError):
    """Raised when a requested parser cannot be found."""
