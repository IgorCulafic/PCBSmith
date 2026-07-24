"""Connector-to-ESD ordering over connector-zone and routed-copper authority."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.connector_protection_order_ir import (
    ConnectorProtectionLegDeclaration,
    ConnectorProtectionOrderDeclaration,
    ConnectorProtectionOrderPolicy,
    ConnectorProtectionOrderResult,
    ConnectorProtectionTransition,
    connector_protection_context_fingerprint,
)
from pcbsmith.connector_zone_ir import (
    ConnectorLocalGeometry,
    ConnectorPadGeometry,
    ConnectorRole,
    ConnectorZoneDeclaration,
    connector_threshold_context_fingerprint,
    fingerprint,
)
from pcbsmith.kicad.board import BoardComponent, BoardLayout, BoardNet, BoardNetlist, TrackSegment
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.kicad.connector_protection_order import evaluate_connector_protection_order
from pcbsmith.kicad.connector_zone import evaluate_connector_zone, outline_edges
from pcbsmith.kicad.routed_copper_graph import build_routed_copper_graph, resolve_copper_path
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon
from pcbsmith.routed_copper_graph_ir import (
    CopperTerminalAnchorBinding,
    DeclaredCopperPathSelection,
)
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticDisposition,
    SemanticRegion,
    SemanticVerification,
)


def _rect(x1: float, y1: float, x2: float, y2: float) -> ExactPlanarCompound:
    return ExactPlanarCompound(
        polygons=(ExactPlanarPolygon(outer=((x1, y1), (x2, y1), (x2, y2), (x1, y2))),)
    )


def _fixture(*, bypass: bool = False, omit_bypass_anchor: bool = False):
    j1 = BoardComponent("J1", "USB", "Connector:Fixture", "uuid:j1")
    u2 = BoardComponent("U2", "ESD", "Package:SOT", "uuid:u2")
    u1 = BoardComponent("U1", "MCU", "Package:MCU", "uuid:u1")
    r1 = BoardComponent("R1", "BYPASS", "Package:R", "uuid:r1")
    components = (j1, u2, u1, *((r1,) if bypass else ()))
    raw_nodes = (("J1", "1"), ("U2", "1"), *(((("R1", "1"),)) if bypass else ()))
    netlist = BoardNetlist(
        components=components,
        nets=(
            BoardNet("USB_RAW", raw_nodes),
            BoardNet("USB_PROTECTED", (("U2", "6"), ("U1", "1"))),
        ),
    )
    layout = BoardLayout(
        placements=tuple(
            (item, x)
            for item, x in zip(components, (0.5, 4.5, 10.5, 2.5), strict=False)
        ),
        segments=(
            TrackSegment(0.5, 2, 4.5, 2, "F.Cu", "USB_RAW", 0.2),
            TrackSegment(5.5, 2, 10.5, 2, "F.Cu", "USB_PROTECTED", 0.2),
        ),
        vias=(),
        width_mm=12,
        height_mm=4,
        parts_row_y_mm=2,
        outline=((0.0, 0.0), (12.0, 0.0), (12.0, 4.0), (0.0, 4.0)),
    )
    anchors = [
        CopperTerminalAnchorBinding(
            anchor_id="connector-out",
            physical_pad_source_id="pad:J1:1",
            component_reference="J1",
            pad_number="1",
            net_name="USB_RAW",
            layer="F.Cu",
            x_mm="0.5",
            y_mm="2",
        ),
        CopperTerminalAnchorBinding(
            anchor_id="esd-in",
            physical_pad_source_id="pad:U2:1",
            component_reference="U2",
            pad_number="1",
            net_name="USB_RAW",
            layer="F.Cu",
            x_mm="4.5",
            y_mm="2",
        ),
        CopperTerminalAnchorBinding(
            anchor_id="esd-out",
            physical_pad_source_id="pad:U2:6",
            component_reference="U2",
            pad_number="6",
            net_name="USB_PROTECTED",
            layer="F.Cu",
            x_mm="5.5",
            y_mm="2",
        ),
        CopperTerminalAnchorBinding(
            anchor_id="load-in",
            physical_pad_source_id="pad:U1:1",
            component_reference="U1",
            pad_number="1",
            net_name="USB_PROTECTED",
            layer="F.Cu",
            x_mm="10.5",
            y_mm="2",
        ),
    ]
    if bypass and not omit_bypass_anchor:
        anchors.append(
            CopperTerminalAnchorBinding(
                anchor_id="bypass-in",
                physical_pad_source_id="pad:R1:1",
                component_reference="R1",
                pad_number="1",
                net_name="USB_RAW",
                layer="F.Cu",
                x_mm="2.5",
                y_mm="3",
            )
        )
    graph = build_routed_copper_graph(layout, netlist, tuple(anchors))
    raw = resolve_copper_path(
        graph,
        DeclaredCopperPathSelection(
            selection_id="selection:raw",
            graph_fingerprint=graph.graph_fingerprint,
            net_name="USB_RAW",
            start_anchor_id="connector-out",
            end_anchor_id="esd-in",
            ordered_edge_ids=None,
        ),
    )
    protected = resolve_copper_path(
        graph,
        DeclaredCopperPathSelection(
            selection_id="selection:protected",
            graph_fingerprint=graph.graph_fingerprint,
            net_name="USB_PROTECTED",
            start_anchor_id="esd-out",
            end_anchor_id="load-in",
            ordered_edge_ids=None,
        ),
    )
    return layout, netlist, raw, protected


def _connector_geometry() -> ConnectorLocalGeometry:
    fields = {
        "reference": "J1",
        "installed_footprint_id": "Connector:Fixture",
        "component_uuid_path": "uuid:j1",
        "source_file_sha256": "c" * 64,
        "source_binding_id": "binding:connector-geometry",
        "body_region_id": "body:J1",
        "body_compound": _rect(-0.3, -0.3, 0.3, 0.3),
        "body_layers": ("F.Fab",),
        "pads": (
            ConnectorPadGeometry(
                pad_id="1",
                compound=_rect(-0.1, -0.1, 0.1, 0.1),
                layers=("F.Cu",),
            ),
        ),
    }
    provisional = ConnectorLocalGeometry.model_construct(
        **fields, geometry_fingerprint="0" * 64
    )
    return ConnectorLocalGeometry(
        **fields,
        geometry_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"geometry_fingerprint"})
        ),
    )


def _connector_binding(context: str) -> EvidenceApplicabilityBinding:
    conditions = ("connector-footprint=fixture",)
    return EvidenceApplicabilityBinding(
        binding_id="binding:connector-geometry",
        evidence=(
            EvidenceRef(
                kind="component_datasheet",
                title="Connector fixture drawing",
                locator="figure 1",
                source_id="source:connector-fixture",
                revision="1",
                local_sha256="d" * 64,
                source_status="pinned",
                locator_status="figure_verified",
                applicability_status="confirmed",
                required_conditions=conditions,
            ),
        ),
        claim_id="claim:connector-geometry",
        applicability_record_id="applicability:connector-geometry",
        required_conditions=conditions,
        excluded_conditions=(),
        matched_conditions=conditions,
        unmatched_conditions=(),
        geometry_source_fingerprint=context,
        reviewer_record_id="review:connector-geometry",
    )


def _connector_zone(layout: BoardLayout, netlist: BoardNetlist, *, on_board: bool = False):
    layout_json = canonical_board_layout_snapshot_json(layout)
    netlist_json = canonical_board_netlist_snapshot_json(netlist)
    layout_fp = board_layout_snapshot_fingerprint(layout_json)
    netlist_fp = board_netlist_snapshot_fingerprint(netlist_json)
    edge = next(
        edge_id
        for edge_id, start, end in outline_edges(layout)
        if {start, end} == {(0.0, 0.0), (0.0, 4.0)}
    )
    role = ConnectorRole.ON_BOARD_MODULE if on_board else ConnectorRole.OFF_BOARD_IO
    zone = SemanticRegion(
        region_id="zone:connector",
        coordinate_space="board",
        owner_reference=None,
        compound=_rect(0, 1, 2, 3),
        layers=("F.Cu",),
        verification=SemanticVerification.EXACT,
        maximum_error_mm=None,
        source_binding_ids=("binding:connector-geometry",),
    )
    context = connector_threshold_context_fingerprint(
        layout_fp,
        netlist_fp,
        ("J1",),
        role,
        zone.semantic_fingerprint(),
        (edge,),
        (),
    )
    declaration = ConnectorZoneDeclaration(
        declaration_id="declaration:connector-zone",
        zone_id=zone.region_id,
        board_layout_snapshot_json=layout_json,
        board_netlist_snapshot_json=netlist_json,
        board_layout_snapshot_fingerprint=layout_fp,
        board_netlist_snapshot_fingerprint=netlist_fp,
        connector_references=("J1",),
        connector_role=role,
        zone_region=zone,
        allowed_edge_ids=(edge,),
        maximum_body_to_edge_distance=None,
        connector_geometries=(_connector_geometry(),),
        body_zone_rule_id="rule:connector-body-zone",
        pad_zone_rule_id="rule:connector-pad-zone",
        body_material_rule_id="rule:connector-body-material",
        pad_material_rule_id="rule:connector-pad-material",
        edge_rule_id="rule:connector-edge",
        evidence_bindings=(_connector_binding(context),),
    )
    return evaluate_connector_zone(layout, netlist, declaration)


def _policy(**updates) -> ConnectorProtectionOrderPolicy:
    fields = {
        "policy_id": "policy:connector-esd-order",
        "mode": "sourced_hard",
        "intended_consumer": "connector signal-chain acceptance",
        "expected_component_order": ("J1", "U2", "U1"),
        "expected_transition_roles": ("esd_protection",),
        "applicability_binding": None,
        **updates,
    }
    return ConnectorProtectionOrderPolicy(**fields)


def _protection_evidence(**updates) -> EvidenceRef:
    fields = {
        "kind": "manufacturer_design_guide",
        "title": "Fixture ESD placement guide",
        "locator": "section 2",
        "source_id": "source:esd-fixture",
        "revision": "1",
        "local_sha256": "e" * 64,
        "source_status": "pinned",
        "locator_status": "text_verified",
        "applicability_status": "confirmed",
        "required_conditions": ("interface=usb2", "threat=user-accessible-connector"),
        **updates,
    }
    return EvidenceRef(**fields)


def _protection_declaration(
    connector_zone,
    raw,
    protected,
    *,
    policy: ConnectorProtectionOrderPolicy | None = None,
    transition_role: str = "esd_protection",
    bind_policy: bool = True,
    allow_raw_parallel: tuple[str, ...] = (),
) -> ConnectorProtectionOrderDeclaration:
    declaration = ConnectorProtectionOrderDeclaration(
        declaration_id="declaration:connector-esd-order",
        connector_zone_result_fingerprint=connector_zone.result_fingerprint,
        board_layout_snapshot_fingerprint=(
            connector_zone.declaration.board_layout_snapshot_fingerprint
        ),
        board_netlist_snapshot_fingerprint=(
            connector_zone.declaration.board_netlist_snapshot_fingerprint
        ),
        connector_references=("J1",),
        legs=(
            ConnectorProtectionLegDeclaration(
                leg_id="leg:connector-to-esd",
                net_name="USB_RAW",
                start_anchor_id="connector-out",
                start_pad_source_id="pad:J1:1",
                end_anchor_id="esd-in",
                end_pad_source_id="pad:U2:1",
                path_result_fingerprint=raw.result_fingerprint,
                declared_parallel_component_references=allow_raw_parallel,
            ),
            ConnectorProtectionLegDeclaration(
                leg_id="leg:esd-to-load",
                net_name="USB_PROTECTED",
                start_anchor_id="esd-out",
                start_pad_source_id="pad:U2:6",
                end_anchor_id="load-in",
                end_pad_source_id="pad:U1:1",
                path_result_fingerprint=protected.result_fingerprint,
            ),
        ),
        transitions=(
            ConnectorProtectionTransition(
                transition_id="transition:esd",
                component_reference="U2",
                role=transition_role,
                ingress_anchor_id="esd-in",
                ingress_pad_source_id="pad:U2:1",
                egress_anchor_id="esd-out",
                egress_pad_source_id="pad:U2:6",
            ),
        ),
        policy=policy or _policy(),
    )
    if (
        bind_policy
        and declaration.policy.mode == "sourced_hard"
        and declaration.policy.applicability_binding is None
    ):
        conditions = ("interface=usb2", "threat=user-accessible-connector")
        binding = EvidenceApplicabilityBinding(
            binding_id="binding:connector-esd-order",
            evidence=(_protection_evidence(),),
            claim_id=declaration.policy.policy_id,
            applicability_record_id="applicability:connector-esd-order",
            required_conditions=conditions,
            excluded_conditions=(),
            matched_conditions=conditions,
            unmatched_conditions=(),
            geometry_source_fingerprint=connector_protection_context_fingerprint(
                declaration
            ),
            reviewer_record_id="review:connector-esd-order",
        )
        declaration = declaration.model_copy(
            update={
                "policy": declaration.policy.model_copy(
                    update={"applicability_binding": binding}
                )
            }
        )
    return declaration


def test_exact_connector_esd_load_order_passes_from_replayed_copper() -> None:
    layout, netlist, raw, protected = _fixture()
    connector_zone = _connector_zone(layout, netlist)
    declaration = _protection_declaration(connector_zone, raw, protected)

    result = evaluate_connector_protection_order(
        connector_zone, (protected, raw), declaration
    )

    assert result.disposition is SemanticDisposition.PASS
    assert result.metrics is not None
    assert result.metrics.derived_component_order == ("J1", "U2", "U1")
    assert result.metrics.derived_transition_roles == ("esd_protection",)
    assert result.violation_ids == ()


def test_non_esd_first_transition_fails_hard_order_policy() -> None:
    layout, netlist, raw, protected = _fixture()
    connector_zone = _connector_zone(layout, netlist)
    declaration = _protection_declaration(
        connector_zone, raw, protected, transition_role="series_filter"
    )

    result = evaluate_connector_protection_order(
        connector_zone, (raw, protected), declaration
    )

    assert result.disposition is SemanticDisposition.FAIL
    assert "expected_protection_role_order_violated" in result.violation_ids


def test_unmodeled_raw_net_component_is_a_bypass_failure() -> None:
    layout, netlist, raw, protected = _fixture(bypass=True)
    connector_zone = _connector_zone(layout, netlist)
    declaration = _protection_declaration(connector_zone, raw, protected)

    result = evaluate_connector_protection_order(
        connector_zone, (raw, protected), declaration
    )

    assert result.disposition is SemanticDisposition.FAIL
    assert (
        "leg:connector-to-esd:unexpected_parallel_or_bypass_component"
        in result.violation_ids
    )


def test_evidence_bound_allowed_parallel_component_can_be_declared() -> None:
    layout, netlist, raw, protected = _fixture(bypass=True)
    connector_zone = _connector_zone(layout, netlist)
    declaration = _protection_declaration(
        connector_zone,
        raw,
        protected,
        allow_raw_parallel=("R1",),
    )

    result = evaluate_connector_protection_order(
        connector_zone, (raw, protected), declaration
    )

    assert result.disposition is SemanticDisposition.PASS


def test_missing_graph_terminal_for_netlist_node_is_unverified_not_pass() -> None:
    layout, netlist, raw, protected = _fixture(bypass=True, omit_bypass_anchor=True)
    connector_zone = _connector_zone(layout, netlist)
    declaration = _protection_declaration(connector_zone, raw, protected)

    result = evaluate_connector_protection_order(
        connector_zone, (raw, protected), declaration
    )

    assert result.disposition is SemanticDisposition.UNVERIFIED
    assert result.violation_ids == ()
    assert (
        "leg:connector-to-esd:terminal_inventory_incomplete"
        in result.unverified_reasons
    )


def test_advisory_policy_cannot_claim_acceptance() -> None:
    layout, netlist, raw, protected = _fixture(bypass=True)
    connector_zone = _connector_zone(layout, netlist)
    declaration = _protection_declaration(
        connector_zone,
        raw,
        protected,
        policy=_policy(mode="advisory"),
    )

    result = evaluate_connector_protection_order(
        connector_zone, (raw, protected), declaration
    )

    assert result.disposition is SemanticDisposition.ADVISORY
    assert result.violation_ids


def test_sourced_hard_policy_without_binding_is_unverified() -> None:
    layout, netlist, raw, protected = _fixture()
    connector_zone = _connector_zone(layout, netlist)
    declaration = _protection_declaration(
        connector_zone, raw, protected, bind_policy=False
    )

    result = evaluate_connector_protection_order(
        connector_zone, (raw, protected), declaration
    )

    assert result.disposition is SemanticDisposition.UNVERIFIED
    assert result.unverified_reasons == ("hard_protection_policy_evidence_missing",)


@pytest.mark.parametrize(
    ("binding_update", "expected_reason"),
    (
        (
            {"claim_id": "policy:wrong"},
            "hard_protection_policy_claim_identity_mismatch",
        ),
        (
            {"reviewer_record_id": None},
            "hard_protection_policy_applicability_incomplete",
        ),
        (
            {"geometry_source_fingerprint": "a" * 64},
            "hard_protection_policy_context_fingerprint_mismatch",
        ),
    ),
)
def test_invalid_hard_binding_is_unverified(binding_update, expected_reason: str) -> None:
    layout, netlist, raw, protected = _fixture()
    connector_zone = _connector_zone(layout, netlist)
    declaration = _protection_declaration(connector_zone, raw, protected)
    binding = declaration.policy.applicability_binding
    assert binding is not None
    policy = declaration.policy.model_copy(
        update={"applicability_binding": binding.model_copy(update=binding_update)}
    )

    result = evaluate_connector_protection_order(
        connector_zone,
        (raw, protected),
        declaration.model_copy(update={"policy": policy}),
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
def test_non_authoritative_source_cannot_drive_hard_order(evidence_update) -> None:
    layout, netlist, raw, protected = _fixture()
    connector_zone = _connector_zone(layout, netlist)
    declaration = _protection_declaration(connector_zone, raw, protected)
    binding = declaration.policy.applicability_binding
    assert binding is not None
    evidence = binding.evidence[0].model_copy(update=evidence_update)
    policy = declaration.policy.model_copy(
        update={
            "applicability_binding": binding.model_copy(update={"evidence": (evidence,)})
        }
    )

    result = evaluate_connector_protection_order(
        connector_zone,
        (raw, protected),
        declaration.model_copy(update={"policy": policy}),
    )

    assert result.disposition is SemanticDisposition.UNVERIFIED
    assert (
        "hard_protection_policy_evidence_not_revisioned_pinned_verified_applicable"
        in result.unverified_reasons
    )


def test_changed_expected_order_invalidates_old_binding() -> None:
    layout, netlist, raw, protected = _fixture()
    connector_zone = _connector_zone(layout, netlist)
    declaration = _protection_declaration(connector_zone, raw, protected)
    changed = declaration.policy.model_copy(
        update={"expected_component_order": ("J1", "U3", "U1")}
    )

    result = evaluate_connector_protection_order(
        connector_zone,
        (raw, protected),
        declaration.model_copy(update={"policy": changed}),
    )

    assert result.disposition is SemanticDisposition.UNVERIFIED
    assert result.violation_ids == ()
    assert (
        "hard_protection_policy_context_fingerprint_mismatch"
        in result.unverified_reasons
    )


def test_on_board_module_is_not_subject_to_external_esd_order() -> None:
    layout, netlist, raw, protected = _fixture()
    connector_zone = _connector_zone(layout, netlist, on_board=True)
    declaration = _protection_declaration(connector_zone, raw, protected)

    result = evaluate_connector_protection_order(
        connector_zone, (raw, protected), declaration
    )

    assert result.disposition is SemanticDisposition.NOT_APPLICABLE


def test_path_pad_snapshot_and_transition_tampering_rejects() -> None:
    layout, netlist, raw, protected = _fixture()
    connector_zone = _connector_zone(layout, netlist)
    declaration = _protection_declaration(connector_zone, raw, protected)

    stale_leg = declaration.legs[0].model_copy(
        update={"start_pad_source_id": "pad:wrong"}
    )
    with pytest.raises(ValueError, match="physical pad authority"):
        evaluate_connector_protection_order(
            connector_zone,
            (raw, protected),
            declaration.model_copy(update={"legs": (stale_leg, declaration.legs[1])}),
        )

    stale_transition = declaration.transitions[0].model_copy(
        update={"component_reference": "U3"}
    )
    with pytest.raises(ValueError, match="does not join adjacent path pads"):
        evaluate_connector_protection_order(
            connector_zone,
            (raw, protected),
            declaration.model_copy(update={"transitions": (stale_transition,)}),
        )


def test_result_replay_and_direct_tamper_rejection() -> None:
    layout, netlist, raw, protected = _fixture()
    connector_zone = _connector_zone(layout, netlist)
    declaration = _protection_declaration(connector_zone, raw, protected)
    result = evaluate_connector_protection_order(
        connector_zone, (raw, protected), declaration
    )

    assert ConnectorProtectionOrderResult.model_validate_json(result.model_dump_json()) == result
    payload = deepcopy(result.model_dump(mode="json"))
    payload["disposition"] = "fail"
    with pytest.raises(ValidationError, match="stale or not replay-derived"):
        ConnectorProtectionOrderResult.model_validate(payload)


def test_advisory_policy_rejects_hard_binding() -> None:
    layout, netlist, raw, protected = _fixture()
    connector_zone = _connector_zone(layout, netlist)
    hard = _protection_declaration(connector_zone, raw, protected).policy

    with pytest.raises(ValidationError, match="cannot carry hard authority"):
        ConnectorProtectionOrderPolicy(
            **hard.model_dump(mode="python") | {"mode": "advisory"}
        )
