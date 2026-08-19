"""Parser specialized for the IITM (Indian Institute of Tropical Meteorology) website."""

from __future__ import annotations

from parser.generic_html import GenericHTMLParser


class IITMParser(GenericHTMLParser):
    """IITM-specific parser.

    Currently extends `GenericHTMLParser` unchanged; will be customized
    once IITM's HTML structure requires site-specific extraction logic.
    """
