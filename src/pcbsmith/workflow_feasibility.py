"""Phase 17 pre-route capacity, concept drift, and failing-net diagnostics."""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.prompt_examiner import AnchorKind, TypedSpatialAnchor
from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel

Point = tuple[float, float]


class FeasibilityOutcome(StrEnum):
    READY = "ready"
    ATTENTION_REQUIRED = "attention_required"
    BLOCKED = "blocked"
    UNVERIFIED = "unverified"


class PlacementEnvelope(SemanticIrModel):
    schema_id: Literal["pcbsmith-placement-capacity-envelope"] = (
        "pcbsmith-placement-capacity-envelope"
    )
    schema_version: Literal[1] = 1
    envelope_id: str
    subject_id: str
    polygon: tuple[Point, ...] = Field(min_length=3)
    source_geometry_sha256: str
    access_polygon: tuple[Point, ...] = ()

    @model_validator(mode="after")
    def envelope_is_valid(self) -> Self:
        require_identity(self.envelope_id, "envelope_id")
        require_identity(self.subject_id, "subject_id")
        require_sha256(self.source_geometry_sha256, "source_geometry_sha256")
        for polygon in (self.polygon, self.access_polygon):
            if polygon and (
                len(polygon) < 3
                or any(not math.isfinite(value) for point in polygon for value in point)
            ):
                raise ValueError("placement/access polygon must be finite with >=3 points")
        return self


class NeckSection(SemanticIrModel):
    schema_id: Literal["pcbsmith-routing-neck-section"] = (
        "pcbsmith-routing-neck-section"
    )
    schema_version: Literal[1] = 1
    neck_id: str
    usable_width_mm: float = Field(gt=0)
    routing_layers: tuple[str, ...] = Field(min_length=1)
    capacity_quantum_mm: float = Field(gt=0)
    source_geometry_sha256: str

    @model_validator(mode="after")
    def neck_is_canonical(self) -> Self:
        require_identity(self.neck_id, "neck_id")
        require_sha256(self.source_geometry_sha256, "source_geometry_sha256")
        layers = tuple(sorted(self.routing_layers))
        if len(layers) != len(set(layers)):
            raise ValueError("routing neck layers must be unique")
        object.__setattr__(self, "routing_layers", layers)
        return self


class PreRouteNetDemand(SemanticIrModel):
    schema_id: Literal["pcbsmith-pre-route-net-demand"] = (
        "pcbsmith-pre-route-net-demand"
    )
    schema_version: Literal[1] = 1
    net_name: str
    terminal_ids: tuple[str, ...] = Field(min_length=2)
    trace_width_mm: float = Field(gt=0)
    clearance_mm: float = Field(ge=0)
    candidate_neck_ids: tuple[str, ...] = ()
    net_class_id: str
    priority: int = Field(ge=0)

    @model_validator(mode="after")
    def demand_is_canonical(self) -> Self:
        require_identity(self.net_name, "net_name")
        require_identity(self.net_class_id, "net_class_id")
        terminals = tuple(sorted(self.terminal_ids))
        necks = tuple(sorted(self.candidate_neck_ids))
        if len(terminals) != len(set(terminals)) or len(necks) != len(set(necks)):
            raise ValueError("demand terminals and candidate necks must be unique")
        object.__setattr__(self, "terminal_ids", terminals)
        object.__setattr__(self, "candidate_neck_ids", necks)
        return self

    @property
    def reserved_width_mm(self) -> float:
        return self.trace_width_mm + 2 * self.clearance_mm


class FailingNetDiagnostic(SemanticIrModel):
    schema_id: Literal["pcbsmith-failing-net-diagnostic"] = (
        "pcbsmith-failing-net-diagnostic"
    )
    schema_version: Literal[1] = 1
    net_name: str
    terminal_ids: tuple[str, ...]
    failed_neck_ids: tuple[str, ...]
    required_units: int
    maximum_available_units: int
    blocker_ids: tuple[str, ...]
    finding: str
    next_actions: tuple[str, ...] = Field(min_length=2)


class NeckCapacityRecord(SemanticIrModel):
    schema_id: Literal["pcbsmith-neck-capacity-record"] = (
        "pcbsmith-neck-capacity-record"
    )
    schema_version: Literal[1] = 1
    neck_id: str
    capacity_units: int = Field(ge=0)
    committed_units: int = Field(ge=0)
    demand_net_names: tuple[str, ...]
    over_capacity_units: int = Field(ge=0)


