"""Fail-closed declaration authority for physical ordered-bus swap regions.

This module deliberately stops before carrier search.  A semantic
``BusSwapEvent`` is retained and checked, but is never represented as routed
copper or as a successful physical crossover.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Literal, Self, TypeAlias

from pydantic import Field, StrictInt, field_validator, model_validator

from pcbsmith.bus_allocator import BusLaneAllocationResult, BusSwapEvent, allocate_bus_lanes
from pcbsmith.bus_geometry import (
    CertifiedLaneGeometry,
    CertifiedLaneGeometryRegistry,
    GridPoint,
    certified_keep_in_fingerprint,
)
from pcbsmith.bus_ir import BusGroup, BusLayer, BusViaPolicy, CorridorCapacityCertificate
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.routing_ir import RoutingIrModel
from pcbsmith.rule_profiles import PcbRuleProfile

LayerGridNode: TypeAlias = tuple[BusLayer, StrictInt, StrictInt]
SwapGraphTransition: TypeAlias = tuple[LayerGridNode, LayerGridNode]


def _fingerprint(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def bus_physical_swap_profile_fingerprint(profile: PcbRuleProfile) -> str:
    """Bind the complete rule-profile schema used by this authority."""

    return _fingerprint(
        {
            "schema_id": "pcbsmith-bus-physical-swap-profile",
            "schema_version": 1,
            "profile": profile.model_dump(mode="json"),
        }
    )


def bus_physical_swap_board_geometry_fingerprint(layout: BoardLayout) -> str:
    """Fingerprint exact neutral board-boundary geometry."""

    normalized = json.loads(canonical_board_layout_snapshot_json(layout))
    return _fingerprint(
        {
            "schema_id": "pcbsmith-bus-physical-swap-board-geometry",
            "schema_version": 1,
            "width_mm": normalized["width_mm"],
            "height_mm": normalized["height_mm"],
            "outline": normalized["outline"],
            "cutouts": normalized["cutouts"],
        }
    )


def bus_physical_swap_static_obstacle_fingerprint(
    layout: BoardLayout,
    netlist: BoardNetlist,
) -> str:
    """Fingerprint all neutral inputs accepted as exact static authority."""

    return _fingerprint(
        {
            "schema_id": "pcbsmith-bus-physical-swap-static-obstacles",
            "schema_version": 1,
            "layout": json.loads(canonical_board_layout_snapshot_json(layout)),
            "netlist": json.loads(canonical_board_netlist_snapshot_json(netlist)),
        }
    )


class BusPhysicalSwapBudget(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-physical-swap-budget"] = "pcbsmith-bus-physical-swap-budget"
    schema_version: Literal[1] = 1
    max_events: StrictInt = Field(ge=0)
    max_candidates_per_event: StrictInt = Field(ge=0)
    max_expansions_per_candidate: StrictInt = Field(ge=0)


class BusPhysicalSwapWindowPolicy(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-physical-swap-window-policy"] = (
        "pcbsmith-bus-physical-swap-window-policy"
    )
    schema_version: Literal[1] = 1
    window_id: str = Field(min_length=1)
    bridge_layer: BusLayer
    via_process_id: str = Field(min_length=1)
    vias_per_swap: Literal[2] = 2


class BusPhysicalSwapPolicy(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-physical-swap-policy"] = "pcbsmith-bus-physical-swap-policy"
    schema_version: Literal[1] = 1
    windows: tuple[BusPhysicalSwapWindowPolicy, ...] = ()
    maximum_physical_vias_per_member: StrictInt = Field(ge=0)
    maximum_combined_vias_per_member: StrictInt = Field(ge=0)
    maximum_combined_via_count_spread: StrictInt = Field(ge=0)
    budget: BusPhysicalSwapBudget

    @model_validator(mode="after")
    def mappings_are_canonical(self) -> Self:
        windows = tuple(sorted(self.windows, key=lambda item: item.window_id))
        if len({item.window_id for item in windows}) != len(windows):
            raise ValueError("physical-swap window mappings must be unique")
        if self.maximum_physical_vias_per_member < 2:
            raise ValueError("physical-swap policy must permit the required two crossover vias")
        if self.maximum_combined_vias_per_member < self.maximum_physical_vias_per_member:
            raise ValueError("combined via maximum cannot be below the physical via maximum")
        object.__setattr__(self, "windows", windows)
        return self


class BusSwapMemberPortalAuthority(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-swap-member-portals"] = "pcbsmith-bus-swap-member-portals"
    schema_version: Literal[1] = 1
    member_id: str = Field(min_length=1)
    incoming_section_id: str = Field(min_length=1)
    outgoing_section_id: str = Field(min_length=1)
    incoming_geometry_id: str = Field(min_length=1)
    outgoing_geometry_id: str = Field(min_length=1)
    incoming_portal_id: str = Field(min_length=1)
    outgoing_portal_id: str = Field(min_length=1)
    incoming_portal_point: GridPoint
    outgoing_portal_point: GridPoint


class CertifiedBusSwapRegion(RoutingIrModel):
    """Replay-bound search-space declaration for one semantic swap event.

    No field in this model is a carrier, copper realization, route claim, or
    physical-success result.
    """

    schema_id: Literal["pcbsmith-certified-bus-swap-region"] = "pcbsmith-certified-bus-swap-region"
    schema_version: Literal[1] = 1
    region_id: str = Field(min_length=1)
    layout_snapshot_json: str = Field(min_length=2)
    netlist_snapshot_json: str = Field(min_length=2)
    layout_snapshot_fingerprint: str
    netlist_snapshot_fingerprint: str
    bus: BusGroup
    certificate: CorridorCapacityCertificate
    allocation: BusLaneAllocationResult
    lane_geometry_registry: CertifiedLaneGeometryRegistry
    rule_profile: PcbRuleProfile
    swap_event: BusSwapEvent
    physical_policy: BusPhysicalSwapPolicy
    keep_in_polygon: tuple[GridPoint, ...] = Field(min_length=3)
    keep_in_fingerprint: str
    allowed_nodes: tuple[LayerGridNode, ...] = Field(min_length=1)
    allowed_transitions: tuple[SwapGraphTransition, ...] = Field(min_length=1)
    allowed_via_cells: tuple[GridPoint, ...] = Field(min_length=2)
    member_portals: tuple[BusSwapMemberPortalAuthority, ...] = Field(min_length=2)
    bridge_layer: BusLayer
    region_fingerprint: str

    @field_validator(
        "layout_snapshot_fingerprint",
        "netlist_snapshot_fingerprint",
        "keep_in_fingerprint",
        "region_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError(f"{info.field_name} must be a lowercase SHA-256 digest")
        return value

    @model_validator(mode="after")
    def authority_is_complete(self) -> Self:
        layout = parse_canonical_board_layout_snapshot(self.layout_snapshot_json)
        netlist = parse_canonical_board_netlist_snapshot(self.netlist_snapshot_json)
        if self.layout_snapshot_fingerprint != board_layout_snapshot_fingerprint(
            self.layout_snapshot_json
        ):
            raise ValueError("layout snapshot fingerprint is stale")
        if self.netlist_snapshot_fingerprint != board_netlist_snapshot_fingerprint(
            self.netlist_snapshot_json
        ):
            raise ValueError("netlist snapshot fingerprint is stale")
        if layout.placements or layout.graphics:
            raise ValueError(
                "physical-swap authority cannot infer opaque footprint or raw graphic obstacles"
            )
        if layout.zones:
            raise ValueError(
                "physical-swap authority cannot infer the exact result of an unfilled copper zone"
            )
        if any(segment.layer not in {"F.Cu", "B.Cu"} for segment in layout.segments):
            raise ValueError("physical-swap authority found an unsupported static copper layer")

        bus_fp = self.bus.semantic_fingerprint()
        certificate_fp = self.certificate.semantic_fingerprint()
        allocation_fp = self.allocation.allocation_fingerprint
        if self.certificate.board_geometry_fingerprint != (
            bus_physical_swap_board_geometry_fingerprint(layout)
        ):
            raise ValueError("certificate board geometry is stale")
        if self.certificate.static_obstacle_fingerprint != (
            bus_physical_swap_static_obstacle_fingerprint(layout, netlist)
        ):
            raise ValueError("certificate static-obstacle authority is stale")
        if self.certificate.rule_profile_fingerprint != (
            bus_physical_swap_profile_fingerprint(self.rule_profile)
        ):
            raise ValueError("certificate rule profile is stale")
        if self.certificate.demand_fingerprint != bus_fp:
            raise ValueError("certificate bus demand is stale")
        if self.bus.rule_profile_id != self.rule_profile.profile_id:
            raise ValueError("bus and rule-profile identities differ")
        if self.allocation.bus_fingerprint != bus_fp:
            raise ValueError("allocation bus authority is stale")
        if self.allocation.certificate_fingerprint != certificate_fp:
            raise ValueError("allocation certificate authority is stale")
        if not self.allocation.success:
            raise ValueError("physical swaps require a successful semantic allocation")
        replay = allocate_bus_lanes(self.bus, self.certificate, budget=self.allocation.budget)
        if replay != self.allocation:
            raise ValueError("semantic lane allocation does not replay exactly")
        if self.lane_geometry_registry.certificate_fingerprint != certificate_fp:
            raise ValueError("lane registry certificate authority is stale")
        if self.lane_geometry_registry.allocation_fingerprint != allocation_fp:
            raise ValueError("lane registry allocation authority is stale")
        if self.lane_geometry_registry.grid_mm != self.certificate.grid_mm:
            raise ValueError("lane registry grid differs from its certificate")

        self._validate_netlist(netlist)
        self._validate_policy()
        self._validate_semantic_events()
        self._validate_geometry_registry()
        canonical_polygon = _canonical_polygon(self.keep_in_polygon)
        if self.keep_in_polygon != canonical_polygon:
            object.__setattr__(self, "keep_in_polygon", canonical_polygon)
        if self.keep_in_fingerprint != certified_keep_in_fingerprint(
            self.certificate.grid_mm, canonical_polygon
        ):
            raise ValueError("swap-region keep-in fingerprint is stale")
        self._validate_graph(canonical_polygon)
        self._validate_member_portals()

        expected_region_fp = _fingerprint(
            {
                "schema_id": "pcbsmith-certified-bus-swap-region-decision",
                "schema_version": 1,
                "region": self.model_dump(mode="json", exclude={"region_fingerprint"}),
            }
        )
        if self.region_fingerprint != expected_region_fp:
            raise ValueError("region_fingerprint must bind the complete declaration")
        return self

    def require_authority(self) -> Self:
        """Revalidate all nested authority through exact JSON reconstruction."""

        replay = type(self).model_validate_json(self.model_dump_json())
        if replay != self:
            raise ValueError("physical-swap authority changed during JSON reconstruction")
        return self

    @property
    def layout(self) -> BoardLayout:
        return parse_canonical_board_layout_snapshot(self.layout_snapshot_json)

    @property
    def netlist(self) -> BoardNetlist:
        return parse_canonical_board_netlist_snapshot(self.netlist_snapshot_json)

    def _validate_netlist(self, netlist: BoardNetlist) -> None:
        component_ids = {item.reference for item in netlist.components}
        net_by_name = {item.name: set(item.nodes) for item in netlist.nets}
        if len(component_ids) != len(netlist.components) or len(net_by_name) != len(netlist.nets):
            raise ValueError("board netlist identities must be unique")
        for member in self.bus.members:
            nodes = net_by_name.get(member.net_name)
            if nodes is None:
                raise ValueError("board netlist is missing a bus-member net")
            for terminal in member.terminals:
                if terminal.component_ref not in component_ids:
                    raise ValueError("board netlist is missing a bus-terminal component")
                if (terminal.component_ref, terminal.pad_number) not in nodes:
                    raise ValueError("board netlist bus-terminal ownership is stale")

    def _validate_policy(self) -> None:
        events = self.allocation.swaps
        event_windows = {item.window_id for item in events}
        mappings = {item.window_id: item for item in self.physical_policy.windows}
        if set(mappings) != event_windows:
            raise ValueError("physical policy must map exactly every semantic swap window")
        budget = self.physical_policy.budget
        if len(events) > budget.max_events:
            raise ValueError("physical-swap event budget is insufficient")
        if budget.max_candidates_per_event < 2:
            raise ValueError("physical-swap candidate budget must cover both bridge members")
        if budget.max_expansions_per_candidate < 1:
            raise ValueError("physical-swap expansion budget must be positive")
        via_policy = self.bus.layer_policy.via_policy
        if via_policy.mode in {"forbidden", "escape_only"}:
            raise ValueError("bus via policy forbids physical corridor crossovers")
        semantic_counts = {item.member_id: item.via_count for item in self.allocation.via_counts}
        for event in events:
            mapping = mappings[event.window_id]
            if mapping.bridge_layer == event.layer:
                raise ValueError("physical-swap bridge layer must oppose the event layer")
            if {mapping.bridge_layer, event.layer} != {"F.Cu", "B.Cu"}:
                raise ValueError("schema-v1 physical swaps require the two copper layers")
            section = next(
                (item for item in self.certificate.sections if item.section_id == event.section_id),
                None,
            )
            if section is None:
                raise ValueError("physical-swap event names an unknown section")
            if via_policy.mode in {"declared_transition_windows", "synchronous"} and (
                event.window_id not in via_policy.transition_window_ids
                or event.window_id not in section.transition_window_ids
            ):
                raise ValueError("physical swap lacks its required declared transition window")
        if not physical_swap_via_assignment_is_feasible(
            events=events,
            semantic_via_counts=semantic_counts,
            physical_policy=self.physical_policy,
            bus_via_policy=via_policy,
        ):
            raise ValueError("no complete bridge-member assignment satisfies combined via limits")

    def _validate_semantic_events(self) -> None:
        if self.swap_event not in self.allocation.swaps:
            raise ValueError("region does not retain an exact allocation swap event")
        event_sections = [item.section_id for item in self.allocation.swaps]
        if len(set(event_sections)) != len(event_sections):
            raise ValueError(
                "schema-v1 physical swaps allow at most one event per corridor section"
            )
        boundaries = {item.boundary_id: item for item in self.bus.boundaries}
        windows = {item.window_id: item for item in self.bus.permutation_policy.swap_windows}
        for section_index, section in enumerate(self.certificate.sections):
            events = tuple(
                item for item in self.allocation.swaps if item.section_id == section.section_id
            )
            if not events:
                continue
            if tuple(item.sequence_index for item in events) != tuple(range(len(events))):
                raise ValueError("swap-event sequence is incomplete or noncanonical")
            exit_boundary = self.bus.boundaries[section_index + 1]
            incoming = self.allocation.normalized_boundary_orders[section_index]
            outgoing = self.allocation.normalized_boundary_orders[section_index + 1]
            common = set(incoming) & set(outgoing)
            current = [item for item in incoming if item in common]
            target = [item for item in outgoing if item in common]
            for event in events:
                window = windows.get(event.window_id)
                if (
                    event.exit_boundary_id != exit_boundary.boundary_id
                    or event.exit_boundary_id not in boundaries
                    or event.window_id not in section.swap_window_ids
                    or window is None
                    or window.corridor_region_id != section.section_id
                    or event.layer not in window.allowed_layers
                    or tuple(sorted((event.first_member_id, event.second_member_id)))
                    not in window.allowed_adjacent_pairs
                ):
                    raise ValueError("swap event is stale against its section/window authority")
                index = event.order_index
                if index + 1 >= len(current) or tuple(current[index : index + 2]) != (
                    event.first_member_id,
                    event.second_member_id,
                ):
                    raise ValueError("swap event members are not the declared adjacent order")
                current[index], current[index + 1] = current[index + 1], current[index]
            if current != target:
                raise ValueError("swap events do not produce the exact outgoing permutation")

    def _validate_geometry_registry(self) -> None:
        slots = {
            (section.section_id, slot.slot_id): slot
            for section in self.certificate.sections
            for slot in section.lane_slots
        }
        expected_ids: set[str] = set()
        members = {item.member_id: item for item in self.bus.members}
        geometries = {
            item.centerline_geometry_id: item for item in self.lane_geometry_registry.geometries
        }
        for assignment in self.allocation.assignments:
            slot = slots.get((assignment.section_id, assignment.slot_id))
            if slot is None or slot.layer != assignment.layer:
                raise ValueError("allocation assignment is stale against its certified slot")
            member = members.get(assignment.member_id)
            geometry = geometries.get(slot.centerline_geometry_id)
            if member is None or geometry is None:
                raise ValueError("assigned physical-swap width authority is incomplete")
            if (
                geometry.track_width_mm != member.width_mm
                or member.width_mm > slot.maximum_track_width_mm
                or member.width_mm < self.rule_profile.geometry.minimum_trace_width_mm
            ):
                raise ValueError("assigned physical-swap track width authority is stale")
            expected_ids.add(slot.centerline_geometry_id)
        actual_ids = {
            item.centerline_geometry_id for item in self.lane_geometry_registry.geometries
        }
        if actual_ids != expected_ids:
            raise ValueError("lane registry must contain exactly the assigned geometries")

    def _validate_graph(self, polygon: tuple[GridPoint, ...]) -> None:
        nodes = tuple(sorted(self.allowed_nodes))
        if len(set(nodes)) != len(nodes):
            raise ValueError("swap-region graph nodes must be unique")
        if {item[0] for item in nodes} != {"F.Cu", "B.Cu"}:
            raise ValueError("swap-region graph must explicitly declare both copper layers")
        if any(item[1] < 0 or item[2] < 0 for item in nodes):
            raise ValueError("swap-region graph coordinates must be non-negative")
        if any(not _point_in_or_on_polygon((item[1], item[2]), polygon) for item in nodes):
            raise ValueError("swap-region graph node leaves its lattice keep-in")
        via_cells = tuple(sorted(self.allowed_via_cells))
        if len(set(via_cells)) != len(via_cells):
            raise ValueError("allowed via cells must be unique")
        if any((layer, *cell) not in nodes for cell in via_cells for layer in ("F.Cu", "B.Cu")):
            raise ValueError("every allowed via cell requires an explicit node on both layers")
        transitions: list[SwapGraphTransition] = []
        vertical_cells: set[GridPoint] = set()
        for first, second in self.allowed_transitions:
            edge = (first, second) if first < second else (second, first)
            if first not in nodes or second not in nodes or first == second:
                raise ValueError("swap-region transition references an invalid graph node")
            if first[0] == second[0]:
                if max(abs(first[1] - second[1]), abs(first[2] - second[2])) != 1:
                    raise ValueError("same-layer swap transitions must join adjacent cells")
            else:
                if first[1:] != second[1:]:
                    raise ValueError("layer transitions must remain at one via cell")
                vertical_cells.add((first[1], first[2]))
            transitions.append(edge)
        canonical_transitions = tuple(sorted(transitions))
        if len(set(canonical_transitions)) != len(canonical_transitions):
            raise ValueError("swap-region transitions must be unique")
        if vertical_cells != set(via_cells):
            raise ValueError("allowed via cells and explicit layer transitions must agree exactly")
        adjacency: dict[LayerGridNode, set[LayerGridNode]] = {item: set() for item in nodes}
        for first, second in canonical_transitions:
            adjacency[first].add(second)
            adjacency[second].add(first)
        reached = {nodes[0]}
        pending = [nodes[0]]
        while pending:
            current = pending.pop()
            for neighbour in adjacency[current]:
                if neighbour not in reached:
                    reached.add(neighbour)
                    pending.append(neighbour)
        if reached != set(nodes):
            raise ValueError("swap-region graph must be connected")
        object.__setattr__(self, "allowed_nodes", nodes)
        object.__setattr__(self, "allowed_transitions", canonical_transitions)
        object.__setattr__(self, "allowed_via_cells", via_cells)

    def _validate_member_portals(self) -> None:
        portals = tuple(sorted(self.member_portals, key=lambda item: item.member_id))
        event_members = {self.swap_event.first_member_id, self.swap_event.second_member_id}
        if {item.member_id for item in portals} != event_members or len(portals) != 2:
            raise ValueError("swap region requires exact portal authority for both event members")
        mapping = {item.window_id: item for item in self.physical_policy.windows}[
            self.swap_event.window_id
        ]
        if self.bridge_layer != mapping.bridge_layer or self.bridge_layer == self.swap_event.layer:
            raise ValueError("region bridge layer differs from its physical policy")
        section_positions = {
            item.section_id: index for index, item in enumerate(self.certificate.sections)
        }
        position = section_positions[self.swap_event.section_id]
        if position + 1 >= len(self.certificate.sections):
            raise ValueError("swap carrier requires a following certified corridor section")
        incoming_section = self.certificate.sections[position]
        outgoing_section = self.certificate.sections[position + 1]
        assignments = {
            (item.section_id, item.member_id): item for item in self.allocation.assignments
        }
        slot_by_key = {
            (section.section_id, slot.slot_id): slot
            for section in self.certificate.sections
            for slot in section.lane_slots
        }
        geometry_by_id = {
            item.centerline_geometry_id: item for item in self.lane_geometry_registry.geometries
        }
        for portal in portals:
            incoming_assignment = assignments.get((incoming_section.section_id, portal.member_id))
            outgoing_assignment = assignments.get((outgoing_section.section_id, portal.member_id))
            if incoming_assignment is None or outgoing_assignment is None:
                raise ValueError("swap portal member lacks adjacent section assignments")
            incoming = _assigned_geometry(
                incoming_assignment.slot_id,
                incoming_section,
                slot_by_key,
                geometry_by_id,
            )
            outgoing = _assigned_geometry(
                outgoing_assignment.slot_id,
                outgoing_section,
                slot_by_key,
                geometry_by_id,
            )
            if (
                incoming_assignment.layer != self.swap_event.layer
                or outgoing_assignment.layer != self.swap_event.layer
                or incoming.layer != self.swap_event.layer
                or outgoing.layer != self.swap_event.layer
            ):
                raise ValueError("swap endpoint geometries must return to the event layer")
            expected = (
                incoming_section.section_id,
                outgoing_section.section_id,
                incoming.centerline_geometry_id,
                outgoing.centerline_geometry_id,
                incoming.exit_portal_id,
                outgoing.entry_portal_id,
                incoming.exit_portal_point,
                outgoing.entry_portal_point,
            )
            actual = (
                portal.incoming_section_id,
                portal.outgoing_section_id,
                portal.incoming_geometry_id,
                portal.outgoing_geometry_id,
                portal.incoming_portal_id,
                portal.outgoing_portal_id,
                portal.incoming_portal_point,
                portal.outgoing_portal_point,
            )
            if actual != expected:
                raise ValueError("swap member portal identity or point is stale")
            if (self.swap_event.layer, *portal.incoming_portal_point) not in self.allowed_nodes or (
                self.swap_event.layer,
                *portal.outgoing_portal_point,
            ) not in self.allowed_nodes:
                raise ValueError("swap endpoint portal is absent from the declared graph")
        object.__setattr__(self, "member_portals", portals)


def certified_bus_swap_region_fingerprint(payload: dict[str, Any]) -> str:
    """Compute the final fingerprint for a complete region constructor payload."""

    return _fingerprint(
        {
            "schema_id": "pcbsmith-certified-bus-swap-region-decision",
            "schema_version": 1,
            "region": payload,
        }
    )


def physical_swap_via_assignment_is_feasible(
    *,
    events: tuple[BusSwapEvent, ...],
    semantic_via_counts: dict[str, int],
    physical_policy: BusPhysicalSwapPolicy,
    bus_via_policy: BusViaPolicy,
) -> bool:
    """Exact DP feasibility for cumulative physical and combined via limits.

    Each DP transition is one candidate bridge-member choice and adds the
    window policy's literal two vias.  State is only the complete physical-via
    count vector, so equivalent histories collapse without changing the exact
    feasibility result.  The event, candidate, and per-candidate expansion
    bounds are checked before work begins.
    """

    budget = physical_policy.budget
    if (
        len(events) > budget.max_events
        or budget.max_candidates_per_event < 2
        or budget.max_expansions_per_candidate < 1
    ):
        return False
    member_ids = tuple(sorted(semantic_via_counts))
    member_position = {member_id: index for index, member_id in enumerate(member_ids)}
    if any(
        event.first_member_id not in member_position
        or event.second_member_id not in member_position
        for event in events
    ):
        return False
    mapping_by_window = {item.window_id: item for item in physical_policy.windows}
    if any(event.window_id not in mapping_by_window for event in events):
        return False

    states: set[tuple[int, ...]] = {tuple(0 for _ in member_ids)}
    for event in events:
        mapping = mapping_by_window[event.window_id]
        next_states: set[tuple[int, ...]] = set()
        for state in sorted(states):
            for bridge_member in sorted((event.first_member_id, event.second_member_id)):
                candidate = list(state)
                position = member_position[bridge_member]
                candidate[position] += mapping.vias_per_swap
                if candidate[position] > physical_policy.maximum_physical_vias_per_member:
                    continue
                combined_count = semantic_via_counts[bridge_member] + candidate[position]
                if combined_count > physical_policy.maximum_combined_vias_per_member:
                    continue
                if combined_count > bus_via_policy.maximum_vias_per_member:
                    continue
                next_states.add(tuple(candidate))
        if not next_states:
            return False
        states = next_states

    for state in sorted(states):
        combined_counts = tuple(
            semantic_via_counts[member_id] + state[index]
            for index, member_id in enumerate(member_ids)
        )
        spread = max(combined_counts, default=0) - min(combined_counts, default=0)
        if spread > physical_policy.maximum_combined_via_count_spread:
            continue
        if (
            bus_via_policy.maximum_via_count_spread is not None
            and spread > bus_via_policy.maximum_via_count_spread
        ):
            continue
        return True
    return False


def _assigned_geometry(
    slot_id: str,
    section: Any,
    slot_by_key: dict[tuple[str, str], Any],
    geometry_by_id: dict[str, CertifiedLaneGeometry],
) -> CertifiedLaneGeometry:
    slot = slot_by_key.get((section.section_id, slot_id))
    if slot is None:
        raise ValueError("swap endpoint assignment names an unknown lane slot")
    geometry = geometry_by_id.get(slot.centerline_geometry_id)
    if geometry is None or geometry.section_id != section.section_id:
        raise ValueError("swap endpoint assignment names stale lane geometry")
    return geometry


def _canonical_polygon(points: tuple[GridPoint, ...]) -> tuple[GridPoint, ...]:
    if len(set(points)) != len(points):
        raise ValueError("swap keep-in vertices must be unique")
    if any(value < 0 for point in points for value in point):
        raise ValueError("swap keep-in vertices must be non-negative")
    area2 = sum(
        first[0] * second[1] - second[0] * first[1]
        for first, second in zip(points, (*points[1:], points[0]), strict=True)
    )
    if area2 == 0:
        raise ValueError("swap keep-in polygon must have non-zero area")
    _validate_simple_polygon(points)
    candidates: list[tuple[GridPoint, ...]] = []
    for sequence in (points, tuple(reversed(points))):
        for index in range(len(sequence)):
            candidates.append((*sequence[index:], *sequence[:index]))
    return min(candidates)


def _validate_simple_polygon(points: tuple[GridPoint, ...]) -> None:
    edges = tuple(zip(points, (*points[1:], points[0]), strict=True))
    for first_index, first in enumerate(edges):
        for second_index, second in enumerate(edges[first_index + 1 :], start=first_index + 1):
            if second_index in {first_index, first_index + 1} or (
                first_index == 0 and second_index == len(edges) - 1
            ):
                continue
            if _segments_intersect(first, second):
                raise ValueError("swap keep-in polygon must be simple")


def _segments_intersect(
    first: tuple[GridPoint, GridPoint],
    second: tuple[GridPoint, GridPoint],
) -> bool:
    a, b = first
    c, d = second

    def orientation(p: GridPoint, q: GridPoint, r: GridPoint) -> int:
        cross = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
        return (cross > 0) - (cross < 0)

    def on_segment(p: GridPoint, q: GridPoint, r: GridPoint) -> bool:
        return min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and min(p[1], r[1]) <= q[1] <= max(
            p[1], r[1]
        )

    o1, o2 = orientation(a, b, c), orientation(a, b, d)
    o3, o4 = orientation(c, d, a), orientation(c, d, b)
    if o1 != o2 and o3 != o4:
        return True
    return (
        (o1 == 0 and on_segment(a, c, b))
        or (o2 == 0 and on_segment(a, d, b))
        or (o3 == 0 and on_segment(c, a, d))
        or (o4 == 0 and on_segment(c, b, d))
    )


def _point_in_or_on_polygon(point: GridPoint, polygon: tuple[GridPoint, ...]) -> bool:
    x, y = point
    inside = False
    for first, second in zip(polygon, (*polygon[1:], polygon[0]), strict=True):
        x1, y1 = first
        x2, y2 = second
        cross = (x - x1) * (y2 - y1) - (y - y1) * (x2 - x1)
        if cross == 0 and min(x1, x2) <= x <= max(x1, x2) and min(y1, y2) <= y <= max(y1, y2):
            return True
        if (y1 > y) != (y2 > y):
            intersection_x = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if math.isclose(intersection_x, x) or intersection_x > x:
                inside = not inside
    return inside
