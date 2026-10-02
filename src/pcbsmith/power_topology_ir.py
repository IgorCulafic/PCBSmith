"""Board-level power, return, zone, and copper-topology authority."""

from __future__ import annotations

import math
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel


class PowerTerminalRole(StrEnum):
    SOURCE = "source"
    SINK = "sink"


class CopperTopologyRole(StrEnum):
    POWER_TRUNK = "power_trunk"
    POWER_BRANCH = "power_branch"
    LOCAL_POUR = "local_pour"
    REFERENCE_POUR = "reference_pour"
    CHASSIS_OR_SHIELD = "chassis_or_shield"


class ElectricalRegionClass(StrEnum):
    ORDINARY = "ordinary"
    SENSITIVE = "sensitive"
    NOISY = "noisy"
    SWITCHING = "switching"
    HIGH_CURRENT = "high_current"


class ZonePadConnection(StrEnum):
    SOLID = "solid"
    THERMAL = "thermal"
    NO_ZONE = "no_zone"


class IslandPolicy(StrEnum):
    REMOVE_UNREACHABLE = "remove_unreachable"
    KEEP_DECLARED_ONLY = "keep_declared_only"
    KEEP_ALL = "keep_all"


class CurrentSharingStatus(StrEnum):
    REQUIRED = "required"
    NOT_REQUIRED = "not_required"
    UNVERIFIED = "unverified"


class TopologyClaimDisposition(StrEnum):
    READY_FOR_GEOMETRY_EVALUATION = "ready_for_geometry_evaluation"
    UNVERIFIED = "unverified"
    FAILED = "failed"


class PowerTerminal(SemanticIrModel):
    terminal_id: str
    component_reference: str
    pad_number: str
    role: PowerTerminalRole

    @model_validator(mode="after")
    def identity_is_complete(self) -> Self:
        for name in ("terminal_id", "component_reference", "pad_number"):
            require_identity(getattr(self, name), name)
        return self


class OperatingScenarioCurrent(SemanticIrModel):
    scenario_id: str
    expected_current_a: float | None = Field(default=None, ge=0)
    maximum_current_a: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def current_is_coherent(self) -> Self:
        require_identity(self.scenario_id, "scenario_id")
        for name in ("expected_current_a", "maximum_current_a"):
            value = getattr(self, name)
            if value is not None and not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
        if (
            self.expected_current_a is not None
            and self.maximum_current_a is not None
            and self.expected_current_a > self.maximum_current_a
        ):
            raise ValueError("expected current cannot exceed maximum current")
        return self


class NeckdownAllowance(SemanticIrModel):
    neckdown_id: str
    pad_ids: tuple[str, ...] = Field(min_length=1)
    minimum_width_mm: float = Field(gt=0)
    maximum_length_mm: float = Field(gt=0)
    rationale_authority_id: str

    @model_validator(mode="after")
    def allowance_is_canonical(self) -> Self:
        require_identity(self.neckdown_id, "neckdown_id")
        require_identity(self.rationale_authority_id, "rationale_authority_id")
        pads = tuple(sorted(self.pad_ids))
        if len(pads) != len(set(pads)):
            raise ValueError("neckdown pad identities must be unique")
        for pad in pads:
            require_identity(pad, "pad_ids")
        object.__setattr__(self, "pad_ids", pads)
        return self


class ZonePadConnectionIntent(SemanticIrModel):
    pad_id: str
    connection: ZonePadConnection
    neckdown_id: str | None = None

    @model_validator(mode="after")
    def connection_is_explicit(self) -> Self:
        require_identity(self.pad_id, "pad_id")
        if self.connection is ZonePadConnection.THERMAL:
            if self.neckdown_id is None:
                raise ValueError("thermal zone connection requires an explicit neckdown")
            require_identity(self.neckdown_id, "neckdown_id")
        elif self.neckdown_id is not None:
            raise ValueError("only thermal connections may reference a neckdown")
        return self


class ViaTopologyRequirement(SemanticIrModel):
    requirement_id: str
    transition_layers: tuple[str, str]
    minimum_via_count: int = Field(ge=0)
    minimum_via_diameter_mm: float | None = Field(default=None, gt=0)
    minimum_via_drill_mm: float | None = Field(default=None, gt=0)
    current_sharing_status: CurrentSharingStatus

    @model_validator(mode="after")
    def requirement_is_coherent(self) -> Self:
        require_identity(self.requirement_id, "requirement_id")
        for layer in self.transition_layers:
            require_identity(layer, "transition_layers")
        if self.transition_layers[0] == self.transition_layers[1]:
            raise ValueError("via transition requires distinct layers")
        if (self.minimum_via_diameter_mm is None) != (self.minimum_via_drill_mm is None):
            raise ValueError("via diameter and drill requirements must be declared together")
        if (
            self.minimum_via_diameter_mm is not None
            and self.minimum_via_drill_mm is not None
            and self.minimum_via_diameter_mm <= self.minimum_via_drill_mm
        ):
            raise ValueError("via diameter must exceed via drill")
        return self


