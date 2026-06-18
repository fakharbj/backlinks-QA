"""Opaque keyset-pagination cursors.

A cursor is a base64url-encoded ``"<sortvalue>|<id>"`` tuple. Keyset pagination on
an indexed ``(sort_col, id)`` pair is constant-time regardless of offset, which is
what keeps the 1M-row grid fast (Arch §10).
"""

from __future__ import annotations

import base64
import uuid


def encode_cursor(sort_value: object, row_id: uuid.UUID) -> str:
    raw = f"{sort_value}|{row_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode()


def decode_cursor(cursor: str) -> tuple[str, uuid.UUID]:
    raw = base64.urlsafe_b64decode(cursor.encode()).decode()
    sort_value, _, row_id = raw.rpartition("|")
    return sort_value, uuid.UUID(row_id)
