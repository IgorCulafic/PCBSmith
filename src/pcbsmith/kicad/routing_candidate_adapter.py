"""PCBSmith native A* adapter for the immutable routing-candidate contract.

This module translates one closed :class:`RouteRequest` into the existing
``route_board`` call. It does not publish a board, run release checks, or own a
second transaction authority.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import defaultdict, deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from pcbsmith.kicad.astar_router import BoardRouteResult, route_board, routing_copper_layers
from pcbsmith.kicad.board import (
    BOARD_SHEET_ORIGIN_MM,
    BoardLayout,
    BoardNetlist,
    TrackSegment,
    ViaSpec,
    _mm,
)
from pcbsmith.kicad.board_serialization import (
    board_netlist_snapshot_fingerprint,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.routing_ir import (
    ConstraintConsumption,
    PartialCandidateStatus,
    RouteCandidateResult,
    RouteConstraintDisposition,
    RouteFailureEvidence,
    RouteFailureKind,
    RouteMutationKind,
    RouteObjectKind,
    RoutePoint,
    RouteRequest,
    RouteSegmentDelta,
    RouteSegmentGeometry,
    RouteTerminationEvidence,
    RouteTerminationState,
    RouteTopologyConstraint,
    RouteViaDelta,
    RouteViaGeometry,
    RouteZoneDelta,
    RouteZoneGeometry,
    RoutingEngineIdentity,
    StableRouteObjectIdentity,
    validate_route_candidate_result,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile

_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


class NativePlanePour(BaseModel):
    """An explicit rectangular plane added after routing, before native final fill."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    net_name: str = Field(min_length=1)
    layer: str = "F.Cu"
    edge_inset_mm: float = Field(default=0.5, ge=0)
    connect_by_plane: bool = Field(default=False, exclude_if=lambda v: not v)

    @property
    def constraint_id(self) -> str:
        return "native-plane-pour:" + _fingerprint(self.model_dump(mode="json"))

    def zone(
        self, layout: BoardLayout, request: RouteRequest
    ) -> tuple[str, str, tuple[float, float, float, float]]:
        names = {n.net_name for d in request.target_domains for n in d.nets}
        if self.net_name not in names or self.layer not in request.allowed_layers:
            raise ValueError("plane pour must target a routed net on an allowed layer")
        inset = self.edge_inset_mm
        if 2 * inset >= min(layout.width_mm, layout.height_mm):
            raise ValueError("plane pour inset leaves no copper area")
        return (
            self.net_name,
            self.layer,
            (inset, inset, layout.width_mm - inset, layout.height_mm - inset),
        )


def native_routing_profile_fingerprint(profile: PcbRuleProfile) -> str:
    """Fingerprint the complete operative native routing profile."""

    return _fingerprint(
        {
            "schema_id": "pcbsmith-native-routing-profile",
            "schema_version": 1,
            "profile": profile.model_dump(mode="json"),
        }
    )


def native_routing_netlist_fingerprint(netlist: BoardNetlist) -> str:
    """Return the canonical neutral-netlist identity consumed by this adapter."""

    return board_netlist_snapshot_fingerprint(canonical_board_netlist_snapshot_json(netlist))


def stable_route_terminal_object_id(
    *,
    net_name: str,
    reference: str,
    pin: str,
) -> str:
    """Derive one stable terminal identity from canonical netlist semantics."""

    return "route-terminal:" + _fingerprint(
        {
            "schema_id": "pcbsmith-route-terminal-object",
            "schema_version": 1,
            "net_name": net_name,
            "reference": reference,
            "pin": pin,
        }
    )


def _segment_geometry(segment: TrackSegment) -> RouteSegmentGeometry:
    return RouteSegmentGeometry(
        net_name=segment.net_name,
        start=RoutePoint(x_mm=segment.x1, y_mm=segment.y1),
        end=RoutePoint(x_mm=segment.x2, y_mm=segment.y2),
        layer=segment.layer,
        width_mm=segment.width_mm,
    )


def _via_geometry(
    via: ViaSpec,
    *,
    technology_id: str,
) -> RouteViaGeometry:
    return RouteViaGeometry(
        net_name=via.net_name,
        position=RoutePoint(x_mm=via.x, y_mm=via.y),
        technology_id=technology_id,
        start_layer="F.Cu",
        end_layer="B.Cu",
        diameter_mm=via.size_mm,
        drill_mm=via.drill_mm,
    )