class NetCapacityAssignment(SemanticIrModel):
    schema_id: Literal["pcbsmith-net-capacity-assignment"] = (
        "pcbsmith-net-capacity-assignment"
    )
    schema_version: Literal[1] = 1
    net_name: str
    neck_id: str
    committed_units: int = Field(gt=0)


class PreRouteFeasibilityReport(SemanticIrModel):
    schema_id: Literal["pcbsmith-pre-route-feasibility-report"] = (
        "pcbsmith-pre-route-feasibility-report"
    )
    schema_version: Literal[1] = 1
    board_outline_sha256: str
    board_area_mm2: float = Field(gt=0)
    usable_area_mm2: float = Field(ge=0)
    envelope_area_mm2: float = Field(ge=0)
    area_utilization: float = Field(ge=0)
    outcome: FeasibilityOutcome
    uncontained_envelope_ids: tuple[str, ...]
    access_conflict_envelope_ids: tuple[str, ...]
    assignments: tuple[NetCapacityAssignment, ...]
    neck_records: tuple[NeckCapacityRecord, ...]
    failing_nets: tuple[FailingNetDiagnostic, ...]
    search_state_budget: int = Field(gt=0)
    search_states_explored: int = Field(ge=0)
    search_complete: bool
    findings: tuple[str, ...]
    report_fingerprint: str

    @model_validator(mode="after")
    def report_is_replay_derived(self) -> Self:
        require_sha256(self.board_outline_sha256, "board_outline_sha256")
        require_sha256(self.report_fingerprint, "report_fingerprint")
        payload = self.model_dump(mode="json", exclude={"report_fingerprint"})
        if self.report_fingerprint != fingerprint(payload):
            raise ValueError("pre-route feasibility fingerprint is stale")
        return self


