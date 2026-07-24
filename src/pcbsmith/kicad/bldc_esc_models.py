"""Dimensioned mechanical-envelope proxies for BLDC ESC placement review."""

from __future__ import annotations

from pathlib import Path

from pcbsmith.kicad.retro_pad_models import _box, _cylinder

HEATSINK_WIDTH_MM = 42.0
HEATSINK_LENGTH_MM = 82.0
HEATSINK_BASE_BOTTOM_MM = 2.6
HEATSINK_BASE_THICKNESS_MM = 2.0
HEATSINK_FIN_HEIGHT_MM = 9.0
TIM_THICKNESS_MM = 0.3


def generate_bldc_esc_proxy_models(output_dir: Path) -> dict[str, Path]:
    """Write deterministic VRML envelopes; none are exact manufacturer CAD."""
    model_dir = output_dir / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    models = {
        "drv8353-rta-envelope.wrl": _box(6.0, 6.0, 0.8, 0.4, "0.12 0.12 0.13"),
        "iptc011n08-tolt-envelope.wrl": _box(10.3, 15.4, 2.3, 1.15, "0.16 0.16 0.17"),
        "wslp2726-envelope.wrl": _box(7.0, 6.35, 0.9, 0.45, "0.32 0.30 0.28"),
        "a781-10x12p4-envelope.wrl": _cylinder(5.0, 12.4, 6.2, "0.16 0.20 0.24"),
        "7kpd-smpd-envelope.wrl": _box(10.5, 13.0, 4.8, 2.4, "0.10 0.10 0.11"),
        "lm5164-dda-envelope.wrl": _box(3.9, 4.9, 1.75, 0.875, "0.13 0.13 0.14"),
        "tlv767-drb-envelope.wrl": _box(3.0, 3.0, 1.0, 0.5, "0.13 0.13 0.14"),
    }
    result: dict[str, Path] = {}
    for filename, geometry in models.items():
        target = model_dir / filename
        target.write_text(
            "\n".join(
                (
                    "#VRML V2.0 utf8",
                    "# PCBSmith datasheet-envelope proxy; not exact assembly CAD.",
                    geometry,
                    "",
                )
            ),
            encoding="ascii",
        )
        result[filename] = target
    return result


def generate_bldc_esc_r002_mechanical_models(output_dir: Path) -> dict[str, Path]:
    """Write the explicit R002 cooling-envelope models used for placement review."""
    model_dir = output_dir / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    result = generate_bldc_esc_proxy_models(output_dir)
    heatsink = model_dir / "bldc-r002-heatsink-envelope.wrl"
    tim = model_dir / "bldc-r002-isolating-tim-envelope.wrl"
    standoff = model_dir / "bldc-r002-clamp-standoff-envelope.wrl"

    base_center = HEATSINK_BASE_BOTTOM_MM + HEATSINK_BASE_THICKNESS_MM / 2.0
    fin_center = (
        HEATSINK_BASE_BOTTOM_MM
        + HEATSINK_BASE_THICKNESS_MM
        + HEATSINK_FIN_HEIGHT_MM / 2.0
    )
    heatsink_geometry = [
        _box(
            HEATSINK_WIDTH_MM,
            HEATSINK_LENGTH_MM,
            HEATSINK_BASE_THICKNESS_MM,
            base_center,
            "0.48 0.50 0.52",
        )
    ]
    for x_center in (-18.0, -12.0, -6.0, 0.0, 6.0, 12.0, 18.0):
        heatsink_geometry.append(
            _box(
                1.2,
                HEATSINK_LENGTH_MM,
                HEATSINK_FIN_HEIGHT_MM,
                fin_center,
                "0.34 0.36 0.38",
                x_center_mm=x_center,
            )
        )
    heatsink.write_text(
        "\n".join(
            (
                "#VRML V2.0 utf8",
                "# PCBSmith R002 thermal-mechanical envelope; not a selected heatsink.",
                *heatsink_geometry,
                "",
            )
        ),
        encoding="ascii",
    )
    tim.write_text(
        "\n".join(
            (
                "#VRML V2.0 utf8",
                "# PCBSmith electrically-isolating TIM envelope; material is not selected.",
                _box(
                    10.3,
                    15.4,
                    TIM_THICKNESS_MM,
                    2.3 + TIM_THICKNESS_MM / 2.0,
                    "0.55 0.62 0.66",
                ),
                "",
            )
        ),
        encoding="ascii",
    )
    standoff.write_text(
        "\n".join(
            (
                "#VRML V2.0 utf8",
                "# PCBSmith clamp-support envelope; exact hardware is not selected.",
                _cylinder(
                    2.75,
                    HEATSINK_BASE_BOTTOM_MM,
                    HEATSINK_BASE_BOTTOM_MM / 2.0,
                    "0.55 0.56 0.58",
                ),
                "",
            )
        ),
        encoding="ascii",
    )
    result.update({path.name: path for path in (heatsink, tim, standoff)})
    return result
