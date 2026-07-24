"""Replay-bound connector-to-protection ordering over exact routed copper paths."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.connector_zone_ir import ConnectorZoneResult
from pcbsmith.routed_copper_graph_ir import (
    ResolvedCopperPathResult,
    fingerprint,
    require_identity,
    require_sha256,
)
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticDisposition,
    SemanticIrModel,
)

ProtectionTransitionRole = Literal[
    "esd_protection",
    "series_filter",
    "common_mode_filter",
    "galvanic_protection",
]


class ConnectorProtectionLegDeclaration(SemanticIrModel):
    """One routed copper leg between adjacent components in a protection chain."""

    schema_id: Literal["pcbsmith-connector-protection-leg-declaration"] = (
        "pcbsmith-connector-protection-leg-declaration"
    )
    schema_version: Literal[1] = 1
    leg_id: str
    net_name: str
    start_anchor_id: str
    start_pad_source_id: str
    end_anchor_id: str
    end_pad_source_id: str
    path_result_fingerprint: str
    declared_parallel_component_references: tuple[str, ...] = ()

    @model_validator(mode="after")
    def leg_is_explicit(self) -> Self:
        for name in (
            "leg_id",
            "net_name",
            "start_anchor_id",
            "start_pad_source_id",
            "end_anchor_id",
            "end_pad_source_id",
        ):
            require_identity(getattr(self, name), name)
        require_sha256(self.path_result_fingerprint, "path_result_fingerprint")
        if self.start_anchor_id == self.end_anchor_id:
            raise ValueError("connector protection leg anchors must differ")
        allowed = tuple(
            sorted(
                require_identity(item, "declared_parallel_component_references")
                for item in self.declared_parallel_component_references
            )
        )
        if len(allowed) != len(set(allowed)):
            raise ValueError("declared parallel component references must be unique")
        object.__setattr__(self, "declared_parallel_component_references", allowed)
        return self


class ConnectorProtectionTransition(SemanticIrModel):
    """Explicit traversal through one protection/filter component."""

    schema_id: Literal["pcbsmith-connector-protection-transition"] = (
        "pcbsmith-connector-protection-transition"
    )
    schema_version: Literal[1] = 1
    transition_id: str
    component_reference: str
    role: ProtectionTransitionRole
    ingress_anchor_id: str
    ingress_pad_source_id: str
    egress_anchor_id: str
    egress_pad_source_id: str

    @model_validator(mode="after")
    def transition_is_explicit(self) -> Self:
        for name in (
            "transition_id",
            "component_reference",
            "ingress_anchor_id",
            "ingress_pad_source_id",
            "egress_anchor_id",
            "egress_pad_source_id",
        ):
            require_identity(getattr(self, name), name)
        if self.ingress_anchor_id == self.egress_anchor_id:
            raise ValueError("protection transition requires distinct ingress and egress anchors")
        if self.ingress_pad_source_id == self.egress_pad_source_id:
            raise ValueError("protection transition requires distinct physical pads")
        return self


class ConnectorProtectionOrderPolicy(SemanticIrModel):
    schema_id: Literal["pcbsmith-connector-protection-order-policy"] = (
        "pcbsmith-connector-protection-order-policy"
    )
    schema_version: Literal[1] = 1
    policy_id: str
    mode: Literal["advisory", "sourced_hard"]
    intended_consumer: str
    expected_component_order: tuple[str, ...] = Field(min_length=3)
    expected_transition_roles: tuple[ProtectionTransitionRole, ...] = Field(min_length=1)
    applicability_binding: EvidenceApplicabilityBinding | None

    @model_validator(mode="after")
    def policy_is_typed(self) -> Self:
        require_identity(self.policy_id, "policy_id")
        require_identity(self.intended_consumer, "intended_consumer")
        order = tuple(
            require_identity(item, "expected_component_order")
            for item in self.expected_component_order
        )
        if len(order) != len(set(order)):
            raise ValueError("expected protection component order must be unique")
        object.__setattr__(self, "expected_component_order", order)
        if len(self.expected_transition_roles) != len(order) - 2:
            raise ValueError(
                "transition roles must cover every component between connector and protected load"
            )
        if self.expected_transition_roles[0] != "esd_protection":
            raise ValueError("connector protection policy must place ESD first after the connector")
        if self.mode == "advisory" and self.applicability_binding is not None:
            raise ValueError("advisory connector protection policy cannot carry hard authority")
        return self


class ConnectorProtectionOrderDeclaration(SemanticIrModel):
    schema_id: Literal["pcbsmith-connector-protection-order-declaration"] = (
        "pcbsmith-connector-protection-order-declaration"
    )
    schema_version: Literal[1] = 1
    declaration_id: str
    connector_zone_result_fingerprint: str
    board_layout_snapshot_fingerprint: str
    board_netlist_snapshot_fingerprint: str
    connector_references: tuple[str, ...] = Field(min_length=1)
    legs: tuple[ConnectorProtectionLegDeclaration, ...] = Field(min_length=2)
    transitions: tuple[ConnectorProtectionTransition, ...] = Field(min_length=1)
    policy: ConnectorProtectionOrderPolicy

    @model_validator(mode="after")
    def declaration_is_a_chain(self) -> Self:
        require_identity(self.declaration_id, "declaration_id")
        for name in (
            "connector_zone_result_fingerprint",
            "board_layout_snapshot_fingerprint",
            "board_netlist_snapshot_fingerprint",
        ):
            require_sha256(getattr(self, name), name)
        connector_references = tuple(
            sorted(
                require_identity(item, "connector_references")
                for item in self.connector_references
            )
        )
        if len(connector_references) != len(set(connector_references)):
            raise ValueError("connector references must be unique")
        object.__setattr__(self, "connector_references", connector_references)
        if len(self.transitions) != len(self.legs) - 1:
            raise ValueError("each adjacent routed leg requires one component transition")
        if len(self.policy.expected_component_order) != len(self.legs) + 1:
            raise ValueError("expected component order must cover every routed leg endpoint")
        if len({item.leg_id for item in self.legs}) != len(self.legs):
            raise ValueError("connector protection leg identities must be unique")
        if len({item.transition_id for item in self.transitions}) != len(self.transitions):
            raise ValueError("connector protection transition identities must be unique")
        if self.policy.expected_component_order[0] not in connector_references:
            raise ValueError("expected protection order must originate at a declared connector")
        return self


def connector_protection_context_fingerprint(
    declaration: ConnectorProtectionOrderDeclaration,
) -> str:
    """Bind hard ordering authority to the exact connector and routed chain."""

    policy = declaration.policy
    return fingerprint(
        {
            "schema_id": "pcbsmith-connector-protection-source-context",
            "schema_version": 1,
            "declaration_id": declaration.declaration_id,
            "connector_zone_result_fingerprint": (
                declaration.connector_zone_result_fingerprint
            ),
            "board_layout_snapshot_fingerprint": (
                declaration.board_layout_snapshot_fingerprint
            ),
            "board_netlist_snapshot_fingerprint": (
                declaration.board_netlist_snapshot_fingerprint
            ),
            "connector_references": declaration.connector_references,
            "legs": [item.model_dump(mode="json") for item in declaration.legs],
            "transitions": [
                item.model_dump(mode="json") for item in declaration.transitions
            ],
            "policy": {
                "policy_id": policy.policy_id,
                "mode": policy.mode,
                "intended_consumer": policy.intended_consumer,
                "expected_component_order": policy.expected_component_order,
                "expected_transition_roles": policy.expected_transition_roles,
            },
        }
    )


class ConnectorProtectionOrderMetrics(SemanticIrModel):
    schema_id: Literal["pcbsmith-connector-protection-order-metrics"] = (
        "pcbsmith-connector-protection-order-metrics"
    )
    schema_version: Literal[1] = 1
    derived_component_order: tuple[str, ...]
    derived_transition_roles: tuple[ProtectionTransitionRole, ...]
    leg_terminal_component_references: tuple[tuple[str, tuple[str, ...]], ...]
    ordered_path_result_fingerprints: tuple[str, ...]


class ConnectorProtectionOrderResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-connector-protection-order-result"] = (
        "pcbsmith-connector-protection-order-result"
    )
    schema_version: Literal[1] = 1
    scope: Literal[
        "declared_connector_signal_chain_only_no_esd_rating_emc_or_system_immunity_claim"
    ] = "declared_connector_signal_chain_only_no_esd_rating_emc_or_system_immunity_claim"
    connector_zone: ConnectorZoneResult
    paths: tuple[ResolvedCopperPathResult, ...]
    declaration: ConnectorProtectionOrderDeclaration
    metrics: ConnectorProtectionOrderMetrics | None
    disposition: SemanticDisposition
    violation_ids: tuple[str, ...]
    unverified_reasons: tuple[str, ...]
    input_fingerprint: str
    result_fingerprint: str

    @field_validator("input_fingerprint", "result_fingerprint")
    @classmethod
    def sha_is_valid(cls, value: str, info: Any) -> str:
        return require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def result_is_replay_derived(self) -> Self:
        from pcbsmith.kicad.connector_protection_order import (
            rederive_connector_protection_order,
        )

        expected = rederive_connector_protection_order(
            self.connector_zone,
            self.paths,
            self.declaration,
        )
        names = (
            "paths",
            "declaration",
            "metrics",
            "disposition",
            "violation_ids",
            "unverified_reasons",
            "input_fingerprint",
        )
        if any(getattr(self, name) != expected[name] for name in names):
            raise ValueError("connector protection result is stale or not replay-derived")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("connector protection result fingerprint is stale")
        return self
