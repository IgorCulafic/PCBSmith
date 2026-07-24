"""Replay-bound project context and automatic Phase 14 applicability gate IR."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.connector_protection_order_ir import ConnectorProtectionOrderResult
from pcbsmith.decoupling_loop_ir import DecouplingLoopEvaluationResult
from pcbsmith.evidence.part_discovery import ExactPartDiscoveryReport, PartResourceRole
from pcbsmith.kicad.board import BoardNetlist
from pcbsmith.kicad.board_serialization import (
    board_netlist_snapshot_fingerprint,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.oscillator_zone_ir import OscillatorZoneResult
from pcbsmith.return_adjacency_ir import ReturnAdjacencyResult
from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticDisposition, SemanticIrModel
from pcbsmith.switching_hot_loop_ir import SwitchingHotLoopEvaluationResult


class Phase14RuleFamily(StrEnum):
    DECOUPLING_LOOP = "decoupling_loop"
    CONNECTOR_PROTECTION_ORDER = "connector_protection_order"
    OSCILLATOR_ZONE = "oscillator_zone"
    SWITCHING_HOT_LOOP = "switching_hot_loop"
    RETURN_ADJACENCY = "return_adjacency"


ALL_PHASE14_RULE_FAMILIES = tuple(Phase14RuleFamily)


class ComponentIdentityStatus(StrEnum):
    EXACT_MPN = "exact_mpn"
    GENERIC_VALUE = "generic_value"
    UNKNOWN = "unknown"


class InventoryStatus(StrEnum):
    COMPLETE_REVIEWED = "complete_reviewed"
    INCOMPLETE = "incomplete"


class ProjectComponentProfile(SemanticIrModel):
    schema_id: Literal["pcbsmith-project-component-profile"] = (
        "pcbsmith-project-component-profile"
    )
    schema_version: Literal[1] = 1
    reference: str
    identity_status: ComponentIdentityStatus
    manufacturer: str | None = None
    part_number: str | None = None
    required_resource_roles: tuple[PartResourceRole, ...] = ()

    @model_validator(mode="after")
    def identity_is_coherent(self) -> Self:
        require_identity(self.reference, "reference")
        roles = tuple(sorted(set(self.required_resource_roles), key=lambda item: item.value))
        if len(roles) != len(self.required_resource_roles):
            raise ValueError("component resource roles must be unique")
        object.__setattr__(self, "required_resource_roles", roles)
        if self.identity_status is ComponentIdentityStatus.EXACT_MPN:
            if self.manufacturer is None or self.part_number is None:
                raise ValueError("exact-MPN components require manufacturer and part number")
            require_identity(self.manufacturer, "manufacturer")
            require_identity(self.part_number, "part_number")
        elif self.manufacturer is not None or self.part_number is not None or roles:
            raise ValueError(
                "generic or unknown components cannot claim exact-part resources"
            )
        return self


class Phase14FeatureDeclaration(SemanticIrModel):
    """Reviewed project fact from which rule applicability is derived."""

    schema_id: Literal["pcbsmith-phase14-feature-declaration"] = (
        "pcbsmith-phase14-feature-declaration"
    )
    schema_version: Literal[1] = 1
    feature_id: str
    family: Phase14RuleFamily
    subject_component_references: tuple[str, ...]
    required_declaration_ids: tuple[str, ...] = Field(min_length=1)
    rationale: str
    source_context_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def feature_is_canonical(self) -> Self:
        require_identity(self.feature_id, "feature_id")
        require_identity(self.rationale, "rationale")
        for name in (
            "subject_component_references",
            "required_declaration_ids",
            "source_context_ids",
        ):
            values = tuple(sorted(require_identity(item, name) for item in getattr(self, name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")
            object.__setattr__(self, name, values)
        return self


class ProjectEngineeringContext(SemanticIrModel):
    schema_id: Literal["pcbsmith-project-engineering-context"] = (
        "pcbsmith-project-engineering-context"
    )
    schema_version: Literal[1] = 1
    project_id: str
    complexity_level: Literal["L0", "L1", "L2", "L3"]
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_json: str
    board_netlist_snapshot_fingerprint: str
    inventory_status: InventoryStatus
    component_profiles: tuple[ProjectComponentProfile, ...]
    phase14_features: tuple[Phase14FeatureDeclaration, ...]
    source_context_ids: tuple[str, ...]
    reviewer_record_id: str | None
    intended_consumer: str
    context_fingerprint: str

    @model_validator(mode="after")
    def context_is_complete_and_replay_bound(self) -> Self:
        require_identity(self.project_id, "project_id")
        require_identity(self.intended_consumer, "intended_consumer")
        require_sha256(
            self.board_layout_snapshot_fingerprint,
            "board_layout_snapshot_fingerprint",
        )
        require_sha256(
            self.board_netlist_snapshot_fingerprint,
            "board_netlist_snapshot_fingerprint",
        )
        if (
            board_netlist_snapshot_fingerprint(self.board_netlist_snapshot_json)
            != self.board_netlist_snapshot_fingerprint
        ):
            raise ValueError("project context BoardNetlist fingerprint is stale")
        netlist = parse_canonical_board_netlist_snapshot(self.board_netlist_snapshot_json)
        component_refs = {item.reference for item in netlist.components}
        profiles = tuple(sorted(self.component_profiles, key=lambda item: item.reference))
        if len(profiles) != len({item.reference for item in profiles}):
            raise ValueError("project component profiles must be unique")
        profile_refs = {item.reference for item in profiles}
        if not profile_refs.issubset(component_refs):
            raise ValueError("project component profile references are absent from BoardNetlist")
        features = tuple(sorted(self.phase14_features, key=lambda item: item.feature_id))
        if len(features) != len({item.feature_id for item in features}):
            raise ValueError("Phase 14 feature identities must be unique")
        if any(
            not set(item.subject_component_references).issubset(component_refs)
            for item in features
        ):
            raise ValueError("Phase 14 feature subjects are absent from BoardNetlist")
        source_context_ids = tuple(
            sorted(require_identity(item, "source_context_ids") for item in self.source_context_ids)
        )
        if len(source_context_ids) != len(set(source_context_ids)):
            raise ValueError("project source-context identities must be unique")
        if self.inventory_status is InventoryStatus.COMPLETE_REVIEWED:
            if profile_refs != component_refs:
                raise ValueError("complete inventory must profile every BoardNetlist component")
            if self.reviewer_record_id is None or not source_context_ids:
                raise ValueError(
                    "complete inventory requires reviewer and source-context identities"
                )
            require_identity(self.reviewer_record_id, "reviewer_record_id")
        elif features:
            raise ValueError("incomplete inventory cannot assert Phase 14 applicability facts")
        object.__setattr__(self, "component_profiles", profiles)
        object.__setattr__(self, "phase14_features", features)
        object.__setattr__(self, "source_context_ids", source_context_ids)
        require_sha256(self.context_fingerprint, "context_fingerprint")
        payload = self.model_dump(mode="json", exclude={"context_fingerprint"})
        if self.context_fingerprint != fingerprint(payload):
            raise ValueError("project engineering context fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        project_id: str,
        complexity_level: Literal["L0", "L1", "L2", "L3"],
        board_layout_snapshot_fingerprint: str,
        board_netlist: BoardNetlist,
        inventory_status: InventoryStatus,
        component_profiles: tuple[ProjectComponentProfile, ...],
        phase14_features: tuple[Phase14FeatureDeclaration, ...],
        source_context_ids: tuple[str, ...],
        reviewer_record_id: str | None,
        intended_consumer: str,
    ) -> ProjectEngineeringContext:
        snapshot_json = canonical_board_netlist_snapshot_json(board_netlist)
        canonical_profiles = tuple(sorted(component_profiles, key=lambda item: item.reference))
        canonical_features = tuple(sorted(phase14_features, key=lambda item: item.feature_id))
        canonical_sources = tuple(sorted(source_context_ids))
        fields: dict[str, Any] = {
            "project_id": project_id,
            "complexity_level": complexity_level,
            "board_layout_snapshot_fingerprint": board_layout_snapshot_fingerprint,
            "board_netlist_snapshot_json": snapshot_json,
            "board_netlist_snapshot_fingerprint": board_netlist_snapshot_fingerprint(
                snapshot_json
            ),
            "inventory_status": inventory_status,
            "component_profiles": canonical_profiles,
            "phase14_features": canonical_features,
            "source_context_ids": canonical_sources,
            "reviewer_record_id": reviewer_record_id,
            "intended_consumer": intended_consumer,
        }
        provisional = cls.model_construct(**fields, context_fingerprint="0" * 64)
        payload = provisional.model_dump(mode="json", exclude={"context_fingerprint"})
        return cls(**fields, context_fingerprint=fingerprint(payload))


class Phase14EvaluationBundle(SemanticIrModel):
    schema_id: Literal["pcbsmith-phase14-evaluation-bundle"] = (
        "pcbsmith-phase14-evaluation-bundle"
    )
    schema_version: Literal[1] = 1
    decoupling_loops: tuple[DecouplingLoopEvaluationResult, ...] = ()
    connector_protection_orders: tuple[ConnectorProtectionOrderResult, ...] = ()
    oscillator_zones: tuple[OscillatorZoneResult, ...] = ()
    switching_hot_loops: tuple[SwitchingHotLoopEvaluationResult, ...] = ()
    return_adjacencies: tuple[ReturnAdjacencyResult, ...] = ()

    @model_validator(mode="after")
    def results_are_canonical(self) -> Self:
        for name in (
            "decoupling_loops",
            "connector_protection_orders",
            "oscillator_zones",
            "switching_hot_loops",
            "return_adjacencies",
        ):
            results = tuple(
                sorted(getattr(self, name), key=lambda item: item.declaration.declaration_id)
            )
            ids = tuple(item.declaration.declaration_id for item in results)
            if len(ids) != len(set(ids)):
                raise ValueError(f"{name} declaration identities must be unique")
            object.__setattr__(self, name, results)
        return self


class Phase14AxisGateRecord(SemanticIrModel):
    schema_id: Literal["pcbsmith-phase14-axis-gate-record"] = (
        "pcbsmith-phase14-axis-gate-record"
    )
    schema_version: Literal[1] = 1
    family: Phase14RuleFamily
    applicability: Literal["applicable", "not_applicable", "unresolved"]
    required_declaration_ids: tuple[str, ...]
    supplied_declaration_ids: tuple[str, ...]
    result_fingerprints: tuple[str, ...]
    disposition: SemanticDisposition
    findings: tuple[str, ...]


class PartResourceReadinessRecord(SemanticIrModel):
    schema_id: Literal["pcbsmith-part-resource-readiness-record"] = (
        "pcbsmith-part-resource-readiness-record"
    )
    schema_version: Literal[1] = 1
    component_reference: str
    manufacturer: str
    part_number: str
    role: PartResourceRole
    ready: bool
    discovery_report_fingerprint: str | None
    status: str
    findings: tuple[str, ...]


class ProjectGateOutcome(StrEnum):
    BLOCKED = "blocked"
    UNVERIFIED = "unverified"
    REVIEW = "review"
    READY = "ready"


class ProjectEngineeringGateResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-project-engineering-gate-result"] = (
        "pcbsmith-project-engineering-gate-result"
    )
    schema_version: Literal[1] = 1
    context: ProjectEngineeringContext
    evaluation_bundle: Phase14EvaluationBundle
    discovery_reports: tuple[ExactPartDiscoveryReport, ...]
    axis_records: tuple[Phase14AxisGateRecord, ...]
    part_resource_records: tuple[PartResourceReadinessRecord, ...]
    outcome: ProjectGateOutcome
    result_fingerprint: str

    @model_validator(mode="after")
    def result_is_replay_derived(self) -> Self:
        from pcbsmith.project_engineering_gate import rederive_project_engineering_gate

        expected = rederive_project_engineering_gate(
            self.context,
            self.evaluation_bundle,
            self.discovery_reports,
        )
        for name in (
            "discovery_reports",
            "axis_records",
            "part_resource_records",
            "outcome",
        ):
            if getattr(self, name) != expected[name]:
                raise ValueError("project engineering gate result is stale or not replay-derived")
        require_sha256(self.result_fingerprint, "result_fingerprint")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("project engineering gate result fingerprint is stale")
        return self
