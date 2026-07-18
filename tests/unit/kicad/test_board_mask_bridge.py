from __future__ import annotations

from dataclasses import replace

from tests.unit.kicad.test_metal_detector_board import _netlist

from pcbsmith.kicad.board import BOARD_SHEET_ORIGIN_MM, render_board_from_layout
from pcbsmith.kicad.board_mask import render_board_mask_aperture
from pcbsmith.kicad.metal_detector_board import (
    COIL_CENTER,
    MASK_OPENING_RADIUS,
    compute_detector_board_layout,
)
from pcbsmith.kicad.shaped_board import (
    mask_opening_disc,
    mask_opening_disc_aperture,
)
from pcbsmith.mask_geometry import (
    Disc,
    MaskSide,
    MaskSourceKind,
    MaskVerification,
    Point,
    stable_mask_source_id,
)


def test_mask_disc_has_exact_stable_semantic_geometry() -> None:
    aperture = mask_opening_disc_aperture((4.0, 5.0), 2.0)

    assert aperture.source_kind is MaskSourceKind.BOARD_GRAPHIC
    assert aperture.side is MaskSide.FRONT
    assert aperture.verification is MaskVerification.EXACT
    assert aperture.geometry == Disc(
        center=Point(x_mm=4.0, y_mm=5.0),
        radius_mm=2.0,
    )
    assert aperture.source_id == stable_mask_source_id(
        "board_graphic",
        "mask-opening-disc",
        "front",
        "x:4",
        "y:5",
        "radius:2",
        "occurrence:0",
    )


def test_typed_mask_disc_preserves_legacy_bytes_and_identity() -> None:
    legacy = mask_opening_disc((4.0, 5.0), 2.0, 20.0)
    typed = render_board_mask_aperture(
        mask_opening_disc_aperture((4.0, 5.0), 2.0),
        20.0,
    )

    assert typed == legacy
    assert typed.count('(layer "F.Mask")') == 1


def test_detector_typed_mask_emits_once_and_preserves_board_bytes() -> None:
    netlist = _netlist()
    layout = compute_detector_board_layout(netlist)

    assert len(layout.mask_apertures) == 1
    assert not any('(layer "F.Mask")' in graphic for graphic in layout.graphics)
    typed_text = render_board_from_layout(netlist, layout)
    legacy_layout = replace(
        layout,
        mask_apertures=(),
        graphics=(
            mask_opening_disc(
                COIL_CENTER,
                MASK_OPENING_RADIUS,
                BOARD_SHEET_ORIGIN_MM,
            ),
            *layout.graphics,
        ),
    )
    legacy_text = render_board_from_layout(netlist, legacy_layout)

    assert typed_text == legacy_text
    assert typed_text.count('(layer "F.Mask")') == 1
