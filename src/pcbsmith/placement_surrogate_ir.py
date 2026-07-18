"""Typed placement routability surrogate IR for R5.3."""

from __future__ import annotations

from decimal import ROUND_CEILING, Decimal
from enum import StrEnum
from fractions import Fraction
from itertools import combinations
from math import isqrt
from typing import Literal, Self

from pydantic import Field, model_validator

from pcbsmith.corridor_summary import (
    CorridorPlanSummary,
    VerifiedCorridorPlanSummary,
)
from pcbsmith.placement_geometry import ExactPlanarCompound
from pcbsmith.placement_ir import PlacementIrModel


def _id(v: str) -> str:
    if not v or v != v.strip():
        raise ValueError("identity must be canonical and non-empty")
    return v


def _ids(v: tuple[str, ...]) -> tuple[str, ...]:
    out = tuple(sorted(v))
    if len(set(out)) != len(out):
        raise ValueError("identities must be unique")
    return tuple(_id(x) for x in out)


class EscapeRay(PlacementIrModel):
    dx: int
    dy: int
    alignment_penalty_units: int = Field(default=0, ge=0)
    constrained_portal_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def valid(self) -> Self:
        if (self.dx, self.dy) not in {(1, 0), (-1, 0), (0, 1), (0, -1)}:
            raise ValueError("escape rays must be cardinal unit vectors")
        object.__setattr__(self, "constrained_portal_ids", _ids(self.constrained_portal_ids))
        return self


class PlacedTerminalCopper(PlacementIrModel):
    terminal_id: str
    source_id: str
    component_reference: str
    net_name: str
    layer: Literal["F.Cu", "B.Cu"]
    center_mm: tuple[float, float]
    copper: ExactPlanarCompound
    escape_rays: tuple[EscapeRay, ...] = ()
    escape_length_mm: float = Field(default=0.5, gt=0)

    @model_validator(mode="after")
    def valid(self) -> Self:
        for n in ("terminal_id", "source_id", "component_reference", "net_name"):
            object.__setattr__(self, n, _id(getattr(self, n)))
        rays = tuple(sorted(self.escape_rays, key=lambda x: x.semantic_json()))
        if len({x.semantic_fingerprint() for x in rays}) != len(rays):
            raise ValueError("escape rays must be unique")
        object.__setattr__(self, "escape_rays", rays)
        return self


class CallerClearanceGroup(PlacementIrModel):
    nets_a: tuple[str, ...]
    nets_b: tuple[str, ...]
    minimum_clearance_mm: float = Field(gt=0)
    exempt_component_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def valid(self) -> Self:
        a, b = _ids(self.nets_a), _ids(self.nets_b)
        if not a or not b or set(a) & set(b):
            raise ValueError("clearance groups require disjoint non-empty nets")
        object.__setattr__(self, "nets_a", a)
        object.__setattr__(self, "nets_b", b)
        object.__setattr__(self, "exempt_component_refs", _ids(self.exempt_component_refs))
        return self


class BusBoundaryOrderObservation(PlacementIrModel):
    bus_id: str
    boundary_id: str
    declared_member_ids: tuple[str, ...]
    observed_member_ids: tuple[str, ...]
    allow_whole_bundle_reversal: bool = False
    allowed_member_permutations: tuple[tuple[str, ...], ...] = ()

    @model_validator(mode="after")
    def valid(self) -> Self:
        object.__setattr__(self, "bus_id", _id(self.bus_id))
        object.__setattr__(self, "boundary_id", _id(self.boundary_id))
        d = tuple(_id(item) for item in self.declared_member_ids)
        o = tuple(_id(item) for item in self.observed_member_ids)
        if not d or len(set(d)) != len(d) or set(d) != set(o) or len(o) != len(d):
            raise ValueError("observed order must exactly cover unique declared members")
        allowed = tuple(
            sorted(
                set(
                    tuple(_id(item) for item in permutation)
                    for permutation in self.allowed_member_permutations
                )
            )
        )
        if any(len(p) != len(d) or set(p) != set(d) for p in allowed):
            raise ValueError("allowed permutations must cover declared members")
        object.__setattr__(self, "declared_member_ids", d)
        object.__setattr__(self, "observed_member_ids", o)
        object.__setattr__(self, "allowed_member_permutations", allowed)
        return self