def evaluate_pre_route_feasibility(
    *,
    board_outline: tuple[Point, ...],
    board_outline_sha256: str,
    keepout_polygons: tuple[tuple[Point, ...], ...],
    envelopes: tuple[PlacementEnvelope, ...],
    necks: tuple[NeckSection, ...],
    net_demands: tuple[PreRouteNetDemand, ...],
    attention_utilization: float = 0.70,
    search_state_budget: int = 50_000,
) -> PreRouteFeasibilityReport:
    """Evaluate exact containment and bounded alternative-neck allocation."""

    try:
        from shapely.geometry import Polygon  # type: ignore[import-untyped]
        from shapely.ops import unary_union  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Install the artwork extra for feasibility geometry.") from exc
    require_sha256(board_outline_sha256, "board_outline_sha256")
    if search_state_budget <= 0:
        raise ValueError("search_state_budget must be positive")
    board = Polygon(board_outline)
    if not board.is_valid or board.is_empty or board.area <= 0:
        raise ValueError("board outline must be one valid positive-area polygon")
    keepouts = tuple(Polygon(item) for item in keepout_polygons)
    if any(not item.is_valid for item in keepouts):
        raise ValueError("keepout polygons must be valid")
    keepout_union = unary_union(keepouts) if keepouts else None
    usable = board if keepout_union is None else board.difference(keepout_union)
    if usable.is_empty:
        raise ValueError("keepouts consume the entire board")
    envelope_ids = tuple(item.envelope_id for item in envelopes)
    if len(envelope_ids) != len(set(envelope_ids)):
        raise ValueError("placement envelope identities must be unique")
    uncontained: list[str] = []
    access_conflicts: list[str] = []
    envelope_area = 0.0
    for envelope in envelopes:
        shape = Polygon(envelope.polygon)
        if not shape.is_valid or shape.area <= 0:
            raise ValueError(f"{envelope.envelope_id} polygon is invalid")
        envelope_area += float(shape.area)
        if not usable.covers(shape):
            uncontained.append(envelope.envelope_id)
        if envelope.access_polygon:
            access = Polygon(envelope.access_polygon)
            if not access.is_valid or not board.covers(access):
                access_conflicts.append(envelope.envelope_id)

    by_neck = {item.neck_id: item for item in necks}
    if len(by_neck) != len(necks):
        raise ValueError("routing neck identities must be unique")
    demand_names = tuple(item.net_name for item in net_demands)
    if len(demand_names) != len(set(demand_names)):
        raise ValueError("pre-route net names must be unique")
    unknown_necks = sorted(
        {
            neck_id
            for demand in net_demands
            for neck_id in demand.candidate_neck_ids
            if neck_id not in by_neck
        }
    )
    if unknown_necks:
        raise ValueError(f"net demands reference unknown necks: {unknown_necks!r}")

    capacity_by_neck = {
        neck.neck_id: (
            math.floor(neck.usable_width_mm / neck.capacity_quantum_mm)
            * len(neck.routing_layers)
        )
        for neck in necks
    }
    demand_units: dict[tuple[str, str], int] = {}
    for demand in net_demands:
        for neck_id in demand.candidate_neck_ids:
            neck = by_neck[neck_id]
            demand_units[(demand.net_name, neck_id)] = math.ceil(
                demand.reserved_width_mm / neck.capacity_quantum_mm
            )

    constrained = tuple(
        sorted(
            (item for item in net_demands if item.candidate_neck_ids),
            key=lambda item: (len(item.candidate_neck_ids), item.priority, item.net_name),
        )
    )
    best_assignment: dict[str, str] = {}
    full_assignment: dict[str, str] | None = None
    search_states_explored = 0
    search_complete = True

    def search(
        index: int,
        remaining: dict[str, int],
        assigned: dict[str, str],
    ) -> None:
        nonlocal best_assignment, full_assignment, search_complete
        nonlocal search_states_explored
        if full_assignment is not None or not search_complete:
            return
        if search_states_explored >= search_state_budget:
            search_complete = False
            return
        search_states_explored += 1
        if len(assigned) > len(best_assignment):
            best_assignment = dict(assigned)
        if index == len(constrained):
            if len(assigned) == len(constrained):
                full_assignment = dict(assigned)
            return
        demand = constrained[index]
        options = sorted(
            demand.candidate_neck_ids,
            key=lambda neck_id: (
                -(
                    remaining[neck_id]
                    - demand_units[(demand.net_name, neck_id)]
                ),
                neck_id,
            ),
        )
        for neck_id in options:
            units = demand_units[(demand.net_name, neck_id)]
            if units > remaining[neck_id]:
                continue
            assigned[demand.net_name] = neck_id
            remaining[neck_id] -= units
            search(index + 1, remaining, assigned)
            remaining[neck_id] += units
            assigned.pop(demand.net_name)
            if full_assignment is not None or not search_complete:
                return
        # A skipped demand permits compact diagnostics from the best partial
        # assignment if exhaustive search proves that no full allocation exists.
        search(index + 1, remaining, assigned)

    search(0, dict(capacity_by_neck), {})
    selected_assignment = (
        full_assignment if full_assignment is not None else best_assignment
    )
    assignments = tuple(
        NetCapacityAssignment(
            net_name=net_name,
            neck_id=neck_id,
            committed_units=demand_units[(net_name, neck_id)],
        )
        for net_name, neck_id in sorted(selected_assignment.items())
    )
    assignment_by_neck: dict[str, list[NetCapacityAssignment]] = {
        item.neck_id: [] for item in necks
    }
    for assignment in assignments:
        assignment_by_neck[assignment.neck_id].append(assignment)

    records: list[NeckCapacityRecord] = []
    for neck in sorted(necks, key=lambda item: item.neck_id):
        committed = sum(
            item.committed_units for item in assignment_by_neck[neck.neck_id]
        )
        records.append(
            NeckCapacityRecord(
                neck_id=neck.neck_id,
                capacity_units=capacity_by_neck[neck.neck_id],
                committed_units=committed,
                demand_net_names=tuple(
                    sorted(item.net_name for item in assignment_by_neck[neck.neck_id])
                ),
                over_capacity_units=max(
                    0, committed - capacity_by_neck[neck.neck_id]
                ),
            )
        )

    failing: list[FailingNetDiagnostic] = []
    for demand in sorted(net_demands, key=lambda item: (item.priority, item.net_name)):
        if (
            not demand.candidate_neck_ids
            or demand.net_name in selected_assignment
        ):
            continue
        required = min(
            demand_units[(demand.net_name, neck_id)]
            for neck_id in demand.candidate_neck_ids
        )
        maximum = max(
            capacity_by_neck[neck_id]
            for neck_id in demand.candidate_neck_ids
        )
        blockers = sorted(
            {
                other.net_name
                for neck_id in demand.candidate_neck_ids
                for other in assignment_by_neck[neck_id]
            }
        )
        failing.append(
            FailingNetDiagnostic(
                net_name=demand.net_name,
                terminal_ids=demand.terminal_ids,
                failed_neck_ids=demand.candidate_neck_ids,
                required_units=required,
                maximum_available_units=maximum,
                blocker_ids=tuple(blockers),
                finding=(
                    "No complete assignment fits this net through any declared "
                    "candidate neck within retained capacity."
                ),
                next_actions=(
                    "Increase or add a routing neck without changing the required function.",
                    "Reposition endpoint groups to reduce shared-neck demand.",
                ),
            )
        )
    area = float(board.area)
    usable_area = float(usable.area)
    utilization = envelope_area / usable_area if usable_area else math.inf
    findings: list[str] = []
    if uncontained:
        findings.append("Placement envelopes exceed the usable substrate.")
    if access_conflicts:
        findings.append("Mating or service access envelopes exceed the substrate.")
    if failing and search_complete:
        findings.append("One or more nets have no capacity-feasible declared neck.")
    if not necks and net_demands:
        findings.append("Routing-neck evidence is incomplete.")
    if not search_complete:
        findings.append("Routing-neck allocation exhausted its declared search budget.")
    if uncontained or access_conflicts or (failing and search_complete):
        outcome = FeasibilityOutcome.BLOCKED
    elif (not necks and net_demands) or not search_complete:
        outcome = FeasibilityOutcome.UNVERIFIED
    elif utilization >= attention_utilization:
        outcome = FeasibilityOutcome.ATTENTION_REQUIRED
        findings.append("Aggregate envelope-area utilization is high.")
    else:
        outcome = FeasibilityOutcome.READY
    fields: dict[str, Any] = {
        "board_outline_sha256": board_outline_sha256,
        "board_area_mm2": area,
        "usable_area_mm2": usable_area,
        "envelope_area_mm2": envelope_area,
        "area_utilization": utilization,
        "outcome": outcome,
        "uncontained_envelope_ids": tuple(sorted(uncontained)),
        "access_conflict_envelope_ids": tuple(sorted(access_conflicts)),
        "assignments": assignments,
        "neck_records": tuple(records),
        "failing_nets": tuple(failing),
        "search_state_budget": search_state_budget,
        "search_states_explored": search_states_explored,
        "search_complete": search_complete,
        "findings": tuple(findings),
    }
    provisional = PreRouteFeasibilityReport.model_construct(
        **fields, report_fingerprint="0" * 64
    )
    return PreRouteFeasibilityReport(
        **fields,
        report_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"report_fingerprint"})
        ),
    )