def _zone_geometry(
    zone: tuple[str, str, tuple[float, float, float, float]],
) -> RouteZoneGeometry:
    net_name, layer, (x1, y1, x2, y2) = zone
    return RouteZoneGeometry(
        net_name=net_name,
        layer=layer,
        boundary=(
            RoutePoint(x_mm=x1, y_mm=y1),
            RoutePoint(x_mm=x2, y_mm=y1),
            RoutePoint(x_mm=x2, y_mm=y2),
            RoutePoint(x_mm=x1, y_mm=y2),
        ),
        clearance_mm=0.0,
    )


@dataclass(frozen=True)
class NativeRouteObjectBinding:
    """Stable request identity bound to one neutral source geometry."""

    identity: StableRouteObjectIdentity
    geometry: RouteSegmentGeometry | RouteViaGeometry | RouteZoneGeometry
    source_index: int


def _stable_source_object(
    *,
    source_board_sha256: str,
    object_kind: RouteObjectKind,
    geometry: RouteSegmentGeometry | RouteViaGeometry | RouteZoneGeometry,
    occurrence: int,
    source_index: int,
) -> NativeRouteObjectBinding:
    geometry_fingerprint = geometry.semantic_fingerprint()
    object_id = "route-source:" + _fingerprint(
        {
            "schema_id": "pcbsmith-route-source-object",
            "schema_version": 1,
            "source_board_sha256": source_board_sha256,
            "object_kind": object_kind,
            "geometry_fingerprint": geometry_fingerprint,
            "occurrence": occurrence,
        }
    )
    return NativeRouteObjectBinding(
        identity=StableRouteObjectIdentity(
            object_id=object_id,
            object_kind=object_kind,
            source_board_sha256=source_board_sha256,
            source_object_fingerprint=geometry_fingerprint,
        ),
        geometry=geometry,
        source_index=source_index,
    )


def native_source_route_objects(
    layout: BoardLayout,
    *,
    source_board_sha256: str,
    via_technology_id: str = "via:through-default",
) -> tuple[StableRouteObjectIdentity, ...]:
    """Inventory every source segment, via, and zone with deterministic IDs."""

    return tuple(
        item.identity
        for item in native_source_route_object_bindings(
            layout,
            source_board_sha256=source_board_sha256,
            via_technology_id=via_technology_id,
        )
    )


def native_source_route_object_bindings(
    layout: BoardLayout,
    *,
    source_board_sha256: str,
    via_technology_id: str,
) -> tuple[NativeRouteObjectBinding, ...]:
    occurrences: dict[tuple[RouteObjectKind, str], int] = defaultdict(int)
    result: list[NativeRouteObjectBinding] = []

    typed_geometry: tuple[
        tuple[
            RouteObjectKind,
            RouteSegmentGeometry | RouteViaGeometry | RouteZoneGeometry,
            int,
        ],
        ...,
    ] = (
        *(
            (RouteObjectKind.SEGMENT, _segment_geometry(item), index)
            for index, item in enumerate(layout.segments)
        ),
        *(
            (
                RouteObjectKind.VIA,
                _via_geometry(item, technology_id=via_technology_id),
                index,
            )
            for index, item in enumerate(layout.vias)
        ),
        *(
            (RouteObjectKind.ZONE, _zone_geometry(item), index)
            for index, item in enumerate(layout.zones)
        ),
    )
    for kind, geometry, source_index in typed_geometry:
        key = (kind, geometry.semantic_fingerprint())
        occurrence = occurrences[key]
        occurrences[key] += 1
        result.append(
            _stable_source_object(
                source_board_sha256=source_board_sha256,
                object_kind=kind,
                geometry=geometry,
                occurrence=occurrence,
                source_index=source_index,
            )
        )
    return tuple(
        sorted(
            result,
            key=lambda item: (item.identity.object_kind, item.identity.object_id),
        )
    )


def _netlist_terminal_ids(netlist: BoardNetlist) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    for net in netlist.nets:
        result[net.name] = tuple(
            sorted(
                stable_route_terminal_object_id(
                    net_name=net.name,
                    reference=reference,
                    pin=pin,
                )
                for reference, pin in net.nodes
            )
        )
    return result


