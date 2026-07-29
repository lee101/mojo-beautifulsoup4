from __future__ import annotations

import re
from dataclasses import dataclass, field

from .element import NavigableString, Tag


class SelectorSyntaxError(ValueError):
    pass


@dataclass
class Compound:
    tag: str | None = None
    element_id: str | None = None
    classes: list[str] = field(default_factory=list)
    attrs: list[tuple[str, str | None, str | None]] = field(default_factory=list)
    pseudos: list[tuple[str, str | None]] = field(default_factory=list)


def _identifier(text, start):
    match = re.match(r"(?:\\.|[-_a-zA-Z0-9|])+", text[start:])
    if not match:
        raise SelectorSyntaxError(f"Expected identifier at position {start}")
    value = re.sub(r"\\(.)", r"\1", match.group())
    return value, start + len(match.group())


def _balanced(text, start, opening, closing):
    depth = 1
    quote = None
    i = start
    while i < len(text):
        c = text[i]
        if quote:
            if c == quote and text[i - 1] != "\\":
                quote = None
        elif c in "\"'":
            quote = c
        elif c == opening:
            depth += 1
        elif c == closing:
            depth -= 1
            if depth == 0:
                return text[start:i], i + 1
        i += 1
    raise SelectorSyntaxError(f"Unclosed {opening}")


def _split_groups(selector):
    groups, start, depth, quote = [], 0, 0, None
    for i, c in enumerate(selector):
        if quote:
            if c == quote and selector[i - 1] != "\\":
                quote = None
        elif c in "\"'":
            quote = c
        elif c in "[(":
            depth += 1
        elif c in "])":
            depth -= 1
        elif c == "," and depth == 0:
            groups.append(selector[start:i].strip())
            start = i + 1
    groups.append(selector[start:].strip())
    if any(not group for group in groups):
        raise SelectorSyntaxError("Empty selector")
    return groups


def _parse_attr(content):
    match = re.match(
        r"^\s*([^\s~|^$*!=]+)\s*(?:(~=|\|=|\^=|\$=|\*=|=|!=)\s*(.*?)\s*)?$",
        content,
    )
    if not match:
        raise SelectorSyntaxError(f"Invalid attribute selector [{content}]")
    name, op, value = match.groups()
    if value and len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    return name.lower(), op, value


def _parse_compound(text):
    compound = Compound()
    i = 0
    if text.startswith("*"):
        compound.tag, i = "*", 1
    elif text and text[0] not in "#.[:":
        compound.tag, i = _identifier(text, 0)
        compound.tag = compound.tag.split("|")[-1].lower()
    while i < len(text):
        marker = text[i]
        if marker == "#":
            compound.element_id, i = _identifier(text, i + 1)
        elif marker == ".":
            value, i = _identifier(text, i + 1)
            compound.classes.append(value)
        elif marker == "[":
            value, i = _balanced(text, i + 1, "[", "]")
            compound.attrs.append(_parse_attr(value))
        elif marker == ":":
            name, i = _identifier(text, i + 1)
            argument = None
            if i < len(text) and text[i] == "(":
                argument, i = _balanced(text, i + 1, "(", ")")
            compound.pseudos.append((name.lower(), argument))
        else:
            raise SelectorSyntaxError(f"Unexpected {marker!r} in {text!r}")
    return compound