class PlacementCorridorState(StrEnum):
    ABSENT = "absent"
    UNSUPPORTED = "unsupported"
    READY = "ready"


class PortalOverloadEvidence(PlacementIrModel):
    resource_id: str
    overuse_units: int = Field(gt=0)
    contributing_demand_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def valid(self) -> Self:
        object.__setattr__(self, "resource_id", _id(self.resource_id))
        object.__setattr__(self, "contributing_demand_ids", _ids(self.contributing_demand_ids))
        return self


class PlacementCorridorEvidence(PlacementIrModel):
    state: PlacementCorridorState
    verified_summary: VerifiedCorridorPlanSummary | None = None
    portal_overloads: tuple[PortalOverloadEvidence, ...] = ()

    @property
    def summary(self) -> CorridorPlanSummary | None:
        return None if self.verified_summary is None else self.verified_summary.summary

    @model_validator(mode="after")
    def valid(self) -> Self:
        over = tuple(sorted(self.portal_overloads, key=lambda x: x.resource_id))
        if len({x.resource_id for x in over}) != len(over):
            raise ValueError("portal overloads must be unique")
        if self.state is PlacementCorridorState.ABSENT and (
            self.verified_summary is not None or over
        ):
            raise ValueError("absent R3 evidence cannot have verified evidence")
        if self.state is not PlacementCorridorState.ABSENT and self.verified_summary is None:
            raise ValueError("non-absent R3 evidence requires a verified summary")
        summary = self.summary
        if summary is not None:
            if (self.state is PlacementCorridorState.READY) != summary.guidance_ready:
                raise ValueError("R3 state and readiness disagree")
            total = summary.channel_total_overflow_units + summary.via_total_overflow_units
            if sum(x.overuse_units for x in over) != total:
                raise ValueError("portal overload totals are stale")
        object.__setattr__(self, "portal_overloads", over)
        return self


class EscapeObstacle(PlacementIrModel):
    obstacle_id: str
    layer: Literal["F.Cu", "B.Cu"] = "F.Cu"
    compound: ExactPlanarCompound
    exempt_component_refs: tuple[str, ...] = ()
    source_fingerprint: str | None = None
    verification: Literal["exact"] = "exact"
    clearance_inflated_hard_forbidden: Literal[True] = True

    @model_validator(mode="after")
    def valid(self) -> Self:
        object.__setattr__(self, "obstacle_id", _id(self.obstacle_id))
        object.__setattr__(self, "exempt_component_refs", _ids(self.exempt_component_refs))
        source = self.source_fingerprint or self.compound.semantic_fingerprint()
        if len(source) != 64 or any(c not in "0123456789abcdef" for c in source):
            raise ValueError("escape obstacle source_fingerprint must be SHA-256")
        object.__setattr__(self, "source_fingerprint", source)
        return self


class PlacementSurrogatePolicy(PlacementIrModel):
    clearance_review_bands_um: tuple[int, ...] = (100,)
    escape_grid_mm: float = Field(default=0.25, gt=0)

    @model_validator(mode="after")
    def valid(self) -> Self:
        bands = tuple(sorted(set(self.clearance_review_bands_um)))
        if any(x < 0 for x in bands):
            raise ValueError("review bands must be nonnegative")
        object.__setattr__(self, "clearance_review_bands_um", bands)
        return self


