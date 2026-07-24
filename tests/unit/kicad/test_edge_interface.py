from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcbsmith.connector_zone_ir import outline_edge_id
from pcbsmith.edge_interface_ir import (
    EdgeInterfaceDeclaration,
    EdgeInterfaceFindingKind,
    EdgeInterfaceKind,
    EdgeInterfaceLocalGeometry,
    fingerprint,
)
from pcbsmith.kicad.board import BoardComponent, BoardLayout
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
)
from pcbsmith.kicad.edge_interface import (
    evaluate_edge_interface,
    placement_edge_exception_from_authority,
)
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon
from pcbsmith.semantic_ir import SemanticDisposition, SemanticVerification


def _rect(x1: float, y1: float, x2: float, y2: float) -> ExactPlanarCompound:
    return ExactPlanarCompound(
        polygons=(
            ExactPlanarPolygon(
                outer=((x1, y1), (x2, y1), (x2, y2), (x1, y2))
            ),
        )
    )


def _layout(*, x_mm: float = 0.0, rotation_deg: float = 0.0) -> BoardLayout:
    component = BoardComponent(
        reference="J1",
        value="USB-C",
        footprint="Fixture:Edge_USB_C",
        uuid_path="fixture/edge/J1",
    )
    return BoardLayout(
        placements=((component, x_mm),),
        segments=(),
        vias=(),
        width_mm=20.0,
        height_mm=20.0,
        parts_row_y_mm=10.0,
        part_rotation=(("J1", rotation_deg),) if rotation_deg else (),
    )


def _local_geometry(
    *,
    overhang: ExactPlanarCompound | None = None,
    pads: tuple[ExactPlanarCompound, ...] | None = None,
) -> EdgeInterfaceLocalGeometry:
    payload = {
        "schema_id": "pcbsmith-edge-interface-local-geometry",
        "schema_version": 1,
        "installed_footprint_id": "Fixture:Edge_USB_C",
        "component_uuid_path": "fixture/edge/J1",
        "source_file_sha256": "a" * 64,
        "source_binding_id": "fixture.usb-c.mechanical-drawing",
        "retained_support_compounds": [
            _rect(0.5, -1.5, 2.5, 1.5).model_dump(mode="json")
        ],
        "pad_compounds": [
            item.model_dump(mode="json")
            for item in (pads or (_rect(0.75, -0.4, 1.25, 0.4),))
        ],
        "overhang_compound": (
            overhang or _rect(-2.0, -1.0, 0.0, 1.0)
        ).model_dump(mode="json"),
    }
    return EdgeInterfaceLocalGeometry(
        installed_footprint_id=payload["installed_footprint_id"],
        component_uuid_path=payload["component_uuid_path"],
        source_file_sha256=payload["source_file_sha256"],
        source_binding_id=payload["source_binding_id"],
        retained_support_compounds=(_rect(0.5, -1.5, 2.5, 1.5),),
        pad_compounds=pads or (_rect(0.75, -0.4, 1.25, 0.4),),
        overhang_compound=overhang or _rect(-2.0, -1.0, 0.0, 1.0),
        geometry_fingerprint=fingerprint(payload),
    )


def _declaration(
    *,
    layout: BoardLayout | None = None,
    selected_edge_id: str | None = None,
    overhang: ExactPlanarCompound | None = None,
    pads: tuple[ExactPlanarCompound, ...] | None = None,
    minimum_mm: float = 1.0,
    maximum_mm: float = 2.5,
) -> EdgeInterfaceDeclaration:
    retained_layout = layout or _layout()
    snapshot = canonical_board_layout_snapshot_json(retained_layout)
    left_edge = outline_edge_id((0.0, 0.0), (0.0, 20.0))
    return EdgeInterfaceDeclaration(
        declaration_id="fixture.edge-interface.J1",
        reference="J1",
        interface_kind=EdgeInterfaceKind.CONNECTOR,
        selected_outline_edge_id=selected_edge_id or left_edge,
        board_layout_snapshot_json=snapshot,
        board_layout_snapshot_fingerprint=board_layout_snapshot_fingerprint(snapshot),
        local_geometry=_local_geometry(overhang=overhang, pads=pads),
        minimum_useful_overhang_mm=minimum_mm,
        maximum_allowed_overhang_mm=maximum_mm,
        minimum_retained_edge_clearance_mm=0.25,
        minimum_pad_edge_clearance_mm=0.5,
        exception_rule_id="assembly.connector-j1-overhang",
        retained_rule_id="assembly.connector-j1-retained",
        pad_rule_id="assembly.connector-j1-pads",
        selected_edge_rule_id="assembly.connector-j1-edge",
        overhang_rule_id="assembly.connector-j1-projection",
    )


