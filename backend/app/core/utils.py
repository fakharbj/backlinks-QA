"""Small pure helpers."""

from __future__ import annotations

import re
import secrets
import unicodedata

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str, *, max_length: int = 80) -> str:
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = _SLUG_RE.sub("-", value.lower()).strip("-")
    return (value or "item")[:max_length].strip("-")


def unique_slug(value: str) -> str:
    """Slug with a short random suffix to avoid collisions on create."""
    return f"{slugify(value, max_length=64)}-{secrets.token_hex(3)}"