class ObservedAnchor(SemanticIrModel):
    schema_id: Literal["pcbsmith-observed-spatial-anchor"] = (
        "pcbsmith-observed-spatial-anchor"
    )
    schema_version: Literal[1] = 1
    anchor_id: str
    subject_ids: tuple[str, ...] = Field(min_length=1)
    kind: AnchorKind
    observed_value_mm: float | None = None
    observed_side: Literal["front", "back", "either"] | None = None
    observed_orientation_deg: float | None = None
    evidence_sha256: str

    @model_validator(mode="after")
    def observation_is_bound(self) -> Self:
        require_identity(self.anchor_id, "anchor_id")
        require_sha256(self.evidence_sha256, "evidence_sha256")
        subjects = tuple(sorted(self.subject_ids))
        if len(subjects) != len(set(subjects)):
            raise ValueError("observed anchor subjects must be unique")
        object.__setattr__(self, "subject_ids", subjects)
        return self


class ConceptDriftRecord(SemanticIrModel):
    schema_id: Literal["pcbsmith-concept-drift-record"] = (
        "pcbsmith-concept-drift-record"
    )
    schema_version: Literal[1] = 1
    anchor_id: str
    state: Literal["conformant", "drifted", "missing", "foreign"]
    approved_value: str
    observed_value: str
    finding: str


