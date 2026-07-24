"""Connector-to-protection ordering over replayed connector and copper authorities."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pcbsmith.connector_protection_order_ir import (
    ConnectorProtectionLegDeclaration,
    ConnectorProtectionOrderDeclaration,
    ConnectorProtectionOrderMetrics,
    ConnectorProtectionOrderResult,
    connector_protection_context_fingerprint,
)
from pcbsmith.connector_zone_ir import ConnectorRole, ConnectorZoneResult
from pcbsmith.kicad.board_serialization import parse_canonical_board_netlist_snapshot
from pcbsmith.routed_copper_graph_ir import ResolvedCopperPathResult, fingerprint
from pcbsmith.semantic_ir import SemanticDisposition, SemanticVerification


def _is_sha256(value: str | None) -> bool:
    return (
        value is not None
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_path_leg(
    path: ResolvedCopperPathResult,
    leg: ConnectorProtectionLegDeclaration,
) -> None:
    actual = (
        path.selection.start_anchor_id,
        path.selection.end_anchor_id,
        path.selection.net_name,
    )
    expected = (leg.start_anchor_id, leg.end_anchor_id, leg.net_name)
    if actual != expected:
        raise ValueError("connector protection path does not follow its declared anchors/net")
    anchors = {item.anchor_id: item for item in path.graph.terminal_anchors}
    expected_pads = {
        leg.start_anchor_id: leg.start_pad_source_id,
        leg.end_anchor_id: leg.end_pad_source_id,
    }
    if any(
        anchor_id not in anchors or anchors[anchor_id].physical_pad_source_id != pad_source_id
        for anchor_id, pad_source_id in expected_pads.items()
    ):
        raise ValueError("connector protection leg physical pad authority is stale")


def _validate_inputs(
    connector_zone_result: ConnectorZoneResult,
    path_results: Sequence[ResolvedCopperPathResult],
    declaration: ConnectorProtectionOrderDeclaration,
) -> tuple[
    ConnectorZoneResult,
    tuple[ResolvedCopperPathResult, ...],
    ConnectorProtectionOrderDeclaration,
]:
    connector_zone = ConnectorZoneResult.model_validate_json(
        connector_zone_result.model_dump_json()
    )
    retained = ConnectorProtectionOrderDeclaration.model_validate_json(
        declaration.model_dump_json()
    )
    supplied = tuple(
        ResolvedCopperPathResult.model_validate_json(item.model_dump_json())
        for item in path_results
    )
    by_fingerprint = {item.result_fingerprint: item for item in supplied}
    if len(by_fingerprint) != len(supplied):
        raise ValueError("connector protection path identities must be unique")
    expected_fingerprints = tuple(item.path_result_fingerprint for item in retained.legs)
    if set(by_fingerprint) != set(expected_fingerprints):
        raise ValueError("connector protection declaration/path authority is stale")
    paths = tuple(by_fingerprint[item] for item in expected_fingerprints)
    connector_declaration = connector_zone.declaration
    if (
        retained.connector_zone_result_fingerprint != connector_zone.result_fingerprint
        or retained.board_layout_snapshot_fingerprint
        != connector_declaration.board_layout_snapshot_fingerprint
        or retained.board_netlist_snapshot_fingerprint
        != connector_declaration.board_netlist_snapshot_fingerprint
        or retained.connector_references != connector_declaration.connector_references
    ):
        raise ValueError("connector protection declaration has stale connector-zone authority")
    for leg, path in zip(retained.legs, paths, strict=True):
        if (
            path.graph.board_layout_snapshot_fingerprint
            != retained.board_layout_snapshot_fingerprint
            or path.graph.board_netlist_snapshot_fingerprint
            != retained.board_netlist_snapshot_fingerprint
        ):
            raise ValueError("connector protection path is bound to stale board snapshots")
        _validate_path_leg(path, leg)
    for index, transition in enumerate(retained.transitions):
        left = paths[index]
        right = paths[index + 1]
        left_anchors = {item.anchor_id: item for item in left.graph.terminal_anchors}
        right_anchors = {item.anchor_id: item for item in right.graph.terminal_anchors}
        ingress = left_anchors.get(transition.ingress_anchor_id)
        egress = right_anchors.get(transition.egress_anchor_id)
        if (
            left.selection.end_anchor_id != transition.ingress_anchor_id
            or right.selection.start_anchor_id != transition.egress_anchor_id
            or ingress is None
            or egress is None
            or ingress.physical_pad_source_id != transition.ingress_pad_source_id
            or egress.physical_pad_source_id != transition.egress_pad_source_id
            or ingress.component_reference != transition.component_reference
            or egress.component_reference != transition.component_reference
        ):
            raise ValueError("connector protection transition does not join adjacent path pads")
    return connector_zone, paths, retained


def _hard_binding_reasons(
    declaration: ConnectorProtectionOrderDeclaration,
) -> tuple[str, ...]:
    policy = declaration.policy
    binding = policy.applicability_binding
    if binding is None:
        return ("hard_protection_policy_evidence_missing",)
    reasons = []
    if binding.claim_id != policy.policy_id:
        reasons.append("hard_protection_policy_claim_identity_mismatch")
    if (
        not binding.required_conditions
        or binding.unmatched_conditions
        or set(binding.matched_conditions) != set(binding.required_conditions)
        or binding.reviewer_record_id is None
    ):
        reasons.append("hard_protection_policy_applicability_incomplete")
    if binding.geometry_source_fingerprint != connector_protection_context_fingerprint(
        declaration
    ):
        reasons.append("hard_protection_policy_context_fingerprint_mismatch")
    binding_conditions = set(binding.required_conditions)
    if not all(
        bool(item.source_id and item.source_id.strip())
        and bool(item.revision and item.revision.strip())
        and item.source_status == "pinned"
        and _is_sha256(item.local_sha256)
        and item.locator_status in {"text_verified", "figure_verified"}
        and item.applicability_status == "confirmed"
        and item.required_conditions
        and set(item.required_conditions).issubset(binding_conditions)
        for item in binding.evidence
    ):
        reasons.append(
            "hard_protection_policy_evidence_not_revisioned_pinned_verified_applicable"
        )
    return tuple(sorted(reasons))


def _terminal_inventory(
    path: ResolvedCopperPathResult,
    leg: ConnectorProtectionLegDeclaration,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    netlist = parse_canonical_board_netlist_snapshot(path.graph.board_netlist_snapshot_json)
    netlist_nodes = {
        node for net in netlist.nets if net.name == leg.net_name for node in net.nodes
    }
    anchors = tuple(
        item for item in path.graph.terminal_anchors if item.net_name == leg.net_name
    )
    anchor_nodes = tuple((item.component_reference, item.pad_number) for item in anchors)
    reasons = []
    if (
        len(anchor_nodes) != len(set(anchor_nodes))
        or len({item.physical_pad_source_id for item in anchors}) != len(anchors)
    ):
        reasons.append(f"{leg.leg_id}:duplicate_terminal_anchor_alias")
    if set(anchor_nodes) != netlist_nodes:
        reasons.append(f"{leg.leg_id}:terminal_inventory_incomplete")
    component_references = tuple(sorted({reference for reference, _pad in netlist_nodes}))
    return component_references, tuple(reasons)


def _derive_metrics_and_reasons(
    paths: tuple[ResolvedCopperPathResult, ...],
    declaration: ConnectorProtectionOrderDeclaration,
) -> tuple[ConnectorProtectionOrderMetrics | None, tuple[str, ...]]:
    reasons = []
    for leg, path in zip(declaration.legs, paths, strict=True):
        if (
            path.connectivity_state != "connected"
            or path.verification is not SemanticVerification.EXACT
            or path.unknown_reasons
        ):
            reasons.append(f"{leg.leg_id}:path_not_exact_connected")
    if reasons:
        return None, tuple(sorted(reasons))
    first_anchors = {item.anchor_id: item for item in paths[0].graph.terminal_anchors}
    final_anchors = {item.anchor_id: item for item in paths[-1].graph.terminal_anchors}
    component_order = (
        first_anchors[declaration.legs[0].start_anchor_id].component_reference,
        *(item.component_reference for item in declaration.transitions),
        final_anchors[declaration.legs[-1].end_anchor_id].component_reference,
    )
    inventory: list[tuple[str, tuple[str, ...]]] = []
    for leg, path in zip(declaration.legs, paths, strict=True):
        component_references, leg_reasons = _terminal_inventory(path, leg)
        inventory.append((leg.leg_id, component_references))
        reasons.extend(leg_reasons)
    metrics = ConnectorProtectionOrderMetrics(
        derived_component_order=component_order,
        derived_transition_roles=tuple(item.role for item in declaration.transitions),
        leg_terminal_component_references=tuple(inventory),
        ordered_path_result_fingerprints=tuple(item.result_fingerprint for item in paths),
    )
    return metrics, tuple(sorted(reasons))


def _policy_violations(
    metrics: ConnectorProtectionOrderMetrics,
    declaration: ConnectorProtectionOrderDeclaration,
) -> tuple[str, ...]:
    policy = declaration.policy
    violations = []
    if metrics.derived_component_order != policy.expected_component_order:
        violations.append("expected_component_order_violated")
    if metrics.derived_transition_roles != policy.expected_transition_roles:
        violations.append("expected_protection_role_order_violated")
    if metrics.derived_component_order[0] not in declaration.connector_references:
        violations.append("protection_chain_does_not_originate_at_connector")
    for index, (leg_id, actual_references) in enumerate(
        metrics.leg_terminal_component_references
    ):
        expected_references = {
            policy.expected_component_order[index],
            policy.expected_component_order[index + 1],
            *declaration.legs[index].declared_parallel_component_references,
        }
        if set(actual_references) != expected_references:
            violations.append(f"{leg_id}:unexpected_parallel_or_bypass_component")
    return tuple(sorted(violations))


def rederive_connector_protection_order(
    connector_zone_result: ConnectorZoneResult,
    path_results: Sequence[ResolvedCopperPathResult],
    declaration: ConnectorProtectionOrderDeclaration,
) -> dict[str, Any]:
    connector_zone, paths, retained = _validate_inputs(
        connector_zone_result, path_results, declaration
    )
    metrics, intrinsic_reasons = _derive_metrics_and_reasons(paths, retained)
    unverified = list(intrinsic_reasons)
    if metrics is not None and retained.policy.mode == "sourced_hard":
        unverified.extend(_hard_binding_reasons(retained))
    violations = (
        () if metrics is None or unverified else _policy_violations(metrics, retained)
    )
    unverified_tuple = tuple(sorted(set(unverified)))
    if connector_zone.declaration.connector_role is ConnectorRole.ON_BOARD_MODULE:
        disposition = SemanticDisposition.NOT_APPLICABLE
        violations = ()
        unverified_tuple = ()
    else:
        disposition = (
            SemanticDisposition.UNVERIFIED
            if unverified_tuple
            else SemanticDisposition.ADVISORY
            if retained.policy.mode == "advisory"
            else SemanticDisposition.FAIL
            if violations
            else SemanticDisposition.PASS
        )
    input_fp = fingerprint(
        {
            "connector_zone": connector_zone.result_fingerprint,
            "paths": tuple(item.result_fingerprint for item in paths),
            "declaration": retained.semantic_fingerprint(),
        }
    )
    return {
        "paths": paths,
        "declaration": retained,
        "metrics": metrics,
        "disposition": disposition,
        "violation_ids": violations,
        "unverified_reasons": unverified_tuple,
        "input_fingerprint": input_fp,
    }


def evaluate_connector_protection_order(
    connector_zone: ConnectorZoneResult,
    paths: Sequence[ResolvedCopperPathResult],
    declaration: ConnectorProtectionOrderDeclaration,
) -> ConnectorProtectionOrderResult:
    derived = rederive_connector_protection_order(connector_zone, paths, declaration)
    fields = {"connector_zone": connector_zone, **derived}
    provisional = ConnectorProtectionOrderResult.model_construct(
        **fields, result_fingerprint="0" * 64
    )
    result_fp = fingerprint(
        provisional.model_dump(mode="json", exclude={"result_fingerprint"})
    )
    return ConnectorProtectionOrderResult(**fields, result_fingerprint=result_fp)
