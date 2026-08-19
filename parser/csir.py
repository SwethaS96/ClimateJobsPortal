"""Parser specialized for the CSIR (Council of Scientific and Industrial Research) website."""

from __future__ import annotations

from parser.generic_html import GenericHTMLParser


class CSIRParser(GenericHTMLParser):
    """CSIR-specific parser.

    Currently extends `GenericHTMLParser` unchanged; will be customized
    once CSIR's HTML structure requires site-specific extraction logic.
    """