def _by_kind(result):
    return {item.kind: item for item in result.findings}


def test_exact_selected_edge_overhang_earns_placement_exception() -> None:
    result = evaluate_edge_interface(_declaration())

    assert result.approved
    assert all(
        finding.verification is SemanticVerification.EXACT
        and finding.disposition is SemanticDisposition.PASS
        for finding in result.findings
    )
    measured = _by_kind(result)[EdgeInterfaceFindingKind.OVERHANG_BOUNDS]
    assert (
        measured.measured_overhang_squared_numerator,
        measured.measured_overhang_squared_denominator,
    ) == (4, 1)

    exception = placement_edge_exception_from_authority(result)
    assert exception.reference == "J1"
    assert exception.waive_outer_edge_containment
    assert exception.waive_courtyard_outer_edge_containment
    assert exception.interface_authority == result


@pytest.mark.parametrize(
    ("overhang", "expected_kind"),
    (
        (_rect(-3.0, -1.0, 0.0, 1.0), EdgeInterfaceFindingKind.OVERHANG_BOUNDS),
        (_rect(-0.5, -1.0, 0.0, 1.0), EdgeInterfaceFindingKind.OVERHANG_BOUNDS),
        (_rect(-2.0, -1.0, 0.25, 1.0), EdgeInterfaceFindingKind.SELECTED_EDGE),
    ),
)
def test_excessive_recessed_and_material_intruding_overhangs_fail(
    overhang: ExactPlanarCompound,
    expected_kind: EdgeInterfaceFindingKind,
) -> None:
    result = evaluate_edge_interface(_declaration(overhang=overhang))

    assert not result.approved
    assert _by_kind(result)[expected_kind].disposition is SemanticDisposition.FAIL


def test_wrong_edge_and_pad_outside_fail_independently() -> None:
    right_edge = outline_edge_id((20.0, 0.0), (20.0, 20.0))
    wrong_edge = evaluate_edge_interface(_declaration(selected_edge_id=right_edge))
    assert (
        _by_kind(wrong_edge)[EdgeInterfaceFindingKind.SELECTED_EDGE].disposition
        is SemanticDisposition.FAIL
    )

    bad_pad = evaluate_edge_interface(
        _declaration(pads=(_rect(-0.25, -0.4, 0.25, 0.4),))
    )
    assert (
        _by_kind(bad_pad)[EdgeInterfaceFindingKind.PAD_MATERIAL].disposition
        is SemanticDisposition.FAIL
    )


def test_non_orthogonal_transform_is_unverified_and_cannot_grant_exception() -> None:
    result = evaluate_edge_interface(_declaration(layout=_layout(rotation_deg=45.0)))

    assert not result.approved
    assert any(
        finding.verification is SemanticVerification.BOUNDED_APPROXIMATION
        and finding.disposition is SemanticDisposition.UNVERIFIED
        for finding in result.findings
    )
    with pytest.raises(ValueError, match="failed authority"):
        placement_edge_exception_from_authority(result)


def test_result_and_geometry_tampering_are_rejected() -> None:
    result = evaluate_edge_interface(_declaration())
    with pytest.raises(ValidationError, match="stale or not replay-derived"):
        result.model_copy(update={"approved": False}).model_validate(
            result.model_copy(update={"approved": False})
        )

    geometry = _local_geometry()
    with pytest.raises(ValidationError, match="geometry fingerprint is stale"):
        EdgeInterfaceLocalGeometry(
            **{
                **geometry.model_dump(),
                "overhang_compound": _rect(-4.0, -1.0, 0.0, 1.0),
            }
        )
