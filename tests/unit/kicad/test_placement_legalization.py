from __future__ import annotations

import hashlib
import math

import pytest
from pydantic import ValidationError

from pcbsmith.kicad.board import BoardComponent, BoardCutoutPolygon, BoardLayout
from pcbsmith.kicad.placement_routability import (
    bind_component_placement_geometry,
    build_placement_geometry_catalog,
    build_placement_probe,
    legalize_placement_probe,
)
from pcbsmith.placement_geometry import (
    ExactPlanarCompound,
    ExactPlanarPolygon,
    PlacementTransform,
    compound_minimum_squared_distance,
    diagnostic_distance_mm,
    transform_compound_bounded,
)
from pcbsmith.placement_ir import (
    ComponentPose,
    FootprintPlacementRegion,
    PlacementBudget,
    PlacementEdgeException,
    PlacementFindingDisposition,
    PlacementGeometryCatalog,
    PlacementLegalizationFinding,
    PlacementLegalizationFindingKind,
    PlacementLegalizationOutcome,
    PlacementLegalizationPolicy,
    PlacementLegalizationResult,
    PlacementOccupancySpan,
    PlacementProbePolicy,
    PlacementRegionVerification,
    PlacementSidePermission,
    placement_findings_fingerprint,
)


def _component(reference: str) -> BoardComponent:
    return BoardComponent(
        reference=reference,
        value=f"value:{reference}",
        footprint=f"fixture:{reference}",
        uuid_path=f"uuid:{reference}",
        fields=(("identity", reference.lower()),),
    )


def _rect(x1: float, y1: float, x2: float, y2: float) -> ExactPlanarCompound:
    return ExactPlanarCompound(
        polygons=(ExactPlanarPolygon(outer=((x1, y1), (x2, y1), (x2, y2), (x1, y2))),)
    )


def _layout(
    poses: tuple[ComponentPose, ...],
    *,
    width_mm: float = 20.0,
    height_mm: float = 20.0,
    outline: tuple[tuple[float, float], ...] | None = None,
    cutouts: tuple[BoardCutoutPolygon, ...] = (),
    graphics: tuple[str, ...] = (),
) -> BoardLayout:
    components = tuple(_component(pose.reference) for pose in poses)
    return BoardLayout(
        placements=tuple(
            (component, pose.x_mm) for component, pose in zip(components, poses, strict=True)
        ),
        segments=(),
        vias=(),
        width_mm=width_mm,
        height_mm=height_mm,
        parts_row_y_mm=poses[0].y_mm,
        part_y_mm=tuple((pose.reference, pose.y_mm) for pose in poses[1:]),
        part_rotation=tuple(
            (pose.reference, pose.rotation_deg) for pose in poses if pose.rotation_deg != 0.0
        ),
        part_flip=tuple(pose.reference for pose in poses if pose.side == "back"),
        outline=outline,
        cutouts=cutouts,
        graphics=graphics,
    )


def _budget(limit: int = 2) -> PlacementBudget:
    return PlacementBudget(
        max_proposals=1,
        max_legalization_evaluations=limit,
        max_surrogate_evaluations=1,
        max_corridor_plans=1,
        max_detailed_candidates=1,
        max_exact_checks=1,
        max_r3_geometry_cells_per_candidate=1,
        max_r3_geometry_portals_per_candidate=1,
        max_r3_expansions_per_candidate=1,
        max_r2_passes_per_candidate=1,
        max_r2_expansions_per_candidate=1,
        max_r2_expansions_per_net=1,
        max_r2_stagnant_passes=1,
    )


def _probe(layout: BoardLayout, *, limit: int = 2):
    poses = tuple(
        ComponentPose(
            reference=component.reference,
            x_mm=x_mm,
            y_mm=dict(layout.part_y_mm).get(component.reference, layout.parts_row_y_mm),
            rotation_deg=dict(layout.part_rotation).get(component.reference, 0.0),
            side="back" if component.reference in layout.part_flip else "front",
        )
        for component, x_mm in layout.placements
    )
    return build_placement_probe(
        layout,
        poses,
        ("/N",),
        known_net_names=("/N",),
        policy=PlacementProbePolicy(),
        budget=_budget(limit),
    )