def _translation_consumption(
    request: RouteRequest,
    *,
    profile: PcbRuleProfile,
    plane_pour: NativePlanePour | None = None,
) -> tuple[tuple[ConstraintConsumption, ...], tuple[RouteFailureEvidence, ...]]:
    consumptions: dict[str, ConstraintConsumption] = {}
    failures: list[RouteFailureEvidence] = []

    def consumed(constraint_id: str, detail: str) -> None:
        consumptions[constraint_id] = ConstraintConsumption(
            constraint_id=constraint_id,
            disposition=RouteConstraintDisposition.CONSUMED,
            backend_constraint_id=f"native:{constraint_id}",
            detail=detail,
        )

    def unsupported(constraint_id: str, detail: str) -> None:
        consumptions[constraint_id] = ConstraintConsumption(
            constraint_id=constraint_id,
            disposition=RouteConstraintDisposition.UNSUPPORTED,
            detail=detail,
        )
        failures.append(
            RouteFailureEvidence(
                failure_id=f"failure:unsupported:{constraint_id}",
                kind=RouteFailureKind.UNSUPPORTED_CONSTRAINT,
                message=detail,
                constraint_ids=(constraint_id,),
            )
        )

    for width_constraint in request.width_constraints:
        consumed(
            width_constraint.constraint_id,
            "native A* consumes the preferred width and output is range checked",
        )
    for clearance_constraint in request.clearance_constraints:
        if clearance_constraint.other_net_names:
            consumed(
                clearance_constraint.constraint_id,
                "native A* operative profile enforces this same-layer copper clearance"
                if clearance_constraint.minimum_clearance_mm
                <= profile.fab_spacing.minimum_copper_clearance_mm
                else "native A* consumes the stronger declared pairwise clearance group",
            )
        else:
            unsupported(
                clearance_constraint.constraint_id,
                "native A* requires an explicit other-net set for request-local clearance",
            )
    for via_constraint in request.via_technologies:
        expected_diameter = profile.geometry.routing_via_diameter_mm
        expected_drill = profile.geometry.routing_via_drill_mm
        if (
            profile.geometry.copper_layer_count == 2
            and via_constraint.start_layer == "F.Cu"
            and via_constraint.end_layer == "B.Cu"
            and via_constraint.diameter_mm == expected_diameter
            and via_constraint.drill_mm == expected_drill
        ):
            consumed(
                via_constraint.constraint_id,
                "native A* uses the operative profile through-via technology",
            )
        else:
            unsupported(
                via_constraint.constraint_id,
                "native A* supports only the operative two-layer through-via technology",
            )
    for guide in request.route_guides:
        unsupported(
            guide.constraint_id,
            "legacy native A* has no RouteRequest guide/corridor adapter",
        )
    for topology in request.topology_constraints:
        if topology.topology_kind == "any_tree":
            consumed(
                topology.constraint_id,
                (
                    "declared native plane supplies terminal connectivity; exact filled-board "
                    "DRC/open checks required before acceptance"
                )
                if plane_pour is not None
                and plane_pour.connect_by_plane
                and plane_pour.net_name == topology.net_name
                else "native A* connects the complete terminal inventory as an unconstrained tree",
            )
        else:
            unsupported(
                topology.constraint_id,
                f"native A* cannot guarantee {topology.topology_kind} topology",
            )
    for constraint_id in request.additional_constraint_ids:
        if plane_pour is not None and constraint_id == plane_pour.constraint_id:
            consumed(constraint_id, "declared rectangular plane added before exact native fill")
        else:
            unsupported(constraint_id, "constraint has no typed native A* translation")
    count = profile.geometry.copper_layer_count
    expected_layers = routing_copper_layers(profile) if count in {1, 2} else ()
    if set(request.allowed_layers) != set(expected_layers):
        synthetic_id = "request:allowed-layers"
        failures.append(
            RouteFailureEvidence(
                failure_id=f"failure:unsupported:{synthetic_id}",
                kind=RouteFailureKind.UNSUPPORTED_CONSTRAINT,
                message=(
                    "native A* requires layers matching its one-front-side or two-layer profile"
                ),
                resource_ids=(synthetic_id,),
            )
        )
    return (
        tuple(consumptions[item] for item in sorted(consumptions)),
        tuple(sorted(failures, key=lambda item: item.failure_id)),
    )


