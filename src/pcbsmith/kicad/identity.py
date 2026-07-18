"""Stable identities for generated KiCad objects.

KiCad UUIDs are file identities, not random nonces. Deriving them from a
frozen PCBSmith namespace and explicit semantic parts makes regeneration
byte-stable while keeping unrelated objects distinct.
"""

from __future__ import annotations

import json
from uuid import UUID, uuid5

KICAD_IDENTITY_SCHEMA = "pcbsmith-kicad-identity-v1"
KICAD_UUID_NAMESPACE_V1 = UUID("abe13b3e-32bb-5b28-8aeb-bca2848f8393")


def stable_kicad_uuid(*identity: str) -> str:
    """Return a deterministic UUID5 for an ordered KiCad identity tuple.

    JSON encoding preserves part boundaries, so identities like two separate
    strings cannot alias through string concatenation. Callers should pass
    semantic strings rather than mutable display values or unformatted
    floating-point coordinates.
    """
    if not identity:
        raise ValueError("A stable KiCad UUID requires at least one identity part.")
    if any(not isinstance(part, str) for part in identity):
        raise TypeError("Stable KiCad UUID identity parts must be strings.")
    canonical = json.dumps(
        identity, ensure_ascii=False, separators=(",", ":")
    )
    return str(uuid5(KICAD_UUID_NAMESPACE_V1, canonical))