def _region(
    reference: str,
    purpose: str,
    compound: ExactPlanarCompound | None,
    *,
    verification: PlacementRegionVerification = PlacementRegionVerification.EXACT,
    error_mm: float | None = None,
    span: PlacementOccupancySpan = PlacementOccupancySpan.PLACED_SIDE,
) -> FootprintPlacementRegion:
    source = (
        compound.semantic_fingerprint()
        if compound is not None
        else hashlib.sha256(f"unsupported:{reference}:{purpose}".encode()).hexdigest()
    )
    return FootprintPlacementRegion(
        region_id=f"{reference}:{purpose}",
        purpose=purpose,
        occupancy_span=span,
        local_compound=compound,
        verification=verification,
        maximum_error_mm=error_mm,
        source_layers=()
        if verification is PlacementRegionVerification.UNSUPPORTED
        else ("F.Fab" if purpose == "body" else "F.CrtYd",),
        source_fingerprint=source,
    )


def _catalog(
    layout: BoardLayout,
    *,
    body: ExactPlanarCompound | None = None,
    courtyard: ExactPlanarCompound | None = None,
    verification: PlacementRegionVerification = PlacementRegionVerification.EXACT,
    error_mm: float | None = None,
    body_span: PlacementOccupancySpan = PlacementOccupancySpan.PLACED_SIDE,
    courtyard_span: PlacementOccupancySpan = PlacementOccupancySpan.PLACED_SIDE,
) -> PlacementGeometryCatalog:
    body = body or _rect(-0.25, -0.25, 0.25, 0.25)
    courtyard = courtyard or _rect(-0.5, -0.5, 0.5, 0.5)
    geometries = []
    for component, _x_mm in layout.placements:
        geometries.append(
            bind_component_placement_geometry(
                component,
                regions=(
                    _region(
                        component.reference,
                        "body",
                        None if verification is PlacementRegionVerification.UNSUPPORTED else body,
                        verification=verification,
                        error_mm=error_mm,
                        span=body_span,
                    ),
                    _region(
                        component.reference,
                        "courtyard",
                        None
                        if verification is PlacementRegionVerification.UNSUPPORTED
                        else courtyard,
                        verification=verification,
                        error_mm=error_mm,
                        span=courtyard_span,
                    ),
                ),
            )
        )
    return build_placement_geometry_catalog(layout, geometries)


def _policy(
    *,
    body: float = 0.01,
    courtyard: float = 0.0,
    outer: float = 0.01,
    cutout: float = 0.01,
    contain_courtyard: bool = False,
    courtyard_outer: float = 0.0,
    permissions: tuple[PlacementSidePermission, ...] = (),
    exceptions: tuple[PlacementEdgeException, ...] = (),
) -> PlacementLegalizationPolicy:
    return PlacementLegalizationPolicy(
        policy_id="fixture-policy",
        minimum_body_spacing_mm=body,
        minimum_courtyard_spacing_mm=courtyard,
        minimum_body_outer_edge_clearance_mm=outer,
        minimum_body_cutout_clearance_mm=cutout,
        require_courtyard_containment=contain_courtyard,
        minimum_courtyard_outer_edge_clearance_mm=courtyard_outer,
        side_permissions=permissions,
        edge_exceptions=exceptions,
    )


def _kinds(result: PlacementLegalizationResult) -> set[PlacementLegalizationFindingKind]:
    return {finding.kind for finding in result.findings}


def test_exact_legal_result_is_deterministic_versioned_and_charges_one_evaluation() -> None:
    layout = _layout(
        (ComponentPose(reference="U1", x_mm=10.0, y_mm=10.0, rotation_deg=90.0, side="front"),)
    )
    probe = _probe(layout)
    catalog = _catalog(layout)
    first = legalize_placement_probe(probe, catalog, _policy(outer=0.2))
    second = legalize_placement_probe(probe, catalog, _policy(outer=0.2))

    assert first == second
    assert first.outcome is PlacementLegalizationOutcome.LEGAL_EXACT
    assert first.schema_version == first.telemetry.schema_version == 1
    assert first.telemetry.legalization_evaluations_consumed_after == 1
    assert first.telemetry.legalization_evaluations_remaining == 1
    assert first.semantic_fingerprint() == second.semantic_fingerprint()
    assert (
        catalog.semantic_fingerprint()
        == "5885fbe80e1d4b16fd7e5f646db1e34ecde465cd39b65e27ad7ce81dfb370213"
    )
    assert (
        first.telemetry.input_fingerprint
        == "360aa32d03220f1c21edc322ae4ed820d6d104bf588ff8a2503ff5d78f1c0363"
    )
    assert (
        first.telemetry.semantic_fingerprint()
        == "39c4477fd5f2b427d53da64f7384bebe4f64d67e1eacd31248153d967731b608"
    )
    assert (
        first.semantic_fingerprint()
        == "80b627db25377526062e715f4fb2f09d7fd31aec15e769a20c22ad3ef67369e8"
    )


