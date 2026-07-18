"""Source-bound R17/D17 thermometer PWLED micro-pilot input authority.

This module deliberately stops before candidate evaluation, routing, or exact
acceptance.  It uses two real components and one real net from the production
thermometer declarations while retaining literal exclusions that prevent the
slice from being mistaken for the complete board.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Literal, Self, TypeAlias

from pydantic import Field, field_validator, model_validator

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.corridor_ir import CorridorBudget, CorridorCostPolicy, CorridorViaPolicy
from pcbsmith.generation.thermometer import compose_thermometer
from pcbsmith.kicad.board import BoardComponent, BoardLayout, BoardNet, BoardNetlist
from pcbsmith.kicad.corridor_planner import CorridorGraphBuildBudget, OpaqueGraphicsPolicy
from pcbsmith.kicad.export_thermometer import INSTANCES
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.library import VENDORED_DIR, QuotedString, SList, parse_sexpr
from pcbsmith.kicad.negotiated_graph import NegotiatedCostPolicy
from pcbsmith.kicad.placement_routability import (
    bind_component_placement_geometry,
    build_placement_geometry_catalog,
)
from pcbsmith.kicad.thermometer_board import FLIPPED_REFS, PLACEMENTS, thermometer_outline
from pcbsmith.placement_candidate_ir import PlacementMovePolicy
from pcbsmith.placement_detail_ir import (
    PlacementDetailBudget,
    PlacementDetailSelectionPolicy,
    PlacementR2Policy,
)
from pcbsmith.placement_exact_ir import PlacementExactBudget, PlacementExactPolicy
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon
from pcbsmith.placement_ir import (
    ComponentPose,
    FootprintPlacementRegion,
    PlacementBudget,
    PlacementGeometryCatalog,
    PlacementIrModel,
    PlacementLegalizationPolicy,
    PlacementOccupancySpan,
    PlacementRegionVerification,
    PlacementSidePermission,
)
from pcbsmith.placement_pilot_authority import (
    PlacementPilotAuthority,
    PlacementPilotCorridorDemandPolicy,
    build_placement_pilot_authority,
)
from pcbsmith.placement_surrogate_ir import PlacementSurrogatePolicy
from pcbsmith.routing_ir import RoutingBudget
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

THERMOMETER_REQUEST = "thermometer temperature humidity display pcb"
MICRO_REFERENCES = ("D17", "R17")
TARGET_NETS = ("/PWLED",)
TRACK_WIDTH_MM = 0.25
TRANSLATION_STEP_MM = 0.5
COARSE_GRID_MM = 1.0
DETAILED_GRID_MM = 0.5
CAPACITY_QUANTUM_MM = 0.25

MICRO_SCOPE: Literal["real_thermometer_r17_d17_pwled_input_slice_only"] = (
    "real_thermometer_r17_d17_pwled_input_slice_only"
)
MICRO_EXCLUDED_CLAIMS = (
    "not_64_part_thermometer_board",
    "not_full_template_preservation",
    "not_full_neighbor_preservation",
    "not_circuit_equivalence",
    "not_circuit_readiness",
    "not_layout_superiority",
    "not_routing",
    "not_exact_acceptance",
)
CROP_ORIGIN_MM = (28.0, 144.0)
CROP_SIZE_MM = (10.0, 6.0)
CROP_TRANSLATION: Literal["absolute_xy_minus_crop_origin_to_local_xy"] = (
    "absolute_xy_minus_crop_origin_to_local_xy"
)

_FOOTPRINT_SOURCE: dict[str, tuple[str, str, str]] = {
    "Resistor_SMD:R_0603_1608Metric": (
        "ai_assets/kicad_footprints/Resistor_SMD__R_0603_1608Metric.kicad_mod",
        "7190ac4a00125b807e54129ef0d87d87f2a658eeb74d025a7028203419b09f23",
        "03fc7902b2661df01b4d828fdb6eab9eddf974e7130ed2b98892607387a50c4b",
    ),
    "LED_SMD:LED_0805_2012Metric": (
        "ai_assets/kicad_footprints/LED_SMD__LED_0805_2012Metric.kicad_mod",
        "8806125556e590701b13b47a1725dff28fc47fca41a7905c7d78c8312d08cbbd",
        "ce3a8266ee445b343374e2391b3b931a2bbc27f83d4f06af397cbea91df53178",
    ),
}
_REFERENCE_FOOTPRINT = {
    "D17": "LED_SMD:LED_0805_2012Metric",
    "R17": "Resistor_SMD:R_0603_1608Metric",
}

Point: TypeAlias = tuple[float, float]


def _json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _atom(value: object) -> str:
    if isinstance(value, QuotedString):
        return value.value
    if isinstance(value, str):
        return value
    raise ValueError("expected an atomic KiCad s-expression value")


def _head(node: SList) -> str:
    if not node:
        return ""
    return _atom(node[0])


def _children(node: SList, name: str) -> tuple[SList, ...]:
    return tuple(child for child in node if isinstance(child, list) and _head(child) == name)


def _layer(shape: SList) -> str:
    layers = _children(shape, "layer")
    if len(layers) != 1 or len(layers[0]) != 2:
        raise ValueError("footprint geometry shape requires exactly one layer")
    return _atom(layers[0][1])


def _point_clause(shape: SList, name: str) -> Point:
    clauses = _children(shape, name)
    if len(clauses) != 1 or len(clauses[0]) != 3:
        raise ValueError(f"footprint geometry requires one {name} point")
    try:
        return (float(_atom(clauses[0][1])), float(_atom(clauses[0][2])))
    except ValueError as error:
        raise ValueError(f"footprint geometry has a non-numeric {name} point") from error


def _rect_polygon(shape: SList, *, layer: str) -> ExactPlanarCompound:
    first = _point_clause(shape, "start")
    second = _point_clause(shape, "end")
    if first[0] == second[0] or first[1] == second[1]:
        raise ValueError(f"{layer} rectangle has zero area")
    x1, x2 = sorted((first[0], second[0]))
    y1, y2 = sorted((first[1], second[1]))
    return ExactPlanarCompound(
        polygons=(ExactPlanarPolygon(outer=((x1, y1), (x2, y1), (x2, y2), (x1, y2))),)
    )


def _closed_line_polygon(lines: tuple[SList, ...], *, layer: str) -> ExactPlanarCompound:
    if len(lines) < 3:
        raise ValueError(f"{layer} line body is open or incomplete")
    adjacency: dict[Point, set[Point]] = defaultdict(set)
    edges: set[frozenset[Point]] = set()
    for line in lines:
        start = _point_clause(line, "start")
        end = _point_clause(line, "end")
        if start == end:
            raise ValueError(f"{layer} line body contains a zero-length edge")
        edge = frozenset((start, end))
        if edge in edges:
            raise ValueError(f"{layer} line body contains a duplicate edge")
        edges.add(edge)
        adjacency[start].add(end)
        adjacency[end].add(start)
    if any(len(neighbours) != 2 for neighbours in adjacency.values()):
        raise ValueError(f"{layer} line body must be one closed, unbranched polygon")
    start = min(adjacency)
    previous: Point | None = None
    current = start
    ordered: list[Point] = []
    consumed: set[frozenset[Point]] = set()
    while True:
        ordered.append(current)
        candidates = sorted(adjacency[current])
        next_point = candidates[0] if candidates[0] != previous else candidates[1]
        edge = frozenset((current, next_point))
        if edge in consumed:
            if next_point == start and len(consumed) == len(edges):
                break
            raise ValueError(f"{layer} contains multiple or self-repeating contours")
        consumed.add(edge)
        previous, current = current, next_point
        if current == start:
            if len(consumed) != len(edges):
                raise ValueError(f"{layer} contains multiple closed contours")
            break
    if len(ordered) != len(adjacency):
        raise ValueError(f"{layer} line body did not consume one exact contour")
    return ExactPlanarCompound(polygons=(ExactPlanarPolygon(outer=tuple(ordered)),))


def _parse_exact_layer(tree: SList, layer: str) -> ExactPlanarCompound:
    geometric_names = {"fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly", "fp_curve"}
    relevant = tuple(
        child
        for child in tree
        if isinstance(child, list) and _head(child) in geometric_names and _layer(child) == layer
    )
    if not relevant:
        raise ValueError(f"{layer} has no exact closed geometry")
    unsupported = tuple(
        _head(item) for item in relevant if _head(item) not in {"fp_line", "fp_rect"}
    )
    if unsupported:
        raise ValueError(f"{layer} uses unsupported geometry: {unsupported!r}")
    rectangles = tuple(item for item in relevant if _head(item) == "fp_rect")
    lines = tuple(item for item in relevant if _head(item) == "fp_line")
    if rectangles:
        if len(rectangles) != 1 or lines:
            raise ValueError(f"{layer} must contain exactly one relevant closed shape")
        return _rect_polygon(rectangles[0], layer=layer)
    return _closed_line_polygon(lines, layer=layer)


def parse_exact_placement_footprint_source(
    source_text: str,
    footprint_id: str,
) -> tuple[ExactPlanarCompound, ExactPlanarCompound]:
    """Parse one supported, lossless fab body and courtyard or fail closed."""

    if footprint_id not in _FOOTPRINT_SOURCE:
        raise ValueError(f"unsupported micro-pilot footprint {footprint_id!r}")
    tree = parse_sexpr(source_text)
    if _head(tree) != "footprint" or len(tree) < 2:
        raise ValueError("source must contain exactly one KiCad footprint")
    expected_name = footprint_id.split(":", 1)[1]
    if _atom(tree[1]) != expected_name:
        raise ValueError("footprint source name does not match its declared identity")
    body = _parse_exact_layer(tree, "F.Fab")
    courtyard = _parse_exact_layer(tree, "F.CrtYd")
    return body, courtyard


def _region_source_fingerprint(
    source_sha256: str,
    purpose: Literal["body", "courtyard"],
    compound: ExactPlanarCompound,
) -> str:
    return _sha_text(
        _json(
            {
                "schema_id": "pcbsmith-exact-vendored-footprint-region-source",
                "schema_version": 1,
                "source_text_sha256": source_sha256,
                "purpose": purpose,
                "compound_fingerprint": compound.semantic_fingerprint(),
            }
        )
    )


class ThermometerMicroFootprintSource(PlacementIrModel):
    """Retained exact vendored source and its replayed lossless regions."""

    schema_id: Literal["pcbsmith-thermometer-micro-footprint-source"] = (
        "pcbsmith-thermometer-micro-footprint-source"
    )
    schema_version: Literal[1] = 1
    reference: str
    footprint_id: str
    vendored_relative_path: str
    source_text: str = Field(min_length=1)
    source_text_sha256: str
    upstream_kicad10_source_sha256: str
    body: ExactPlanarCompound
    courtyard: ExactPlanarCompound

    @field_validator("source_text_sha256", "upstream_kicad10_source_sha256")
    @classmethod
    def digest_is_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("source_text_sha256 must be a lowercase SHA-256 digest")
        return value

    @model_validator(mode="after")
    def source_is_pinned_and_replayable(self) -> Self:
        expected_footprint = _REFERENCE_FOOTPRINT.get(self.reference)
        if expected_footprint is None or self.footprint_id != expected_footprint:
            raise ValueError("micro footprint source has a foreign reference or footprint")
        expected_path, expected_sha, expected_upstream_sha = _FOOTPRINT_SOURCE[self.footprint_id]
        if self.vendored_relative_path != expected_path:
            raise ValueError("micro footprint source is not bound to the vendored path")
        actual_sha = _sha_text(self.source_text)
        if self.source_text_sha256 != actual_sha:
            raise ValueError("retained footprint source text hash is stale")
        if actual_sha != expected_sha:
            raise ValueError("retained footprint source is not the pinned normalized KiCad 10 file")
        if self.upstream_kicad10_source_sha256 != expected_upstream_sha:
            raise ValueError("upstream KiCad 10 footprint source hash changed")
        body, courtyard = parse_exact_placement_footprint_source(
            self.source_text, self.footprint_id
        )
        if self.body != body or self.courtyard != courtyard:
            raise ValueError("retained footprint geometry does not replay from source")
        return self

    def region_source_fingerprint(self, purpose: Literal["body", "courtyard"]) -> str:
        compound = self.body if purpose == "body" else self.courtyard
        return _region_source_fingerprint(self.source_text_sha256, purpose, compound)


def _read_exact_vendored_source(reference: str) -> ThermometerMicroFootprintSource:
    footprint_id = _REFERENCE_FOOTPRINT[reference]
    relative_path, _expected_sha, upstream_sha = _FOOTPRINT_SOURCE[footprint_id]
    path = VENDORED_DIR / Path(relative_path).name
    if not path.is_file():
        raise ValueError(f"required exact vendored footprint is missing: {relative_path}")
    # Universal-newline reading matches the repository's explicit LF policy;
    # the original installed-file byte hash is retained separately.
    source_text = path.read_text(encoding="utf-8")
    body, courtyard = parse_exact_placement_footprint_source(source_text, footprint_id)
    return ThermometerMicroFootprintSource(
        reference=reference,
        footprint_id=footprint_id,
        vendored_relative_path=relative_path,
        source_text=source_text,
        source_text_sha256=_sha_text(source_text),
        upstream_kicad10_source_sha256=upstream_sha,
        body=body,
        courtyard=courtyard,
    )


def _source_absolute_poses() -> tuple[ComponentPose, ...]:
    return tuple(
        ComponentPose(
            reference=reference,
            x_mm=PLACEMENTS[reference][0],
            y_mm=PLACEMENTS[reference][1],
            rotation_deg=PLACEMENTS[reference][2],
            side="back" if reference in FLIPPED_REFS else "front",
        )
        for reference in MICRO_REFERENCES
    )


def _full_outline_fingerprint() -> str:
    return _sha_text(
        _json(
            {
                "schema_id": "pcbsmith-thermometer-full-outline",
                "schema_version": 1,
                "points_mm": thermometer_outline(),
            }
        )
    )


def build_thermometer_pwled_micro_board() -> tuple[BoardNetlist, BoardLayout]:
    """Build the honest translated R17/D17, /PWLED routing crop."""

    intent = classify_circuit_intent(THERMOMETER_REQUEST)
    circuit = compose_thermometer(intent, select_topology(intent))
    by_reference = {component.reference: component for component in circuit.components}
    components = tuple(
        BoardComponent(
            reference=reference,
            value=by_reference[reference].value,
            footprint=by_reference[reference].footprint or "",
            uuid_path=stable_kicad_uuid(
                "board-component-path", "thermometer-real-data-micro-pilot", reference
            ),
        )
        for reference in MICRO_REFERENCES
    )
    if {component.footprint for component in components} != set(_REFERENCE_FOOTPRINT.values()):
        raise ValueError("production thermometer footprints changed for R17/D17")

    pwled_nodes: list[tuple[str, str]] = []
    for reference, _library, _x, _y, pin_nets in INSTANCES:
        if reference not in MICRO_REFERENCES:
            continue
        for pad, net_name in pin_nets.items():
            if net_name == "PWLED":
                pwled_nodes.append((reference, pad))
    if tuple(sorted(pwled_nodes)) != (("D17", "2"), ("R17", "2")):
        raise ValueError("production thermometer /PWLED nodes changed")
    netlist = BoardNetlist(
        components=components,
        nets=(BoardNet(name="/PWLED", nodes=tuple(sorted(pwled_nodes))),),
    )

    component_by_reference = {component.reference: component for component in components}
    absolute_poses = _source_absolute_poses()
    pose_by_reference = {pose.reference: pose for pose in absolute_poses}
    placements = tuple(
        (component_by_reference[reference], pose_by_reference[reference].x_mm - CROP_ORIGIN_MM[0])
        for reference in MICRO_REFERENCES
    )
    layout = BoardLayout(
        placements=placements,
        segments=(),
        vias=(),
        width_mm=CROP_SIZE_MM[0],
        height_mm=CROP_SIZE_MM[1],
        part_y_mm=tuple(
            (reference, pose_by_reference[reference].y_mm - CROP_ORIGIN_MM[1])
            for reference in MICRO_REFERENCES
        ),
        part_rotation=tuple(
            (reference, PLACEMENTS[reference][2])
            for reference in MICRO_REFERENCES
            if PLACEMENTS[reference][2]
        ),
        outline=((0.0, 0.0), (CROP_SIZE_MM[0], 0.0), CROP_SIZE_MM, (0.0, CROP_SIZE_MM[1])),
        part_flip=tuple(reference for reference in MICRO_REFERENCES if reference in FLIPPED_REFS),
    )
    return netlist, layout


def _geometry_catalog(
    layout: BoardLayout,
    sources: tuple[ThermometerMicroFootprintSource, ...],
) -> PlacementGeometryCatalog:
    by_reference = {source.reference: source for source in sources}
    bound = []
    purposes: tuple[Literal["body", "courtyard"], ...] = ("body", "courtyard")
    for component, _x in layout.placements:
        source = by_reference[component.reference]
        regions = tuple(
            FootprintPlacementRegion(
                region_id=f"thermometer-pwled:{component.reference}:{purpose}",
                purpose=purpose,
                occupancy_span=PlacementOccupancySpan.PLACED_SIDE,
                local_compound=source.body if purpose == "body" else source.courtyard,
                verification=PlacementRegionVerification.EXACT,
                source_layers=("F.Fab" if purpose == "body" else "F.CrtYd",),
                source_fingerprint=source.region_source_fingerprint(purpose),
            )
            for purpose in purposes
        )
        bound.append(bind_component_placement_geometry(component, regions=regions))
    return build_placement_geometry_catalog(layout, tuple(bound))


def _placement_budget() -> PlacementBudget:
    # The 10x6 mm crop has only 10x6 nominal coarse-grid cells per layer;
    # 256/512 therefore leaves bounded headroom without inheriting full-board
    # limits.  The direct 0.5 mm-grid /PWLED route has been observed around
    # 776 expansions, so 5,000 is a deliberate replay ceiling, not infinity.
    return PlacementBudget(
        max_proposals=5,
        max_legalization_evaluations=5,
        max_surrogate_evaluations=5,
        max_corridor_plans=1,
        max_detailed_candidates=1,
        max_exact_checks=0,
        max_r3_geometry_cells_per_candidate=256,
        max_r3_geometry_portals_per_candidate=512,
        max_r3_expansions_per_candidate=2_000,
        max_r2_passes_per_candidate=4,
        max_r2_expansions_per_candidate=5_000,
        max_r2_expansions_per_net=5_000,
        max_r2_stagnant_passes=2,
    )


def _build_authority(
    netlist: BoardNetlist,
    layout: BoardLayout,
    sources: tuple[ThermometerMicroFootprintSource, ...],
) -> PlacementPilotAuthority:
    placement_budget = _placement_budget()
    negotiated = NegotiatedCostPolicy()
    return build_placement_pilot_authority(
        layout,
        netlist,
        geometry_catalog=_geometry_catalog(layout, sources),
        movable_references=("R17",),
        move_policy=PlacementMovePolicy(
            movable_references=("R17",),
            rotatable_references=(),
            flippable_references=(),
            translation_step_mm=TRANSLATION_STEP_MM,
            maximum_translation_steps=1,
            allowed_rotation_deg=(),
            pair_move_limit=0,
            seed=20260718,
        ),
        legalization_policy=PlacementLegalizationPolicy(
            policy_id="thermometer-pwled-real-data-micro-legalization-v1",
            minimum_body_spacing_mm=0.1,
            minimum_courtyard_spacing_mm=0.0,
            minimum_body_outer_edge_clearance_mm=0.5,
            minimum_body_cutout_clearance_mm=0.5,
            require_courtyard_containment=True,
            minimum_courtyard_outer_edge_clearance_mm=0.0,
            side_permissions=(
                PlacementSidePermission(reference="R17", allowed_sides=("front",)),
            ),
            edge_exceptions=(),
        ),
        target_net_names=TARGET_NETS,
        target_net_widths_mm=(("/PWLED", TRACK_WIDTH_MM),),
        corridor_demand_policies=(
            PlacementPilotCorridorDemandPolicy(
                net_name="/PWLED",
                allowed_layers=("F.Cu",),
                via_policy=CorridorViaPolicy.FORBIDDEN,
            ),
        ),
        profile=DEFAULT_PCB_RULE_PROFILE,
        clearance_groups=(),
        coarse_grid_mm=COARSE_GRID_MM,
        detailed_grid_mm=DETAILED_GRID_MM,
        corridor_capacity_quantum_mm=CAPACITY_QUANTUM_MM,
        placement_budget=placement_budget,
        surrogate_policy=PlacementSurrogatePolicy(
            clearance_review_bands_um=(100,), escape_grid_mm=DETAILED_GRID_MM
        ),
        corridor_graphics_policy=OpaqueGraphicsPolicy.REJECT_OPAQUE,
        corridor_graph_budget=CorridorGraphBuildBudget(
            max_cells=placement_budget.max_r3_geometry_cells_per_candidate,
            max_portals=placement_budget.max_r3_geometry_portals_per_candidate,
        ),
        corridor_budget=CorridorBudget(
            max_passes=4,
            max_expansions=placement_budget.max_r3_expansions_per_candidate,
            max_expansions_per_demand=placement_budget.max_r3_expansions_per_candidate,
            max_stagnant_passes=2,
        ),
        corridor_cost_policy=CorridorCostPolicy(),
        detail_selection_policy=PlacementDetailSelectionPolicy(
            policy_id="thermometer-pwled-real-data-micro-detail-v1",
            portal_overflow_bucket_upper_bounds=(0, 1, 3),
            coarse_failure_exploration_quota=1,
            # The R3 plan is review evidence. Conservative bounded roundrect
            # issues intentionally make exact-only guide projection decline,
            # so the reviewed R2 fallback may retain INCOMPATIBLE/unguided.
            allow_unguided_when_corridor_unavailable=True,
        ),
        detail_budget=PlacementDetailBudget(
            max_selected_candidates=placement_budget.max_detailed_candidates,
            max_corridor_evaluations=placement_budget.max_corridor_plans,
            max_routing_evaluations=placement_budget.max_detailed_candidates,
        ),
        r2_policy=PlacementR2Policy(
            target_nets=TARGET_NETS,
            net_widths_mm=(("/PWLED", TRACK_WIDTH_MM),),
            net_order=TARGET_NETS,
            default_width_mm=TRACK_WIDTH_MM,
            grid_mm=DETAILED_GRID_MM,
            off_corridor_penalty_units=50,
            max_passes=placement_budget.max_r2_passes_per_candidate,
            max_expansions=placement_budget.max_r2_expansions_per_candidate,
            max_expansions_per_net=placement_budget.max_r2_expansions_per_net,
            max_stagnant_passes=placement_budget.max_r2_stagnant_passes,
            length_units_per_grid=negotiated.length_units_per_grid,
            diagonal_length_units=negotiated.diagonal_length_units,
            via_cost_units=negotiated.via_cost_units,
            turn_cost_units=negotiated.turn_cost_units,
            present_factor_units=negotiated.present_factor_units,
            present_growth_numerator=negotiated.present_growth_numerator,
            present_growth_denominator=negotiated.present_growth_denominator,
            history_increment_units=negotiated.history_increment_units,
        ),
        routing_budget=RoutingBudget(
            max_passes=placement_budget.max_r2_passes_per_candidate,
            max_expansions=placement_budget.max_r2_expansions_per_candidate,
            max_expansions_per_net=placement_budget.max_r2_expansions_per_net,
            max_stagnant_passes=placement_budget.max_r2_stagnant_passes,
            max_exact_check_rejections=0,
        ),
        negotiated_cost_policy=negotiated,
        exact_policy=PlacementExactPolicy(
            policy_id="thermometer-pwled-real-data-micro-no-acceptance-v1",
            checker_id="thermometer-pwled-micro-exact-checker-unimplemented@1",
        ),
        exact_budget=PlacementExactBudget(max_exact_checks=0),
    )


def _input_fingerprint(
    authority: PlacementPilotAuthority,
    sources: tuple[ThermometerMicroFootprintSource, ...],
) -> str:
    return _sha_text(
        _json(
            {
                "schema_id": "pcbsmith-thermometer-pwled-micro-pilot-input-binding",
                "schema_version": 1,
                "scope": MICRO_SCOPE,
                "included_references": MICRO_REFERENCES,
                "target_net_names": TARGET_NETS,
                "excluded_claims": MICRO_EXCLUDED_CLAIMS,
                "full_thermometer_board_part_count": 64,
                "source_absolute_poses": [
                    pose.model_dump(mode="json") for pose in _source_absolute_poses()
                ],
                "full_thermometer_outline_fingerprint": _full_outline_fingerprint(),
                "crop_origin_mm": CROP_ORIGIN_MM,
                "crop_size_mm": CROP_SIZE_MM,
                "crop_translation": CROP_TRANSLATION,
                "authority_fingerprint": authority.authority_fingerprint,
                "source_fingerprints": [source.semantic_fingerprint() for source in sources],
            }
        )
    )


class ThermometerPwledMicroPilotInput(PlacementIrModel):
    """Explicitly limited real-data input slice; never an acceptance record."""

    schema_id: Literal["pcbsmith-thermometer-pwled-micro-pilot-input"] = (
        "pcbsmith-thermometer-pwled-micro-pilot-input"
    )
    schema_version: Literal[1] = 1
    scope: Literal["real_thermometer_r17_d17_pwled_input_slice_only"] = MICRO_SCOPE
    included_references: tuple[str, ...] = MICRO_REFERENCES
    target_net_names: tuple[str, ...] = TARGET_NETS
    excluded_claims: tuple[str, ...] = MICRO_EXCLUDED_CLAIMS
    full_thermometer_board_part_count: Literal[64] = 64
    source_absolute_poses: tuple[ComponentPose, ...] = Field(min_length=2, max_length=2)
    full_thermometer_outline_fingerprint: str
    crop_origin_mm: tuple[float, float] = CROP_ORIGIN_MM
    crop_size_mm: tuple[float, float] = CROP_SIZE_MM
    crop_translation: Literal["absolute_xy_minus_crop_origin_to_local_xy"] = CROP_TRANSLATION
    sources: tuple[ThermometerMicroFootprintSource, ...] = Field(min_length=2, max_length=2)
    authority: PlacementPilotAuthority
    input_fingerprint: str

    @field_validator("input_fingerprint", "full_thermometer_outline_fingerprint")
    @classmethod
    def fingerprint_is_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("input_fingerprint must be a lowercase SHA-256 digest")
        return value

    @model_validator(mode="after")
    def bindings_replay_exactly(self) -> Self:
        if self.included_references != MICRO_REFERENCES:
            raise ValueError("micro-pilot included references changed")
        if self.target_net_names != TARGET_NETS:
            raise ValueError("micro-pilot target nets changed")
        if self.excluded_claims != MICRO_EXCLUDED_CLAIMS:
            raise ValueError("micro-pilot exclusions changed")
        expected_poses = _source_absolute_poses()
        if self.source_absolute_poses != expected_poses:
            raise ValueError("micro-pilot absolute source poses changed")
        if self.full_thermometer_outline_fingerprint != _full_outline_fingerprint():
            raise ValueError("micro-pilot full thermometer outline binding changed")
        if self.crop_origin_mm != CROP_ORIGIN_MM or self.crop_size_mm != CROP_SIZE_MM:
            raise ValueError("micro-pilot crop changed")
        sources = tuple(sorted(self.sources, key=lambda item: item.reference))
        if tuple(source.reference for source in sources) != MICRO_REFERENCES:
            raise ValueError("micro-pilot sources must exactly cover R17 and D17")
        object.__setattr__(self, "sources", sources)
        authority = PlacementPilotAuthority.model_validate_json(self.authority.model_dump_json())
        object.__setattr__(self, "authority", authority)
        expected_netlist, expected_layout = build_thermometer_pwled_micro_board()
        if authority.netlist() != expected_netlist or authority.layout() != expected_layout:
            raise ValueError(
                "micro-pilot authority is not bound to the real R17/D17 layout subset"
            )
        if authority.geometry_catalog != _geometry_catalog(expected_layout, sources):
            raise ValueError("micro-pilot geometry catalog is stale for its retained sources")
        if authority.movable_references != ("R17",) or authority.target_net_names != TARGET_NETS:
            raise ValueError("micro-pilot move or target scope changed")
        if authority.exact_budget.max_exact_checks != 0:
            raise ValueError("micro-pilot input slice cannot authorize exact acceptance")
        expected = _input_fingerprint(authority, sources)
        if self.input_fingerprint != expected:
            raise ValueError("micro-pilot input fingerprint is stale")
        return self


def build_thermometer_pwled_micro_pilot_input() -> ThermometerPwledMicroPilotInput:
    """Build the deterministic, source-bound, input-only micro authority."""

    sources = tuple(_read_exact_vendored_source(reference) for reference in MICRO_REFERENCES)
    netlist, layout = build_thermometer_pwled_micro_board()
    authority = _build_authority(netlist, layout, sources)
    return ThermometerPwledMicroPilotInput(
        source_absolute_poses=_source_absolute_poses(),
        full_thermometer_outline_fingerprint=_full_outline_fingerprint(),
        sources=sources,
        authority=authority,
        input_fingerprint=_input_fingerprint(authority, sources),
    )


__all__ = [
    "MICRO_EXCLUDED_CLAIMS",
    "MICRO_REFERENCES",
    "MICRO_SCOPE",
    "TARGET_NETS",
    "ThermometerPwledMicroPilotInput",
    "ThermometerMicroFootprintSource",
    "build_thermometer_pwled_micro_board",
    "build_thermometer_pwled_micro_pilot_input",
    "parse_exact_placement_footprint_source",
]
