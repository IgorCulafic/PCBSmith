from __future__ import annotations

import hashlib

import pytest

from pcbsmith.kicad.installed_footprint_geometry import (
    FootprintGeometryRole,
    build_installed_footprint_geometry_authority,
)
from pcbsmith.kicad.library import load_footprint
from pcbsmith.semantic_ir import SemanticVerification


@pytest.mark.parametrize(
    "footprint_id",
    (
        "Package_QFP:TQFP-48_7x7mm_P0.5mm",
        "Package_DFN_QFN:QFN-16-1EP_3x3mm_P0.5mm_EP1.9x1.9mm",
        "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm",
        "Connector_PinHeader_2.54mm:PinHeader_2x10_P2.54mm_Vertical",
    ),
)
def test_real_routing_corpus_footprints_retain_source_pads_and_courtyard(
    footprint_id: str,
) -> None:
    authority = build_installed_footprint_geometry_authority(
        footprint_id,
        component_reference="U1",
        component_uuid_path="fixture/U1",
        anchor_x_mm=10.0,
        anchor_y_mm=20.0,
    )
    imported = load_footprint(footprint_id)

    assert len(authority.pads) == len(imported.spec.pads)
    assert authority.source_file_sha256 == hashlib.sha256(
        imported.source_file.read_bytes()
    ).hexdigest()
    by_role = {item.role: item for item in authority.layer_geometry}
    assert by_role[FootprintGeometryRole.FAB_BODY].canonical_clauses
    assert by_role[FootprintGeometryRole.COURTYARD].canonical_clauses
    assert by_role[FootprintGeometryRole.COURTYARD].verification is SemanticVerification.EXACT


def test_asymmetric_offset_pad_uses_orthogonal_kicad_transform() -> None:
    footprint_id = "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical"
    imported = load_footprint(footprint_id)
    source_pad = next(pad for pad in imported.spec.pads if pad.name == "1")
    authority = build_installed_footprint_geometry_authority(
        footprint_id,
        component_reference="J2",
        component_uuid_path="fixture/J2",
        anchor_x_mm=30.0,
        anchor_y_mm=40.0,
        rotation_deg=90,
    )
    placed = next(item for item in authority.placed_pads if ":pad:1:" in item.pad_id)

    assert placed.x_mm == pytest.approx(30.0 + source_pad.y_mm)
    assert placed.y_mm == pytest.approx(40.0 - source_pad.x_mm)
    assert placed.rotation_deg == pytest.approx((90 + source_pad.angle_deg) % 360)


def test_back_side_transform_mirrors_local_x_before_rotation() -> None:
    authority = build_installed_footprint_geometry_authority(
        "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
        component_reference="U2",
        component_uuid_path="fixture/U2",
        anchor_x_mm=12.0,
        anchor_y_mm=8.0,
        side="back",
    )
    source = authority.pads[0]
    placed = authority.placed_pads[0]

    assert placed.x_mm == pytest.approx(12.0 - source.local_x_mm)
    assert placed.y_mm == pytest.approx(8.0 + source.local_y_mm)
    assert placed.side == "back"


def test_mating_and_tool_envelopes_remain_explicit_external_authorities() -> None:
    authority = build_installed_footprint_geometry_authority(
        "Connector_PinHeader_2.54mm:PinHeader_1x08_P2.54mm_Vertical",
        component_reference="J2",
        component_uuid_path="fixture/J2",
        anchor_x_mm=0.0,
        anchor_y_mm=0.0,
        mating_envelope_fingerprint="a" * 64,
        tool_envelope_fingerprint="b" * 64,
    )

    assert authority.mating_envelope_fingerprint == "a" * 64
    assert authority.tool_envelope_fingerprint == "b" * 64
