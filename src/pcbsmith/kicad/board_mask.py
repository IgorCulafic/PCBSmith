"""KiCad rendering bridge for typed board-level solder-mask apertures.

Only the legacy 96-point front-mask disc is supported here. The typed
geometry remains engine-neutral; this module is the explicit serialization
boundary that preserves the historical KiCad bytes and graphic UUID.
"""

from __future__ import annotations

import math

from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.mask_geometry import (
    Disc,
    MaskAperture,
    MaskSide,
    MaskSourceKind,
    MaskVerification,
    Point,
    stable_mask_source_id,
)

BoardPoint = tuple[float, float]


def mask_opening_disc_aperture(
    center: BoardPoint,
    radius: float,
    *,
    occurrence: int = 0,
) -> MaskAperture:
    """Return the exact semantic aperture behind the legacy disc helper."""
    if occurrence < 0:
        raise ValueError("Graphic occurrence must be non-negative.")
    geometry = Disc(
        center=Point(x_mm=center[0], y_mm=center[1]),
        radius_mm=radius,
    )
    return MaskAperture(
        source_id=stable_mask_source_id(
            "board_graphic",
            "mask-opening-disc",
            "front",
            f"x:{_identity_number(center[0])}",
            f"y:{_identity_number(center[1])}",
            f"radius:{_identity_number(radius)}",
            f"occurrence:{occurrence}",
        ),
        source_kind=MaskSourceKind.BOARD_GRAPHIC,
        side=MaskSide.FRONT,
        geometry=geometry,
        verification=MaskVerification.EXACT,
    )


def mask_aperture_render_identity(aperture: MaskAperture) -> tuple[str, ...]:
    """Return the render identity used to assign duplicate occurrences."""
    geometry = _supported_disc(aperture)
    return (
        aperture.source_kind.value,
        aperture.side.value,
        _identity_number(geometry.center.x_mm),
        _identity_number(geometry.center.y_mm),
        _identity_number(geometry.radius_mm),
    )


def render_board_mask_aperture(
    aperture: MaskAperture,
    origin: float,
    *,
    occurrence: int = 0,
) -> str:
    """Render one supported aperture with legacy byte/UUID compatibility."""
    if occurrence < 0:
        raise ValueError("Graphic occurrence must be non-negative.")
    geometry = _supported_disc(aperture)
    center = (geometry.center.x_mm, geometry.center.y_mm)
    rendered_center = (
        f"{center[0] + origin:.3f}",
        f"{center[1] + origin:.3f}",
    )
    radius = geometry.radius_mm
    rendered = "\n          ".join(
        f"(xy {center[0] + radius * math.cos(angle) + origin:.3f} "
        f"{center[1] + radius * math.sin(angle) + origin:.3f})"
        for angle in (2 * math.pi * step / 96 for step in range(96))
    )
    item_uuid = stable_kicad_uuid(
        "board-graphic",
        "mask-opening-disc",
        "F.Mask",
        f"{rendered_center[0]},{rendered_center[1]}",
        f"radius:{_identity_number(radius)}",
        "samples:96",
        str(occurrence),
    )
    return f"""  (gr_poly
    (pts
          {rendered}
    )
    (stroke (width 0) (type solid))
    (fill yes)
    (layer "F.Mask")
    (uuid {item_uuid})
  )"""


def _supported_disc(aperture: MaskAperture) -> Disc:
    if (
        aperture.source_kind is not MaskSourceKind.BOARD_GRAPHIC
        or aperture.side is not MaskSide.FRONT
        or aperture.verification is not MaskVerification.EXACT
        or not isinstance(aperture.geometry, Disc)
    ):
        raise ValueError(
            "KiCad board-mask rendering currently supports exact front-side "
            "board-graphic discs only."
        )
    return aperture.geometry


def _identity_number(value: float) -> str:
    return format(value, ".12g")
