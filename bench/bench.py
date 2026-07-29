"""Benchmarks against Beautiful Soup on identical HTML and queries."""

from __future__ import annotations

import os
import platform
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "python"))

from bs4 import BeautifulSoup as ReferenceSoup  # noqa: E402
from mojo_beautifulsoup4 import BeautifulSoup  # noqa: E402


def timeit(function, repetitions=5):
    values = []
    result = None
    for _ in range(repetitions):
        start = time.perf_counter()
        result = function()
        values.append(time.perf_counter() - start)
    return min(values), statistics.median(values), result


def cpu_name():
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("model name"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return platform.processor() or "unknown CPU"


def main():
    count = 10_000
    items = "".join(
        f'<article id="p{i}" class="card {"active" if i % 7 == 0 else "idle"}" '
        f'data-kind="{"news" if i % 3 == 0 else "note"}">'
        f"<h2>Title {i}</h2><p>Body &amp; value {i}</p><a href=\"/p/{i}\">read</a></article>"
        for i in range(count)
    )
    markup = f"<!doctype html><main>{items}</main>"

    mojo_parse, _, mojo_soup = timeit(
        lambda: BeautifulSoup(markup, "html.parser"), repetitions=3
    )
    ref_parse, _, ref_soup = timeit(
        lambda: ReferenceSoup(markup, "html.parser"), repetitions=3
    )
    assert len(mojo_soup.find_all("article")) == len(ref_soup.find_all("article")) == count
    assert str(mojo_soup.select_one("#p9999 h2").string) == str(
        ref_soup.select_one("#p9999 h2").string
    )

    cases = [
        (
            "parse document / 40k tags",
            mojo_parse,
            ref_parse,
            "BeautifulSoup(..., 'html.parser')",
        )
    ]
    queries = [
        ("select .card.active", ".card.active"),
        ("select article[data-kind=news]", "article[data-kind=news]"),
        ("select main > article#p9999", "main > article#p9999"),
    ]
    mojo_soup.select(".card.active")
    for label, query in queries:
        mojo_time, _, mojo_result = timeit(lambda q=query: mojo_soup.select(q))
        ref_time, _, ref_result = timeit(lambda q=query: ref_soup.select(q))
        assert len(mojo_result) == len(ref_result)
        assert [node.get("id") for node in mojo_result[:3]] == [
            node.get("id") for node in ref_result[:3]
        ]
        cases.append((label, mojo_time, ref_time, "CSS selector"))

    mojo_find, _, mojo_result = timeit(
        lambda: mojo_soup.find_all("article", class_="active")
    )
    ref_find, _, ref_result = timeit(
        lambda: ref_soup.find_all("article", class_="active")
    )
    assert len(mojo_result) == len(ref_result)
    cases.append(("find_all article.active", mojo_find, ref_find, "tree traversal"))

    size_mb = len(markup.encode()) / 1_000_000
    machine = f"{cpu_name()}, {platform.system()} {platform.release()}, Python {platform.python_version()}"
    print(f"Machine: {machine}")
    print(f"Input: {size_mb:.2f} MB, {count * 4:,} tags")
    print()
    print("| operation | mojo-beautifulsoup4 | beautifulsoup4 | speedup |")
    print("| --- | ---: | ---: | ---: |")
    for label, mojo_time, ref_time, _ in cases:
        speedup = ref_time / mojo_time
        print(
            f"| {label} | {mojo_time * 1000:.2f} ms | "
            f"{ref_time * 1000:.2f} ms | {speedup:.2f}x |"
        )


if __name__ == "__main__":
    main()
