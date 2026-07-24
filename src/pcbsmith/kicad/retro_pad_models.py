"""Deterministic visual proxy models for Retro-Pad mechanical controls."""

from __future__ import annotations

import math
from pathlib import Path


def generate_retro_pad_proxy_models(output_dir: Path) -> dict[str, Path]:
    """Write simple dimensioned VRML proxies when upstream CAD is unavailable."""
    model_dir = output_dir / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    switch = model_dir / "retro-pad-cherry-mx-proxy.wrl"
    encoder = model_dir / "retro-pad-ec11-proxy.wrl"
    switch.write_text(_switch_model(), encoding="ascii")
    encoder.write_text(_encoder_model(), encoding="ascii")
    return {"switch": switch, "encoder": encoder}


def _box(
    x_mm: float,
    y_mm: float,
    z_mm: float,
    z_center_mm: float,
    color: str,
    *,
    x_center_mm: float = 0.0,
    y_center_mm: float = 0.0,
) -> str:
    scale = 1.0 / 2.54
    return f"""Transform {{
  translation {x_center_mm * scale:.6f} {y_center_mm * scale:.6f} {z_center_mm * scale:.6f}
  children [ Shape {{
    appearance Appearance {{ material Material {{ diffuseColor {color} }} }}
    geometry Box {{ size {x_mm * scale:.6f} {y_mm * scale:.6f} {z_mm * scale:.6f} }}
  }} ]
}}"""


def _cylinder(
    radius_mm: float,
    height_mm: float,
    z_center_mm: float,
    color: str,
    *,
    x_center_mm: float = 0.0,
    y_center_mm: float = 0.0,
) -> str:
    """Render a vertical faceted cylinder without relying on VRML axis semantics."""
    scale = 1.0 / 2.54
    segments = 24
    z_low = (z_center_mm - height_mm / 2.0) * scale
    z_high = (z_center_mm + height_mm / 2.0) * scale
    points: list[str] = []
    for z in (z_low, z_high):
        for index in range(segments):
            angle = 2.0 * math.pi * index / segments
            x = (x_center_mm + radius_mm * math.cos(angle)) * scale
            y = (y_center_mm + radius_mm * math.sin(angle)) * scale
            points.append(f"{x:.6f} {y:.6f} {z:.6f}")
    faces: list[str] = [
        " ".join(str(index) for index in reversed(range(segments))) + " -1",
        " ".join(str(index + segments) for index in range(segments)) + " -1",
    ]
    for index in range(segments):
        following = (index + 1) % segments
        faces.append(
            f"{index} {following} {following + segments} {index + segments} -1"
        )
    return f"""Shape {{
  appearance Appearance {{ material Material {{ diffuseColor {color} }} }}
  geometry IndexedFaceSet {{
    solid TRUE
    creaseAngle 0.65
    coord Coordinate {{ point [ {', '.join(points)} ] }}
    coordIndex [ {', '.join(faces)} ]
  }}
}}"""


def _switch_model() -> str:
    return "\n".join((
        "#VRML V2.0 utf8",
        "# PCBSmith dimensioned visual proxy; not assembly-authoritative CAD.",
        _box(
            14.0, 14.0, 5.0, 2.5, "0.12 0.12 0.14",
            x_center_mm=-2.54, y_center_mm=-5.08,
        ),
        _box(
            6.0, 6.0, 4.0, 7.0, "0.45 0.08 0.08",
            x_center_mm=-2.54, y_center_mm=-5.08,
        ),
        "",
    ))


def _encoder_model() -> str:
    return "\n".join((
        "#VRML V2.0 utf8",
        "# PCBSmith dimensioned visual proxy; not assembly-authoritative CAD.",
        _box(
            13.0, 12.0, 7.0, 3.5, "0.55 0.56 0.58",
            x_center_mm=7.5, y_center_mm=-2.5,
        ),
        _cylinder(
            3.0, 20.0, 17.0, "0.72 0.72 0.74",
            x_center_mm=7.5, y_center_mm=-2.5,
        ),
        "",
    ))
