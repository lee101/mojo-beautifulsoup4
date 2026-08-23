from __future__ import annotations

import html
import re
import warnings

import numpy as np

from . import _lib
from .element import (
    Comment,
    Declaration,
    Doctype,
    NavigableString,
    ProcessingInstruction,
    SoupStrainer,
    Tag,
)

_ATTR = re.compile(
    r"""([^\s=/>]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?"""
)
_VOID = Tag._void_elements
class FeatureNotFound(ValueError):
    pass


class BeautifulSoup(Tag):
    ROOT_TAG_NAME = "[document]"

    def __init__(
        self,
        markup="",
        features=None,
        builder=None,
        parse_only=None,
        from_encoding=None,
        exclude_encodings=None,
        element_classes=None,
        **kwargs,
    ):
        if features and isinstance(features, (list, tuple)):
            features = features[0] if features else None
        if features not in (None, "html", "html.parser", "mojo"):
            raise FeatureNotFound(
                f"Couldn't find a tree builder with the features you requested: {features}"
            )
        super().__init__(self.ROOT_TAG_NAME)
        self.builder = builder
        self.parse_only = parse_only
        self._selector_cache = None
        self._position_cache = {}
        self.contains_replacement_characters = False
        if hasattr(markup, "read"):
            markup = markup.read()
        if isinstance(markup, bytes):
            encoding = from_encoding or self._detect_encoding(markup)
            text = markup.decode(encoding, "replace")
            self.original_encoding = encoding
            self.contains_replacement_characters = "\ufffd" in text
        else:
            text = str(markup or "")
            self.original_encoding = None
            if from_encoding:
                warnings.warn("You provided Unicode markup but also provided a value for from_encoding.")
        self.markup = text
        self._parse(text)
        if parse_only is not None:
            self._apply_strainer(parse_only)

    @staticmethod
    def _detect_encoding(markup):
        head = markup[:2048]
        match = re.search(br"(?i)(?:charset\s*=\s*|encoding\s*=\s*[\"'])([-\w.]+)", head)
        if match:
            return match.group(1).decode("ascii", "ignore").lower()
        try:
            markup.decode("utf-8")
            return "utf-8"
        except UnicodeDecodeError:
            return "windows-1252"

    @staticmethod
    def _attrs(raw, name_end):
        attrs = {}
        for match in _ATTR.finditer(raw, name_end):
            key = match.group(1).lower()
            double, single, unquoted = match.group(2, 3, 4)
            value = double if double is not None else single
            if value is None:
                value = unquoted if unquoted is not None else ""
            if "&" in value:
                value = html.unescape(value)
            if key == "class":
                value = value.split()
            attrs[key] = value
        return attrs

    def _parse(self, text):
        encoded = text.encode("utf-8")
        kinds, starts, ends, aux = _lib.tokenize(encoded)
        stack = [self]
        raw_names = {"script", "style"}
        tokens = zip(*(field.tolist() for field in (kinds, starts, ends, aux)))
        for kind, start, end, extra in tokens:
            if kind == 0:
                chunk = encoded[start:end].decode("utf-8")
                if stack[-1].name not in raw_names:
                    if "&" in chunk:
                        chunk = html.unescape(chunk)
                if chunk:
                    node = NavigableString(chunk)
                    node.parent = stack[-1]
                    stack[-1].contents.append(node)
            elif kind == 1:
                name = encoded[start:extra].decode("ascii", "ignore").lower()
                if not name:
                    continue
                raw = encoded[start:end].decode("utf-8")
                tag = Tag(name, self._attrs(raw, extra - start), stack[-1])
                stack[-1].contents.append(tag)
                self_closing = raw.rstrip().endswith("/")
                if name not in _VOID and not self_closing:
                    stack.append(tag)
            elif kind == 2:
                name = encoded[start:extra].decode("ascii", "ignore").lower()
                for index in range(len(stack) - 1, 0, -1):
                    if stack[index].name == name:
                        del stack[index:]
                        break
            elif kind == 3:
                chunk = encoded[start:end].decode("utf-8")
                node = Comment(chunk)
                node.parent = stack[-1]
                stack[-1].contents.append(node)
            elif kind == 4:
                chunk = encoded[start:end].decode("utf-8")
                declaration = chunk.strip()
                if declaration.lower().startswith("doctype"):
                    value = declaration[7:].strip()
                    node = Doctype(value)
                else:
                    node = Declaration(declaration)
                node.parent = stack[-1]
                stack[-1].contents.append(node)
            elif kind == 5:
                chunk = encoded[start:end].decode("utf-8")
                node = ProcessingInstruction(chunk.rstrip("?"))
                node.parent = stack[-1]
                stack[-1].contents.append(node)

    def _apply_strainer(self, strainer):
        kept = []
        for child in list(self.contents):
            if isinstance(child, Tag):
                matches = strainer.search(child) if hasattr(strainer, "search") else None
                if matches:
                    kept.append(child)
                else:
                    for node in child.find_all(
                        getattr(strainer, "name", None),
                        getattr(strainer, "attrs", {}),
                        **getattr(strainer, "kwargs", {}),
                    ):
                        node.extract()
                        kept.append(node)
        self.contents = kept
        for child in kept:
            child.parent = self
        self._invalidate()

    def new_tag(self, name, namespace=None, nsprefix=None, attrs={}, **kwargs):
        values = dict(attrs)
        values.update(kwargs)
        return Tag(name, values)

    def new_string(self, s, subclass=None):
        return (subclass or NavigableString)(s)

    def _all_elements(self):
        return [node for node in self.descendants if isinstance(node, Tag)]

    def _build_selector_cache(self):
        elements = self._all_elements()
        blob = bytearray()
        arrays = [[] for _ in range(6)]
        for node in elements:
            values = (
                node.name,
                str(node.get("id", "")),
                " ".join(node.get("class", []))
                if isinstance(node.get("class", []), list)
                else str(node.get("class", "")),
            )
            for index, value in enumerate(values):
                arrays[index * 2].append(len(blob))
                blob.extend(value.encode())
                arrays[index * 2 + 1].append(len(blob))
        packed = tuple(np.asarray(values, dtype=np.int64) for values in arrays)
        self._selector_cache = (elements, blob, packed)

    def _prefilter(self, tag, element_id, classes):
        if self._selector_cache is None:
            self._build_selector_cache()
        elements, blob, packed = self._selector_cache
        if not elements:
            return []
        mask = _lib.prefilter(
            blob,
            *packed,
            tag=tag,
            element_id=element_id,
            classes=classes,
        )
        return [elements[index] for index in np.flatnonzero(mask)]

    def __copy__(self):
        return BeautifulSoup(str(self), "html.parser")

    def __deepcopy__(self, memo):
        return self.__copy__()

    def __str__(self):
        values = []
        for child in self.contents:
            values.append(self._serialize_child(child))
            if isinstance(child, Doctype):
                values.append("\n")
        return "".join(values)


BeautifulStoneSoup = BeautifulSoup
