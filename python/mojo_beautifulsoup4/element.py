from __future__ import annotations

import html
import re
from collections.abc import Iterable


class ResultSet(list):
    def __init__(self, source=None, result=()):
        super().__init__(result)
        self.source = source


class PageElement:
    parent: Tag | None = None

    def _sibling_index(self):
        for index, node in enumerate(self.parent.contents):
            if node is self:
                return index
        raise ValueError("Element is not present in its parent")

    @property
    def next_sibling(self):
        if self.parent is None:
            return None
        siblings = self.parent.contents
        index = self._sibling_index()
        return siblings[index + 1] if index + 1 < len(siblings) else None

    @property
    def previous_sibling(self):
        if self.parent is None:
            return None
        siblings = self.parent.contents
        index = self._sibling_index()
        return siblings[index - 1] if index else None

    @property
    def next_element(self):
        if isinstance(self, Tag) and self.contents:
            return self.contents[0]
        node = self
        while node.parent is not None:
            sibling = node.next_sibling
            if sibling is not None:
                return sibling
            node = node.parent
        return None

    @property
    def previous_element(self):
        sibling = self.previous_sibling
        if sibling is None:
            return self.parent
        while isinstance(sibling, Tag) and sibling.contents:
            sibling = sibling.contents[-1]
        return sibling

    def extract(self):
        if self.parent is not None:
            self.parent.contents.pop(self._sibling_index())
            root = self.parent._root()
            self.parent = None
            root._invalidate()
        return self

    def decompose(self):
        self.extract()
        if isinstance(self, Tag):
            self.clear(decompose=True)

    def replace_with(self, *replacements):
        if self.parent is None:
            raise ValueError("Cannot replace an element with no parent.")
        parent = self.parent
        index = self._sibling_index()
        parent.contents.pop(index)
        self.parent = None
        for value in reversed(replacements):
            node = value if isinstance(value, PageElement) else NavigableString(str(value))
            if node.parent is not None:
                node.extract()
            node.parent = parent
            parent.contents.insert(index, node)
        parent._root()._invalidate()
        return self

    def insert_before(self, *args):
        if self.parent is None:
            raise ValueError("Element has no parent.")
        index = self._sibling_index()
        for value in args:
            self.parent.insert(index, value)
            index += 1

    def insert_after(self, *args):
        if self.parent is None:
            raise ValueError("Element has no parent.")
        index = self._sibling_index() + 1
        for value in args:
            self.parent.insert(index, value)
            index += 1


class NavigableString(str, PageElement):
    def __new__(cls, value=""):
        obj = str.__new__(cls, value)
        obj.parent = None
        return obj

    def __repr__(self):
        return str.__repr__(self)

    @property
    def string(self):
        return self

    @property
    def output_ready(self):
        return True


class PreformattedString(NavigableString):
    PREFIX = ""
    SUFFIX = ""


class Comment(PreformattedString):
    PREFIX = "<!--"
    SUFFIX = "-->"


class Declaration(PreformattedString):
    PREFIX = "<!"
    SUFFIX = ">"


class Doctype(PreformattedString):
    PREFIX = "<!DOCTYPE "
    SUFFIX = ">"


class ProcessingInstruction(PreformattedString):
    PREFIX = "<?"
    SUFFIX = "?>"


def _matches(value, criterion) -> bool:
    if criterion is None:
        return True
    if criterion is True:
        return value is not None
    if callable(criterion) and not hasattr(criterion, "search"):
        return bool(criterion(value))
    if hasattr(criterion, "search"):
        return value is not None and bool(criterion.search(str(value)))
    if isinstance(criterion, (list, tuple, set, frozenset)):
        return any(_matches(value, item) for item in criterion)
    if isinstance(value, list):
        return criterion in value or str(criterion) == " ".join(map(str, value))
    return value == criterion or (value is not None and str(value) == str(criterion))


class AttributeValueList(list):
    def __init__(self, values=(), owner=None):
        super().__init__(values)
        self.owner = owner

    def _changed(self):
        if self.owner is not None:
            self.owner._invalidate()

    def append(self, value):
        super().append(value)
        self._changed()

    def extend(self, values):
        super().extend(values)
        self._changed()

    def insert(self, index, value):
        super().insert(index, value)
        self._changed()

    def pop(self, index=-1):
        value = super().pop(index)
        self._changed()
        return value

    def remove(self, value):
        super().remove(value)
        self._changed()

    def clear(self):
        super().clear()
        self._changed()

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self._changed()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._changed()


