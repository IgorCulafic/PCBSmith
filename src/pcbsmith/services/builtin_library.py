"""Compatibility imports for the relocated built-in component library."""

from __future__ import annotations

from pcbsmith.knowledge.builtin_library import (
    FOOTPRINTS,
    SYMBOLS,
    get_footprint,
    get_symbol,
)

__all__ = ["FOOTPRINTS", "SYMBOLS", "get_footprint", "get_symbol"]
