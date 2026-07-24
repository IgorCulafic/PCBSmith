"""Controlled selected-edge overhang evaluation for connectors and user controls."""

from __future__ import annotations

from fractions import Fraction
from typing import TYPE_CHECKING, Any

from pcbsmith.connector_zone_ir import outline_edge_id
from pcbsmith.edge_interface_ir import (
    EdgeInterfaceAuthorityResult,
    EdgeInterfaceDeclaration,
    EdgeInterfaceFinding,
    EdgeInterfaceFindingKind,
    EdgeInterfacePlacedGeometry,
    fingerprint,
)
from pcbsmith.kicad.board_serialization import parse_canonical_board_layout_snapshot
from pcbsmith.placement_geometry import (
    ExactPlanarCompound,
    ExactPlanarPolygon,
    PlacementTransform,
    PlacementTransformAuthority,
    PlanarRelation,
    compound_boundary_clearance_at_least,
    compound_clearance_at_least,
    compound_inside_polygon,
    compound_relation,
    compound_to_segment_distance_witness,
    compound_to_segment_maximum_distance_witness,
    transform_compound_bounded,
)
from pcbsmith.placement_pose_authority import derive_exact_placement_poses
from pcbsmith.semantic_ir import SemanticDisposition, SemanticVerification

if TYPE_CHECKING:
    from pcbsmith.placement_ir import PlacementEdgeException


def _outline_edges(
    declaration: EdgeInterfaceDeclaration,
) -> tuple[tuple[str, tuple[float, float], tuple[float, float]], ...]:
    layout = parse_canonical_board_layout_snapshot(declaration.board_layout_snapshot_json)
    points = layout.outline or (
        (0.0, 0.0),
        (layout.width_mm, 0.0),
        (layout.width_mm, layout.height_mm),
        (0.0, layout.height_mm),
    )
    return tuple(
        sorted(
            (
                outline_edge_id(points[index], points[(index + 1) % len(points)]),
                points[index],
                points[(index + 1) % len(points)],
            )
            for index in range(len(points))
        )
    )


def _finding(
    kind: EdgeInterfaceFindingKind,
    rule_id: str,
    passed: bool,
    message: str,
    *,
    exact: bool,
    selected_edge_id: str | None = None,
    other_contact_edge_ids: tuple[str, ...] = (),
    measured_overhang: Fraction | None = None,
) -> EdgeInterfaceFinding:
    return EdgeInterfaceFinding(
        kind=kind,
        rule_id=rule_id,
        verification=(
            SemanticVerification.EXACT
            if exact
            else SemanticVerification.BOUNDED_APPROXIMATION
        ),
        disposition=(
            (SemanticDisposition.PASS if passed else SemanticDisposition.FAIL)
            if exact
            else SemanticDisposition.UNVERIFIED
        ),
        selected_edge_id=selected_edge_id,
        other_contact_edge_ids=other_contact_edge_ids,
        measured_overhang_squared_numerator=(
            measured_overhang.numerator if measured_overhang is not None else None
        ),
        measured_overhang_squared_denominator=(
            measured_overhang.denominator if measured_overhang is not None else None
        ),
        message=message,
    )


