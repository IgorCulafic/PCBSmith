"""Shared in-memory identities for outer-copper geometry.

These helpers keep the KiCad mask, physical-geometry, and exposure collectors on
one join contract. They intentionally preserve the current human-readable IDs;
persistent semantic object IDs remain a separate migration.
"""

from __future__ import annotations


def pad_copper_source_id(reference: str, pad_index: int, layer: str) -> str:
    return f"pad:{reference}:{pad_index}:copper:{layer}"


def track_copper_source_id(segment_index: int) -> str:
    return f"track:{segment_index}"


def via_copper_source_id(via_index: int, layer: str) -> str:
    return f"via:{via_index}:copper:{layer}"