class IntentionalCopperIsland(SemanticIrModel):
    island_id: str
    source_authority_sha256: str
    rationale: str

    @model_validator(mode="after")
    def source_is_explicit(self) -> Self:
        require_identity(self.island_id, "island_id")
        require_identity(self.rationale, "rationale")
        require_sha256(self.source_authority_sha256, "source_authority_sha256")
        return self


class CopperRegionDeclaration(SemanticIrModel):
    region_id: str
    net_name: str
    role: CopperTopologyRole
    electrical_class: ElectricalRegionClass
    allowed_layers: tuple[str, ...] = Field(min_length=1)
    pad_connections: tuple[ZonePadConnectionIntent, ...] = ()
    island_policy: IslandPolicy
    intentional_islands: tuple[IntentionalCopperIsland, ...] = ()

    @model_validator(mode="after")
    def region_is_canonical(self) -> Self:
        require_identity(self.region_id, "region_id")
        require_identity(self.net_name, "net_name")
        layers = tuple(sorted(self.allowed_layers))
        if len(layers) != len(set(layers)):
            raise ValueError("region allowed layers must be unique")
        for layer in layers:
            require_identity(layer, "allowed_layers")
        connections = tuple(sorted(self.pad_connections, key=lambda item: item.pad_id))
        if len(connections) != len({item.pad_id for item in connections}):
            raise ValueError("region pad connection identities must be unique")
        islands = tuple(sorted(self.intentional_islands, key=lambda item: item.island_id))
        if self.island_policy is not IslandPolicy.KEEP_DECLARED_ONLY and islands:
            raise ValueError("intentional islands require keep-declared-only policy")
        if self.role is CopperTopologyRole.CHASSIS_OR_SHIELD:
            if self.island_policy is IslandPolicy.KEEP_ALL:
                raise ValueError("shield copper cannot retain unauthorised islands")
        object.__setattr__(self, "allowed_layers", layers)
        object.__setattr__(self, "pad_connections", connections)
        object.__setattr__(self, "intentional_islands", islands)
        return self