def _candidate_object_id(
    *,
    request_fingerprint: str,
    kind: RouteObjectKind,
    geometry_fingerprint: str,
    occurrence: int,
) -> str:
    return "route-candidate:" + _fingerprint(
        {
            "schema_id": "pcbsmith-route-candidate-object",
            "schema_version": 1,
            "request_fingerprint": request_fingerprint,
            "object_kind": kind,
            "geometry_fingerprint": geometry_fingerprint,
            "occurrence": occurrence,
        }
    )


def _typed_final_geometry(
    layout: BoardLayout,
    *,
    via_technology_id: str,
) -> tuple[
    tuple[
        RouteObjectKind,
        RouteSegmentGeometry | RouteViaGeometry | RouteZoneGeometry,
    ],
    ...,
]:
    return (
        *((RouteObjectKind.SEGMENT, _segment_geometry(item)) for item in layout.segments),
        *(
            (RouteObjectKind.VIA, _via_geometry(item, technology_id=via_technology_id))
            for item in layout.vias
        ),
        *((RouteObjectKind.ZONE, _zone_geometry(item)) for item in layout.zones),
    )


def _route_deltas(
    *,
    request: RouteRequest,
    source_records: tuple[NativeRouteObjectBinding, ...],
    final_layout: BoardLayout,
    via_technology_id: str,
) -> tuple[
    tuple[RouteSegmentDelta, ...],
    tuple[RouteViaDelta, ...],
    tuple[RouteZoneDelta, ...],
]:
    source_by_geometry: dict[
        tuple[RouteObjectKind, str],
        deque[NativeRouteObjectBinding],
    ] = defaultdict(deque)
    for item in source_records:
        source_by_geometry[
            (item.identity.object_kind, item.geometry.semantic_fingerprint())
        ].append(item)

    additions: list[
        tuple[
            RouteObjectKind,
            str,
            RouteSegmentGeometry | RouteViaGeometry | RouteZoneGeometry,
        ]
    ] = []
    candidate_occurrences: dict[tuple[RouteObjectKind, str], int] = defaultdict(int)
    for kind, geometry in _typed_final_geometry(
        final_layout,
        via_technology_id=via_technology_id,
    ):
        geometry_fingerprint = geometry.semantic_fingerprint()
        retained = source_by_geometry[(kind, geometry_fingerprint)]
        if retained:
            retained.popleft()
            continue
        occurrence_key = (kind, geometry_fingerprint)
        occurrence = candidate_occurrences[occurrence_key]
        candidate_occurrences[occurrence_key] += 1
        additions.append(
            (
                kind,
                _candidate_object_id(
                    request_fingerprint=request.semantic_fingerprint(),
                    kind=kind,
                    geometry_fingerprint=geometry_fingerprint,
                    occurrence=occurrence,
                ),
                geometry,
            )
        )
    removals = tuple(
        sorted(
            (item for remaining in source_by_geometry.values() for item in remaining),
            key=lambda item: (item.identity.object_kind, item.identity.object_id),
        )
    )
    additions.sort(key=lambda item: (item[0], item[1]))

    segment_deltas: list[RouteSegmentDelta] = []
    via_deltas: list[RouteViaDelta] = []
    zone_deltas: list[RouteZoneDelta] = []

    for item in removals:
        identity = item.identity
        mutation_id = f"mutation:remove:{identity.object_id}"
        if identity.object_kind is RouteObjectKind.SEGMENT:
            assert isinstance(item.geometry, RouteSegmentGeometry)
            segment_deltas.append(
                RouteSegmentDelta(
                    mutation_id=mutation_id,
                    operation=RouteMutationKind.REMOVE,
                    object_id=identity.object_id,
                    source_object_id=identity.object_id,
                    source_object_fingerprint=identity.source_object_fingerprint,
                    before=item.geometry,
                )
            )
        elif identity.object_kind is RouteObjectKind.VIA:
            assert isinstance(item.geometry, RouteViaGeometry)
            via_deltas.append(
                RouteViaDelta(
                    mutation_id=mutation_id,
                    operation=RouteMutationKind.REMOVE,
                    object_id=identity.object_id,
                    source_object_id=identity.object_id,
                    source_object_fingerprint=identity.source_object_fingerprint,
                    before=item.geometry,
                )
            )
        else:
            assert isinstance(item.geometry, RouteZoneGeometry)
            zone_deltas.append(
                RouteZoneDelta(
                    mutation_id=mutation_id,
                    operation=RouteMutationKind.REMOVE,
                    object_id=identity.object_id,
                    source_object_id=identity.object_id,
                    source_object_fingerprint=identity.source_object_fingerprint,
                    before=item.geometry,
                )
            )
    for kind, object_id, geometry in additions:
        mutation_id = f"mutation:add:{object_id}"
        if kind is RouteObjectKind.SEGMENT:
            assert isinstance(geometry, RouteSegmentGeometry)
            segment_deltas.append(
                RouteSegmentDelta(
                    mutation_id=mutation_id,
                    operation=RouteMutationKind.ADD,
                    object_id=object_id,
                    after=geometry,
                )
            )
        elif kind is RouteObjectKind.VIA:
            assert isinstance(geometry, RouteViaGeometry)
            via_deltas.append(
                RouteViaDelta(
                    mutation_id=mutation_id,
                    operation=RouteMutationKind.ADD,
                    object_id=object_id,
                    after=geometry,
                )
            )
        else:
            assert isinstance(geometry, RouteZoneGeometry)
            zone_deltas.append(
                RouteZoneDelta(
                    mutation_id=mutation_id,
                    operation=RouteMutationKind.ADD,
                    object_id=object_id,
                    after=geometry,
                )
            )
    return (
        tuple(segment_deltas),
        tuple(via_deltas),
        tuple(zone_deltas),
    )