class ConceptDriftReport(SemanticIrModel):
    schema_id: Literal["pcbsmith-concept-drift-report"] = "pcbsmith-concept-drift-report"
    schema_version: Literal[1] = 1
    approved_concept_sha256: str
    observed_design_sha256: str
    conformant: bool
    records: tuple[ConceptDriftRecord, ...]
    report_fingerprint: str

    @model_validator(mode="after")
    def drift_report_is_bound(self) -> Self:
        require_sha256(self.approved_concept_sha256, "approved_concept_sha256")
        require_sha256(self.observed_design_sha256, "observed_design_sha256")
        require_sha256(self.report_fingerprint, "report_fingerprint")
        if self.conformant != all(item.state == "conformant" for item in self.records):
            raise ValueError("concept drift disposition is stale")
        payload = self.model_dump(mode="json", exclude={"report_fingerprint"})
        if self.report_fingerprint != fingerprint(payload):
            raise ValueError("concept drift fingerprint is stale")
        return self


def compare_concept_anchors(
    *,
    approved_concept_sha256: str,
    observed_design_sha256: str,
    approved: tuple[TypedSpatialAnchor, ...],
    observed: tuple[ObservedAnchor, ...],
) -> ConceptDriftReport:
    """Compare typed approved anchors against measured design observations."""

    require_sha256(approved_concept_sha256, "approved_concept_sha256")
    require_sha256(observed_design_sha256, "observed_design_sha256")
    approved_by_id = {item.anchor_id: item for item in approved}
    observed_by_id = {item.anchor_id: item for item in observed}
    if len(approved_by_id) != len(approved) or len(observed_by_id) != len(observed):
        raise ValueError("approved and observed anchor identities must be unique")
    records: list[ConceptDriftRecord] = []
    for anchor_id in sorted(set(approved_by_id) | set(observed_by_id)):
        expected = approved_by_id.get(anchor_id)
        actual = observed_by_id.get(anchor_id)
        if expected is None:
            state: Literal["conformant", "drifted", "missing", "foreign"] = "foreign"
            approved_value = "<undeclared>"
            observed_value = _observed_value(actual)
            finding = "Observed design contains an undeclared anchor."
        elif actual is None:
            state = "missing"
            approved_value = _approved_value(expected)
            observed_value = "<missing>"
            finding = "Approved anchor was not measured in the design."
        else:
            same_subject = expected.subject_ids == actual.subject_ids
            same_kind = expected.kind is actual.kind
            tolerance = 0.0 if expected.tolerance_mm is None else expected.tolerance_mm
            if expected.kind is AnchorKind.SIDE:
                same_value = expected.side == actual.observed_side
            elif expected.kind is AnchorKind.ORIENTATION:
                same_value = (
                    expected.orientation_deg is not None
                    and actual.observed_orientation_deg is not None
                    and abs(expected.orientation_deg - actual.observed_orientation_deg)
                    <= tolerance
                )
            elif expected.kind is AnchorKind.CENTER:
                same_value = (
                    actual.observed_value_mm is not None
                    and abs(actual.observed_value_mm) <= tolerance
                )
            elif expected.value_mm is None:
                same_value = actual.observed_value_mm is None
            else:
                same_value = (
                    actual.observed_value_mm is not None
                    and abs(expected.value_mm - actual.observed_value_mm) <= tolerance
                )
            state = "conformant" if same_subject and same_kind and same_value else "drifted"
            approved_value = _approved_value(expected)
            observed_value = _observed_value(actual)
            finding = (
                "Observed anchor matches the approved concept."
                if state == "conformant"
                else "Observed anchor differs from approved subject, kind, or tolerance."
            )
        records.append(
            ConceptDriftRecord(
                anchor_id=anchor_id,
                state=state,
                approved_value=approved_value,
                observed_value=observed_value,
                finding=finding,
            )
        )
    fields: dict[str, Any] = {
        "approved_concept_sha256": approved_concept_sha256,
        "observed_design_sha256": observed_design_sha256,
        "conformant": all(item.state == "conformant" for item in records),
        "records": tuple(records),
    }
    provisional = ConceptDriftReport.model_construct(
        **fields, report_fingerprint="0" * 64
    )
    return ConceptDriftReport(
        **fields,
        report_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"report_fingerprint"})
        ),
    )


def _approved_value(anchor: TypedSpatialAnchor) -> str:
    return (
        f"value_mm={anchor.value_mm}; tolerance_mm={anchor.tolerance_mm}; "
        f"side={anchor.side}; orientation_deg={anchor.orientation_deg}"
    )


def _observed_value(anchor: ObservedAnchor | None) -> str:
    if anchor is None:
        return "<missing>"
    return (
        f"value_mm={anchor.observed_value_mm}; side={anchor.observed_side}; "
        f"orientation_deg={anchor.observed_orientation_deg}"
    )
