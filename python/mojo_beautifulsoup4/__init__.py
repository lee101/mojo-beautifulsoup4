"""Beautiful Soup-compatible HTML trees accelerated by Mojo."""

from .element import (
    Comment,
    Declaration,
    Doctype,
    NavigableString,
    PageElement,
    ProcessingInstruction,
    ResultSet,
    SoupStrainer,
    Tag,
)
from .selector import SelectorSyntaxError
from .soup import BeautifulSoup, BeautifulStoneSoup, FeatureNotFound

__version__ = "0.1.0"

__all__ = [
    "BeautifulSoup",
    "BeautifulStoneSoup",
    "Comment",
    "Declaration",
    "Doctype",
    "FeatureNotFound",
    "NavigableString",
    "PageElement",
    "ProcessingInstruction",
    "ResultSet",
    "SelectorSyntaxError",
    "SoupStrainer",
    "Tag",
]
