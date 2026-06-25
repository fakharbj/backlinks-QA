"""Crawler fetch helpers — the defensive Content-Encoding decompressor.

A missing decoder library (e.g. ``brotli``) makes httpx pass compressed bytes
through undecoded, which silently corrupts parsing (0 links → false "link
missing"). ``_maybe_decompress`` is the safety net for the magic-detectable
codecs; these tests lock its behaviour in.
"""

from __future__ import annotations

import gzip
import zlib

from app.crawler.fetch import _maybe_decompress

_HTML = b"<!doctype html><html><body><a href='https://x.test/'>x</a></body></html>"


def test_maybe_decompress_gzip_roundtrips():
    assert _maybe_decompress(gzip.compress(_HTML)) == _HTML


def test_maybe_decompress_zlib_roundtrips():
    assert _maybe_decompress(zlib.compress(_HTML)) == _HTML


def test_maybe_decompress_zstd_roundtrips():
    import zstandard

    comp = zstandard.ZstdCompressor().compress(_HTML)
    assert _maybe_decompress(comp) == _HTML


def test_maybe_decompress_passes_plain_html_through_unchanged():
    # Already-decoded HTML bears no compression magic → returned as-is.
    assert _maybe_decompress(_HTML) == _HTML


def test_maybe_decompress_tolerates_short_or_garbage_input():
    assert _maybe_decompress(b"") == b""
    assert _maybe_decompress(b"ab") == b"ab"
    # gzip magic but corrupt payload → left as-is rather than raising.
    assert _maybe_decompress(b"\x1f\x8b\x00\x00garbage") == b"\x1f\x8b\x00\x00garbage"
