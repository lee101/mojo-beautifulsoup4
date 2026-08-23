# mojo-beautifulsoup4

A standalone Mojo port of the compute-heavy core of
[Beautiful Soup 4](https://www.crummy.com/software/BeautifulSoup/): HTML byte
tokenization and CSS selector candidate matching. It exposes a Python tree API
with the upstream names and signatures for the covered subset.

The implementation is useful on large, regularly structured HTML documents. Python
still owns the tree objects, so tags remain convenient to inspect and mutate; Mojo
does the full-document byte scans that benefit from compiled loops.

## Install

The repository pins the tested Mojo nightly and installs the real `beautifulsoup4`
package for parity tests:

```bash
pixi install
pixi run build
pixi run test
```

The build task creates `dist/libmojo-beautifulsoup4.so`.

## Usage

This example runs as written after `pixi install`:

```python
from mojo_beautifulsoup4 import BeautifulSoup

document = """
<main>
  <article class="card featured"><h2>Mojo</h2><a href="/mojo">Read</a></article>
  <article class="card"><h2>Python</h2><a href="/python">Read</a></article>
</main>
"""

soup = BeautifulSoup(document, "html.parser")
print(soup.select_one("article.featured > h2").get_text())
print([a["href"] for a in soup.select("article.card a")])
```

Output:

```text
Mojo
['/mojo', '/python']
```

## Covered subset

HTML parsing covers Unicode and byte input, basic encoding detection, entity
decoding, quoted and unquoted attributes, multi-valued `class`, comments, doctypes,
processing instructions, void and self-closing elements, malformed nesting, and
raw-text `script`, `style`, `title`, and `textarea` scanning.

The tested tree surface includes `BeautifulSoup`, `Tag`, `NavigableString`, `Comment`,
`Doctype`, and `SoupStrainer`; attribute mapping and mutation; serialization;
`get_text`, `string`, and `stripped_strings`; parent traversal; `find`, `find_all`,
`find_next_sibling`, and `find_previous`; plus `new_tag`, insertion, extraction, and
replacement. Other upstream methods may exist for convenience but are not compatibility
claims.

Selectors cover:

- type, universal, ID, class, and selector-list syntax;
- descendant, child, adjacent-sibling, and general-sibling combinators;
- attribute presence and `=`, `~=`, `|=`, `^=`, `$=`, and `*=` operators;
- child and type position pseudo-classes, including `nth-*`;
- `:scope`, `:empty`, `:not`, `:is`, `:where`, `:has`, and
  `:-soup-contains`.

The 59 tests compare behavior directly with Beautiful Soup 4.15.0 using its
`html.parser` builder. They assert tree output and query results, not merely successful
execution. They also exercise the SIMD remainder, parallel threshold boundary, cache
invalidation, and rejected FFI array layouts and bounds.

## Not covered

This is not the entire Beautiful Soup parser ecosystem. It does not implement XML,
namespace-aware selectors, the `lxml` or `html5lib` builders, full HTML5 error recovery
such as the adoption-agency and foster-parenting algorithms, SoupSieve's complete CSS
grammar (including reliable `:root` behavior for fragments), advanced output formatter
hooks, or Beautiful Soup's builder/plugin registry.
Code that relies on those features should continue using upstream.

For the covered subset, class names and common method signatures mirror upstream. The
package name is intentionally distinct, so adopting it requires changing the import
from `bs4` to `mojo_beautifulsoup4`.

## Benchmarks

Measured with `pixi run bench` on an Intel(R) Xeon(R) CPU E5-2697 v4 @ 2.30GHz, Linux
6.8.0-136-generic, Python 3.13.14. The input is a 1.38 MB generated HTML document
containing 40,000 tags. Each implementation parses and queries identical text;
the benchmark asserts equal counts and sample identities before reporting the best
time.

| operation | mojo-beautifulsoup4 | beautifulsoup4 | speedup |
| --- | ---: | ---: | ---: |
| parse document / 40k tags | 370.98 ms | 1471.86 ms | 3.97x |
| select .card.active | 3.45 ms | 185.57 ms | 53.86x |
| select article[data-kind=news] | 22.21 ms | 151.84 ms | 6.84x |
| select main > article#p9999 | 0.58 ms | 105.32 ms | 180.60x |
| find_all article.active | 0.89 ms | 54.70 ms | 61.55x |

Simple root-level `find_all` calls for a literal tag and optional single class now reuse
the compiled candidate prefilter. Other `find_all` criteria retain the general Python
tree traversal path.

No GPU path is provided. Tokenization is a branch-heavy byte scan with well under two
operations per byte, and profiling shows it is only a small fraction of parse time.
The remaining tree assembly is dependency-ordered Python object construction, so
device transfer and launch overhead cannot be recovered by useful parallel GPU work.

## How it works

Python encodes markup as UTF-8 and owns all allocations. One C-ABI call passes the byte
address and four contiguous `int64` output arrays into Mojo. The tokenizer scans
quotes, declarations, comments, and raw-text closing tags, returning token kinds and
source offsets. Python then builds familiar linked `Tag` and `NavigableString` objects.
Initial construction links nodes directly without mutation-time cache invalidation;
public mutations retain normal invalidation behavior. Token offsets are converted from
NumPy scalars in bulk, and slices are decoded only for token kinds that consume them.

For selectors, the tree lazily caches tag names, IDs, and space-delimited classes in one
contiguous byte blob plus six `int64` offset arrays. Mojo compares the rightmost
compound selector against every element and returns a byte mask. Python evaluates
attributes, combinators, and pseudo-classes only on those candidates. Tree and attribute
mutations invalidate both caches.

Byte equality uses SIMD-width unaligned loads and a scalar remainder loop. Prefiltering
stays serial for smaller trees and splits larger independent scans into fixed-size
chunks. All buffers cross the ABI as integer addresses and remain Python-owned; query
and selector byte buffers are exposed to NumPy without copies. The shared library
neither allocates nor retains pointers after a call. The wrapper validates array dtype,
shape, contiguity, alignment, equal lengths, and blob-relative offset bounds before
calling Mojo; local references keep every NumPy-backed buffer alive until the
synchronous call returns.

## Development

```bash
pixi run build
pixi run test
pixi run bench
```

Benchmarks must be run through the Pixi task because it holds a machine-wide lock.

MIT licensed.
