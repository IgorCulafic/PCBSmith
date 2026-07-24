"""R6.4 exact decoupling-loop metrics and declarative policy fixture."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from fractions import Fraction

import pytest
from pydantic import ValidationError

from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.decoupling_loop_ir import (
    DecouplingLoopDeclaration,
    DecouplingLoopEvaluationResult,
    DecouplingLoopPolicy,
    DecouplingTerminalInventory,
    DecouplingTerminalInventoryEntry,
    decoupling_loop_context_fingerprint,
)
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    TrackSegment,
    ViaSpec,
)
from pcbsmith.kicad.decoupling_loop import evaluate_decoupling_loop
from pcbsmith.kicad.routed_copper_graph import (
    build_routed_copper_graph,
    resolve_copper_path,
)
from pcbsmith.routed_copper_graph_ir import (
    CopperTerminalAnchorBinding,
    DeclaredCopperPathSelection,
    ExactRational,
)
from pcbsmith.semantic_ir import EvidenceApplicabilityBinding, SemanticDisposition


def _component(reference: str) -> BoardComponent:
    return BoardComponent(
        reference=reference,
        value="fixture",
        footprint="Fixture:TwoPad",
        uuid_path=f"uuid:{reference}",
    )


def _netlist(*, daisy: bool = False) -> BoardNetlist:
    refs = ("U1", "C1", "R1") if daisy else ("U1", "C1")
    return BoardNetlist(
        components=tuple(_component(item) for item in refs),
        nets=(
            BoardNet(
                name="VDD",
                nodes=(
                    ("U1", "1"),
                    ("C1", "1"),
                    *((("R1", "1"),) if daisy else ()),
                ),
            ),
            BoardNet(name="GND", nodes=(("U1", "2"), ("C1", "2"))),
        ),
    )


def _anchors(*, daisy: bool = False, bowtie: bool = False):
    load_power = (10, 2) if bowtie else (10, 0)
    load_return = (10, 0) if bowtie else (10, 2)
    values = [
        ("source-power", "pad:U1:1", "U1", "1", "VDD", "F.Cu", 0, 0),
        ("load-power", "pad:C1:1", "C1", "1", "VDD", "B.Cu", *load_power),
        ("load-return", "pad:C1:2", "C1", "2", "GND", "B.Cu", *load_return),
        ("source-return", "pad:U1:2", "U1", "2", "GND", "F.Cu", 0, 2),
    ]
    if daisy:
        values.append(("daisy-power", "pad:R1:1", "R1", "1", "VDD", "F.Cu", 2.5, 0))
    return tuple(
        CopperTerminalAnchorBinding(
            anchor_id=anchor_id,
            physical_pad_source_id=pad_id,
            component_reference=reference,
            pad_number=pad,
            net_name=net,
            layer=layer,
            x_mm=str(x_value),
            y_mm=str(y_value),
        )
        for anchor_id, pad_id, reference, pad, net, layer, x_value, y_value in values
    )


def _layout(
    *, daisy: bool = False, bowtie: bool = False, zone: bool = False, contact: bool = False
):
    netlist = _netlist(daisy=daisy)
    if bowtie:
        segments = (
            TrackSegment(0, 0, 5, 1, "F.Cu", "VDD", 0.2),
            TrackSegment(5, 1, 10, 2, "B.Cu", "VDD", 0.2),
            TrackSegment(10, 0, 5, 1, "B.Cu", "GND", 0.2),
            TrackSegment(5, 1, 0, 2, "F.Cu", "GND", 0.2),
        )
        vias = (ViaSpec(5, 1, "VDD"), ViaSpec(5, 1, "GND"))
    else:
        supply_front = (
            (
                TrackSegment(0, 0, 2.5, 0, "F.Cu", "VDD", 0.2),
                TrackSegment(2.5, 0, 5, 0, "F.Cu", "VDD", 0.2),
            )
            if daisy
            else (TrackSegment(0, 0, 5, 0, "F.Cu", "VDD", 0.2),)
        )
        segments = (
            *supply_front,
            TrackSegment(5, 0, 10, 0, "B.Cu", "VDD", 0.2),
            TrackSegment(10, 2, 5, 2, "B.Cu", "GND", 0.2),
            TrackSegment(5, 2, 0, 2, "F.Cu", "GND", 0.2),
            *((TrackSegment(2.5, 0, 2.5, 3, "F.Cu", "VDD", 0.2),) if contact else ()),
        )
        vias = (ViaSpec(5, 0, "VDD"), ViaSpec(5, 2, "GND"))
    return BoardLayout(
        placements=tuple((item, float(index)) for index, item in enumerate(netlist.components)),
        segments=segments,
        vias=vias,
        width_mm=12,
        height_mm=4,
        parts_row_y_mm=1,
        zones=(("VDD", "F.Cu", (0, 0, 10, 2)),) if zone else (),
    )


def _graph_paths(
    *, daisy: bool = False, bowtie: bool = False, zone: bool = False, contact: bool = False
):
    graph = build_routed_copper_graph(
        _layout(daisy=daisy, bowtie=bowtie, zone=zone, contact=contact),
        _netlist(daisy=daisy),
        _anchors(daisy=daisy, bowtie=bowtie),
    )
    supply = resolve_copper_path(
        graph,
        DeclaredCopperPathSelection(
            selection_id="selection:supply",
            graph_fingerprint=graph.graph_fingerprint,
            net_name="VDD",
            start_anchor_id="source-power",
            end_anchor_id="load-power",
            ordered_edge_ids=None,
        ),
    )
    return_leg = resolve_copper_path(
        graph,
        DeclaredCopperPathSelection(
            selection_id="selection:return",
            graph_fingerprint=graph.graph_fingerprint,
            net_name="GND",
            start_anchor_id="load-return",
            end_anchor_id="source-return",
            ordered_edge_ids=None,
        ),
    )
    return graph, supply, return_leg


def _inventory(graph, *, complete: bool = True, reverse: bool = False):
    anchors = graph.terminal_anchors
    entries = tuple(
        DecouplingTerminalInventoryEntry(
            anchor_id=item.anchor_id,
            physical_pad_source_id=item.physical_pad_source_id,
            component_reference=item.component_reference,
            pad_number=item.pad_number,
            net_name=item.net_name,
        )
        for item in anchors
    )
    if reverse:
        entries = tuple(reversed(entries))
    return DecouplingTerminalInventory(
        inventory_id="inventory:decoupling-terminals",
        graph_fingerprint=graph.graph_fingerprint,
        power_net_name="VDD",
        return_net_name="GND",
        completeness="complete" if complete else "incomplete",
        entries=entries,
    )


def _policy(**updates):
    fields = {
        "policy_id": "policy:decoupling-loop",
        "mode": "sourced_hard",
        "intended_consumer": "routed decoupling-loop acceptance",
        "maximum_via_count": ExactRational.build(Fraction(2)),
        "minimum_track_width_mm": Decimal("0.2"),
        "maximum_projected_loop_area_mm2": ExactRational.build(Fraction(20)),
        "require_dedicated": True,
        "applicability_binding": None,
        **updates,
    }
    return DecouplingLoopPolicy(**fields)


def _evidence(**updates) -> EvidenceRef:
    fields = {
        "kind": "manufacturer_design_guide",
        "title": "Fixture decoupling guide",
        "locator": "section 1",
        "source_id": "fixture-decoupling-guide",
        "organization_or_author": "PCBSmith fixture",
        "revision": "1",
        "official_url": "https://example.invalid/fixture.pdf",
        "local_sha256": "b" * 64,
        "source_status": "pinned",
        "locator_status": "text_verified",
        "applicability_status": "confirmed",
        "required_conditions": ("device=fixture-u1", "network=fixture-c1"),
        **updates,
    }
    return EvidenceRef(**fields)


def _declaration(
    graph,
    supply,
    return_leg,
    *,
    complete: bool = True,
    policy=None,
    reverse_inventory=False,
    bind_policy: bool = True,
):
    anchors = {item.anchor_id: item for item in graph.terminal_anchors}
    declaration = DecouplingLoopDeclaration(
        declaration_id="declaration:decoupling-loop",
        graph_fingerprint=graph.graph_fingerprint,
        board_layout_snapshot_fingerprint=graph.board_layout_snapshot_fingerprint,
        board_netlist_snapshot_fingerprint=graph.board_netlist_snapshot_fingerprint,
        supply_path_result_fingerprint=supply.result_fingerprint,
        return_path_result_fingerprint=return_leg.result_fingerprint,
        source_power_anchor_id="source-power",
        source_power_pad_source_id=anchors["source-power"].physical_pad_source_id,
        load_power_anchor_id="load-power",
        load_power_pad_source_id=anchors["load-power"].physical_pad_source_id,
        load_return_anchor_id="load-return",
        load_return_pad_source_id=anchors["load-return"].physical_pad_source_id,
        source_return_anchor_id="source-return",
        source_return_pad_source_id=anchors["source-return"].physical_pad_source_id,
        expected_power_net_name="VDD",
        expected_return_net_name="GND",
        terminal_inventory=_inventory(graph, complete=complete, reverse=reverse_inventory),
        policy=policy or _policy(),
    )
    if (
        bind_policy
        and declaration.policy.mode == "sourced_hard"
        and declaration.policy.applicability_binding is None
    ):
        conditions = ("device=fixture-u1", "network=fixture-c1")
        binding = EvidenceApplicabilityBinding(
            binding_id="binding:decoupling-policy",
            evidence=(_evidence(),),
            claim_id=declaration.policy.policy_id,
            applicability_record_id="applicability:decoupling-fixture",
            required_conditions=conditions,
            excluded_conditions=(),
            matched_conditions=conditions,
            unmatched_conditions=(),
            geometry_source_fingerprint=decoupling_loop_context_fingerprint(declaration),
            reviewer_record_id="review:decoupling-fixture",
        )
        declaration = declaration.model_copy(
            update={
                "policy": declaration.policy.model_copy(
                    update={"applicability_binding": binding}
                )
            }
        )
    return declaration


def test_exact_metrics_and_all_threshold_equalities_pass() -> None:
    graph, supply, return_leg = _graph_paths()
    result = evaluate_decoupling_loop(
        graph, supply, return_leg, _declaration(graph, supply, return_leg)
    )

    assert result.disposition is SemanticDisposition.PASS
    assert result.metrics is not None
    assert result.metrics.combined_via_count == 2
    assert len(result.metrics.combined_via_source_ids) == 2
    assert result.metrics.combined_minimum_track_width_mm == Decimal("0.2")
    assert len(result.metrics.combined_neck_edge_ids) == 4
    assert result.metrics.combined_radical_length_terms[0].coefficient_mm.fraction() == 20
    assert result.metrics.projected_loop_area_mm2 is not None
    assert result.metrics.projected_loop_area_mm2.fraction() == 20
    assert result.metrics.projected_closure_verification == "exact_simple"
    assert result.metrics.terminal_classification == "dedicated"
    assert len(result.metrics.closure_segments) == 2


@pytest.mark.parametrize(
    ("policy", "violation"),
    (
        (_policy(maximum_via_count=ExactRational.build(Fraction(1))), "maximum_via_count_exceeded"),
        (_policy(minimum_track_width_mm=Decimal("0.21")), "minimum_track_width_violated"),
        (
            _policy(maximum_projected_loop_area_mm2=ExactRational.build(Fraction(19))),
            "maximum_projected_loop_area_exceeded",
        ),
    ),
)
def test_exact_numeric_policy_violations_fail(policy, violation: str) -> None:
    graph, supply, return_leg = _graph_paths()
    result = evaluate_decoupling_loop(
        graph,
        supply,
        return_leg,
        _declaration(graph, supply, return_leg, policy=policy),
    )
    assert result.disposition is SemanticDisposition.FAIL
    assert violation in result.violation_ids


def test_advisory_policy_reports_candidate_violation_without_acceptance_authority() -> None:
    graph, supply, return_leg = _graph_paths()
    policy = _policy(
        mode="advisory",
        maximum_via_count=ExactRational.build(Fraction(1)),
    )
    result = evaluate_decoupling_loop(
        graph,
        supply,
        return_leg,
        _declaration(graph, supply, return_leg, policy=policy),
    )

    assert result.disposition is SemanticDisposition.ADVISORY
    assert result.violation_ids == ("maximum_via_count_exceeded",)
    assert result.unverified_reasons == ()


def test_sourced_hard_policy_without_binding_is_unverified() -> None:
    graph, supply, return_leg = _graph_paths()
    result = evaluate_decoupling_loop(
        graph,
        supply,
        return_leg,
        _declaration(graph, supply, return_leg, bind_policy=False),
    )

    assert result.disposition is SemanticDisposition.UNVERIFIED
    assert result.violation_ids == ()
    assert result.unverified_reasons == ("hard_policy_evidence_missing",)


@pytest.mark.parametrize(
    ("binding_update", "expected_reason"),
    (
        (
            {"claim_id": "policy:wrong-claim"},
            "hard_policy_claim_identity_mismatch",
        ),
        (
            {"reviewer_record_id": None},
            "hard_policy_applicability_incomplete",
        ),
        (
            {"geometry_source_fingerprint": "a" * 64},
            "hard_policy_context_fingerprint_mismatch",
        ),
    ),
)
def test_invalid_hard_binding_is_unverified(binding_update, expected_reason: str) -> None:
    graph, supply, return_leg = _graph_paths()
    declaration = _declaration(graph, supply, return_leg)
    binding = declaration.policy.applicability_binding
    assert binding is not None
    invalid_policy = declaration.policy.model_copy(
        update={"applicability_binding": binding.model_copy(update=binding_update)}
    )
    result = evaluate_decoupling_loop(
        graph,
        supply,
        return_leg,
        declaration.model_copy(update={"policy": invalid_policy}),
    )

    assert result.disposition is SemanticDisposition.UNVERIFIED
    assert expected_reason in result.unverified_reasons


@pytest.mark.parametrize(
    "evidence_update",
    (
        {"revision": None},
        {"source_status": "unpinned"},
        {"locator_status": "unverified"},
        {"applicability_status": "conditional"},
        {"required_conditions": ()},
    ),
)
def test_non_authoritative_evidence_cannot_drive_hard_policy(evidence_update) -> None:
    graph, supply, return_leg = _graph_paths()
    declaration = _declaration(graph, supply, return_leg)
    binding = declaration.policy.applicability_binding
    assert binding is not None
    invalid_evidence = binding.evidence[0].model_copy(update=evidence_update)
    invalid_binding = binding.model_copy(update={"evidence": (invalid_evidence,)})
    invalid_policy = declaration.policy.model_copy(
        update={"applicability_binding": invalid_binding}
    )
    result = evaluate_decoupling_loop(
        graph,
        supply,
        return_leg,
        declaration.model_copy(update={"policy": invalid_policy}),
    )

    assert result.disposition is SemanticDisposition.UNVERIFIED
    assert (
        "hard_policy_evidence_not_revisioned_pinned_verified_applicable"
        in result.unverified_reasons
    )


def test_stale_binding_cannot_authorize_changed_threshold() -> None:
    graph, supply, return_leg = _graph_paths()
    declaration = _declaration(graph, supply, return_leg)
    changed_policy = declaration.policy.model_copy(
        update={"maximum_via_count": ExactRational.build(Fraction(1))}
    )
    result = evaluate_decoupling_loop(
        graph,
        supply,
        return_leg,
        declaration.model_copy(update={"policy": changed_policy}),
    )

    assert result.disposition is SemanticDisposition.UNVERIFIED
    assert result.violation_ids == ()
    assert "hard_policy_context_fingerprint_mismatch" in result.unverified_reasons


def test_policy_schema_fails_closed_for_legacy_bare_threshold_payload() -> None:
    payload = _policy().model_dump(mode="json")
    payload["schema_version"] = 1
    payload.pop("mode")
    payload.pop("intended_consumer")
    payload.pop("applicability_binding")

    with pytest.raises(ValidationError):
        DecouplingLoopPolicy.model_validate(payload)


def test_advisory_policy_rejects_hard_binding() -> None:
    graph, supply, return_leg = _graph_paths()
    hard_policy = _declaration(graph, supply, return_leg).policy

    with pytest.raises(ValidationError, match="cannot carry hard evidence authority"):
        DecouplingLoopPolicy(**hard_policy.model_dump(mode="python") | {"mode": "advisory"})


def test_complete_inventory_detects_interior_daisy_anchor_and_fails_dedicated_policy() -> None:
    graph, supply, return_leg = _graph_paths(daisy=True)
    result = evaluate_decoupling_loop(
        graph, supply, return_leg, _declaration(graph, supply, return_leg)
    )
    assert result.metrics is not None
    assert result.metrics.terminal_classification == "daisy_chain"
    assert result.metrics.interior_anchor_ids == ("daisy-power",)
    assert result.disposition is SemanticDisposition.FAIL
    assert "dedicated_topology_required" in result.violation_ids


def test_incomplete_inventory_makes_policy_unverified_but_retains_exact_metrics() -> None:
    graph, supply, return_leg = _graph_paths()
    declaration = _declaration(graph, supply, return_leg, complete=False)
    # An incomplete inventory may retain all known entries; it still cannot claim completeness.
    result = evaluate_decoupling_loop(graph, supply, return_leg, declaration)
    assert result.metrics is not None
    assert result.metrics.terminal_classification == "unverified"
    assert result.disposition is SemanticDisposition.UNVERIFIED
    assert "terminal_inventory_incomplete" in result.unverified_reasons

    permissive = _policy(require_dedicated=False)
    result = evaluate_decoupling_loop(
        graph,
        supply,
        return_leg,
        _declaration(graph, supply, return_leg, complete=False, policy=permissive),
    )
    assert result.disposition is SemanticDisposition.UNVERIFIED


def test_complete_inventory_cannot_omit_or_invent_relevant_anchor() -> None:
    graph, supply, return_leg = _graph_paths()
    declaration = _declaration(graph, supply, return_leg)
    incomplete_entries = declaration.terminal_inventory.entries[:-1]
    stale_inventory = declaration.terminal_inventory.model_copy(
        update={"entries": incomplete_entries}
    )
    with pytest.raises(ValueError, match="equal all retained BoardNetlist nodes"):
        evaluate_decoupling_loop(
            graph,
            supply,
            return_leg,
            declaration.model_copy(update={"terminal_inventory": stale_inventory}),
        )


def test_complete_inventory_cannot_hide_netlist_node_from_graph_and_inventory() -> None:
    # R1:1 remains an actual VDD BoardNetlist node and the routed track is split at it,
    # but the caller deliberately omits its physical-pad anchor from both authorities.
    graph = build_routed_copper_graph(
        _layout(daisy=True), _netlist(daisy=True), _anchors(daisy=False)
    )
    supply = resolve_copper_path(
        graph,
        DeclaredCopperPathSelection(
            selection_id="selection:supply-hidden-node",
            graph_fingerprint=graph.graph_fingerprint,
            net_name="VDD",
            start_anchor_id="source-power",
            end_anchor_id="load-power",
            ordered_edge_ids=None,
        ),
    )
    return_leg = resolve_copper_path(
        graph,
        DeclaredCopperPathSelection(
            selection_id="selection:return-hidden-node",
            graph_fingerprint=graph.graph_fingerprint,
            net_name="GND",
            start_anchor_id="load-return",
            end_anchor_id="source-return",
            ordered_edge_ids=None,
        ),
    )
    declaration = _declaration(graph, supply, return_leg)

    with pytest.raises(ValueError, match="equal all retained BoardNetlist nodes"):
        evaluate_decoupling_loop(graph, supply, return_leg, declaration)


def test_inventory_and_graph_reject_duplicate_pad_aliases() -> None:
    graph, supply, return_leg = _graph_paths()
    inventory = _inventory(graph)
    original = inventory.entries[0]
    duplicate_source = original.model_copy(update={"anchor_id": "alias:source"})
    with pytest.raises(ValidationError, match="physical pad source identities"):
        DecouplingTerminalInventory(
            inventory_id=inventory.inventory_id,
            graph_fingerprint=inventory.graph_fingerprint,
            power_net_name=inventory.power_net_name,
            return_net_name=inventory.return_net_name,
            completeness="complete",
            entries=(*inventory.entries, duplicate_source),
        )
    duplicate_pad = original.model_copy(
        update={"anchor_id": "alias:pad", "physical_pad_source_id": "pad:alias"}
    )
    with pytest.raises(ValidationError, match="component/pad identities"):
        DecouplingTerminalInventory(
            inventory_id=inventory.inventory_id,
            graph_fingerprint=inventory.graph_fingerprint,
            power_net_name=inventory.power_net_name,
            return_net_name=inventory.return_net_name,
            completeness="complete",
            entries=(*inventory.entries, duplicate_pad),
        )

    base_anchors = _anchors()
    alias_anchor = base_anchors[0].model_copy(
        update={"anchor_id": "alias:graph-pad", "physical_pad_source_id": "pad:graph-alias"}
    )
    alias_graph = build_routed_copper_graph(_layout(), _netlist(), (*base_anchors, alias_anchor))
    alias_supply = resolve_copper_path(
        alias_graph,
        DeclaredCopperPathSelection(
            selection_id="selection:supply-alias",
            graph_fingerprint=alias_graph.graph_fingerprint,
            net_name="VDD",
            start_anchor_id="source-power",
            end_anchor_id="load-power",
            ordered_edge_ids=None,
        ),
    )
    alias_return = resolve_copper_path(
        alias_graph,
        DeclaredCopperPathSelection(
            selection_id="selection:return-alias",
            graph_fingerprint=alias_graph.graph_fingerprint,
            net_name="GND",
            start_anchor_id="load-return",
            end_anchor_id="source-return",
            ordered_edge_ids=None,
        ),
    )
    base_declaration = _declaration(graph, supply, return_leg, complete=False)
    alias_inventory = base_declaration.terminal_inventory.model_copy(
        update={"graph_fingerprint": alias_graph.graph_fingerprint}
    )
    alias_declaration = base_declaration.model_copy(
        update={
            "graph_fingerprint": alias_graph.graph_fingerprint,
            "board_layout_snapshot_fingerprint": (alias_graph.board_layout_snapshot_fingerprint),
            "board_netlist_snapshot_fingerprint": (alias_graph.board_netlist_snapshot_fingerprint),
            "supply_path_result_fingerprint": alias_supply.result_fingerprint,
            "return_path_result_fingerprint": alias_return.result_fingerprint,
            "terminal_inventory": alias_inventory,
        }
    )
    with pytest.raises(ValueError, match="duplicate component/pad anchor aliases"):
        evaluate_decoupling_loop(alias_graph, alias_supply, alias_return, alias_declaration)


@pytest.mark.parametrize("condition", ("zone", "contact"))
def test_zone_or_contact_unknown_propagates_without_metrics(condition: str) -> None:
    graph, supply, return_leg = _graph_paths(
        zone=condition == "zone", contact=condition == "contact"
    )
    result = evaluate_decoupling_loop(
        graph, supply, return_leg, _declaration(graph, supply, return_leg)
    )
    assert result.metrics is None
    assert result.disposition is SemanticDisposition.UNVERIFIED
    assert "supply_path_not_exact_connected" in result.unverified_reasons


def test_self_intersecting_projected_closure_is_unverified_never_float_area() -> None:
    graph, supply, return_leg = _graph_paths(bowtie=True)
    result = evaluate_decoupling_loop(
        graph, supply, return_leg, _declaration(graph, supply, return_leg)
    )
    assert result.metrics is not None
    assert result.metrics.projected_loop_area_mm2 is None
    assert result.metrics.projected_closure_verification == "unverified_non_simple"
    assert result.disposition is SemanticDisposition.UNVERIFIED
    assert "projected_loop_area_unverified" in result.unverified_reasons


def test_reversed_inventory_order_is_canonical_and_result_deterministic() -> None:
    graph, supply, return_leg = _graph_paths()
    first_declaration = _declaration(graph, supply, return_leg)
    second_declaration = _declaration(graph, supply, return_leg, reverse_inventory=True)
    assert first_declaration == second_declaration
    assert evaluate_decoupling_loop(
        graph, supply, return_leg, first_declaration
    ) == evaluate_decoupling_loop(graph, supply, return_leg, second_declaration)


def test_reversed_path_roles_and_stale_pad_path_graph_bindings_reject() -> None:
    graph, supply, return_leg = _graph_paths()
    declaration = _declaration(graph, supply, return_leg)
    reversed_supply = resolve_copper_path(
        graph,
        DeclaredCopperPathSelection(
            selection_id="selection:supply-reversed",
            graph_fingerprint=graph.graph_fingerprint,
            net_name="VDD",
            start_anchor_id="load-power",
            end_anchor_id="source-power",
            ordered_edge_ids=None,
        ),
    )
    stale = declaration.model_copy(
        update={"supply_path_result_fingerprint": reversed_supply.result_fingerprint}
    )
    with pytest.raises(ValueError, match="terminal roles"):
        evaluate_decoupling_loop(graph, reversed_supply, return_leg, stale)

    for update in (
        {"source_power_pad_source_id": "pad:wrong"},
        {"graph_fingerprint": "a" * 64},
        {"supply_path_result_fingerprint": "a" * 64},
    ):
        with pytest.raises(ValueError):
            evaluate_decoupling_loop(
                graph, supply, return_leg, declaration.model_copy(update=update)
            )


def test_json_replay_direct_tamper_and_input_immutability() -> None:
    graph, supply, return_leg = _graph_paths()
    declaration = _declaration(graph, supply, return_leg)
    before = (
        graph.model_dump_json(),
        supply.model_dump_json(),
        return_leg.model_dump_json(),
        declaration.model_dump_json(),
    )
    result = evaluate_decoupling_loop(graph, supply, return_leg, declaration)
    assert DecouplingLoopEvaluationResult.model_validate_json(result.model_dump_json()) == result
    after = (
        graph.model_dump_json(),
        supply.model_dump_json(),
        return_leg.model_dump_json(),
        declaration.model_dump_json(),
    )
    assert after == before

    for mutate in (
        lambda payload: payload["metrics"].update({"combined_via_count": 0}),
        lambda payload: payload.update({"disposition": "fail"}),
        lambda payload: payload.update({"violation_ids": ["tampered"]}),
        lambda payload: payload.update({"input_fingerprint": "a" * 64}),
        lambda payload: payload.update({"result_fingerprint": "a" * 64}),
    ):
        payload = deepcopy(result.model_dump(mode="json"))
        mutate(payload)
        with pytest.raises(ValidationError):
            DecouplingLoopEvaluationResult.model_validate(payload)

    stale_path = supply.model_copy(update={"connectivity_state": "disconnected"})
    with pytest.raises(ValidationError):
        evaluate_decoupling_loop(graph, stale_path, return_leg, declaration)