def native_layout_route_deltas(
    *,
    request: RouteRequest,
    source_layout: BoardLayout,
    final_layout: BoardLayout,
    via_technology_id: str | None = None,
) -> tuple[
    tuple[RouteSegmentDelta, ...],
    tuple[RouteViaDelta, ...],
    tuple[RouteZoneDelta, ...],
]:
    """Diff detached native layouts through the stable route-object boundary."""

    technology_id = via_technology_id or _native_via_technology_id(request)
    source_records = native_source_route_object_bindings(
        source_layout,
        source_board_sha256=request.inputs.board_sha256,
        via_technology_id=technology_id,
    )
    if tuple(item.identity for item in source_records) != request.source_route_objects:
        raise ValueError("route request source-copper inventory is stale")
    return _route_deltas(
        request=request,
        source_records=source_records,
        final_layout=final_layout,
        via_technology_id=technology_id,
    )


def _failure_from_route(
    route_result: BoardRouteResult,
) -> RouteFailureEvidence:
    reason = route_result.run_result.failure_reason
    if reason is None:
        kind = RouteFailureKind.ENGINE_FAILURE
        message = "native router returned an incomplete result without a typed reason"
        resources: tuple[str, ...] = ()
    elif reason.value in {"expansion_budget", "pass_budget", "stagnation"}:
        kind = RouteFailureKind.BUDGET_EXHAUSTED
        message = f"native router exhausted {reason.value}"
        resources = (reason.value,)
    elif reason.value == "unroutable":
        kind = RouteFailureKind.UNROUTABLE
        message = "native router could not complete the requested nets"
        resources = ()
    else:
        kind = RouteFailureKind.ENGINE_FAILURE
        message = f"native router terminated with {reason.value}"
        resources = (reason.value,)
    return RouteFailureEvidence(
        failure_id=f"failure:native:{kind.value}",
        kind=kind,
        message=message,
        net_names=route_result.run_result.unresolved_net_names,
        resource_ids=resources,
    )


def _termination_from_route(
    route_result: BoardRouteResult,
    *,
    elapsed_seconds: float,
) -> RouteTerminationEvidence:
    reason = route_result.run_result.failure_reason
    if route_result.run_result.success:
        state = RouteTerminationState.COMPLETED
        text = "native router completed"
        exhausted: tuple[str, ...] = ()
    elif reason is not None and reason.value in {"expansion_budget", "pass_budget", "stagnation"}:
        state = RouteTerminationState.BUDGET_EXHAUSTED
        text = reason.value
        exhausted = (reason.value,)
    else:
        state = RouteTerminationState.FAILED
        text = "unknown_failure" if reason is None else reason.value
        exhausted = ()
    return RouteTerminationEvidence(
        state=state,
        reason=text,
        exit_code=None,
        stdout_sha256=_EMPTY_SHA256,
        stderr_sha256=_EMPTY_SHA256,
        elapsed_seconds=elapsed_seconds,
        exhausted_budget_fields=exhausted,
    )