def rederive_edge_interface(declaration: EdgeInterfaceDeclaration) -> dict[str, Any]:
    """Recompute the complete exception authority from its retained layout snapshot."""

    retained = EdgeInterfaceDeclaration.model_validate_json(declaration.model_dump_json())
    layout = parse_canonical_board_layout_snapshot(retained.board_layout_snapshot_json)
    pose = {
        item.reference: item for item in derive_exact_placement_poses(layout)
    }[retained.reference]
    transform = PlacementTransform(
        anchor_x_mm=pose.x_mm,
        anchor_y_mm=pose.y_mm,
        rotation_deg=pose.rotation_deg,
        side="back" if pose.flipped else "front",
    )
    geometry = retained.local_geometry
    placed = EdgeInterfacePlacedGeometry(
        retained_supports=tuple(
            transform_compound_bounded(item, transform)
            for item in geometry.retained_support_compounds
        ),
        pads=tuple(
            transform_compound_bounded(item, transform) for item in geometry.pad_compounds
        ),
        overhang=transform_compound_bounded(geometry.overhang_compound, transform),
    )
    transforms = (*placed.retained_supports, *placed.pads, placed.overhang)
    exact = all(
        item.authority is PlacementTransformAuthority.EXACT for item in transforms
    )
    findings: list[EdgeInterfaceFinding] = [
        _finding(
            EdgeInterfaceFindingKind.TRANSFORM_AUTHORITY,
            "r5.edge_interface.transform",
            exact,
            (
                "All edge-interface regions use an exact orthogonal placement transform."
                if exact
                else "Edge-interface placement transform is bounded, not exact."
            ),
            exact=True,
        )
    ]
    if not exact:
        for kind, rule_id, message in (
            (
                EdgeInterfaceFindingKind.RETAINED_MATERIAL,
                retained.retained_rule_id,
                "Retained support cannot be proved inside board material.",
            ),
            (
                EdgeInterfaceFindingKind.PAD_MATERIAL,
                retained.pad_rule_id,
                "Pad retention cannot be proved inside board material.",
            ),
            (
                EdgeInterfaceFindingKind.SELECTED_EDGE,
                retained.selected_edge_rule_id,
                "Selected-edge contact cannot be proved.",
            ),
            (
                EdgeInterfaceFindingKind.OVERHANG_BOUNDS,
                retained.overhang_rule_id,
                "Useful and maximum overhang cannot be proved.",
            ),
        ):
            findings.append(_finding(kind, rule_id, False, message, exact=False))
    else:
        points = layout.outline or (
            (0.0, 0.0),
            (layout.width_mm, 0.0),
            (layout.width_mm, layout.height_mm),
            (0.0, layout.height_mm),
        )
        outer = ExactPlanarPolygon(outer=points)
        cutouts = tuple(
            ExactPlanarCompound(polygons=(ExactPlanarPolygon(outer=item.points),))
            for item in layout.cutouts
        )
        material_polygon = ExactPlanarPolygon(
            outer=outer.outer,
            holes=tuple(item.polygons[0].outer for item in cutouts),
        )
        material = ExactPlanarCompound(polygons=(material_polygon,))

        def retained_inside(compound: ExactPlanarCompound, clearance: float) -> bool:
            return (
                compound_inside_polygon(compound, outer)
                and all(
                    compound_relation(compound, cutout) is PlanarRelation.DISJOINT
                    and compound_clearance_at_least(compound, cutout, clearance)
                    for cutout in cutouts
                )
                and compound_boundary_clearance_at_least(
                    compound, material_polygon, clearance
                )
            )

        retained_pass = all(
            retained_inside(
                item.compound, retained.minimum_retained_edge_clearance_mm
            )
            for item in placed.retained_supports
        )
        pad_pass = all(
            retained_inside(item.compound, retained.minimum_pad_edge_clearance_mm)
            for item in placed.pads
        )
        findings.extend(
            (
                _finding(
                    EdgeInterfaceFindingKind.RETAINED_MATERIAL,
                    retained.retained_rule_id,
                    retained_pass,
                    "Retained body/support regions remain in board material."
                    if retained_pass
                    else "A retained body/support region violates material or edge clearance.",
                    exact=True,
                ),
                _finding(
                    EdgeInterfaceFindingKind.PAD_MATERIAL,
                    retained.pad_rule_id,
                    pad_pass,
                    "All declared pads remain in board material with edge clearance."
                    if pad_pass
                    else "A declared pad violates board material or edge clearance.",
                    exact=True,
                ),
            )
        )
        edges = _outline_edges(retained)
        selected = next(
            item for item in edges if item[0] == retained.selected_outline_edge_id
        )
        selected_minimum = compound_to_segment_distance_witness(
            placed.overhang.compound, selected[1], selected[2]
        )
        other_contacts = tuple(
            edge_id
            for edge_id, start, end in edges
            if edge_id != selected[0]
            and compound_to_segment_distance_witness(
                placed.overhang.compound, start, end
            ).squared_distance
            == 0
        )
        material_relation = compound_relation(placed.overhang.compound, material)
        edge_pass = (
            selected_minimum.squared_distance == 0
            and not other_contacts
            and material_relation is PlanarRelation.BOUNDARY_TOUCH
        )
        findings.append(
            _finding(
                EdgeInterfaceFindingKind.SELECTED_EDGE,
                retained.selected_edge_rule_id,
                edge_pass,
                (
                    "Overhang touches only the declared outline edge and does not occupy "
                    "board material."
                    if edge_pass
                    else "Overhang uses the wrong edge, another edge, or occupies board material."
                ),
                exact=True,
                selected_edge_id=selected[0],
                other_contact_edge_ids=other_contacts,
            )
        )
        maximum = compound_to_segment_maximum_distance_witness(
            placed.overhang.compound, selected[1], selected[2]
        )
        minimum_required = Fraction(str(retained.minimum_useful_overhang_mm))
        maximum_allowed = Fraction(str(retained.maximum_allowed_overhang_mm))
        bounds_pass = (
            maximum.squared_distance >= minimum_required * minimum_required
            and maximum.squared_distance <= maximum_allowed * maximum_allowed
        )
        findings.append(
            _finding(
                EdgeInterfaceFindingKind.OVERHANG_BOUNDS,
                retained.overhang_rule_id,
                bounds_pass,
                (
                    "User-facing projection is within the declared useful overhang window."
                    if bounds_pass
                    else "User-facing projection is too recessed or exceeds its overhang limit."
                ),
                exact=True,
                selected_edge_id=selected[0],
                measured_overhang=maximum.squared_distance,
            )
        )
    canonical_findings = tuple(sorted(findings, key=lambda item: item.kind))
    approved = bool(canonical_findings) and all(
        item.verification is SemanticVerification.EXACT
        and item.disposition is SemanticDisposition.PASS
        for item in canonical_findings
    )
    evidence_fp = fingerprint(
        {
            "placed_geometry": placed.model_dump(mode="json"),
            "findings": [item.model_dump(mode="json") for item in canonical_findings],
        }
    )
    return {
        "declaration": retained,
        "placed_geometry": placed,
        "findings": canonical_findings,
        "approved": approved,
        "evidence_fingerprint": evidence_fp,
    }