class TerminalClearanceEvidence(PlacementIrModel):
    source_ids: tuple[str, str]
    net_names: tuple[str, str]
    layer: Literal["F.Cu", "B.Cu"]
    exact_squared_distance_numerator: int = Field(ge=0)
    exact_squared_distance_denominator: int = Field(gt=0)
    distance_floor_um: int = Field(ge=0)
    required_clearance_mm: float = Field(gt=0)
    required_clearance_um: int = Field(gt=0)
    margin_floor_um: int
    exact_violation: bool
    contributing_domain_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> Self:
        sources, nets = _ids(self.source_ids), _ids(self.net_names)
        if len(sources) != 2 or len(nets) != 2:
            raise ValueError("clearance evidence requires two distinct sources and nets")
        squared = Fraction(
            self.exact_squared_distance_numerator,
            self.exact_squared_distance_denominator,
        )
        required = Fraction(str(self.required_clearance_mm))
        expected_distance_floor_um = isqrt((squared.numerator * 1_000_000) // squared.denominator)
        if self.distance_floor_um != expected_distance_floor_um:
            raise ValueError("clearance distance floor is stale")
        expected_um = int(
            (Decimal(str(self.required_clearance_mm)) * 1000).to_integral_value(
                rounding=ROUND_CEILING
            )
        )
        if self.required_clearance_um != expected_um:
            raise ValueError("required clearance micrometres are stale")
        if self.margin_floor_um != self.distance_floor_um - self.required_clearance_um:
            raise ValueError("clearance margin is stale")
        if self.exact_violation != (squared < required * required):
            raise ValueError("exact clearance violation flag is stale")
        object.__setattr__(self, "source_ids", sources)
        object.__setattr__(self, "net_names", nets)
        object.__setattr__(self, "contributing_domain_ids", _ids(self.contributing_domain_ids))
        return self


class SketchSegment(PlacementIrModel):
    net_name: str
    layer: Literal["F.Cu", "B.Cu"]
    start_um: tuple[int, int]
    end_um: tuple[int, int]

    @model_validator(mode="after")
    def valid(self) -> Self:
        if self.start_um == self.end_um or (
            self.start_um[0] != self.end_um[0] and self.start_um[1] != self.end_um[1]
        ):
            raise ValueError("sketch segments must be nonzero and rectilinear")
        if self.end_um < self.start_um:
            a, b = self.start_um, self.end_um
            object.__setattr__(self, "start_um", b)
            object.__setattr__(self, "end_um", a)
        return self


class SketchIntersectionKind(StrEnum):
    PROPER = "proper"
    COLLINEAR_AMBIGUITY = "collinear_ambiguity"


def _sketch_intersection_kind(
    first: SketchSegment, second: SketchSegment
) -> SketchIntersectionKind | None:
    first_horizontal = first.start_um[1] == first.end_um[1]
    second_horizontal = second.start_um[1] == second.end_um[1]
    if first_horizontal != second_horizontal:
        horizontal, vertical = (first, second) if first_horizontal else (second, first)
        point = (vertical.start_um[0], horizontal.start_um[1])
        if (
            horizontal.start_um[0] < point[0] < horizontal.end_um[0]
            and vertical.start_um[1] < point[1] < vertical.end_um[1]
        ):
            return SketchIntersectionKind.PROPER
        return None
    if first_horizontal:
        overlaps = first.start_um[1] == second.start_um[1] and max(
            first.start_um[0], second.start_um[0]
        ) < min(first.end_um[0], second.end_um[0])
    else:
        overlaps = first.start_um[0] == second.start_um[0] and max(
            first.start_um[1], second.start_um[1]
        ) < min(first.end_um[1], second.end_um[1])
    return SketchIntersectionKind.COLLINEAR_AMBIGUITY if overlaps else None


class SketchIntersectionEvidence(PlacementIrModel):
    kind: SketchIntersectionKind
    net_names: tuple[str, str]
    layer: Literal["F.Cu", "B.Cu"]
    first_segment: SketchSegment
    second_segment: SketchSegment

    @model_validator(mode="after")
    def coherent(self) -> Self:
        nets = _ids(self.net_names)
        first = SketchSegment.model_validate_json(self.first_segment.model_dump_json())
        second = SketchSegment.model_validate_json(self.second_segment.model_dump_json())
        if (
            len(nets) != 2
            or first.net_name == second.net_name
            or set(nets) != {first.net_name, second.net_name}
        ):
            raise ValueError("intersection evidence must bind two distinct segment nets")
        if first.layer != self.layer or second.layer != self.layer:
            raise ValueError("intersection layer is stale")
        if _sketch_intersection_kind(first, second) is not self.kind:
            raise ValueError("intersection kind is stale")
        ordered = tuple(sorted((first, second), key=lambda item: item.semantic_json()))
        object.__setattr__(self, "net_names", nets)
        object.__setattr__(self, "first_segment", ordered[0])
        object.__setattr__(self, "second_segment", ordered[1])
        return self


class NetHpwlEvidence(PlacementIrModel):
    net_name: str
    hpwl_um: int = Field(ge=0)

    @model_validator(mode="after")
    def valid(self) -> Self:
        object.__setattr__(self, "net_name", _id(self.net_name))
        return self


class BusOrderEvidence(PlacementIrModel):
    bus_id: str
    boundary_id: str
    observed_member_ids: tuple[str, ...]
    conflict: bool
    accepted_as: Literal["declared", "whole_reversal", "allowed_permutation", "conflict"]

    @model_validator(mode="after")
    def coherent(self) -> Self:
        object.__setattr__(self, "bus_id", _id(self.bus_id))
        object.__setattr__(self, "boundary_id", _id(self.boundary_id))
        observed = tuple(_id(item) for item in self.observed_member_ids)
        if len(set(observed)) != len(observed):
            raise ValueError("observed bus members must be unique")
        if self.conflict != (self.accepted_as == "conflict"):
            raise ValueError("bus conflict disposition is stale")
        object.__setattr__(self, "observed_member_ids", observed)
        return self


class PinEscapeEvidence(PlacementIrModel):
    terminal_id: str
    source_id: str
    legal_alternative_count: int = Field(ge=0)
    unescaped: bool
    constrained: bool
    minimum_alignment_penalty_units: int = Field(default=0, ge=0)
    grid_residual_um: int = Field(ge=0)
    off_grid_diagnostic: bool
    ambiguous: bool
    blocked_obstacle_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> Self:
        object.__setattr__(self, "terminal_id", _id(self.terminal_id))
        object.__setattr__(self, "source_id", _id(self.source_id))
        blocked = _ids(self.blocked_obstacle_ids)
        if self.unescaped != (self.legal_alternative_count == 0):
            raise ValueError("pin escape state is stale")
        if self.off_grid_diagnostic != (self.grid_residual_um > 0):
            raise ValueError("off-grid diagnostic is stale")
        object.__setattr__(self, "blocked_obstacle_ids", blocked)
        return self


class PlacementSurrogateResult(PlacementIrModel):
    schema_id: Literal["pcbsmith-placement-surrogate-result"] = (
        "pcbsmith-placement-surrogate-result"
    )
    schema_version: Literal[1] = 1
    pose_fingerprint: str
    probe_layout_fingerprint: str
    terminal_catalog_fingerprint: str
    profile_fingerprint: str
    policy_fingerprint: str
    clearance_groups_fingerprint: str
    bus_observations_fingerprint: str
    corridor_fingerprint: str
    escape_obstacles_fingerprint: str
    input_fingerprint: str
    clearance_domain_ids: tuple[str, ...]
    clearance_requirement_ids: tuple[str, ...]
    clearance_evidence: tuple[TerminalClearanceEvidence, ...]
    minimum_terminal_margin_um: int | None
    terminal_clearance_violation_count: int = Field(ge=0)
    clearance_review_band_counts: tuple[tuple[int, int], ...]
    sketch_segments: tuple[SketchSegment, ...]
    sketch_intersections: tuple[SketchIntersectionEvidence, ...]
    geometric_crossing_count: int = Field(ge=0)
    collinear_ambiguity_count: int = Field(ge=0)
    hpwl_by_net: tuple[NetHpwlEvidence, ...]
    total_hpwl_um: int = Field(ge=0)
    maximum_net_hpwl_um: int = Field(ge=0)
    bus_order_evidence: tuple[BusOrderEvidence, ...]
    declared_order_conflict_count: int = Field(ge=0)
    corridor: PlacementCorridorEvidence
    pin_escape_evidence: tuple[PinEscapeEvidence, ...]
    unescaped_terminal_count: int = Field(ge=0)
    constrained_escape_count: int = Field(ge=0)
    alignment_penalty_units: int = Field(default=0, ge=0)
    grid_residual_units: int = Field(ge=0)
    ambiguous_escape_count: int = Field(ge=0)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        fingerprint_names = (
            "pose_fingerprint",
            "probe_layout_fingerprint",
            "terminal_catalog_fingerprint",
            "profile_fingerprint",
            "policy_fingerprint",
            "clearance_groups_fingerprint",
            "bus_observations_fingerprint",
            "corridor_fingerprint",
            "escape_obstacles_fingerprint",
            "input_fingerprint",
        )
        for name in fingerprint_names:
            value = getattr(self, name)
            if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                raise ValueError(f"{name} must be a lowercase SHA-256 digest")
        expected_input = (
            __import__("hashlib")
            .sha256(
                __import__("json")
                .dumps(
                    {
                        "schema_id": "pcbsmith-placement-surrogate-input",
                        "schema_version": 1,
                        **{name: getattr(self, name) for name in fingerprint_names[:-1]},
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                .encode()
            )
            .hexdigest()
        )
        if self.input_fingerprint != expected_input:
            raise ValueError("surrogate input fingerprint is stale")
        clearance = tuple(
            sorted(
                (
                    TerminalClearanceEvidence.model_validate_json(item.model_dump_json())
                    for item in self.clearance_evidence
                ),
                key=lambda item: item.semantic_json(),
            )
        )
        domains, requirements = (
            _ids(self.clearance_domain_ids),
            _ids(self.clearance_requirement_ids),
        )
        if any(not set(item.contributing_domain_ids) <= set(domains) for item in clearance):
            raise ValueError("clearance evidence references an unknown domain")
        margins = tuple(item.margin_floor_um for item in clearance)
        if self.minimum_terminal_margin_um != min(margins, default=None):
            raise ValueError("minimum terminal margin is stale")
        bands = tuple(sorted(self.clearance_review_band_counts))
        if len({band for band, _count in bands}) != len(bands) or any(
            count != sum(margin < band for margin in margins) for band, count in bands
        ):
            raise ValueError("clearance review band counts are stale")
        sketches = tuple(
            sorted(
                (
                    SketchSegment.model_validate_json(item.model_dump_json())
                    for item in self.sketch_segments
                ),
                key=lambda item: item.semantic_json(),
            )
        )
        intersections = tuple(
            sorted(
                (
                    SketchIntersectionEvidence.model_validate_json(item.model_dump_json())
                    for item in self.sketch_intersections
                ),
                key=lambda item: item.semantic_json(),
            )
        )
        if len(set(sketches)) != len(sketches) or len(set(intersections)) != len(intersections):
            raise ValueError("sketch evidence must be unique")
        expected_intersections = {
            (
                kind,
                first.layer,
                tuple(sorted((first.net_name, second.net_name))),
                min(first.semantic_json(), second.semantic_json()),
                max(first.semantic_json(), second.semantic_json()),
            )
            for first, second in combinations(sketches, 2)
            if first.layer == second.layer
            and first.net_name != second.net_name
            and (kind := _sketch_intersection_kind(first, second)) is not None
        }
        actual_intersections = {
            (
                item.kind,
                item.layer,
                item.net_names,
                item.first_segment.semantic_json(),
                item.second_segment.semantic_json(),
            )
            for item in intersections
        }
        if actual_intersections != expected_intersections:
            raise ValueError("sketch intersection evidence is incomplete or stale")
        hpwl = tuple(
            sorted(
                (
                    NetHpwlEvidence.model_validate_json(item.model_dump_json())
                    for item in self.hpwl_by_net
                ),
                key=lambda item: item.net_name,
            )
        )
        bus = tuple(
            sorted(
                (
                    BusOrderEvidence.model_validate_json(item.model_dump_json())
                    for item in self.bus_order_evidence
                ),
                key=lambda item: (item.bus_id, item.boundary_id),
            )
        )
        escape = tuple(
            sorted(
                (
                    PinEscapeEvidence.model_validate_json(item.model_dump_json())
                    for item in self.pin_escape_evidence
                ),
                key=lambda item: item.terminal_id,
            )
        )
        corridor = PlacementCorridorEvidence.model_validate_json(self.corridor.model_dump_json())
        if len(set(clearance)) != len(clearance):
            raise ValueError("clearance evidence must be unique")
        if len({item.net_name for item in hpwl}) != len(hpwl):
            raise ValueError("HPWL evidence must have unique nets")
        if len({(item.bus_id, item.boundary_id) for item in bus}) != len(bus):
            raise ValueError("bus order evidence must have unique observations")
        if len({item.terminal_id for item in escape}) != len(escape):
            raise ValueError("pin escape evidence must have unique terminals")
        if self.terminal_clearance_violation_count != sum(x.exact_violation for x in clearance):
            raise ValueError("clearance violation count stale")
        if self.geometric_crossing_count != sum(
            x.kind is SketchIntersectionKind.PROPER for x in intersections
        ):
            raise ValueError("crossing count stale")
        if self.collinear_ambiguity_count != sum(
            x.kind is SketchIntersectionKind.COLLINEAR_AMBIGUITY for x in intersections
        ):
            raise ValueError("ambiguity count stale")
        if self.total_hpwl_um != sum(x.hpwl_um for x in hpwl) or self.maximum_net_hpwl_um != max(
            (x.hpwl_um for x in hpwl), default=0
        ):
            raise ValueError("HPWL totals stale")
        if self.declared_order_conflict_count != sum(x.conflict for x in bus):
            raise ValueError("bus conflict count stale")
        if self.unescaped_terminal_count != sum(x.unescaped for x in escape):
            raise ValueError("unescaped count stale")
        if self.constrained_escape_count != sum(x.constrained for x in escape):
            raise ValueError("constrained count stale")
        if self.alignment_penalty_units != sum(x.minimum_alignment_penalty_units for x in escape):
            raise ValueError("alignment total stale")
        if self.grid_residual_units != sum(x.grid_residual_um for x in escape):
            raise ValueError("grid residual total stale")
        if self.ambiguous_escape_count != sum(x.ambiguous for x in escape):
            raise ValueError("ambiguous count stale")
        object.__setattr__(self, "clearance_domain_ids", domains)
        object.__setattr__(self, "clearance_requirement_ids", requirements)
        object.__setattr__(self, "clearance_evidence", clearance)
        object.__setattr__(self, "clearance_review_band_counts", bands)
        object.__setattr__(self, "sketch_segments", sketches)
        object.__setattr__(self, "sketch_intersections", intersections)
        object.__setattr__(self, "hpwl_by_net", hpwl)
        object.__setattr__(self, "bus_order_evidence", bus)
        object.__setattr__(self, "pin_escape_evidence", escape)
        object.__setattr__(self, "corridor", corridor)
        return self