def _validate_request_against_native_inputs(
    *,
    request: RouteRequest,
    layout: BoardLayout,
    netlist: BoardNetlist,
    profile: PcbRuleProfile,
    via_technology_id: str,
) -> tuple[NativeRouteObjectBinding, ...]:
    if request.inputs.netlist_sha256 != native_routing_netlist_fingerprint(netlist):
        raise ValueError("route request netlist identity is stale")
    if request.inputs.rules_sha256 != native_routing_profile_fingerprint(profile):
        raise ValueError("route request rule-profile identity is stale")
    terminal_ids = _netlist_terminal_ids(netlist)
    for domain in request.target_domains:
        for target in domain.nets:
            if terminal_ids.get(target.net_name) != target.terminal_object_ids:
                raise ValueError("route request target terminal inventory is stale")
    records = native_source_route_object_bindings(
        layout,
        source_board_sha256=request.inputs.board_sha256,
        via_technology_id=via_technology_id,
    )
    if tuple(item.identity for item in records) != request.source_route_objects:
        raise ValueError("route request source-copper inventory is stale")
    return records


def _pairwise_clearance_groups(
    request: RouteRequest,
    profile: PcbRuleProfile,
) -> tuple[tuple[tuple[str, ...], tuple[str, ...], float, tuple[str, ...]], ...]:
    return tuple(
        (
            constraint.net_names,
            constraint.other_net_names,
            constraint.minimum_clearance_mm,
            (),
        )
        for constraint in request.clearance_constraints
        if constraint.minimum_clearance_mm > profile.fab_spacing.minimum_copper_clearance_mm
        if constraint.other_net_names
    )


def _native_via_technology_id(request: RouteRequest) -> str:
    if request.via_technologies:
        return request.via_technologies[0].technology_id
    return "via:through-default"


def _translation_failure_result(
    *,
    request: RouteRequest,
    consumption: tuple[ConstraintConsumption, ...],
    failures: tuple[RouteFailureEvidence, ...],
    engine: RoutingEngineIdentity,
) -> RouteCandidateResult:
    result = RouteCandidateResult(
        request_fingerprint=request.semantic_fingerprint(),
        source_board_sha256=request.inputs.board_sha256,
        engine=engine,
        termination=RouteTerminationEvidence(
            state=RouteTerminationState.FAILED,
            reason="constraint_translation_failed",
            exit_code=None,
            stdout_sha256=_EMPTY_SHA256,
            stderr_sha256=_EMPTY_SHA256,
            elapsed_seconds=0.0,
        ),
        partial_status=PartialCandidateStatus.FAILED_NO_DELTA,
        constraint_consumption=consumption,
        failures=failures,
    )
    validate_route_candidate_result(request, result)
    return result


