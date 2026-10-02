from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pcbsmith.kicad.installed_footprint_geometry import (
    build_installed_footprint_geometry_authority,
)
from pcbsmith.package_escape_ir import (
    EscapeNetWidth,
    EscapePadAnchor,
    EscapeSegmentProposal,
    EscapeViaProposal,
    PackageEscapeRequest,
    ReservedEscapeCorridor,
    build_package_escape_certificate,
)
from pcbsmith.power_topology_ir import NeckdownAllowance
from pcbsmith.routing_ir import RoutePoint, RouteSegmentGeometry, RouteViaGeometry

FOOTPRINTS = (
    "Package_SO:TSSOP-20_4.4x6.5mm_P0.65mm",
    "Package_QFP:TQFP-48_7x7mm_P0.5mm",
    "Package_DFN_QFN:QFN-16-1EP_3x3mm_P0.5mm_EP1.9x1.9mm",
)


def _fixture(footprint_id: str):
    authority = build_installed_footprint_geometry_authority(
        footprint_id,
        component_reference="U1",
        component_uuid_path="w5/U1",
        anchor_x_mm=10.0,
        anchor_y_mm=10.0,
    )
    placed = authority.placed_pads[0]
    pad = EscapePadAnchor(
        pad_id="U1.1",
        net_name="SIG",
        layer="F.Cu",
        center=RoutePoint(x_mm=placed.x_mm, y_mm=placed.y_mm),
        width_mm=placed.width_mm,
        height_mm=placed.height_mm,
    )
    request = PackageEscapeRequest(
        source_board_sha256="a" * 64,
        exact_footprint_geometry_fingerprint=authority.geometry_fingerprint,
        fabrication_profile_fingerprint="b" * 64,
        minimum_via_diameter_mm=0.6,
        minimum_via_drill_mm=0.3,
        pads=(pad,),
        net_widths=(EscapeNetWidth(net_name="SIG", bulk_width_mm=0.3),),
        neckdown_allowances=(
            NeckdownAllowance(
                neckdown_id="u1-pad1-local",
                pad_ids=(pad.pad_id,),
                minimum_width_mm=0.18,
                maximum_length_mm=1.5,
                rationale_authority_id="exact-pad-pitch",
            ),
        ),
    )
    escape_end = RoutePoint(
        x_mm=pad.center.x_mm + pad.width_mm / 2 + 0.4,
        y_mm=pad.center.y_mm,
    )
    segments = (
        EscapeSegmentProposal(
            segment_id="seg-local",
            pad_id=pad.pad_id,
            geometry=RouteSegmentGeometry(
                net_name="SIG",
                start=pad.center,
                end=escape_end,
                layer="F.Cu",
                width_mm=0.18,
            ),
            neckdown_id="u1-pad1-local",
        ),
        EscapeSegmentProposal(
            segment_id="seg-bulk",
            pad_id=pad.pad_id,
            geometry=RouteSegmentGeometry(
                net_name="SIG",
                start=escape_end,
                end=RoutePoint(x_mm=escape_end.x_mm + 2.0, y_mm=escape_end.y_mm),
                layer="F.Cu",
                width_mm=0.3,
            ),
        ),
    )
    via = EscapeViaProposal(
        via_id="via-1",
        pad_id=pad.pad_id,
        geometry=RouteViaGeometry(
            net_name="SIG",
            position=escape_end,
            technology_id="home-through-via",
            start_layer="F.Cu",
            end_layer="B.Cu",
            diameter_mm=0.6,
            drill_mm=0.3,
        ),
    )
    return request, segments, (via,)


@pytest.mark.parametrize("footprint_id", FOOTPRINTS)
def test_real_tssop_qfp_qfn_fixtures_emit_source_bound_escape_delta(footprint_id: str) -> None:
    request, segments, vias = _fixture(footprint_id)
    result = build_package_escape_certificate(
        request, segment_proposals=segments, via_proposals=vias
    )
    assert result.qualified
    assert len(result.segment_deltas) == 2 and len(result.via_deltas) == 1
    assert result.request_fingerprint == request.semantic_fingerprint()


def test_every_narrow_segment_requires_a_local_allowance() -> None:
    request, segments, vias = _fixture(FOOTPRINTS[0])
    invalid = segments[0].model_copy(update={"neckdown_id": None})
    result = build_package_escape_certificate(
        request, segment_proposals=(invalid, segments[1]), via_proposals=vias
    )
    assert not result.qualified
    assert "seg-local:neckdown_undeclared" in result.blocker_ids
    assert not result.segment_deltas and not result.via_deltas


def test_automatic_whole_net_width_reduction_fails() -> None:
    request, segments, vias = _fixture(FOOTPRINTS[1])
    result = build_package_escape_certificate(
        request, segment_proposals=(segments[0],), via_proposals=vias
    )
    assert not result.qualified
    assert "U1.1:bulk_width_not_restored" in result.blocker_ids


def test_local_fanout_cannot_occupy_reserved_return_corridor() -> None:
    request, segments, vias = _fixture(FOOTPRINTS[2])
    first = segments[0].geometry
    corridor = ReservedEscapeCorridor(
        corridor_id="gnd-return",
        role="return",
        layer="F.Cu",
        x_min_mm=min(first.start.x_mm, first.end.x_mm) + 0.2,
        x_max_mm=max(first.start.x_mm, first.end.x_mm) + 0.4,
        y_min_mm=first.start.y_mm - 0.2,
        y_max_mm=first.start.y_mm + 0.2,
        permitted_net_names=("GND",),
    )
    blocked_request = request.model_copy(update={"reserved_corridors": (corridor,)})
    result = build_package_escape_certificate(
        blocked_request, segment_proposals=segments, via_proposals=vias
    )
    assert not result.qualified
    assert "seg-local:reserved_return_corridor" in result.blocker_ids


def test_via_in_pad_requires_explicit_fabrication_authority() -> None:
    request, segments, vias = _fixture(FOOTPRINTS[0])
    in_pad = vias[0].model_copy(
        update={
            "geometry": vias[0].geometry.model_copy(update={"position": request.pads[0].center})
        }
    )
    result = build_package_escape_certificate(
        request, segment_proposals=segments, via_proposals=(in_pad,)
    )
    assert not result.qualified
    assert "via-1:via_in_pad_unsupported" in result.blocker_ids


def test_failed_fanout_is_pure_and_leaves_source_file_unchanged(tmp_path: Path) -> None:
    source = tmp_path / "source.kicad_pcb"
    source.write_text("(kicad_pcb (version 20241229))\n", encoding="utf-8")
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    request, segments, vias = _fixture(FOOTPRINTS[0])
    request = request.model_copy(update={"source_board_sha256": before})
    result = build_package_escape_certificate(
        request, segment_proposals=(segments[0],), via_proposals=vias
    )
    assert not result.qualified and not result.segment_deltas and not result.via_deltas
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