def _parse_group(group):
    pieces, combinators = [], []
    start, depth, quote, pending_space = 0, 0, None, False
    i = 0
    while i < len(group):
        c = group[i]
        if quote:
            if c == quote and group[i - 1] != "\\":
                quote = None
        elif c in "\"'":
            quote = c
        elif c in "[(":
            depth += 1
        elif c in "])":
            depth -= 1
        elif depth == 0 and c.isspace():
            if start < i:
                pieces.append(group[start:i])
            pending_space = bool(pieces)
            while i + 1 < len(group) and group[i + 1].isspace():
                i += 1
            start = i + 1
        elif depth == 0 and c in ">+~":
            if start < i:
                pieces.append(group[start:i])
            if len(combinators) >= len(pieces):
                raise SelectorSyntaxError(f"Unexpected combinator {c}")
            combinators.append(c)
            pending_space = False
            i += 1
            while i < len(group) and group[i].isspace():
                i += 1
            start = i
            continue
        elif pending_space:
            if len(combinators) < len(pieces):
                combinators.append(" ")
            pending_space = False
            start = i
        i += 1
    if start < len(group):
        pieces.append(group[start:])
    if not pieces or len(combinators) != len(pieces) - 1:
        raise SelectorSyntaxError(f"Invalid selector {group!r}")
    return [_parse_compound(piece) for piece in pieces], combinators


def compile_selector(selector):
    if not isinstance(selector, str):
        raise TypeError("CSS selector must be a string")
    groups = _split_groups(selector.strip())
    groups = [":scope " + group if group[:1] in ">+~" else group for group in groups]
    return [_parse_group(group) for group in groups]


def _element_siblings(node):
    root = node._root()
    cached = root._position_cache.get(node.parent)
    if cached is None:
        siblings = [child for child in node.parent.contents if isinstance(child, Tag)]
        indexes = {child: index for index, child in enumerate(siblings)}
        by_type = {}
        for sibling in siblings:
            by_type.setdefault(sibling.name, []).append(sibling)
        type_indexes = {
            sibling: index
            for values in by_type.values()
            for index, sibling in enumerate(values)
        }
        cached = (siblings, indexes, by_type, type_indexes)
        root._position_cache[node.parent] = cached
    return cached


def _previous_element(node):
    if node.parent is None:
        return None
    siblings, indexes, _, _ = _element_siblings(node)
    index = indexes[node]
    return siblings[index - 1] if index else None


def _nth(expression, index):
    value = re.sub(r"\s+", "", expression.lower())
    if value == "odd":
        return index % 2 == 1
    if value == "even":
        return index % 2 == 0
    if "n" not in value:
        return index == int(value)
    a_text, b_text = value.split("n", 1)
    a = -1 if a_text == "-" else 1 if a_text in ("", "+") else int(a_text)
    b = int(b_text or 0)
    return (index - b) * a >= 0 and (index - b) % a == 0


def _attr_matches(actual, op, expected):
    if actual is None:
        return False
    actual = " ".join(actual) if isinstance(actual, list) else str(actual)
    if op is None:
        return True
    expected = expected or ""
    if op == "=":
        return actual == expected
    if op == "!=":
        return actual != expected
    if op == "~=":
        return expected in actual.split()
    if op == "|=":
        return actual == expected or actual.startswith(expected + "-")
    if op == "^=":
        return actual.startswith(expected)
    if op == "$=":
        return actual.endswith(expected)
    return expected in actual