def route_native_candidate(
    *,
    request: RouteRequest,
    layout: BoardLayout,
    netlist: BoardNetlist,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    engine_source_commit: str = "working-tree",
    native_serialization: bool = False,
    plane_pour: NativePlanePour | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> RouteCandidateResult:
    """Run the existing native router through the immutable H0 boundary."""

    if request.budget.external_process_seconds is not None:
        raise ValueError("native router requires its native expansion budget")

    engine = RoutingEngineIdentity(
        engine_id="pcbsmith-native-astar",
        engine_version="1",
        adapter_id="pcbsmith.kicad.routing_candidate_adapter",
        adapter_version="1",
        source_commit=engine_source_commit,
    )
    via_technology_id = _native_via_technology_id(request)
    source_records = _validate_request_against_native_inputs(
        request=request,
        layout=layout,
        netlist=netlist,
        profile=profile,
        via_technology_id=via_technology_id,
    )
    if plane_pour is not None:
        if plane_pour.constraint_id not in request.additional_constraint_ids:
            raise ValueError("plane pour is not bound to this request")
        plane_pour.zone(layout, request)
    consumption, translation_failures = _translation_consumption(
        request,
        profile=profile,
        plane_pour=plane_pour,
    )
    if translation_failures:
        return _translation_failure_result(
            request=request,
            consumption=consumption,
            failures=translation_failures,
            engine=engine,
        )

    target_nets = tuple(
        net_name
        for domain in sorted(
            request.target_domains,
            key=lambda item: (item.priority, item.domain_id),
        )
        for net_name in domain.net_names
    )
    all_net_names = {net.name for net in netlist.nets}
    skip_nets = all_net_names - set(target_nets)
    widths = {
        net_name: constraint.preferred_width_mm
        for constraint in request.width_constraints
        for net_name in constraint.net_names
    }
    started = clock()
    if native_serialization and (layout.segments or layout.vias or layout.zones):
        raise ValueError("native precision conversion requires an unrouted source")
    route_result = route_board(
        layout,
        netlist,
        net_widths=widths,
        profile=profile,
        clearance_groups=_pairwise_clearance_groups(request, profile),
        net_order=request.deterministic.route_order,
        max_restarts=max(0, (request.budget.max_passes // 2) - 1),
        max_passes=request.budget.max_passes,
        max_stagnant_passes=request.budget.max_stagnant_passes,
        max_expansions=request.budget.max_expansions,
        max_expansions_per_net=request.budget.max_expansions_per_net,
        skip_nets=(*skip_nets, plane_pour.net_name)
        if plane_pour is not None and plane_pour.connect_by_plane
        else skip_nets,
    )
    elapsed = max(0.0, clock() - started)
    final_layout = route_result.layout
    if native_serialization:
        origin = Decimal(str(BOARD_SHEET_ORIGIN_MM))

        def coordinate(value: float) -> float:
            return float(Decimal(_mm(value + BOARD_SHEET_ORIGIN_MM)) - origin)

        final_layout = replace(
            final_layout,
            segments=tuple(
                replace(
                    s,
                    x1=coordinate(s.x1),
                    y1=coordinate(s.y1),
                    x2=coordinate(s.x2),
                    y2=coordinate(s.y2),
                    width_mm=float(_mm(s.width_mm)),
                )
                for s in final_layout.segments
            ),
            vias=tuple(
                replace(
                    v,
                    x=coordinate(v.x),
                    y=coordinate(v.y),
                    size_mm=float(_mm(v.size_mm)),
                    drill_mm=float(_mm(v.drill_mm)),
                )
                for v in final_layout.vias
            ),
        )
    if plane_pour is not None and route_result.run_result.success:
        final_layout = replace(
            final_layout, zones=(*final_layout.zones, plane_pour.zone(final_layout, request))
        )
    segment_deltas, via_deltas, zone_deltas = _route_deltas(
        request=request,
        source_records=source_records,
        final_layout=final_layout,
        via_technology_id=via_technology_id,
    )
    has_delta = bool(segment_deltas or via_deltas or zone_deltas)
    if route_result.run_result.success:
        partial_status = PartialCandidateStatus.COMPLETE
        failures: tuple[RouteFailureEvidence, ...] = ()
    else:
        partial_status = (
            PartialCandidateStatus.BOUNDED_PARTIAL
            if has_delta
            else PartialCandidateStatus.FAILED_NO_DELTA
        )
        failures = (_failure_from_route(route_result),)
    result = RouteCandidateResult(
        request_fingerprint=request.semantic_fingerprint(),
        source_board_sha256=request.inputs.board_sha256,
        engine=engine,
        termination=_termination_from_route(
            route_result,
            elapsed_seconds=elapsed,
        ),
        partial_status=partial_status,
        segment_deltas=segment_deltas,
        via_deltas=via_deltas,
        zone_deltas=zone_deltas,
        constraint_consumption=consumption,
        failures=failures,
        run_telemetry=route_result.run_result,
    )
    validate_route_candidate_result(request, result)
    return result


def native_any_tree_topology_constraints(
    domains: Sequence[tuple[str, Sequence[tuple[str, Sequence[str]]]]],
) -> tuple[RouteTopologyConstraint, ...]:
    """Convenience builder for the exact topology the legacy router supports."""

    return tuple(
        RouteTopologyConstraint(
            constraint_id=f"constraint:topology:{domain_id}:{net_name}",
            domain_id=domain_id,
            net_name=net_name,
            topology_kind="any_tree",
            ordered_terminal_object_ids=tuple(terminal_ids),
        )
        for domain_id, nets in domains
        for net_name, terminal_ids in nets
    )