def test_catalog_completeness_template_and_component_freshness_are_fail_closed() -> None:
    poses = (
        ComponentPose(reference="U1", x_mm=5.0, y_mm=5.0, rotation_deg=0.0, side="front"),
        ComponentPose(reference="U2", x_mm=10.0, y_mm=5.0, rotation_deg=0.0, side="front"),
    )
    layout = _layout(poses)
    probe = _probe(layout)
    complete = _catalog(layout)
    incomplete = PlacementGeometryCatalog(
        template_fingerprint=complete.template_fingerprint,
        components=(complete.components[0],),
    )
    with pytest.raises(ValueError, match="incomplete or foreign"):
        legalize_placement_probe(probe, incomplete, _policy())

    stale_component = complete.components[0].model_copy(
        update={"component_identity_fingerprint": "0" * 64}
    )
    stale = PlacementGeometryCatalog(
        template_fingerprint=complete.template_fingerprint,
        components=(stale_component, complete.components[1]),
    )
    with pytest.raises(ValueError, match="component identity is stale"):
        legalize_placement_probe(probe, stale, _policy())


def test_same_side_overlap_fires_but_opposite_projection_does_not() -> None:
    front = ComponentPose(reference="U1", x_mm=5.0, y_mm=5.0, rotation_deg=0.0, side="front")
    same_layout = _layout(
        (front, ComponentPose(reference="U2", x_mm=5.0, y_mm=5.0, rotation_deg=0.0, side="front"))
    )
    same = legalize_placement_probe(_probe(same_layout), _catalog(same_layout), _policy())
    assert same.outcome is PlacementLegalizationOutcome.REJECTED
    assert _kinds(same) == {
        PlacementLegalizationFindingKind.BODY_COLLISION,
        PlacementLegalizationFindingKind.COURTYARD_COLLISION,
    }

    opposite_layout = _layout(
        (front, ComponentPose(reference="U2", x_mm=5.0, y_mm=5.0, rotation_deg=0.0, side="back"))
    )
    opposite = legalize_placement_probe(
        _probe(opposite_layout), _catalog(opposite_layout), _policy()
    )
    assert opposite.outcome is PlacementLegalizationOutcome.LEGAL_EXACT


def test_through_body_collides_across_sides_without_merging_courtyards() -> None:
    layout = _layout(
        (
            ComponentPose(reference="U1", x_mm=5.0, y_mm=5.0, rotation_deg=0.0, side="front"),
            ComponentPose(reference="U2", x_mm=5.0, y_mm=5.0, rotation_deg=0.0, side="back"),
        )
    )
    result = legalize_placement_probe(
        _probe(layout),
        _catalog(layout, body_span=PlacementOccupancySpan.BOTH),
        _policy(),
    )

    assert _kinds(result) == {PlacementLegalizationFindingKind.BODY_COLLISION}


def test_courtyard_boundary_touch_is_legal_but_positive_gap_and_overlap_fire() -> None:
    layout = _layout(
        (
            ComponentPose(reference="U1", x_mm=5.0, y_mm=5.0, rotation_deg=0.0, side="front"),
            ComponentPose(reference="U2", x_mm=6.0, y_mm=5.0, rotation_deg=0.0, side="front"),
        )
    )
    assert (
        legalize_placement_probe(_probe(layout), _catalog(layout), _policy()).outcome
        is PlacementLegalizationOutcome.LEGAL_EXACT
    )
    spaced = legalize_placement_probe(_probe(layout), _catalog(layout), _policy(courtyard=0.01))
    assert _kinds(spaced) == {PlacementLegalizationFindingKind.COURTYARD_COLLISION}

    overlap_layout = _layout(
        (
            ComponentPose(reference="U1", x_mm=5.0, y_mm=5.0, rotation_deg=0.0, side="front"),
            ComponentPose(reference="U2", x_mm=5.9, y_mm=5.0, rotation_deg=0.0, side="front"),
        )
    )
    overlap = legalize_placement_probe(_probe(overlap_layout), _catalog(overlap_layout), _policy())
    assert _kinds(overlap) == {PlacementLegalizationFindingKind.COURTYARD_COLLISION}