class PowerPathDeclaration(SemanticIrModel):
    path_id: str
    net_name: str
    source_terminal_id: str
    sink_terminal_ids: tuple[str, ...] = Field(min_length=1)
    current_scenarios: tuple[OperatingScenarioCurrent, ...] = Field(min_length=1)
    region_ids: tuple[str, ...] = Field(min_length=1)
    allowed_layers: tuple[str, ...] = Field(min_length=1)
    allowed_layer_transitions: tuple[tuple[str, str], ...] = ()
    neckdowns: tuple[NeckdownAllowance, ...] = ()
    via_requirements: tuple[ViaTopologyRequirement, ...] = ()
    requires_ampacity_claim: bool = False

    @model_validator(mode="after")
    def path_is_canonical(self) -> Self:
        for name in ("path_id", "net_name", "source_terminal_id"):
            require_identity(getattr(self, name), name)
        for field_name in ("sink_terminal_ids", "region_ids", "allowed_layers"):
            values = tuple(sorted(getattr(self, field_name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must contain unique identities")
            for value in values:
                require_identity(value, field_name)
            object.__setattr__(self, field_name, values)
        scenarios = tuple(sorted(self.current_scenarios, key=lambda item: item.scenario_id))
        if len(scenarios) != len({item.scenario_id for item in scenarios}):
            raise ValueError("current scenario identities must be unique")
        neckdowns = tuple(sorted(self.neckdowns, key=lambda item: item.neckdown_id))
        if len(neckdowns) != len({item.neckdown_id for item in neckdowns}):
            raise ValueError("neckdown identities must be unique")
        object.__setattr__(self, "current_scenarios", scenarios)
        object.__setattr__(self, "neckdowns", neckdowns)
        return self


class SignalReturnRelationship(SemanticIrModel):
    relationship_id: str
    signal_group_id: str
    signal_net_names: tuple[str, ...] = Field(min_length=1)
    reference_region_id: str
    required_relation: Literal["adjacent_continuous", "same_layer_coplanar"]


class BoardPowerTopology(SemanticIrModel):
    schema_id: Literal["pcbsmith-board-power-topology"] = "pcbsmith-board-power-topology"
    schema_version: Literal[1] = 1
    topology_id: str
    board_sha256: str
    fabrication_profile_sha256: str
    applicability: Literal["applicable", "not_applicable", "unresolved"] = "applicable"
    applicability_rationale: str | None = None
    terminals: tuple[PowerTerminal, ...]
    regions: tuple[CopperRegionDeclaration, ...]
    paths: tuple[PowerPathDeclaration, ...]
    return_relationships: tuple[SignalReturnRelationship, ...] = ()
    topology_fingerprint: str

    @model_validator(mode="after")
    def topology_is_cross_referenced(self) -> Self:
        require_identity(self.topology_id, "topology_id")
        require_sha256(self.board_sha256, "board_sha256")
        require_sha256(self.fabrication_profile_sha256, "fabrication_profile_sha256")
        declared_object_count = len(self.terminals) + len(self.regions) + len(self.paths)
        if self.applicability == "applicable" and declared_object_count == 0:
            raise ValueError("applicable topology cannot be an empty declaration")
        if self.applicability == "not_applicable":
            if declared_object_count or self.return_relationships:
                raise ValueError("not-applicable topology cannot retain topology objects")
            if not self.applicability_rationale:
                raise ValueError("not-applicable topology requires a rationale")
        if self.applicability == "unresolved" and not self.applicability_rationale:
            raise ValueError("unresolved topology requires a rationale")
        terminal_by_id = {item.terminal_id: item for item in self.terminals}
        region_by_id = {item.region_id: item for item in self.regions}
        if len(terminal_by_id) != len(self.terminals):
            raise ValueError("power terminal identities must be unique")
        if len(region_by_id) != len(self.regions):
            raise ValueError("copper region identities must be unique")
        for path in self.paths:
            source = terminal_by_id.get(path.source_terminal_id)
            if source is None or source.role is not PowerTerminalRole.SOURCE:
                raise ValueError("power path requires a declared source terminal")
            if any(
                terminal_by_id.get(sink_id) is None
                or terminal_by_id[sink_id].role is not PowerTerminalRole.SINK
                for sink_id in path.sink_terminal_ids
            ):
                raise ValueError("power path requires declared sink terminals")
            if not set(path.region_ids).issubset(region_by_id):
                raise ValueError("power path references an unknown copper region")
            neckdown_ids = {item.neckdown_id for item in path.neckdowns}
            thermal_ids = {
                item.neckdown_id
                for region_id in path.region_ids
                for item in region_by_id[region_id].pad_connections
                if item.connection is ZonePadConnection.THERMAL
            }
            if not thermal_ids.issubset(neckdown_ids):
                raise ValueError("power path has an undeclared thermal-spoke neckdown")
        for relationship in self.return_relationships:
            require_identity(relationship.relationship_id, "relationship_id")
            require_identity(relationship.signal_group_id, "signal_group_id")
            region = region_by_id.get(relationship.reference_region_id)
            if region is None or region.role is not CopperTopologyRole.REFERENCE_POUR:
                raise ValueError("return relationship requires a declared reference-pour role")
        require_sha256(self.topology_fingerprint, "topology_fingerprint")
        expected = fingerprint(self.model_dump(mode="json", exclude={"topology_fingerprint"}))
        if self.topology_fingerprint != expected:
            raise ValueError("board power topology fingerprint is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> BoardPowerTopology:
        provisional = cls.model_construct(**values, topology_fingerprint="0" * 64)
        return cls(
            **values,
            topology_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"topology_fingerprint"})
            ),
        )


class PowerTopologyAssessment(SemanticIrModel):
    topology_fingerprint: str
    ampacity_claim: TopologyClaimDisposition
    return_continuity_claim: TopologyClaimDisposition
    blockers: tuple[str, ...]


def assess_power_topology(topology: BoardPowerTopology) -> PowerTopologyAssessment:
    blockers: list[str] = []
    current_incomplete = any(
        scenario.expected_current_a is None or scenario.maximum_current_a is None
        for path in topology.paths
        for scenario in path.current_scenarios
        if path.requires_ampacity_claim
    )
    ampacity = (
        TopologyClaimDisposition.UNVERIFIED
        if current_incomplete
        else TopologyClaimDisposition.READY_FOR_GEOMETRY_EVALUATION
    )
    if current_incomplete:
        blockers.append("ampacity: source/sink operating current semantics are incomplete")
    returns = (
        TopologyClaimDisposition.READY_FOR_GEOMETRY_EVALUATION
        if topology.return_relationships
        else TopologyClaimDisposition.UNVERIFIED
    )
    if not topology.return_relationships:
        blockers.append("return continuity: no signal-to-reference relationship is declared")
    return PowerTopologyAssessment(
        topology_fingerprint=topology.topology_fingerprint,
        ampacity_claim=ampacity,
        return_continuity_claim=returns,
        blockers=tuple(blockers),
    )


__all__ = [
    "BoardPowerTopology",
    "CopperRegionDeclaration",
    "CopperTopologyRole",
    "CurrentSharingStatus",
    "ElectricalRegionClass",
    "IntentionalCopperIsland",
    "IslandPolicy",
    "NeckdownAllowance",
    "OperatingScenarioCurrent",
    "PowerPathDeclaration",
    "PowerTerminal",
    "PowerTerminalRole",
    "PowerTopologyAssessment",
    "SignalReturnRelationship",
    "TopologyClaimDisposition",
    "ViaTopologyRequirement",
    "ZonePadConnection",
    "ZonePadConnectionIntent",
    "assess_power_topology",
]