def _matches_compound(node, compound, context):
    if compound.tag not in (None, "*") and node.name != compound.tag:
        return False
    if compound.element_id is not None and node.get("id") != compound.element_id:
        return False
    classes = node.get("class", [])
    if isinstance(classes, str):
        classes = classes.split()
    if any(value not in classes for value in compound.classes):
        return False
    if any(not _attr_matches(node.get(name), op, value) for name, op, value in compound.attrs):
        return False
    sibling_info = None
    for pseudo, argument in compound.pseudos:
        if pseudo in {
            "first-child", "last-child", "only-child", "first-of-type",
            "last-of-type", "only-of-type", "nth-child", "nth-last-child",
            "nth-of-type", "nth-last-of-type",
        }:
            if sibling_info is None:
                if node.parent:
                    sibling_info = _element_siblings(node)
                else:
                    sibling_info = ([node], {node: 0}, {node.name: [node]}, {node: 0})
            siblings, indexes, by_type, type_indexes = sibling_info
            index = indexes[node] + 1
            same_type = by_type[node.name]
            type_index = type_indexes[node] + 1
        if pseudo == "scope":
            ok = node is context
        elif pseudo == "root":
            ok = node.parent is not None and node.parent.name == "[document]"
        elif pseudo == "first-child":
            ok = index == 1
        elif pseudo == "last-child":
            ok = index == len(siblings)
        elif pseudo == "only-child":
            ok = len(siblings) == 1
        elif pseudo == "first-of-type":
            ok = type_index == 1
        elif pseudo == "last-of-type":
            ok = type_index == len(same_type)
        elif pseudo == "only-of-type":
            ok = len(same_type) == 1
        elif pseudo == "nth-child":
            ok = _nth(argument or "0", index)
        elif pseudo == "nth-last-child":
            ok = _nth(argument or "0", len(siblings) - index + 1)
        elif pseudo == "nth-of-type":
            ok = _nth(argument or "0", type_index)
        elif pseudo == "nth-last-of-type":
            ok = _nth(argument or "0", len(same_type) - type_index + 1)
        elif pseudo == "empty":
            ok = not any(
                isinstance(child, Tag)
                or (isinstance(child, NavigableString) and str.__str__(child).strip())
                for child in node.contents
            )
        elif pseudo in {"not", "is", "where"}:
            nested = compile_selector(argument or "")
            hit = any(_matches_chain(node, chain, comb, context) for chain, comb in nested)
            ok = not hit if pseudo == "not" else hit
        elif pseudo in {"contains", "-soup-contains"}:
            needle = (argument or "").strip("\"'")
            ok = needle in node.get_text()
        elif pseudo == "has":
            nested = compile_selector(argument or "")
            ok = any(
                _matches_chain(candidate, chain, comb, node)
                for candidate in node.descendants
                if isinstance(candidate, Tag)
                for chain, comb in nested
            )
        else:
            raise SelectorSyntaxError(f"Unsupported pseudo-class :{pseudo}")
        if not ok:
            return False
    return True


def _matches_chain(node, compounds, combinators, context, index=None):
    index = len(compounds) - 1 if index is None else index
    if not _matches_compound(node, compounds[index], context):
        return False
    if index == 0:
        return True
    combinator = combinators[index - 1]
    if combinator == ">":
        return (
            isinstance(node.parent, Tag)
            and _matches_chain(node.parent, compounds, combinators, context, index - 1)
        )
    if combinator == "+":
        previous = _previous_element(node)
        return previous is not None and _matches_chain(
            previous, compounds, combinators, context, index - 1
        )
    if combinator == "~":
        previous = _previous_element(node)
        while previous is not None:
            if _matches_chain(previous, compounds, combinators, context, index - 1):
                return True
            previous = _previous_element(previous)
        return False
    parent = node.parent
    while isinstance(parent, Tag):
        if _matches_chain(parent, compounds, combinators, context, index - 1):
            return True
        if parent is context:
            break
        parent = parent.parent
    return False


def select(context, selector, limit=0):
    compiled = compile_selector(selector)
    root = context._root()
    root_context = context is root
    allowed = None
    if not root_context:
        allowed = {node for node in context.descendants if isinstance(node, Tag)}
        if any(
            any(pseudo == "scope" for pseudo, _ in chain[0].pseudos)
            for chain, _ in compiled
        ):
            allowed.add(context)
    found = []
    seen = set()
    for compounds, combinators in compiled:
        right = compounds[-1]
        candidates = root._prefilter(
            right.tag if right.tag != "*" else None,
            right.element_id,
            tuple(right.classes),
        )
        for node in candidates:
            if (
                (allowed is None or node in allowed)
                and node not in seen
                and _matches_chain(node, compounds, combinators, context)
            ):
                found.append(node)
                seen.add(node)
    if len(compiled) > 1:
        if root._selector_cache is None:
            root._build_selector_cache()
        order = {node: i for i, node in enumerate(root._selector_cache[0])}
        found.sort(key=order.__getitem__)
    return found[:limit] if limit else found