def test_concave_outline_and_donut_cutout_are_checked_as_shapes() -> None:
    outline = (
        (0.0, 0.0),
        (10.0, 0.0),
        (10.0, 10.0),
        (6.0, 10.0),
        (6.0, 4.0),
        (4.0, 4.0),
        (4.0, 10.0),
        (0.0, 10.0),
    )
    notch_layout = _layout(
        (ComponentPose(reference="U1", x_mm=5.0, y_mm=7.0, rotation_deg=0.0, side="front"),),
        outline=outline,
    )
    notch = legalize_placement_probe(
        _probe(notch_layout),
        _catalog(notch_layout, body=_rect(-1.5, -0.5, 1.5, 0.5)),
        _policy(),
    )
    assert PlacementLegalizationFindingKind.OUTER_EDGE_VIOLATION in _kinds(notch)

    cutout_layout = _layout(
        (ComponentPose(reference="U1", x_mm=5.0, y_mm=5.0, rotation_deg=0.0, side="front"),),
        cutouts=(BoardCutoutPolygon(((4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0))),),
    )
    cutout = legalize_placement_probe(_probe(cutout_layout), _catalog(cutout_layout), _policy())
    assert PlacementLegalizationFindingKind.CUTOUT_VIOLATION in _kinds(cutout)


def test_edge_exception_is_reference_and_rule_scoped_only() -> None:
    layout = _layout(
        (ComponentPose(reference="J1", x_mm=0.0, y_mm=10.0, rotation_deg=0.0, side="front"),)
    )
    body = _rect(-1.0, -0.5, 1.0, 0.5)
    rejected = legalize_placement_probe(_probe(layout), _catalog(layout, body=body), _policy())
    assert rejected.outcome is PlacementLegalizationOutcome.REJECTED

    exception = PlacementEdgeException(
        reference="J1",
        rule_id="assembly.connector-j1-overhang",
        waive_outer_edge_containment=True,
        minimum_outer_edge_clearance_mm=0.0,
    )
    accepted = legalize_placement_probe(
        _probe(layout),
        _catalog(layout, body=body),
        _policy(exceptions=(exception,)),
    )
    assert accepted.outcome is PlacementLegalizationOutcome.LEGAL_EXACT
    assert accepted.applied_edge_exception_rule_ids == ("assembly.connector-j1-overhang",)

    off_board_layout = _layout(
        (
            ComponentPose(
                reference="J1",
                x_mm=-5.0,
                y_mm=10.0,
                rotation_deg=0.0,
                side="front",
            ),
        )
    )
    off_board = legalize_placement_probe(
        _probe(off_board_layout),
        _catalog(off_board_layout, body=body),
        _policy(exceptions=(exception,)),
    )
    assert off_board.outcome is PlacementLegalizationOutcome.REJECTED


