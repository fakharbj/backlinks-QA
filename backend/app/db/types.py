"""Reusable column helpers."""

from __future__ import annotations

import enum
from typing import Any

from sqlalchemy import Enum as SAEnum


def pg_enum(enum_cls: type[enum.Enum], name: str, **kwargs: Any) -> SAEnum:
    """A native PostgreSQL ENUM whose members serialise by ``.value`` (not name).

    Using ``.value`` keeps the on-disk representation aligned with API/JSON, and
    ``create_type=False`` lets Alembic own type creation explicitly.
    """
    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda e: [member.value for member in e],
        native_enum=True,
        validate_strings=True,
        **kwargs,
    )
