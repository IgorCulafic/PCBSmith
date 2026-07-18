from __future__ import annotations

from pathlib import Path

import pytest

from pcbsmith.kicad.library import (
    CUSTOM_PAD_MASK_UNSUPPORTED_REASON,
    ImportedFootprint,
    PadSourceAnchor,
    PadSpec,
    _measure,
    parse_sexpr,
    render_embedded_footprint,
)


def _ordinary_tree_text() -> str:
    return """
    (footprint "MaskProbe"
      (pad "1" smd circle
        (at 1 2)
        (size 1.2 1.2)
        (layers "F.Cu" "F.Paste" "F.Mask")
        (solder_mask_margin 0.05))
      (pad "2" smd oval
        (at 3 2 90)
        (size 1.8 0.8)
        (layers "B.Cu" "B.Mask")
        (solder_mask_margin -0.03)
        (solder_mask_margin_ratio -0.1))
      (pad "3" smd rect
        (at 5 2)
        (size 1.4 0.9)
        (layers "F.Cu" "F.Paste"))
      (pad "4" smd roundrect
        (at 7 2 15)
        (size 1.6 1.0)
        (layers "F.Cu" "F.Mask")
        (roundrect_rratio 0.37)
        (chamfer_ratio 0.2)
        (chamfer top_left bottom_right)
        (solder_mask_margin_ratio 0.15))
      (pad "DUP" smd circle
        (at 9 1)
        (size 1 1)
        (layers "F.Cu" "F.Mask")
        (solder_mask_margin 0.01))
      (pad "DUP" smd circle
        (at 9 3)
        (size 1 1)
        (layers "B.Cu")
        (solder_mask_margin -0.02)))
    """


def test_parser_preserves_simple_pad_mask_source_clauses() -> None:
    spec = _measure(parse_sexpr(_ordinary_tree_text()), "Test:MaskProbe")
    circle, oval, rect, roundrect, first_duplicate, second_duplicate = spec.pads

    assert circle.shape == "circle"
    assert circle.source_anchor == PadSourceAnchor(1.0, 2.0, 1.2, 1.2)
    assert circle.layers == ("F.Cu", "F.Paste", "F.Mask")
    assert circle.solder_mask_margin_mm == pytest.approx(0.05)
    assert circle.solder_mask_margin_ratio is None

    assert oval.shape == "oval"
    assert oval.layers == ("B.Cu", "B.Mask")
    assert oval.solder_mask_margin_mm == pytest.approx(-0.03)
    assert oval.solder_mask_margin_ratio == pytest.approx(-0.1)

    assert rect.shape == "rect"
    assert rect.layers == ("F.Cu", "F.Paste")
    assert "F.Mask" not in rect.layers
    assert rect.solder_mask_margin_mm is None
    assert rect.solder_mask_margin_ratio is None

    assert roundrect.shape == "roundrect"
    assert roundrect.roundrect_rratio == pytest.approx(0.37)
    assert roundrect.chamfer_ratio == pytest.approx(0.2)
    assert roundrect.chamfer_positions == ("top_left", "bottom_right")
    assert roundrect.solder_mask_margin_mm is None
    assert roundrect.solder_mask_margin_ratio == pytest.approx(0.15)

    assert first_duplicate.name == second_duplicate.name == "DUP"
    assert first_duplicate is not second_duplicate
    assert first_duplicate.layers == ("F.Cu", "F.Mask")
    assert second_duplicate.layers == ("B.Cu",)
    assert first_duplicate.solder_mask_margin_mm == pytest.approx(0.01)
    assert second_duplicate.solder_mask_margin_mm == pytest.approx(-0.02)


def test_custom_pad_retains_original_anchor_and_canonical_source() -> None:
    text = """
    (footprint "CustomMaskProbe"
      (pad "9" smd custom
        (at 10 20 90)
        (size 1 1)
        (layers "F.Cu" "F.Mask")
        (options
          (clearance outline)
          (anchor rect))
        (primitives
          (gr_poly
            (pts (xy 0 -0.2) (xy 2 -0.2) (xy 2 0.2) (xy 0 0.2))
            (width 0)
            (fill yes)))))
    """
    first = _measure(parse_sexpr(text), "Test:CustomMaskProbe").pads[0]
    second = _measure(parse_sexpr(text), "Test:CustomMaskProbe").pads[0]

    assert first.source_anchor == PadSourceAnchor(10.0, 20.0, 1.0, 1.0)
    assert (first.x_mm, first.y_mm) == pytest.approx((10.0, 19.25))
    assert (first.width_mm, first.height_mm) == pytest.approx((2.5, 1.0))
    assert first.custom_source is not None
    assert first.custom_source == second.custom_source
    assert len(first.custom_source.canonical_clauses) == 2
    assert first.custom_source.canonical_clauses[0].startswith("(options")
    assert "(anchor rect)" in first.custom_source.canonical_clauses[0]
    assert first.custom_source.canonical_clauses[1].startswith("(primitives")
    assert "(xy 2 0.2)" in first.custom_source.canonical_clauses[1]
    assert first.custom_source.unsupported_reason == CUSTOM_PAD_MASK_UNSUPPORTED_REASON


def test_legacy_pad_constructor_keeps_unknown_source_defaults() -> None:
    pad = PadSpec("1", 1.0, 2.0, "smd", 1.2, 0.8)

    assert pad.source_anchor is None
    assert pad.layers == ()
    assert pad.roundrect_rratio is None
    assert pad.chamfer_ratio is None
    assert pad.chamfer_positions == ()
    assert pad.solder_mask_margin_mm is None
    assert pad.solder_mask_margin_ratio is None
    assert pad.custom_source is None


def test_rendering_preserves_front_clauses_and_swaps_back_layers_only() -> None:
    tree = parse_sexpr(_ordinary_tree_text())
    imported = ImportedFootprint(
        library_id="Test:MaskProbe",
        spec=_measure(tree, "Test:MaskProbe"),
        source_file=Path("synthetic.kicad_mod"),
        tree=tree,
    )
    front = render_embedded_footprint(
        imported,
        reference="U1",
        value="MASK-PROBE",
        x_mm=12.0,
        y_mm=34.0,
        rotation=0.0,
        uuid_path="mask-probe",
        pad_nets={},
    )
    back = render_embedded_footprint(
        imported,
        reference="U1",
        value="MASK-PROBE",
        x_mm=12.0,
        y_mm=34.0,
        rotation=0.0,
        uuid_path="mask-probe",
        pad_nets={},
        flip=True,
    )

    assert '(layers "F.Cu" "F.Paste" "F.Mask")' in front
    assert "(solder_mask_margin -0.03)" in front
    assert "(solder_mask_margin_ratio 0.15)" in front
    assert '(layers "B.Cu" "B.Paste" "B.Mask")' in back
    assert '(layers "F.Cu" "F.Mask")' in back
    assert imported.spec.pads[0].layers == ("F.Cu", "F.Paste", "F.Mask")