def test_bounded_safe_geometry_is_legal_bounded_but_failed_proofs_are_unverified() -> None:
    safe_layout = _layout(
        (ComponentPose(reference="U1", x_mm=10.0, y_mm=10.0, rotation_deg=0.0, side="front"),)
    )
    safe = legalize_placement_probe(
        _probe(safe_layout),
        _catalog(
            safe_layout,
            verification=PlacementRegionVerification.BOUNDED_APPROXIMATION,
            error_mm=0.1,
        ),
        _policy(outer=0.2),
    )
    assert safe.outcome is PlacementLegalizationOutcome.LEGAL_BOUNDED
    assert safe.telemetry.maximum_effective_error_mm == 0.1

    pair_layout = _layout(
        (
            ComponentPose(reference="U1", x_mm=5.0, y_mm=5.0, rotation_deg=0.0, side="front"),
            ComponentPose(reference="U2", x_mm=5.1, y_mm=5.0, rotation_deg=0.0, side="front"),
        )
    )
    pair = legalize_placement_probe(
        _probe(pair_layout),
        _catalog(
            pair_layout,
            verification=PlacementRegionVerification.BOUNDED_APPROXIMATION,
            error_mm=0.1,
        ),
        _policy(),
    )
    assert pair.outcome is PlacementLegalizationOutcome.UNVERIFIED
    assert {finding.disposition for finding in pair.findings} == {
        PlacementFindingDisposition.UNVERIFIED
    }

    edge_layout = _layout(
        (ComponentPose(reference="U1", x_mm=0.1, y_mm=5.0, rotation_deg=0.0, side="front"),)
    )
    edge = legalize_placement_probe(
        _probe(edge_layout),
        _catalog(
            edge_layout,
            verification=PlacementRegionVerification.BOUNDED_APPROXIMATION,
            error_mm=0.1,
        ),
        _policy(),
    )
    assert edge.outcome is PlacementLegalizationOutcome.UNVERIFIED
    assert PlacementLegalizationFindingKind.OUTER_EDGE_VIOLATION in _kinds(edge)

    cutout_layout = _layout(
        (ComponentPose(reference="U1", x_mm=5.0, y_mm=5.0, rotation_deg=0.0, side="front"),),
        cutouts=(BoardCutoutPolygon(((4.0, 4.0), (6.0, 4.0), (6.0, 6.0), (4.0, 6.0))),),
    )
    cutout = legalize_placement_probe(
        _probe(cutout_layout),
        _catalog(
            cutout_layout,
            verification=PlacementRegionVerification.BOUNDED_APPROXIMATION,
            error_mm=0.1,
        ),
        _policy(),
    )
    assert cutout.outcome is PlacementLegalizationOutcome.UNVERIFIED
    assert (
        next(
            finding
            for finding in cutout.findings
            if finding.kind is PlacementLegalizationFindingKind.CUTOUT_VIOLATION
        ).disposition
        is PlacementFindingDisposition.UNVERIFIED
    )


def test_unsupported_sources_and_raw_edge_cuts_fail_closed_but_arbitrary_is_bounded() -> None:
    unsupported_layout = _layout(
        (ComponentPose(reference="U1", x_mm=10.0, y_mm=10.0, rotation_deg=0.0, side="front"),)
    )
    unsupported = legalize_placement_probe(
        _probe(unsupported_layout),
        _catalog(unsupported_layout, verification=PlacementRegionVerification.UNSUPPORTED),
        _policy(),
    )
    assert unsupported.outcome is PlacementLegalizationOutcome.UNVERIFIED

    angle_layout = _layout(
        (ComponentPose(reference="U1", x_mm=10.0, y_mm=10.0, rotation_deg=37.0, side="back"),)
    )
    angle = legalize_placement_probe(_probe(angle_layout), _catalog(angle_layout), _policy())
    assert angle.outcome is PlacementLegalizationOutcome.LEGAL_BOUNDED
    assert (
        angle.telemetry.transform_verification is PlacementRegionVerification.BOUNDED_APPROXIMATION
    )
    assert angle.telemetry.maximum_transform_error_mm is not None
    assert angle.telemetry.maximum_transform_error_mm > 0
    assert not angle.findings

    raw_layout = _layout(
        (ComponentPose(reference="U1", x_mm=10.0, y_mm=10.0, rotation_deg=0.0, side="front"),),
        graphics=('(gr_line (start 1 1) (end 2 2) (layer "Edge.Cuts"))',),
    )
    raw = legalize_placement_probe(_probe(raw_layout), _catalog(raw_layout), _policy())
    assert raw.outcome is PlacementLegalizationOutcome.UNVERIFIED
    assert PlacementLegalizationFindingKind.BOARD_GEOMETRY_UNSUPPORTED in _kinds(raw)

    ambiguous_layout = _layout(
        (
            ComponentPose(
                reference="U1",
                x_mm=10.0,
                y_mm=10.0,
                rotation_deg=0.0,
                side="front",
            ),
        ),
        graphics=('(gr_text "missing layer")',),
    )
    ambiguous = legalize_placement_probe(
        _probe(ambiguous_layout),
        _catalog(ambiguous_layout),
        _policy(),
    )
    assert ambiguous.outcome is PlacementLegalizationOutcome.UNVERIFIED

    silk_layout = _layout(
        (
            ComponentPose(
                reference="U1",
                x_mm=10.0,
                y_mm=10.0,
                rotation_deg=0.0,
                side="front",
            ),
        ),
        graphics=('(gr_text "review" (layer "F.SilkS"))',),
    )
    silk = legalize_placement_probe(_probe(silk_layout), _catalog(silk_layout), _policy())
    assert silk.outcome is PlacementLegalizationOutcome.LEGAL_EXACT