def evaluate_edge_interface(
    declaration: EdgeInterfaceDeclaration,
) -> EdgeInterfaceAuthorityResult:
    """Evaluate and replay-bind one controlled board-edge exception."""

    derived = rederive_edge_interface(declaration)
    provisional = EdgeInterfaceAuthorityResult.model_construct(
        **derived, result_fingerprint="0" * 64
    )
    result_fp = fingerprint(
        provisional.model_dump(mode="json", exclude={"result_fingerprint"})
    )
    return EdgeInterfaceAuthorityResult(**derived, result_fingerprint=result_fp)


def placement_edge_exception_from_authority(
    authority: EdgeInterfaceAuthorityResult,
    *,
    waive_courtyard_outer_edge_containment: bool = True,
) -> PlacementEdgeException:
    """Convert only an approved replay result into an R5 legalization exception."""

    from pcbsmith.placement_ir import PlacementEdgeException

    retained = EdgeInterfaceAuthorityResult.model_validate_json(authority.model_dump_json())
    if not retained.approved:
        raise ValueError("cannot create a placement exception from failed authority")
    return PlacementEdgeException(
        reference=retained.declaration.reference,
        rule_id=retained.declaration.exception_rule_id,
        waive_outer_edge_containment=True,
        waive_courtyard_outer_edge_containment=waive_courtyard_outer_edge_containment,
        minimum_outer_edge_clearance_mm=0.0,
        interface_authority=retained,
    )
