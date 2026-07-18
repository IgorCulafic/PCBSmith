"""Replay-bound input authority for a placement pilot.

This module retains inputs only.  It deliberately selects no placement or
routing algorithm and makes no claim about routing, exact acceptance, or
application readiness.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.corridor_ir import CorridorBudget, CorridorCostPolicy, CorridorViaPolicy
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.kicad.corridor_planner import CorridorGraphBuildBudget, OpaqueGraphicsPolicy
from pcbsmith.kicad.negotiated_graph import NegotiatedCostPolicy
from pcbsmith.kicad.placement_routability import (
    board_component_identity_fingerprint,
)
from pcbsmith.kicad.placement_routability import (
    board_layout_fingerprint as placement_layout_fingerprint,
)
from pcbsmith.placement_candidate_ir import PlacementMovePolicy
from pcbsmith.placement_detail_ir import (
    PlacementDetailBudget,
    PlacementDetailSelectionPolicy,
    PlacementR2Policy,
)
from pcbsmith.placement_exact_ir import PlacementExactBudget, PlacementExactPolicy
from pcbsmith.placement_ir import (
    PlacementBudget,
    PlacementGeometryCatalog,
    PlacementIrModel,
    PlacementLegalizationPolicy,
    PlacementRegionVerification,
)
from pcbsmith.placement_surrogate_ir import CallerClearanceGroup, PlacementSurrogatePolicy
from pcbsmith.routing_ir import RoutingBudget
from pcbsmith.rule_profiles import PcbRuleProfile


def _json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _fingerprint(schema_id: str, **values: Any) -> str:
    return hashlib.sha256(
        _json({"schema_id": schema_id, "schema_version": 1, **values}).encode("utf-8")
    ).hexdigest()


def _sha(value: str, name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _identity(value: str, name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{name} must be a canonical non-empty identity")
    return value


def _canonical_identities(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    canonical = tuple(sorted(values))
    if len(set(canonical)) != len(canonical):
        raise ValueError(f"{name} must contain unique identities")
    return tuple(_identity(value, name) for value in canonical)


class PlacementPilotNegotiatedCostPolicy(PlacementIrModel):
    """Versioned retention wrapper for the existing frozen cost dataclass."""

    schema_id: Literal["pcbsmith-placement-pilot-negotiated-cost-policy"] = (
        "pcbsmith-placement-pilot-negotiated-cost-policy"
    )
    schema_version: Literal[1] = 1
    semantic_payload: dict[str, int]

    @model_validator(mode="after")
    def payload_reconstructs_exactly(self) -> Self:
        expected_names = tuple(NegotiatedCostPolicy.__dataclass_fields__)
        if tuple(sorted(self.semantic_payload)) != tuple(sorted(expected_names)):
            raise ValueError("negotiated cost payload must exactly cover the existing policy")
        try:
            reconstructed = NegotiatedCostPolicy(**self.semantic_payload)
        except (TypeError, ValueError) as error:
            raise ValueError(f"negotiated cost payload is invalid: {error}") from error
        if reconstructed.semantic_payload() != self.semantic_payload:
            raise ValueError("negotiated cost payload does not round-trip exactly")
        return self

    def reconstruct(self) -> NegotiatedCostPolicy:
        return NegotiatedCostPolicy(**self.semantic_payload)


class PlacementPilotCorridorDemandPolicy(PlacementIrModel):
    """Per-target layer/via authority for reproducible R3 demand derivation."""

    schema_id: Literal["pcbsmith-placement-pilot-corridor-demand-policy"] = (
        "pcbsmith-placement-pilot-corridor-demand-policy"
    )
    schema_version: Literal[1] = 1
    net_name: str
    allowed_layers: tuple[Literal["F.Cu", "B.Cu"], ...] = Field(min_length=1)
    via_policy: CorridorViaPolicy

    @model_validator(mode="after")
    def canonical_and_coherent(self) -> Self:
        object.__setattr__(self, "net_name", _identity(self.net_name, "net_name"))
        layers = tuple(sorted(self.allowed_layers))
        if len(set(layers)) != len(layers):
            raise ValueError("corridor demand allowed layers must be unique")
        if self.via_policy is CorridorViaPolicy.FORBIDDEN and len(layers) != 1:
            raise ValueError("via-forbidden corridor demand must select exactly one layer")
        object.__setattr__(self, "allowed_layers", layers)
        return self


class PlacementPilotAuthority(PlacementIrModel):
    """Complete immutable input envelope for a future placement pilot."""

    schema_id: Literal["pcbsmith-placement-pilot-authority"] = "pcbsmith-placement-pilot-authority"
    schema_version: Literal[1] = 1
    authority_scope: Literal["input_only_no_algorithm_routing_acceptance_or_readiness"] = (
        "input_only_no_algorithm_routing_acceptance_or_readiness"
    )

    layout_snapshot_json: str = Field(min_length=2)
    netlist_snapshot_json: str = Field(min_length=2)
    layout_snapshot_fingerprint: str
    netlist_snapshot_fingerprint: str
    geometry_catalog: PlacementGeometryCatalog
    geometry_catalog_fingerprint: str
    movable_references: tuple[str, ...] = Field(min_length=1)
    move_policy: PlacementMovePolicy
    legalization_policy: PlacementLegalizationPolicy
    target_net_names: tuple[str, ...] = Field(min_length=1)
    target_net_widths_mm: tuple[tuple[str, float], ...] = Field(min_length=1)
    corridor_demand_policies: tuple[PlacementPilotCorridorDemandPolicy, ...] = Field(min_length=1)
    profile: PcbRuleProfile
    profile_fingerprint: str
    clearance_groups: tuple[CallerClearanceGroup, ...]
    coarse_grid_mm: float = Field(gt=0)
    detailed_grid_mm: float = Field(gt=0)
    corridor_capacity_quantum_mm: float = Field(gt=0)

    placement_budget: PlacementBudget
    surrogate_policy: PlacementSurrogatePolicy
    corridor_graphics_policy: OpaqueGraphicsPolicy
    corridor_graph_budget: CorridorGraphBuildBudget
    corridor_budget: CorridorBudget
    corridor_cost_policy: CorridorCostPolicy
    detail_selection_policy: PlacementDetailSelectionPolicy
    detail_budget: PlacementDetailBudget
    r2_policy: PlacementR2Policy
    routing_budget: RoutingBudget
    negotiated_cost_policy: PlacementPilotNegotiatedCostPolicy
    exact_policy: PlacementExactPolicy
    exact_budget: PlacementExactBudget

    policy_bundle_fingerprint: str
    budget_bundle_fingerprint: str
    grid_fingerprint: str
    clearance_fingerprint: str
    authority_fingerprint: str

    @field_validator(
        "layout_snapshot_fingerprint",
        "netlist_snapshot_fingerprint",
        "geometry_catalog_fingerprint",
        "profile_fingerprint",
        "policy_bundle_fingerprint",
        "budget_bundle_fingerprint",
        "grid_fingerprint",
        "clearance_fingerprint",
        "authority_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _sha(value, info.field_name)

    @model_validator(mode="before")
    @classmethod
    def canonicalize_set_like_inputs(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        result = dict(value)
        for field_name in ("movable_references", "target_net_names"):
            raw = result.get(field_name)
            if isinstance(raw, (tuple, list)):
                result[field_name] = tuple(sorted(raw))
        widths = result.get("target_net_widths_mm")
        if isinstance(widths, (tuple, list)):
            result["target_net_widths_mm"] = tuple(sorted(tuple(item) for item in widths))
        demands = result.get("corridor_demand_policies")
        if isinstance(demands, (tuple, list)):

            def demand_key(item: Any) -> str:
                if isinstance(item, PlacementPilotCorridorDemandPolicy):
                    return item.net_name
                if isinstance(item, dict):
                    return str(item.get("net_name", ""))
                return _json(item)

            result["corridor_demand_policies"] = tuple(sorted(demands, key=demand_key))
        groups = result.get("clearance_groups")
        if isinstance(groups, (tuple, list)):

            def key(item: Any) -> str:
                if isinstance(item, CallerClearanceGroup):
                    return item.semantic_json()
                return _json(item)

            result["clearance_groups"] = tuple(sorted(groups, key=key))
        return result

    @model_validator(mode="after")
    def replay_and_cross_bind(self) -> Self:
        nested_models: tuple[tuple[str, type[Any]], ...] = (
            ("geometry_catalog", PlacementGeometryCatalog),
            ("move_policy", PlacementMovePolicy),
            ("legalization_policy", PlacementLegalizationPolicy),
            ("profile", PcbRuleProfile),
            ("placement_budget", PlacementBudget),
            ("surrogate_policy", PlacementSurrogatePolicy),
            ("corridor_graph_budget", CorridorGraphBuildBudget),
            ("corridor_budget", CorridorBudget),
            ("corridor_cost_policy", CorridorCostPolicy),
            ("detail_selection_policy", PlacementDetailSelectionPolicy),
            ("detail_budget", PlacementDetailBudget),
            ("r2_policy", PlacementR2Policy),
            ("routing_budget", RoutingBudget),
            ("negotiated_cost_policy", PlacementPilotNegotiatedCostPolicy),
            ("exact_policy", PlacementExactPolicy),
            ("exact_budget", PlacementExactBudget),
        )
        for field_name, model_type in nested_models:
            retained = model_type.model_validate_json(getattr(self, field_name).model_dump_json())
            object.__setattr__(self, field_name, retained)
        retained_groups = tuple(
            CallerClearanceGroup.model_validate_json(group.model_dump_json())
            for group in self.clearance_groups
        )
        object.__setattr__(self, "clearance_groups", retained_groups)
        retained_demand_policies = tuple(
            PlacementPilotCorridorDemandPolicy.model_validate_json(item.model_dump_json())
            for item in self.corridor_demand_policies
        )
        object.__setattr__(self, "corridor_demand_policies", retained_demand_policies)

        layout = parse_canonical_board_layout_snapshot(self.layout_snapshot_json)
        netlist = parse_canonical_board_netlist_snapshot(self.netlist_snapshot_json)
        layout_fp = board_layout_snapshot_fingerprint(self.layout_snapshot_json)
        netlist_fp = board_netlist_snapshot_fingerprint(self.netlist_snapshot_json)
        if self.layout_snapshot_fingerprint != layout_fp:
            raise ValueError("layout snapshot fingerprint is stale")
        if self.netlist_snapshot_fingerprint != netlist_fp:
            raise ValueError("netlist snapshot fingerprint is stale")

        layout_references = tuple(component.reference for component, _x in layout.placements)
        netlist_references = tuple(component.reference for component in netlist.components)
        net_names = tuple(net.name for net in netlist.nets)
        if len(set(layout_references)) != len(layout_references):
            raise ValueError("layout placement references must be unique")
        if len(set(netlist_references)) != len(netlist_references):
            raise ValueError("netlist component references must be unique")
        if len(set(net_names)) != len(net_names):
            raise ValueError("netlist net names must be unique")
        for value in (*layout_references, *netlist_references, *net_names):
            _identity(value, "layout/netlist identity")
        layout_components = {component.reference: component for component, _x in layout.placements}
        netlist_components = {component.reference: component for component in netlist.components}
        missing_netlisted = tuple(sorted(set(netlist_components) - set(layout_components)))
        mismatched_netlisted = tuple(
            sorted(
                reference
                for reference, component in netlist_components.items()
                if reference in layout_components and layout_components[reference] != component
            )
        )
        if missing_netlisted or mismatched_netlisted:
            raise ValueError(
                "every netlisted component must have an exact layout placement: "
                f"missing={missing_netlisted!r}, mismatched={mismatched_netlisted!r}"
            )
        foreign_nodes = tuple(
            sorted(
                (net.name, reference, pad)
                for net in netlist.nets
                for reference, pad in net.nodes
                if reference not in netlist_components
            )
        )
        if foreign_nodes:
            raise ValueError(f"netlist nets contain nodes without components: {foreign_nodes!r}")
        known_nets = set(net_names)

        movable = _canonical_identities(self.movable_references, "movable_references")
        targets = _canonical_identities(self.target_net_names, "target_net_names")
        if movable != self.movable_references or targets != self.target_net_names:
            raise ValueError("authority identities are not canonical")
        declared_moves = (
            set(self.move_policy.movable_references)
            | set(self.move_policy.rotatable_references)
            | set(self.move_policy.flippable_references)
        )
        if set(movable) != declared_moves:
            raise ValueError("movable references must exactly equal all move-policy references")
        if not set(movable) <= set(layout_components):
            raise ValueError("movable references contain foreign components")
        if not (
            set(self.move_policy.rotatable_references) | set(self.move_policy.flippable_references)
        ) <= set(self.move_policy.movable_references):
            raise ValueError("rotation and flip permissions must be bounded by movable references")
        if not set(targets) <= known_nets:
            raise ValueError("target nets contain foreign net identities")
        side_permissions = {
            item.reference: set(item.allowed_sides)
            for item in self.legalization_policy.side_permissions
        }
        if not set(side_permissions) <= set(layout_components):
            raise ValueError("legalization side permissions contain foreign components")
        if any(
            side_permissions.get(reference) != {"front", "back"}
            for reference in self.move_policy.flippable_references
        ):
            raise ValueError("flippable references require explicit front/back legalization")
        if not {item.reference for item in self.legalization_policy.edge_exceptions} <= set(
            layout_components
        ):
            raise ValueError("legalization edge exceptions contain foreign components")

        widths = tuple(sorted(self.target_net_widths_mm))
        if widths != self.target_net_widths_mm or len({name for name, _width in widths}) != len(
            widths
        ):
            raise ValueError("target net widths must be canonical and unique")
        if {name for name, _width in widths} != set(targets):
            raise ValueError("target net widths must exactly cover target nets")
        if any(
            name != name.strip() or not math.isfinite(width) or width <= 0 for name, width in widths
        ):
            raise ValueError("target net widths must use canonical nets and finite positive widths")
        demand_policies = tuple(
            sorted(self.corridor_demand_policies, key=lambda item: item.net_name)
        )
        if demand_policies != self.corridor_demand_policies or len(
            {item.net_name for item in demand_policies}
        ) != len(demand_policies):
            raise ValueError("corridor demand policies must be canonical and unique")
        if {item.net_name for item in demand_policies} != set(targets):
            raise ValueError("corridor demand policies must exactly cover target nets")

        catalog_fp = self.geometry_catalog.semantic_fingerprint()
        if self.geometry_catalog_fingerprint != catalog_fp:
            raise ValueError("geometry catalog fingerprint is stale")
        if self.geometry_catalog.template_fingerprint != placement_layout_fingerprint(layout):
            raise ValueError("geometry catalog is bound to a different layout snapshot")
        geometry = {item.reference: item for item in self.geometry_catalog.components}
        if set(geometry) != set(layout_components):
            raise ValueError("geometry catalog must exactly cover all layout components")
        for reference, component in layout_components.items():
            item = geometry[reference]
            if item.footprint != component.footprint:
                raise ValueError(f"geometry footprint is stale for {reference}")
            if item.component_identity_fingerprint != board_component_identity_fingerprint(
                component
            ):
                raise ValueError(f"geometry component identity is stale for {reference}")
        for reference in movable:
            if any(
                region.verification is not PlacementRegionVerification.EXACT
                or region.local_compound is None
                for region in geometry[reference].regions
            ):
                raise ValueError(f"movable geometry must be exact and supported for {reference}")

        profile_payload = self.profile.model_dump(mode="json")
        profile_fp = _fingerprint("pcbsmith-placement-pilot-profile", profile=profile_payload)
        if self.profile_fingerprint != profile_fp:
            raise ValueError("profile fingerprint is stale")

        groups = tuple(sorted(self.clearance_groups, key=lambda item: item.semantic_json()))
        if groups != self.clearance_groups:
            raise ValueError("clearance groups are not canonical")
        if len({item.semantic_fingerprint() for item in groups}) != len(groups):
            raise ValueError("clearance groups must be unique")
        for group in groups:
            if not (set(group.nets_a) | set(group.nets_b)) <= known_nets:
                raise ValueError("clearance group references a foreign net")
            if not set(group.exempt_component_refs) <= set(layout_components):
                raise ValueError("clearance group references a foreign exempt component")

        if (
            not math.isfinite(self.coarse_grid_mm)
            or not math.isfinite(self.detailed_grid_mm)
            or not math.isfinite(self.corridor_capacity_quantum_mm)
        ):
            raise ValueError("placement pilot grids must be finite")
        if self.r2_policy.target_nets != targets:
            raise ValueError("R2 policy target nets are stale")
        if self.r2_policy.net_widths_mm != widths:
            raise ValueError("R2 policy widths must exactly equal target widths")
        if self.r2_policy.grid_mm != self.detailed_grid_mm:
            raise ValueError("R2 policy grid must equal the detailed pilot grid")

        placement = self.placement_budget
        graph = self.corridor_graph_budget
        corridor = self.corridor_budget
        detail = self.detail_budget
        routing = self.routing_budget
        exact = self.exact_budget
        if (
            placement.max_r3_geometry_cells_per_candidate != graph.max_cells
            or placement.max_r3_geometry_portals_per_candidate != graph.max_portals
            or placement.max_r3_expansions_per_candidate != corridor.max_expansions
            or placement.max_corridor_plans != detail.max_corridor_evaluations
            or placement.max_detailed_candidates != detail.max_selected_candidates
            or placement.max_detailed_candidates != detail.max_routing_evaluations
            or placement.max_r2_passes_per_candidate != routing.max_passes
            or placement.max_r2_expansions_per_candidate != routing.max_expansions
            or placement.max_r2_expansions_per_net != routing.max_expansions_per_net
            or placement.max_r2_stagnant_passes != routing.max_stagnant_passes
            or placement.max_exact_checks != exact.max_exact_checks
        ):
            raise ValueError("stage budgets do not cross-bind to the placement budget")
        if (
            self.r2_policy.max_passes != routing.max_passes
            or self.r2_policy.max_expansions != routing.max_expansions
            or self.r2_policy.max_expansions_per_net != routing.max_expansions_per_net
            or self.r2_policy.max_stagnant_passes != routing.max_stagnant_passes
        ):
            raise ValueError("R2 policy limits do not cross-bind to the routing budget")
        cost = self.negotiated_cost_policy.reconstruct()
        for name in NegotiatedCostPolicy.__dataclass_fields__:
            if hasattr(self.r2_policy, name) and getattr(self.r2_policy, name) != getattr(
                cost, name
            ):
                raise ValueError("R2 policy costs do not cross-bind to negotiated cost policy")

        policy_fp = _pilot_policy_fingerprint(self)
        budget_fp = _pilot_budget_fingerprint(self)
        grid_fp = _pilot_grid_fingerprint(
            self.coarse_grid_mm,
            self.detailed_grid_mm,
            self.corridor_capacity_quantum_mm,
        )
        clearance_fp = _pilot_clearance_fingerprint(groups)
        if self.policy_bundle_fingerprint != policy_fp:
            raise ValueError("policy bundle fingerprint is stale")
        if self.budget_bundle_fingerprint != budget_fp:
            raise ValueError("budget bundle fingerprint is stale")
        if self.grid_fingerprint != grid_fp:
            raise ValueError("grid fingerprint is stale")
        if self.clearance_fingerprint != clearance_fp:
            raise ValueError("clearance fingerprint is stale")
        expected = _pilot_authority_fingerprint(
            layout_fp=layout_fp,
            netlist_fp=netlist_fp,
            catalog_fp=catalog_fp,
            profile_fp=profile_fp,
            movable=movable,
            targets=targets,
            widths=widths,
            policy_fp=policy_fp,
            budget_fp=budget_fp,
            grid_fp=grid_fp,
            clearance_fp=clearance_fp,
        )
        if self.authority_fingerprint != expected:
            raise ValueError("placement pilot authority fingerprint is stale")
        return self

    def layout(self) -> BoardLayout:
        return parse_canonical_board_layout_snapshot(self.layout_snapshot_json)

    def netlist(self) -> BoardNetlist:
        return parse_canonical_board_netlist_snapshot(self.netlist_snapshot_json)


def _pilot_policy_fingerprint(authority: PlacementPilotAuthority) -> str:
    return _fingerprint(
        "pcbsmith-placement-pilot-policy-bundle",
        move=authority.move_policy.model_dump(mode="json"),
        legalization=authority.legalization_policy.model_dump(mode="json"),
        surrogate=authority.surrogate_policy.model_dump(mode="json"),
        corridor_graphics=authority.corridor_graphics_policy.value,
        corridor_demands=[
            item.model_dump(mode="json") for item in authority.corridor_demand_policies
        ],
        corridor_cost=authority.corridor_cost_policy.model_dump(mode="json"),
        detail_selection=authority.detail_selection_policy.model_dump(mode="json"),
        r2=authority.r2_policy.model_dump(mode="json"),
        negotiated_cost=authority.negotiated_cost_policy.model_dump(mode="json"),
        exact=authority.exact_policy.model_dump(mode="json"),
    )


def _pilot_budget_fingerprint(authority: PlacementPilotAuthority) -> str:
    return _fingerprint(
        "pcbsmith-placement-pilot-budget-bundle",
        placement=authority.placement_budget.model_dump(mode="json"),
        corridor_graph=authority.corridor_graph_budget.model_dump(mode="json"),
        corridor=authority.corridor_budget.model_dump(mode="json"),
        detail=authority.detail_budget.model_dump(mode="json"),
        routing=authority.routing_budget.model_dump(mode="json"),
        exact=authority.exact_budget.model_dump(mode="json"),
    )


def _pilot_grid_fingerprint(
    coarse_grid_mm: float,
    detailed_grid_mm: float,
    corridor_capacity_quantum_mm: float,
) -> str:
    return _fingerprint(
        "pcbsmith-placement-pilot-grids",
        coarse_grid_mm=coarse_grid_mm,
        detailed_grid_mm=detailed_grid_mm,
        corridor_capacity_quantum_mm=corridor_capacity_quantum_mm,
    )


def _pilot_clearance_fingerprint(groups: tuple[CallerClearanceGroup, ...]) -> str:
    return _fingerprint(
        "pcbsmith-placement-pilot-clearance-groups",
        groups=[item.model_dump(mode="json") for item in groups],
    )


def _pilot_authority_fingerprint(
    *,
    layout_fp: str,
    netlist_fp: str,
    catalog_fp: str,
    profile_fp: str,
    movable: tuple[str, ...],
    targets: tuple[str, ...],
    widths: tuple[tuple[str, float], ...],
    policy_fp: str,
    budget_fp: str,
    grid_fp: str,
    clearance_fp: str,
) -> str:
    return _fingerprint(
        "pcbsmith-placement-pilot-authority-input",
        layout_fingerprint=layout_fp,
        netlist_fingerprint=netlist_fp,
        geometry_catalog_fingerprint=catalog_fp,
        profile_fingerprint=profile_fp,
        movable_references=movable,
        target_net_names=targets,
        target_net_widths_mm=widths,
        policy_bundle_fingerprint=policy_fp,
        budget_bundle_fingerprint=budget_fp,
        grid_fingerprint=grid_fp,
        clearance_fingerprint=clearance_fp,
    )


def build_placement_pilot_authority(
    layout: BoardLayout,
    netlist: BoardNetlist,
    *,
    geometry_catalog: PlacementGeometryCatalog,
    movable_references: tuple[str, ...],
    move_policy: PlacementMovePolicy,
    legalization_policy: PlacementLegalizationPolicy,
    target_net_names: tuple[str, ...],
    target_net_widths_mm: tuple[tuple[str, float], ...],
    corridor_demand_policies: tuple[PlacementPilotCorridorDemandPolicy, ...],
    profile: PcbRuleProfile,
    clearance_groups: tuple[CallerClearanceGroup, ...],
    coarse_grid_mm: float,
    detailed_grid_mm: float,
    corridor_capacity_quantum_mm: float,
    placement_budget: PlacementBudget,
    surrogate_policy: PlacementSurrogatePolicy,
    corridor_graphics_policy: OpaqueGraphicsPolicy,
    corridor_graph_budget: CorridorGraphBuildBudget,
    corridor_budget: CorridorBudget,
    corridor_cost_policy: CorridorCostPolicy,
    detail_selection_policy: PlacementDetailSelectionPolicy,
    detail_budget: PlacementDetailBudget,
    r2_policy: PlacementR2Policy,
    routing_budget: RoutingBudget,
    negotiated_cost_policy: NegotiatedCostPolicy,
    exact_policy: PlacementExactPolicy,
    exact_budget: PlacementExactBudget,
) -> PlacementPilotAuthority:
    """Retain all caller inputs after clean canonical reconstruction."""

    layout_before = canonical_board_layout_snapshot_json(layout)
    netlist_before = canonical_board_netlist_snapshot_json(netlist)
    retained_layout = parse_canonical_board_layout_snapshot(layout_before)
    retained_netlist = parse_canonical_board_netlist_snapshot(netlist_before)
    layout_json = canonical_board_layout_snapshot_json(retained_layout)
    netlist_json = canonical_board_netlist_snapshot_json(retained_netlist)
    layout_fp = board_layout_snapshot_fingerprint(layout_json)
    netlist_fp = board_netlist_snapshot_fingerprint(netlist_json)
    catalog = PlacementGeometryCatalog.model_validate_json(geometry_catalog.model_dump_json())
    move = PlacementMovePolicy.model_validate_json(move_policy.model_dump_json())
    legalization = PlacementLegalizationPolicy.model_validate_json(
        legalization_policy.model_dump_json()
    )
    retained_profile = PcbRuleProfile.model_validate_json(profile.model_dump_json())
    groups = tuple(
        sorted(
            (
                CallerClearanceGroup.model_validate_json(item.model_dump_json())
                for item in clearance_groups
            ),
            key=lambda item: item.semantic_json(),
        )
    )
    demands = tuple(
        sorted(
            (
                PlacementPilotCorridorDemandPolicy.model_validate_json(item.model_dump_json())
                for item in corridor_demand_policies
            ),
            key=lambda item: item.net_name,
        )
    )
    negotiated = PlacementPilotNegotiatedCostPolicy(
        semantic_payload=negotiated_cost_policy.semantic_payload()
    )
    payload: dict[str, Any] = {
        "layout_snapshot_json": layout_json,
        "netlist_snapshot_json": netlist_json,
        "layout_snapshot_fingerprint": layout_fp,
        "netlist_snapshot_fingerprint": netlist_fp,
        "geometry_catalog": catalog,
        "geometry_catalog_fingerprint": catalog.semantic_fingerprint(),
        "movable_references": movable_references,
        "move_policy": move,
        "legalization_policy": legalization,
        "target_net_names": target_net_names,
        "target_net_widths_mm": target_net_widths_mm,
        "corridor_demand_policies": demands,
        "profile": retained_profile,
        "profile_fingerprint": _fingerprint(
            "pcbsmith-placement-pilot-profile", profile=retained_profile.model_dump(mode="json")
        ),
        "clearance_groups": groups,
        "coarse_grid_mm": coarse_grid_mm,
        "detailed_grid_mm": detailed_grid_mm,
        "corridor_capacity_quantum_mm": corridor_capacity_quantum_mm,
        "placement_budget": placement_budget,
        "surrogate_policy": surrogate_policy,
        "corridor_graphics_policy": corridor_graphics_policy,
        "corridor_graph_budget": corridor_graph_budget,
        "corridor_budget": corridor_budget,
        "corridor_cost_policy": corridor_cost_policy,
        "detail_selection_policy": detail_selection_policy,
        "detail_budget": detail_budget,
        "r2_policy": r2_policy,
        "routing_budget": routing_budget,
        "negotiated_cost_policy": negotiated,
        "exact_policy": exact_policy,
        "exact_budget": exact_budget,
        "policy_bundle_fingerprint": "0" * 64,
        "budget_bundle_fingerprint": "0" * 64,
        "grid_fingerprint": _pilot_grid_fingerprint(
            coarse_grid_mm,
            detailed_grid_mm,
            corridor_capacity_quantum_mm,
        ),
        "clearance_fingerprint": _pilot_clearance_fingerprint(groups),
        "authority_fingerprint": "0" * 64,
    }
    draft = PlacementPilotAuthority.model_construct(**payload)
    payload["policy_bundle_fingerprint"] = _pilot_policy_fingerprint(draft)
    payload["budget_bundle_fingerprint"] = _pilot_budget_fingerprint(draft)
    canonical_movable = tuple(sorted(movable_references))
    canonical_targets = tuple(sorted(target_net_names))
    canonical_widths = tuple(sorted(target_net_widths_mm))
    payload["authority_fingerprint"] = _pilot_authority_fingerprint(
        layout_fp=layout_fp,
        netlist_fp=netlist_fp,
        catalog_fp=catalog.semantic_fingerprint(),
        profile_fp=payload["profile_fingerprint"],
        movable=canonical_movable,
        targets=canonical_targets,
        widths=canonical_widths,
        policy_fp=payload["policy_bundle_fingerprint"],
        budget_fp=payload["budget_bundle_fingerprint"],
        grid_fp=payload["grid_fingerprint"],
        clearance_fp=payload["clearance_fingerprint"],
    )
    result = PlacementPilotAuthority.model_validate(payload)
    if canonical_board_layout_snapshot_json(layout) != layout_before:
        raise ValueError("caller layout mutated while building placement pilot authority")
    if canonical_board_netlist_snapshot_json(netlist) != netlist_before:
        raise ValueError("caller netlist mutated while building placement pilot authority")
    return result


__all__ = [
    "PlacementPilotAuthority",
    "PlacementPilotCorridorDemandPolicy",
    "PlacementPilotNegotiatedCostPolicy",
    "build_placement_pilot_authority",
]