def test_far_front_and_back_arbitrary_placements_are_legal_bounded() -> None:
    layout = _layout(
        (
            ComponentPose(reference="U1", x_mm=5.0, y_mm=5.0, rotation_deg=37.0, side="front"),
            ComponentPose(reference="U2", x_mm=15.0, y_mm=15.0, rotation_deg=89.999, side="back"),
        )
    )

    result = legalize_placement_probe(_probe(layout), _catalog(layout), _policy())

    assert result.outcome is PlacementLegalizationOutcome.LEGAL_BOUNDED
    assert not result.findings
    assert (
        result.telemetry.transform_verification is PlacementRegionVerification.BOUNDED_APPROXIMATION
    )
    assert result.telemetry.maximum_transform_error_mm is not None
    assert math.isfinite(result.telemetry.maximum_transform_error_mm)


def test_uncertain_arbitrary_overlap_is_unverified_not_rejected() -> None:
    layout = _layout(
        (
            ComponentPose(reference="U1", x_mm=10.0, y_mm=10.0, rotation_deg=37.0, side="front"),
            ComponentPose(reference="U2", x_mm=10.0, y_mm=10.0, rotation_deg=37.0, side="front"),
        )
    )

    result = legalize_placement_probe(_probe(layout), _catalog(layout), _policy())

    assert result.outcome is PlacementLegalizationOutcome.UNVERIFIED
    assert PlacementLegalizationFindingKind.BODY_COLLISION in _kinds(result)
    assert all(
        finding.disposition is PlacementFindingDisposition.UNVERIFIED
        for finding in result.findings
        if finding.kind
        in {
            PlacementLegalizationFindingKind.BODY_COLLISION,
            PlacementLegalizationFindingKind.COURTYARD_COLLISION,
        }
    )


def test_bounded_source_and_transform_errors_compose_at_clearance_boundary() -> None:
    poses = (
        ComponentPose(reference="U1", x_mm=5.0, y_mm=10.0, rotation_deg=37.0, side="front"),
        ComponentPose(reference="U2", x_mm=7.0, y_mm=10.0, rotation_deg=37.0, side="front"),
    )
    layout = _layout(poses)
    body = _rect(-0.25, -0.25, 0.25, 0.25)
    placed_bodies = tuple(
        transform_compound_bounded(
            body,
            PlacementTransform(
                anchor_x_mm=pose.x_mm,
                anchor_y_mm=pose.y_mm,
                rotation_deg=pose.rotation_deg,
                side=pose.side,
            ),
        )
        for pose in poses
    )
    gap = diagnostic_distance_mm(
        compound_minimum_squared_distance(placed_bodies[0].compound, placed_bodies[1].compound)
    )
    source_error = 0.01
    effective_errors = tuple(
        math.nextafter(source_error + (placed.maximum_error_mm or 0.0), math.inf)
        for placed in placed_bodies
    )
    conservative_policy_limit = gap - sum(effective_errors)
    catalog = _catalog(
        layout,
        verification=PlacementRegionVerification.BOUNDED_APPROXIMATION,
        error_mm=source_error,
    )

    passing = legalize_placement_probe(
        _probe(layout),
        catalog,
        _policy(body=conservative_policy_limit - 1e-12, outer=0.001),
    )
    one_less_margin = legalize_placement_probe(
        _probe(layout),
        catalog,
        _policy(body=conservative_policy_limit + 1e-12, outer=0.001),
    )

    assert passing.outcome is PlacementLegalizationOutcome.LEGAL_BOUNDED
    assert passing.telemetry.maximum_transform_error_mm is not None
    assert passing.telemetry.maximum_effective_error_mm is not None
    assert (
        passing.telemetry.maximum_effective_error_mm
        > source_error + passing.telemetry.maximum_transform_error_mm
    )
    assert one_less_margin.outcome is PlacementLegalizationOutcome.UNVERIFIED
    spacing = next(
        finding
        for finding in one_less_margin.findings
        if finding.kind is PlacementLegalizationFindingKind.BODY_COLLISION
    )
    assert spacing.disposition is PlacementFindingDisposition.UNVERIFIED


