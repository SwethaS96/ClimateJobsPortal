"""Parser specialized for the IMD (India Meteorological Department) website."""

from __future__ import annotations

from parser.generic_html import GenericHTMLParser


class IMDParser(GenericHTMLParser):
    """IMD-specific parser.

    Currently extends `GenericHTMLParser` unchanged; will be customized
    once IMD's HTML structure requires site-specific extraction logic.
    """