class AttributeDict(dict):
    def __init__(self, values=(), owner=None):
        self.owner = owner
        super().__init__()
        items = values.items() if hasattr(values, "items") else values
        for key, value in items:
            dict.__setitem__(self, key, self._wrap(value))

    def _wrap(self, value):
        if isinstance(value, list) and not isinstance(value, AttributeValueList):
            return AttributeValueList(value, self.owner)
        if isinstance(value, AttributeValueList):
            value.owner = self.owner
        return value

    def _changed(self):
        if self.owner is not None:
            self.owner._invalidate()

    def __setitem__(self, key, value):
        super().__setitem__(key, self._wrap(value))
        self._changed()

    def __delitem__(self, key):
        super().__delitem__(key)
        self._changed()

    def update(self, values=(), **kwargs):
        for key, value in dict(values, **kwargs).items():
            super().__setitem__(key, self._wrap(value))
        self._changed()

    def pop(self, key, *default):
        value = super().pop(key, *default)
        self._changed()
        return value

    def clear(self):
        super().clear()
        self._changed()


class Tag(PageElement):
    _void_elements = {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
    }

    def __init__(self, name: str, attrs=None, parent=None):
        self.name = name
        self.attrs = AttributeDict(attrs or {}, owner=self)
        self.contents: list[PageElement] = []
        self.parent = parent

    def _root(self):
        node = self
        while node.parent is not None:
            node = node.parent
        return node

    def _invalidate(self):
        root = self._root()
        if "_selector_cache" in root.__dict__:
            root._selector_cache = None
        position_cache = root.__dict__.get("_position_cache")
        if position_cache is not None:
            position_cache.clear()

    def append(self, tag):
        return self.insert(len(self.contents), tag)

    def insert(self, position: int, *new_children):
        for child in new_children:
            node = child if isinstance(child, PageElement) else NavigableString(str(child))
            if node is self:
                raise ValueError("Cannot insert a tag into itself.")
            if node.parent is not None:
                node.extract()
            node.parent = self
            self.contents.insert(position, node)
            position += 1
        self._invalidate()
        return new_children[0] if len(new_children) == 1 else None

    def extend(self, tags: Iterable):
        for tag in tags:
            self.append(tag)
        return tags

    def clear(self, decompose=False):
        for child in list(self.contents):
            child.parent = None
            if decompose and isinstance(child, Tag):
                child.clear(decompose=True)
        self.contents.clear()
        self._invalidate()

    @property
    def children(self):
        return iter(self.contents)

    @property
    def descendants(self):
        for child in self.contents:
            yield child
            if isinstance(child, Tag):
                yield from child.descendants

    @property
    def parents(self):
        parent = self.parent
        while parent is not None:
            yield parent
            parent = parent.parent

    @property
    def next_siblings(self):
        node = self.next_sibling
        while node is not None:
            yield node
            node = node.next_sibling

    @property
    def previous_siblings(self):
        node = self.previous_sibling
        while node is not None:
            yield node
            node = node.previous_sibling

    @property
    def strings(self):
        for node in self.descendants:
            if isinstance(node, NavigableString):
                yield node

    @property
    def stripped_strings(self):
        for value in self.strings:
            value = str.__str__(value).strip()
            if value:
                yield value

    @property
    def string(self):
        if len(self.contents) != 1:
            return None
        child = self.contents[0]
        if isinstance(child, NavigableString):
            return child
        return child.string

    @property
    def text(self):
        return self.get_text()

    def get_text(self, separator="", strip=False, types=()):
        values = []
        for value in self.strings:
            plain = str.__str__(value)
            if types and not isinstance(value, types):
                continue
            if strip:
                plain = plain.strip()
            if plain or not strip:
                values.append(plain)
        return separator.join(values)

    def __getitem__(self, key):
        return self.attrs[key]

    def __setitem__(self, key, value):
        self.attrs[key] = value
        self._invalidate()

    def __delitem__(self, key):
        del self.attrs[key]
        self._invalidate()

    def __contains__(self, key):
        return key in self.attrs

    def get(self, key, default=None):
        return self.attrs.get(key, default)

    def get_attribute_list(self, key, default=None):
        value = self.attrs.get(key, default if default is not None else [])
        return value if isinstance(value, list) else [value]

    def has_attr(self, key):
        return key in self.attrs

    def _matches(self, name=None, attrs=None, string=None, **kwargs):
        if name is not None:
            if callable(name) and not hasattr(name, "search"):
                if not name(self):
                    return False
            elif not _matches(self.name, name):
                return False
        criteria = dict(attrs or {})
        criteria.update(kwargs)
        if "class_" in criteria:
            criteria["class"] = criteria.pop("class_")
        for key, expected in criteria.items():
            if not _matches(self.attrs.get(key), expected):
                return False
        if string is not None and not _matches(
            str.__str__(self.string) if isinstance(self.string, NavigableString) else None,
            string,
        ):
            return False
        return True

    def find_all(
        self, name=None, attrs={}, recursive=True, string=None, limit=None, **kwargs
    ):
        if isinstance(attrs, str):
            attrs = {"class": attrs}
        criteria = dict(attrs or {})
        criteria.update(kwargs)
        class_value = criteria.pop("class_", criteria.pop("class", None))
        if (
            recursive
            and self is self._root()
            and self.name == "[document]"
            and isinstance(name, str)
            and string is None
            and not criteria
            and (
                class_value is None
                or (
                    isinstance(class_value, str)
                    and class_value
                    and not any(character.isspace() for character in class_value)
                )
            )
        ):
            candidates = self._prefilter(
                name, None, (class_value,) if class_value is not None else ()
            )
            if limit:
                candidates = candidates[:limit]
            return ResultSet(name, candidates)
        iterator = self.descendants if recursive else self.children
        found = ResultSet(name)
        if string is not None and name is None and not attrs and not kwargs:
            for node in iterator:
                if isinstance(node, NavigableString) and _matches(str.__str__(node), string):
                    found.append(node)
                    if limit and len(found) >= limit:
                        break
            return found
        for node in iterator:
            if isinstance(node, Tag) and node._matches(name, attrs, string, **kwargs):
                found.append(node)
                if limit and len(found) >= limit:
                    break
        return found

    def find(self, name=None, attrs={}, recursive=True, string=None, **kwargs):
        result = self.find_all(name, attrs, recursive, string, limit=1, **kwargs)
        return result[0] if result else None

    def find_parent(self, name=None, attrs={}, **kwargs):
        result = self.find_parents(name, attrs, limit=1, **kwargs)
        return result[0] if result else None

    def find_parents(self, name=None, attrs={}, limit=None, **kwargs):
        found = ResultSet(name)
        for node in self.parents:
            if node._matches(name, attrs, **kwargs):
                found.append(node)
                if limit and len(found) >= limit:
                    break
        return found

    def _find_siblings(self, forward, name=None, attrs={}, string=None, limit=None, **kwargs):
        found = ResultSet(name)
        iterator = self.next_siblings if forward else self.previous_siblings
        for node in iterator:
            if isinstance(node, Tag) and node._matches(name, attrs, string, **kwargs):
                found.append(node)
                if limit and len(found) >= limit:
                    break
        return found

    def find_next_siblings(self, name=None, attrs={}, string=None, limit=None, **kwargs):
        return self._find_siblings(True, name, attrs, string, limit, **kwargs)

    def find_next_sibling(self, name=None, attrs={}, string=None, **kwargs):
        result = self.find_next_siblings(name, attrs, string, 1, **kwargs)
        return result[0] if result else None

    def find_previous_siblings(self, name=None, attrs={}, string=None, limit=None, **kwargs):
        return self._find_siblings(False, name, attrs, string, limit, **kwargs)

    def find_previous_sibling(self, name=None, attrs={}, string=None, **kwargs):
        result = self.find_previous_siblings(name, attrs, string, 1, **kwargs)
        return result[0] if result else None

    def _find_all_elements(self, forward, name=None, attrs={}, string=None, limit=None, **kwargs):
        found = ResultSet(name)
        node = self.next_element if forward else self.previous_element
        while node is not None:
            if isinstance(node, Tag) and node._matches(name, attrs, string, **kwargs):
                found.append(node)
                if limit and len(found) >= limit:
                    break
            node = node.next_element if forward else node.previous_element
        return found

    def find_all_next(self, name=None, attrs={}, string=None, limit=None, **kwargs):
        return self._find_all_elements(True, name, attrs, string, limit, **kwargs)

    def find_next(self, name=None, attrs={}, string=None, **kwargs):
        result = self.find_all_next(name, attrs, string, 1, **kwargs)
        return result[0] if result else None

    def find_all_previous(self, name=None, attrs={}, string=None, limit=None, **kwargs):
        return self._find_all_elements(False, name, attrs, string, limit, **kwargs)

    def find_previous(self, name=None, attrs={}, string=None, **kwargs):
        result = self.find_all_previous(name, attrs, string, 1, **kwargs)
        return result[0] if result else None

    def select(self, selector, namespaces=None, limit=0, **kwargs):
        from .selector import select

        return select(self, selector, limit=limit)

    def select_one(self, selector, namespaces=None, **kwargs):
        result = self.select(selector, limit=1)
        return result[0] if result else None

    def __call__(self, name=None, attrs={}, recursive=True, string=None, limit=None, **kwargs):
        return self.find_all(name, attrs, recursive, string, limit, **kwargs)

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return self.find(name.replace("_", "-"))

    def __iter__(self):
        return iter(self.contents)

    def __len__(self):
        return len(self.contents)

    def __eq__(self, other):
        return self is other

    __hash__ = object.__hash__

    def __repr__(self):
        return str(self)

    def decode(self, indent_level=None, eventual_encoding="utf-8", formatter="minimal", iterator=None):
        return str(self)

    def encode(self, encoding="utf-8", indent_level=None, formatter="minimal", errors="xmlcharrefreplace"):
        return self.decode().encode(encoding, errors)

    def prettify(self, encoding=None, formatter="minimal"):
        def render(node, depth):
            if isinstance(node, NavigableString):
                plain = str.__str__(node).strip()
                owner = node.parent if node.parent is not None else self
                return (" " * depth + owner._serialize_child(node)) if plain else ""
            if node.name == "[document]":
                return "\n".join(filter(None, (render(c, depth) for c in node.contents))) + "\n"
            attrs = node._format_attrs()
            if node.name in node._void_elements:
                return " " * depth + f"<{node.name}{attrs}/>"
            lines = [" " * depth + f"<{node.name}{attrs}>"]
            lines.extend(filter(None, (render(c, depth + 1) for c in node.contents)))
            lines.append(" " * depth + f"</{node.name}>")
            return "\n".join(lines)

        value = render(self, 0)
        return value.encode(encoding) if encoding else value

    def _format_attrs(self):
        values = []
        for key, value in sorted(self.attrs.items()):
            if isinstance(value, list):
                value = " ".join(map(str, value))
            escaped = html.escape("" if value is None else str(value), quote=True)
            values.append(f' {key}="{escaped}"')
        return "".join(values)

    def _serialize_child(self, child):
        if isinstance(child, Comment):
            return f"<!--{str.__str__(child)}-->"
        if isinstance(child, Doctype):
            return f"<!DOCTYPE {str.__str__(child)}>"
        if isinstance(child, Declaration):
            return f"<!{str.__str__(child)}>"
        if isinstance(child, ProcessingInstruction):
            return f"<?{str.__str__(child)}?>"
        if isinstance(child, NavigableString):
            raw = str.__str__(child)
            return raw if self.name in {"script", "style"} else html.escape(raw, quote=False)
        return str(child)

    def __str__(self):
        if self.name == "[document]":
            return "".join(self._serialize_child(child) for child in self.contents)
        attrs = self._format_attrs()
        if self.name in self._void_elements:
            return f"<{self.name}{attrs}/>"
        children = "".join(self._serialize_child(child) for child in self.contents)
        return f"<{self.name}{attrs}>{children}</{self.name}>"


class SoupStrainer:
    def __init__(self, name=None, attrs={}, string=None, **kwargs):
        self.name = name
        self.attrs = attrs
        self.string = string
        self.kwargs = kwargs

    def search(self, markup):
        if isinstance(markup, Tag) and markup._matches(
            self.name, self.attrs, self.string, **self.kwargs
        ):
            return markup
        return None


_whitespace = re.compile(r"\s+")
