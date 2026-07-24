"""Lossless KiCad BoardLayout placement probes for R5.0.

This module only derives a probe from a caller-owned template.  It performs no
legalization, move generation, surrogate scoring, corridor planning, or route
search.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, fields, is_dataclass, replace
from enum import Enum
from itertools import combinations
from typing import Any, Literal

from pydantic import BaseModel

from pcbsmith.kicad.board import BoardComponent, BoardLayout, placement_rotation, placement_y
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
)
from pcbsmith.placement_geometry import (
    ExactPlanarCompound,
    ExactPlanarPolygon,
    PlacementTransform,
    PlacementTransformAuthority,
    PlanarRelation,
    compound_boundary_minimum_squared_distance,
    compound_clearance_at_least,
    compound_inside_polygon,
    compound_minimum_squared_distance,
    compound_relation,
    diagnostic_distance_mm,
    transform_compound_bounded,
)
from pcbsmith.placement_ir import (
    ComponentPlacementGeometry,
    ComponentPose,
    FootprintPlacementRegion,
    PlacementBudget,
    PlacementFindingDisposition,
    PlacementGeometryCatalog,
    PlacementLegalizationFinding,
    PlacementLegalizationFindingKind,
    PlacementLegalizationOutcome,
    PlacementLegalizationPolicy,
    PlacementLegalizationResult,
    PlacementLegalizationTelemetry,
    PlacementOccupancySpan,
    PlacementProbePolicy,
    PlacementProbeResult,
    PlacementProbeTelemetry,
    PlacementRegionVerification,
    PlacementTargetPolicy,
    placement_findings_fingerprint,
    placement_pose_set_fingerprint,
)

PROBE_MUTABLE_LAYOUT_FIELDS = frozenset(
    ("placements", "part_y_mm", "part_rotation", "part_flip", "segments", "vias")
)
PROBE_PRESERVED_LAYOUT_FIELDS = frozenset(
    (
        "width_mm",
        "height_mm",
        "parts_row_y_mm",
        "zones",
        "outline",
        "graphics",
        "hide_references",
        "part_reference_at",
        "mask_apertures",
        "cutouts",
    )
)


def _canonical_payload(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("board layout fingerprint cannot contain non-finite floats")
        return value
    if isinstance(value, Enum):
        return {
            "enum_type": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": _canonical_payload(value.value),
        }
    if isinstance(value, BaseModel):
        return {
            "model_type": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": _canonical_payload(value.model_dump(mode="json")),
        }
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "dataclass_type": f"{type(value).__module__}.{type(value).__qualname__}",
            "fields": [
                (field.name, _canonical_payload(getattr(value, field.name)))
                for field in fields(value)
            ],
        }
    if isinstance(value, Mapping):
        encoded = [
            (_canonical_payload(key), _canonical_payload(item)) for key, item in value.items()
        ]
        return sorted(encoded, key=lambda item: _canonical_json(item[0]))
    if isinstance(value, (tuple, list)):
        return [_canonical_payload(item) for item in value]
    raise TypeError(
        "board layout fingerprint encountered an unsupported value type "
        f"{type(value).__module__}.{type(value).__qualname__}"
    )


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def board_layout_fingerprint(layout: BoardLayout) -> str:
    """Fingerprint every reflected BoardLayout field and nested semantic value."""

    payload = {
        "schema_id": "pcbsmith-board-layout-complete",
        "schema_version": 1,
        "layout": _canonical_payload(layout),
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def verify_probe_preservation(
    template: BoardLayout,
    probe: BoardLayout,
    *,
    mutable_fields: Collection[str] = PROBE_MUTABLE_LAYOUT_FIELDS,
    preserved_fields: Collection[str] = PROBE_PRESERVED_LAYOUT_FIELDS,
) -> tuple[str, ...]:
    """Fail closed unless every reflected field is classified and preserved."""

    template_fields = tuple(field.name for field in fields(template))
    probe_fields = tuple(field.name for field in fields(probe))
    if template_fields != probe_fields:
        raise ValueError("template and probe dataclass fields differ")
    reflected = frozenset(template_fields)
    mutable = frozenset(mutable_fields)
    preserved = frozenset(preserved_fields)
    overlap = tuple(sorted(mutable & preserved))
    if overlap:
        raise ValueError(f"probe field classifications overlap: {overlap!r}")
    missing = tuple(sorted(reflected - (mutable | preserved)))
    foreign = tuple(sorted((mutable | preserved) - reflected))
    if missing or foreign:
        raise ValueError(
            "probe BoardLayout field classification is stale: "
            f"unclassified={missing!r}, foreign={foreign!r}"
        )
    changed_preserved = tuple(
        name
        for name in template_fields
        if name in preserved and getattr(template, name) != getattr(probe, name)
    )
    if changed_preserved:
        raise ValueError(f"probe changed preserved BoardLayout fields: {changed_preserved!r}")
    changed = tuple(
        name
        for name in template_fields
        if name in mutable and getattr(template, name) != getattr(probe, name)
    )
    return tuple(sorted(changed))


@dataclass(frozen=True)
class PlacementProbe:
    """Materialized KiCad probe paired with its versioned semantic result."""

    layout: BoardLayout
    result: PlacementProbeResult

    def __post_init__(self) -> None:
        if board_layout_fingerprint(self.layout) != self.result.telemetry.probe_layout_fingerprint:
            raise ValueError("materialized probe layout fingerprint is stale")


def build_placement_probe(
    template: BoardLayout,
    poses: Mapping[str, ComponentPose] | Iterable[ComponentPose],
    target_nets: Collection[str],
    *,
    known_net_names: Collection[str],
    policy: PlacementProbePolicy,
    budget: PlacementBudget,
) -> PlacementProbe:
    """Build one field-preserving placement probe and strip exact target copper."""

    template_reference_order, base_pose_by_ref = _template_poses(template)
    target_policy = PlacementTargetPolicy(
        known_net_names=tuple(known_net_names),
        target_net_names=tuple(target_nets),
    )
    supplied_pose_by_ref = _canonical_supplied_poses(poses)
    template_references = set(template_reference_order)
    unknown = tuple(sorted(set(supplied_pose_by_ref) - template_references))
    if unknown:
        raise ValueError(f"pose map references unknown template components: {unknown!r}")
    unknown_required = tuple(sorted(set(policy.required_references) - template_references))
    if unknown_required:
        raise ValueError(f"probe policy requires unknown template components: {unknown_required!r}")
    missing_required = tuple(sorted(set(policy.required_references) - set(supplied_pose_by_ref)))
    if missing_required:
        raise ValueError(f"pose map is missing required references: {missing_required!r}")
    if not policy.allow_unchanged_non_target_references:
        missing = tuple(sorted(template_references - set(supplied_pose_by_ref)))
        if missing:
            raise ValueError(f"pose map must exactly cover template references: {missing!r}")

    candidate_pose_by_ref = dict(base_pose_by_ref)
    candidate_pose_by_ref.update(supplied_pose_by_ref)
    candidate_poses = tuple(
        candidate_pose_by_ref[reference] for reference in sorted(candidate_pose_by_ref)
    )
    placements = tuple(
        (component, candidate_pose_by_ref[component.reference].x_mm)
        for component, _x_mm in template.placements
    )
    part_y_mm = _updated_sparse_values(
        template.part_y_mm,
        template_reference_order,
        candidate_pose_by_ref,
        value=lambda pose: pose.y_mm,
        include=lambda value: value != template.parts_row_y_mm,
    )
    part_rotation = _updated_sparse_values(
        template.part_rotation,
        template_reference_order,
        candidate_pose_by_ref,
        value=lambda pose: pose.rotation_deg,
        include=lambda value: value != 0.0,
    )
    part_flip = _updated_flip_references(
        template.part_flip,
        template_reference_order,
        candidate_pose_by_ref,
    )
    targets = set(target_policy.target_net_names)
    segments = tuple(segment for segment in template.segments if segment.net_name not in targets)
    vias = tuple(via for via in template.vias if via.net_name not in targets)
    probe_layout = replace(
        template,
        placements=placements,
        part_y_mm=part_y_mm,
        part_rotation=part_rotation,
        part_flip=part_flip,
        segments=segments,
        vias=vias,
    )
    changed_fields = verify_probe_preservation(template, probe_layout)
    if any(
        original_component is not probe_component
        for (original_component, _old_x), (probe_component, _new_x) in zip(
            template.placements,
            probe_layout.placements,
            strict=True,
        )
    ):
        raise ValueError("probe must preserve exact BoardComponent objects")
    if tuple(component.reference for component, _x in probe_layout.placements) != (
        template_reference_order
    ):
        raise ValueError("probe must preserve template placement order")

    template_fingerprint = board_layout_fingerprint(template)
    probe_fingerprint = board_layout_fingerprint(probe_layout)
    pose_fingerprint = placement_pose_set_fingerprint(candidate_poses)
    supplied_references = tuple(sorted(supplied_pose_by_ref))
    preserved_references = tuple(sorted(template_references - set(supplied_references)))
    telemetry = PlacementProbeTelemetry(
        template_fingerprint=template_fingerprint,
        target_policy_fingerprint=target_policy.semantic_fingerprint(),
        probe_policy_fingerprint=policy.semantic_fingerprint(),
        budget_fingerprint=budget.semantic_fingerprint(),
        pose_fingerprint=pose_fingerprint,
        probe_layout_fingerprint=probe_fingerprint,
        template_reference_order=template_reference_order,
        explicit_pose_references=supplied_references,
        preserved_pose_references=preserved_references,
        changed_layout_fields=changed_fields,
        stripped_segment_count=len(template.segments) - len(segments),
        stripped_via_count=len(template.vias) - len(vias),
    )
    result = PlacementProbeResult(
        target_policy=target_policy,
        probe_policy=policy,
        budget=budget,
        poses=candidate_poses,
        telemetry=telemetry,
    )
    return PlacementProbe(layout=probe_layout, result=result)


def _template_poses(
    template: BoardLayout,
) -> tuple[tuple[str, ...], dict[str, ComponentPose]]:
    references = tuple(component.reference for component, _x_mm in template.placements)
    if not references:
        raise ValueError("placement template must contain at least one component")
    if len(set(references)) != len(references):
        raise ValueError("placement template references must be unique")
    if any(not reference or reference != reference.strip() for reference in references):
        raise ValueError("placement template references must be canonical and non-empty")
    reference_set = set(references)
    _validate_sparse_references(template.part_y_mm, reference_set, "part_y_mm")
    _validate_sparse_references(template.part_rotation, reference_set, "part_rotation")
    if len(set(template.part_flip)) != len(template.part_flip):
        raise ValueError("part_flip references must be unique")
    unknown_flips = tuple(sorted(set(template.part_flip) - reference_set))
    if unknown_flips:
        raise ValueError(f"part_flip references unknown template components: {unknown_flips!r}")
    flipped = set(template.part_flip)
    poses: dict[str, ComponentPose] = {}
    for component, x_mm in template.placements:
        poses[component.reference] = ComponentPose(
            reference=component.reference,
            x_mm=x_mm,
            y_mm=placement_y(template, component.reference),
            rotation_deg=placement_rotation(template, component.reference),
            side="back" if component.reference in flipped else "front",
        )
    return references, poses


def _validate_sparse_references(
    values: tuple[tuple[str, float], ...],
    template_references: set[str],
    field_name: str,
) -> None:
    references = tuple(reference for reference, _value in values)
    if len(set(references)) != len(references):
        raise ValueError(f"{field_name} references must be unique")
    unknown = tuple(sorted(set(references) - template_references))
    if unknown:
        raise ValueError(f"{field_name} references unknown template components: {unknown!r}")
    if any(not math.isfinite(value) for _reference, value in values):
        raise ValueError(f"{field_name} values must be finite")


def _canonical_supplied_poses(
    poses: Mapping[str, ComponentPose] | Iterable[ComponentPose],
) -> dict[str, ComponentPose]:
    if isinstance(poses, Mapping):
        items = tuple(poses.items())
        for key, pose in items:
            if not isinstance(pose, ComponentPose):
                raise TypeError("pose mapping values must be ComponentPose records")
            if key != pose.reference:
                raise ValueError("pose mapping keys must match pose references")
        pose_values = tuple(pose for _key, pose in items)
    else:
        pose_values = tuple(poses)
        if any(not isinstance(pose, ComponentPose) for pose in pose_values):
            raise TypeError("pose iterable values must be ComponentPose records")
    references = tuple(pose.reference for pose in pose_values)
    if len(set(references)) != len(references):
        raise ValueError("supplied pose references must be unique")
    return {pose.reference: pose for pose in sorted(pose_values, key=lambda item: item.reference)}


def _updated_sparse_values(
    original: tuple[tuple[str, float], ...],
    reference_order: tuple[str, ...],
    pose_by_ref: Mapping[str, ComponentPose],
    *,
    value: Callable[[ComponentPose], float],
    include: Callable[[float], bool],
) -> tuple[tuple[str, float], ...]:
    original_references = {reference for reference, _old_value in original}
    retained = tuple(
        (reference, float(value(pose_by_ref[reference]))) for reference, _old_value in original
    )
    added = tuple(
        (reference, float(value(pose_by_ref[reference])))
        for reference in reference_order
        if reference not in original_references and include(value(pose_by_ref[reference]))
    )
    return (*retained, *added)


def _updated_flip_references(
    original: tuple[str, ...],
    reference_order: tuple[str, ...],
    pose_by_ref: Mapping[str, ComponentPose],
) -> tuple[str, ...]:
    original_set = set(original)
    retained = tuple(reference for reference in original if pose_by_ref[reference].side == "back")
    added = tuple(
        reference
        for reference in reference_order
        if reference not in original_set and pose_by_ref[reference].side == "back"
    )
    return (*retained, *added)


@dataclass(frozen=True)
class _PlacedRegion:
    reference: str
    region_id: str
    purpose: Literal["body", "courtyard"]
    occupied_sides: frozenset[str]
    compound: ExactPlanarCompound
    verification: PlacementRegionVerification
    maximum_error_mm: float
    transform_error_mm: float


def board_component_identity_fingerprint(component: BoardComponent) -> str:
    """Fingerprint every semantic BoardComponent field used by a catalog binding."""

    return hashlib.sha256(
        _canonical_json(
            {
                "schema_id": "pcbsmith-placement-component-identity",
                "schema_version": 1,
                "component": _canonical_payload(component),
            }
        ).encode("utf-8")
    ).hexdigest()


def bind_component_placement_geometry(
    component: BoardComponent,
    *,
    regions: Collection[FootprintPlacementRegion],
) -> ComponentPlacementGeometry:
    """Bind typed local regions to an exact immutable template component."""

    return ComponentPlacementGeometry(
        reference=component.reference,
        footprint=component.footprint,
        component_identity_fingerprint=board_component_identity_fingerprint(component),
        regions=tuple(regions),
    )


def build_placement_geometry_catalog(
    template: BoardLayout,
    components: Collection[ComponentPlacementGeometry],
) -> PlacementGeometryCatalog:
    """Build a complete/fresh catalog; legacy footprint hulls are never consulted."""

    catalog = PlacementGeometryCatalog(
        template_fingerprint=board_layout_fingerprint(template),
        components=tuple(components),
    )
    _verify_geometry_catalog(template, catalog, catalog.template_fingerprint)
    return catalog


def _verify_geometry_catalog(
    layout: BoardLayout,
    catalog: PlacementGeometryCatalog,
    expected_template_fingerprint: str,
) -> None:
    if catalog.template_fingerprint != expected_template_fingerprint:
        raise ValueError("placement geometry catalog is bound to a different template")
    component_by_ref = {component.reference: component for component, _x_mm in layout.placements}
    geometry_by_ref = {component.reference: component for component in catalog.components}
    missing = tuple(sorted(set(component_by_ref) - set(geometry_by_ref)))
    extra = tuple(sorted(set(geometry_by_ref) - set(component_by_ref)))
    if missing or extra:
        raise ValueError(
            "placement geometry catalog is incomplete or foreign: "
            f"missing={missing!r}, extra={extra!r}"
        )
    for reference, component in component_by_ref.items():
        geometry = geometry_by_ref[reference]
        if geometry.footprint != component.footprint:
            raise ValueError(f"placement geometry footprint is stale for {reference}")
        expected = board_component_identity_fingerprint(component)
        if geometry.component_identity_fingerprint != expected:
            raise ValueError(f"placement geometry component identity is stale for {reference}")


def _legalization_input_fingerprint(
    probe: PlacementProbe,
    catalog: PlacementGeometryCatalog,
    policy: PlacementLegalizationPolicy,
    consumed_before: int,
) -> str:
    payload = {
        "schema_id": "pcbsmith-placement-legalization-input",
        "schema_version": 1,
        "probe_result_fingerprint": probe.result.semantic_fingerprint(),
        "probe_layout_fingerprint": board_layout_fingerprint(probe.layout),
        "catalog_fingerprint": catalog.semantic_fingerprint(),
        "policy_fingerprint": policy.semantic_fingerprint(),
        "legalization_evaluations_consumed_before": consumed_before,
    }
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _place_region(
    region: FootprintPlacementRegion,
    pose: ComponentPose,
) -> _PlacedRegion | None:
    if region.verification is PlacementRegionVerification.UNSUPPORTED:
        return None
    if region.local_compound is None:
        raise ValueError("supported placement region lost local geometry")
    placed_transform = transform_compound_bounded(
        region.local_compound,
        PlacementTransform(
            anchor_x_mm=pose.x_mm,
            anchor_y_mm=pose.y_mm,
            rotation_deg=pose.rotation_deg,
            side=pose.side,
        ),
    )
    source_error = region.maximum_error_mm or 0.0
    transform_error = placed_transform.maximum_error_mm or 0.0
    verification = (
        PlacementRegionVerification.BOUNDED_APPROXIMATION
        if region.verification is PlacementRegionVerification.BOUNDED_APPROXIMATION
        or placed_transform.authority is PlacementTransformAuthority.BOUNDED_APPROXIMATION
        else PlacementRegionVerification.EXACT
    )
    error_terms = tuple(value for value in (source_error, transform_error) if value > 0)
    maximum_error = sum(error_terms)
    if len(error_terms) > 1:
        maximum_error = math.nextafter(maximum_error, math.inf)
    occupied_sides = (
        frozenset(("front", "back"))
        if region.occupancy_span is PlacementOccupancySpan.BOTH
        else frozenset((pose.side,))
    )
    return _PlacedRegion(
        reference=pose.reference,
        region_id=region.region_id,
        purpose=region.purpose,
        occupied_sides=occupied_sides,
        compound=placed_transform.compound,
        verification=verification,
        maximum_error_mm=maximum_error,
        transform_error_mm=transform_error,
    )


def _finding(
    kind: PlacementLegalizationFindingKind,
    disposition: PlacementFindingDisposition,
    references: tuple[str, ...],
    *,
    rule_id: str,
    region_ids: tuple[str, ...] = (),
    verification: PlacementRegionVerification | None = None,
    required_clearance_mm: float | None = None,
    diagnostic_clearance_mm: float | None = None,
) -> PlacementLegalizationFinding:
    return PlacementLegalizationFinding(
        kind=kind,
        disposition=disposition,
        references=references,
        region_ids=region_ids,
        rule_id=rule_id,
        verification=verification,
        required_clearance_mm=required_clearance_mm,
        diagnostic_clearance_mm=diagnostic_clearance_mm,
    )


_RAW_GRAPHIC_LAYER = re.compile(r'\(layer\s+"?([^"\s()]+)', re.IGNORECASE)


def _raw_graphic_boundary_unverified(graphic: str) -> bool:
    """Fail closed unless every raw graphic declares a non-Edge.Cuts layer."""

    layers = tuple(match.group(1).lower() for match in _RAW_GRAPHIC_LAYER.finditer(graphic))
    return not layers or "edge.cuts" in layers


def legalize_placement_probe(
    probe: PlacementProbe,
    catalog: PlacementGeometryCatalog,
    policy: PlacementLegalizationPolicy,
    *,
    legalization_evaluations_consumed: int = 0,
) -> PlacementLegalizationResult:
    """Evaluate one probe exactly once, returning every deterministic finding."""

    # A read-only seam still runs the reflected-field authority check.  A future
    # BoardLayout field therefore fails closed until explicitly classified.
    verify_probe_preservation(probe.layout, probe.layout)
    _verify_geometry_catalog(
        probe.layout,
        catalog,
        probe.result.telemetry.template_fingerprint,
    )
    references = set(probe.result.telemetry.template_reference_order)
    policy_references = {item.reference for item in policy.side_permissions} | {
        item.reference for item in policy.edge_exceptions
    }
    unknown_policy_references = tuple(sorted(policy_references - references))
    if unknown_policy_references:
        raise ValueError(
            "placement legalization policy references unknown components: "
            f"{unknown_policy_references!r}"
        )
    if isinstance(legalization_evaluations_consumed, bool):
        raise TypeError("legalization_evaluations_consumed must be an integer")
    limit = probe.result.budget.max_legalization_evaluations
    if legalization_evaluations_consumed < 0 or legalization_evaluations_consumed > limit:
        raise ValueError("legalization_evaluations_consumed is outside the fixed budget")
    input_fingerprint = _legalization_input_fingerprint(
        probe,
        catalog,
        policy,
        legalization_evaluations_consumed,
    )
    if legalization_evaluations_consumed == limit:
        budget_findings = (
            _finding(
                PlacementLegalizationFindingKind.LEGALIZATION_BUDGET,
                PlacementFindingDisposition.NOT_EVALUATED,
                tuple(sorted(references)),
                rule_id="r5.legalization.budget",
            ),
        )
        telemetry = _legalization_telemetry(
            probe,
            catalog,
            policy,
            input_fingerprint,
            budget_findings,
            transform_verification=PlacementRegionVerification.UNSUPPORTED,
            effective_geometry_verification=PlacementRegionVerification.UNSUPPORTED,
            maximum_transform_error_mm=None,
            maximum_effective_error_mm=None,
            consumed_before=legalization_evaluations_consumed,
            consumed_after=legalization_evaluations_consumed,
        )
        return PlacementLegalizationResult(
            outcome=PlacementLegalizationOutcome.BUDGET_EXHAUSTED,
            findings=budget_findings,
            telemetry=telemetry,
        )

    pose_by_ref = {pose.reference: pose for pose in probe.result.poses}
    geometry_by_ref = {component.reference: component for component in catalog.components}
    side_permission_by_ref = {item.reference: item for item in policy.side_permissions}
    exception_by_ref = {item.reference: item for item in policy.edge_exceptions}
    probe_layout_snapshot_fingerprint = board_layout_snapshot_fingerprint(
        canonical_board_layout_snapshot_json(probe.layout)
    )
    findings_list: list[PlacementLegalizationFinding] = []
    raw_edge_cuts_unverified = any(
        _raw_graphic_boundary_unverified(graphic) for graphic in probe.layout.graphics
    )
    if raw_edge_cuts_unverified:
        findings_list.append(
            _finding(
                PlacementLegalizationFindingKind.BOARD_GEOMETRY_UNSUPPORTED,
                PlacementFindingDisposition.UNVERIFIED,
                tuple(sorted(references)),
                rule_id="r5.board.raw_edge_cuts",
                verification=PlacementRegionVerification.UNSUPPORTED,
            )
        )
    placed_regions: list[_PlacedRegion] = []
    bounded_transform_seen = False
    maximum_transform_error = 0.0
    applied_exception_rule_ids: set[str] = set()

    for reference in sorted(references):
        pose = pose_by_ref[reference]
        permission = side_permission_by_ref.get(reference)
        if permission is not None and pose.side not in permission.allowed_sides:
            findings_list.append(
                _finding(
                    PlacementLegalizationFindingKind.POLICY_SIDE,
                    PlacementFindingDisposition.VIOLATION,
                    (reference,),
                    rule_id="r5.policy.side",
                )
            )
        for region in geometry_by_ref[reference].regions:
            if region.verification is PlacementRegionVerification.UNSUPPORTED:
                findings_list.append(
                    _finding(
                        PlacementLegalizationFindingKind.REGION_UNSUPPORTED,
                        PlacementFindingDisposition.UNVERIFIED,
                        (reference,),
                        rule_id=f"r5.region.unsupported.{region.purpose}",
                        region_ids=(region.region_id,),
                        verification=PlacementRegionVerification.UNSUPPORTED,
                    )
                )
                continue
            if region.local_compound is None:
                raise ValueError("supported region lost geometry after IR validation")
            placed = _place_region(region, pose)
            if placed is None:
                raise ValueError("supported placement region unexpectedly failed placement")
            if placed.transform_error_mm > 0:
                bounded_transform_seen = True
                maximum_transform_error = max(
                    maximum_transform_error,
                    placed.transform_error_mm,
                )
            placed_regions.append(placed)

    bodies = tuple(region for region in placed_regions if region.purpose == "body")
    courtyards = tuple(region for region in placed_regions if region.purpose == "courtyard")
    for first, second in combinations(bodies, 2):
        if first.occupied_sides.isdisjoint(second.occupied_sides):
            continue
        _append_pair_finding(
            findings_list,
            first,
            second,
            policy.minimum_body_spacing_mm,
            PlacementLegalizationFindingKind.BODY_COLLISION,
            "r5.body.spacing",
        )
    for first, second in combinations(courtyards, 2):
        if first.occupied_sides.isdisjoint(second.occupied_sides):
            continue
        _append_pair_finding(
            findings_list,
            first,
            second,
            policy.minimum_courtyard_spacing_mm,
            PlacementLegalizationFindingKind.COURTYARD_COLLISION,
            "r5.courtyard.spacing",
        )

    outer = ExactPlanarPolygon(
        outer=probe.layout.outline
        or (
            (0.0, 0.0),
            (probe.layout.width_mm, 0.0),
            (probe.layout.width_mm, probe.layout.height_mm),
            (0.0, probe.layout.height_mm),
        )
    )
    outer_boundary = ExactPlanarCompound(polygons=(ExactPlanarPolygon(outer=outer.outer),))
    cutouts = tuple(
        (
            cutout.semantic_fingerprint(),
            ExactPlanarCompound(polygons=(ExactPlanarPolygon(outer=cutout.points),)),
        )
        for cutout in probe.layout.cutouts
    )
    for body in bodies:
        exception = exception_by_ref.get(body.reference)
        required_outer = policy.minimum_body_outer_edge_clearance_mm
        waive_containment = False
        rule_id = "r5.body.outer_edge"
        if exception is not None:
            authority = exception.interface_authority
            authority_matches = (
                authority is not None
                and authority.declaration.board_layout_snapshot_fingerprint
                == probe_layout_snapshot_fingerprint
            )
            if authority_matches:
                required_outer = exception.minimum_outer_edge_clearance_mm
                waive_containment = exception.waive_outer_edge_containment
                rule_id = exception.rule_id
                applied_exception_rule_ids.add(exception.rule_id)
            else:
                findings_list.append(
                    _finding(
                        PlacementLegalizationFindingKind.EDGE_INTERFACE_AUTHORITY,
                        PlacementFindingDisposition.VIOLATION,
                        (body.reference,),
                        rule_id="r5.edge_interface.authority_context",
                        region_ids=(body.region_id,),
                        verification=body.verification,
                    )
                )
        required_with_error = required_outer + body.maximum_error_mm
        contained = compound_inside_polygon(body.compound, outer)
        exception_scope_ok = (
            waive_containment
            and compound_relation(body.compound, outer_boundary) is not PlanarRelation.DISJOINT
        )
        clearance_ok = _boundary_clearance_at_least(
            body.compound,
            outer_boundary,
            required_with_error,
        )
        if (not contained and not exception_scope_ok) or not clearance_ok:
            findings_list.append(
                _finding(
                    PlacementLegalizationFindingKind.OUTER_EDGE_VIOLATION,
                    _region_failure_disposition(body),
                    (body.reference,),
                    rule_id=rule_id,
                    region_ids=(body.region_id,),
                    verification=body.verification,
                    required_clearance_mm=required_with_error,
                    diagnostic_clearance_mm=diagnostic_distance_mm(
                        compound_boundary_minimum_squared_distance(body.compound, outer_boundary)
                    ),
                )
            )
        for cutout_fingerprint, cutout in cutouts:
            required_cutout = policy.minimum_body_cutout_clearance_mm + body.maximum_error_mm
            relation = compound_relation(body.compound, cutout)
            clearance_ok = compound_clearance_at_least(
                body.compound,
                cutout,
                required_cutout,
            )
            if relation is PlanarRelation.INTERIOR_OVERLAP or not clearance_ok:
                findings_list.append(
                    _finding(
                        PlacementLegalizationFindingKind.CUTOUT_VIOLATION,
                        _region_failure_disposition(body),
                        (body.reference,),
                        rule_id=f"r5.body.cutout.{cutout_fingerprint}",
                        region_ids=(body.region_id,),
                        verification=body.verification,
                        required_clearance_mm=required_cutout,
                        diagnostic_clearance_mm=diagnostic_distance_mm(
                            compound_minimum_squared_distance(body.compound, cutout)
                        ),
                    )
                )

    if policy.require_courtyard_containment:
        for courtyard in courtyards:
            exception = exception_by_ref.get(courtyard.reference)
            authority = exception.interface_authority if exception is not None else None
            courtyard_waived = (
                exception is not None
                and exception.waive_courtyard_outer_edge_containment
                and authority is not None
                and authority.declaration.board_layout_snapshot_fingerprint
                == probe_layout_snapshot_fingerprint
            )
            if courtyard_waived:
                continue
            required = policy.minimum_courtyard_outer_edge_clearance_mm + courtyard.maximum_error_mm
            contained = compound_inside_polygon(courtyard.compound, outer)
            clearance_ok = _boundary_clearance_at_least(
                courtyard.compound,
                outer_boundary,
                required,
            )
            if not contained or not clearance_ok:
                findings_list.append(
                    _finding(
                        PlacementLegalizationFindingKind.COURTYARD_CONTAINMENT,
                        _region_failure_disposition(courtyard),
                        (courtyard.reference,),
                        rule_id="r5.courtyard.outer_edge",
                        region_ids=(courtyard.region_id,),
                        verification=courtyard.verification,
                        required_clearance_mm=required,
                        diagnostic_clearance_mm=diagnostic_distance_mm(
                            compound_boundary_minimum_squared_distance(
                                courtyard.compound,
                                outer_boundary,
                            )
                        ),
                    )
                )

    findings = tuple(findings_list)
    source_verifications = {
        region.verification for component in catalog.components for region in component.regions
    }
    transform_verification = (
        PlacementRegionVerification.BOUNDED_APPROXIMATION
        if bounded_transform_seen
        else PlacementRegionVerification.EXACT
    )
    if PlacementRegionVerification.UNSUPPORTED in source_verifications or raw_edge_cuts_unverified:
        effective_verification = PlacementRegionVerification.UNSUPPORTED
        maximum_effective_error = None
    elif (
        PlacementRegionVerification.BOUNDED_APPROXIMATION in source_verifications
        or transform_verification is PlacementRegionVerification.BOUNDED_APPROXIMATION
    ):
        effective_verification = PlacementRegionVerification.BOUNDED_APPROXIMATION
        maximum_effective_error = max(
            (region.maximum_error_mm for region in placed_regions),
            default=0.0,
        )
    else:
        effective_verification = PlacementRegionVerification.EXACT
        maximum_effective_error = None
    dispositions = {finding.disposition for finding in findings}
    if PlacementFindingDisposition.VIOLATION in dispositions:
        outcome = PlacementLegalizationOutcome.REJECTED
    elif PlacementFindingDisposition.UNVERIFIED in dispositions:
        outcome = PlacementLegalizationOutcome.UNVERIFIED
    elif effective_verification is PlacementRegionVerification.BOUNDED_APPROXIMATION:
        outcome = PlacementLegalizationOutcome.LEGAL_BOUNDED
    else:
        outcome = PlacementLegalizationOutcome.LEGAL_EXACT
    telemetry = _legalization_telemetry(
        probe,
        catalog,
        policy,
        input_fingerprint,
        findings,
        transform_verification=transform_verification,
        effective_geometry_verification=effective_verification,
        maximum_transform_error_mm=maximum_transform_error
        if transform_verification is PlacementRegionVerification.BOUNDED_APPROXIMATION
        else None,
        maximum_effective_error_mm=maximum_effective_error,
        consumed_before=legalization_evaluations_consumed,
        consumed_after=legalization_evaluations_consumed + 1,
    )
    return PlacementLegalizationResult(
        outcome=outcome,
        findings=findings,
        applied_edge_exception_rule_ids=tuple(applied_exception_rule_ids),
        telemetry=telemetry,
    )


def _region_failure_disposition(
    *regions: _PlacedRegion,
) -> PlacementFindingDisposition:
    return (
        PlacementFindingDisposition.UNVERIFIED
        if any(
            region.verification is PlacementRegionVerification.BOUNDED_APPROXIMATION
            for region in regions
        )
        else PlacementFindingDisposition.VIOLATION
    )


def _append_pair_finding(
    findings: list[PlacementLegalizationFinding],
    first: _PlacedRegion,
    second: _PlacedRegion,
    policy_clearance_mm: float,
    kind: PlacementLegalizationFindingKind,
    rule_id: str,
) -> None:
    required = policy_clearance_mm + first.maximum_error_mm + second.maximum_error_mm
    relation = compound_relation(first.compound, second.compound)
    clearance_ok = compound_clearance_at_least(first.compound, second.compound, required)
    if relation is PlanarRelation.INTERIOR_OVERLAP or not clearance_ok:
        verification = (
            PlacementRegionVerification.BOUNDED_APPROXIMATION
            if PlacementRegionVerification.BOUNDED_APPROXIMATION
            in {first.verification, second.verification}
            else PlacementRegionVerification.EXACT
        )
        findings.append(
            _finding(
                kind,
                _region_failure_disposition(first, second),
                (first.reference, second.reference),
                rule_id=rule_id,
                region_ids=(first.region_id, second.region_id),
                verification=verification,
                required_clearance_mm=required,
                diagnostic_clearance_mm=diagnostic_distance_mm(
                    compound_minimum_squared_distance(first.compound, second.compound)
                ),
            )
        )


def _boundary_clearance_at_least(
    compound: ExactPlanarCompound,
    boundary: ExactPlanarCompound,
    clearance_mm: float,
) -> bool:
    """Exact rational squared comparison against a boundary-only distance."""

    if not math.isfinite(clearance_mm) or clearance_mm < 0:
        raise ValueError("clearance_mm must be finite and non-negative")
    from fractions import Fraction

    required = Fraction(str(clearance_mm))
    return compound_boundary_minimum_squared_distance(compound, boundary) >= required * required


def _legalization_telemetry(
    probe: PlacementProbe,
    catalog: PlacementGeometryCatalog,
    policy: PlacementLegalizationPolicy,
    input_fingerprint: str,
    findings: tuple[PlacementLegalizationFinding, ...],
    *,
    transform_verification: PlacementRegionVerification,
    effective_geometry_verification: PlacementRegionVerification,
    maximum_transform_error_mm: float | None,
    maximum_effective_error_mm: float | None,
    consumed_before: int,
    consumed_after: int,
) -> PlacementLegalizationTelemetry:
    limit = probe.result.budget.max_legalization_evaluations
    return PlacementLegalizationTelemetry(
        template_fingerprint=probe.result.telemetry.template_fingerprint,
        probe_layout_fingerprint=probe.result.telemetry.probe_layout_fingerprint,
        pose_fingerprint=probe.result.telemetry.pose_fingerprint,
        catalog_fingerprint=catalog.semantic_fingerprint(),
        policy_fingerprint=policy.semantic_fingerprint(),
        budget_fingerprint=probe.result.budget.semantic_fingerprint(),
        input_fingerprint=input_fingerprint,
        findings_fingerprint=placement_findings_fingerprint(findings),
        transform_verification=transform_verification,
        effective_geometry_verification=effective_geometry_verification,
        maximum_transform_error_mm=maximum_transform_error_mm,
        maximum_effective_error_mm=maximum_effective_error_mm,
        legalization_evaluations_limit=limit,
        legalization_evaluations_consumed_before=consumed_before,
        legalization_evaluations_consumed_after=consumed_after,
        legalization_evaluations_remaining=limit - consumed_after,
    )