def test_result_revalidation_rejects_forged_bounded_transform_telemetry() -> None:
    layout = _layout(
        (ComponentPose(reference="U1", x_mm=10.0, y_mm=10.0, rotation_deg=37.0, side="back"),)
    )
    legal = legalize_placement_probe(_probe(layout), _catalog(layout), _policy())
    transform_error = legal.telemetry.maximum_transform_error_mm
    assert transform_error is not None

    missing_error = legal.telemetry.model_copy(update={"maximum_transform_error_mm": None})
    forged_missing = legal.model_copy(update={"telemetry": missing_error})
    with pytest.raises(ValidationError, match="bounded transform requires"):
        PlacementLegalizationResult.model_validate_json(forged_missing.model_dump_json())

    understated = legal.telemetry.model_copy(
        update={"maximum_effective_error_mm": transform_error / 2}
    )
    forged_understated = legal.model_copy(update={"telemetry": understated})
    with pytest.raises(ValidationError, match="cannot understate transform error"):
        PlacementLegalizationResult.model_validate_json(forged_understated.model_dump_json())


def test_side_policy_and_fixed_zero_budget_are_typed() -> None:
    layout = _layout(
        (ComponentPose(reference="U1", x_mm=10.0, y_mm=10.0, rotation_deg=0.0, side="back"),)
    )
    side = legalize_placement_probe(
        _probe(layout),
        _catalog(layout),
        _policy(permissions=(PlacementSidePermission(reference="U1", allowed_sides=("front",)),)),
    )
    assert side.outcome is PlacementLegalizationOutcome.REJECTED
    assert _kinds(side) == {PlacementLegalizationFindingKind.POLICY_SIDE}

    zero_probe = _probe(layout, limit=0)
    zero = legalize_placement_probe(zero_probe, _catalog(layout), _policy())
    assert zero.outcome is PlacementLegalizationOutcome.BUDGET_EXHAUSTED
    assert zero.telemetry.legalization_evaluations_consumed_before == 0
    assert zero.telemetry.legalization_evaluations_consumed_after == 0
    assert zero.telemetry.legalization_evaluations_remaining == 0


def test_result_validator_rejects_forged_outcomes_and_mixed_budget_findings() -> None:
    layout = _layout(
        (ComponentPose(reference="U1", x_mm=10.0, y_mm=10.0, rotation_deg=0.0, side="front"),)
    )
    legal = legalize_placement_probe(_probe(layout), _catalog(layout), _policy())
    with pytest.raises(ValidationError, match="inconsistent"):
        PlacementLegalizationResult.model_validate(
            {**legal.model_dump(mode="json"), "outcome": "rejected"}
        )

    budget = legalize_placement_probe(_probe(layout, limit=0), _catalog(layout), _policy())
    unverified = PlacementLegalizationFinding(
        kind=PlacementLegalizationFindingKind.REGION_UNSUPPORTED,
        disposition=PlacementFindingDisposition.UNVERIFIED,
        references=("U1",),
        rule_id="fixture.unverified",
        verification=PlacementRegionVerification.UNSUPPORTED,
    )
    mixed_findings = (*budget.findings, unverified)
    forged_telemetry = budget.telemetry.model_copy(
        update={"findings_fingerprint": placement_findings_fingerprint(mixed_findings)}
    )
    with pytest.raises(ValidationError, match="cannot mix"):
        PlacementLegalizationResult.model_validate(
            {
                **budget.model_dump(mode="json"),
                "findings": [finding.model_dump(mode="json") for finding in mixed_findings],
                "telemetry": forged_telemetry.model_dump(mode="json"),
            }
        )
