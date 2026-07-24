"""R6.5 caller-declared switching-hot-loop path and area authority."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from fractions import Fraction

import pytest
from pydantic import ValidationError

from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.kicad.board import BoardComponent, BoardLayout, BoardNet, BoardNetlist, TrackSegment
from pcbsmith.kicad.routed_copper_graph import build_routed_copper_graph, resolve_copper_path
from pcbsmith.kicad.switching_hot_loop import evaluate_switching_hot_loop
from pcbsmith.routed_copper_graph_ir import (
    CopperTerminalAnchorBinding,
    DeclaredCopperPathSelection,
    ExactRational,
)
from pcbsmith.semantic_ir import EvidenceApplicabilityBinding, SemanticDisposition
from pcbsmith.switching_hot_loop_ir import (
    SwitchingHotLoopDeclaration,
    SwitchingHotLoopEvaluationResult,
    SwitchingHotLoopLegDeclaration,
    SwitchingHotLoopLimitAuthority,
    SwitchingHotLoopTerminalTransition,
    switching_hot_loop_context_fingerprint,
)

POINTS = ((0, 0), (4, 0), (4, 1), (3, 3), (1, 3), (0, 1))
TALL_POINTS = ((0, 0), (4, 0), (4, 2), (3, 5), (1, 5), (0, 2))
BOWTIE_POINTS = ((0, 0), (4, 4), (0, 4), (4, 0), (3, -1), (1, -1))
ANCHORS = ("a0", "a1", "b0", "b1", "c0", "c1")
NETS = ("VIN", "SW", "RETURN")
ANCHOR_COMPONENTS = ("CIN", "Q1", "Q1", "D1", "D1", "CIN")
ANCHOR_PADS = ("1", "1", "2", "1", "2", "2")
TRANSITION_ROLES = ("high_side_switch", "freewheel_rectifier", "input_energy_storage")


def _component(reference: str) -> BoardComponent:
    return BoardComponent(
        reference=reference,
        value="fixture",
        footprint="Fixture:OnePad",
        uuid_path=f"uuid:{reference}",
    )


def _fixture(
    points=POINTS,
    *,
    reverse_construction: bool = False,
    branch: bool = False,
    zone: bool = False,
    contact: bool = False,
    bypass: bool = False,
    omit_bypass_anchor: bool = False,
):
    component_refs = ("CIN", "Q1", "D1", *(("R1",) if bypass else ()))
    components = tuple(_component(name) for name in component_refs)
    netlist = BoardNetlist(
        components=components,
        nets=(
            BoardNet(
                name="VIN",
                nodes=(("CIN", "1"), ("Q1", "1"), *(((("R1", "1"),)) if bypass else ())),
            ),
            BoardNet(name="SW", nodes=(("Q1", "2"), ("D1", "1"))),
            BoardNet(name="RETURN", nodes=(("D1", "2"), ("CIN", "2"))),
        ),
    )
    anchors = [
        CopperTerminalAnchorBinding(
            anchor_id=name,
            physical_pad_source_id=f"pad:{name}",
            component_reference=ANCHOR_COMPONENTS[index],
            pad_number=ANCHOR_PADS[index],
            net_name=NETS[index // 2],
            layer="F.Cu",
            x_mm=str(points[index][0]),
            y_mm=str(points[index][1]),
        )
        for index, name in enumerate(ANCHORS)
    ]
    if bypass and not omit_bypass_anchor:
        anchors.append(
            CopperTerminalAnchorBinding(
                anchor_id="bypass",
                physical_pad_source_id="pad:bypass",
                component_reference="R1",
                pad_number="1",
                net_name="VIN",
                layer="F.Cu",
                x_mm="2",
                y_mm="-2",
            )
        )
    segments = [
        TrackSegment(*points[0], *points[1], "F.Cu", NETS[0], 0.3),
        TrackSegment(*points[2], *points[3], "F.Cu", NETS[1], 0.2),
        TrackSegment(*points[4], *points[5], "F.Cu", NETS[2], 0.25),
    ]
    if branch:
        segments.extend(
            (
                TrackSegment(*points[0], 2, -1, "F.Cu", NETS[0], 0.3),
                TrackSegment(2, -1, *points[1], "F.Cu", NETS[0], 0.3),
            )
        )
    if contact:
        segments.append(TrackSegment(2, 0, 2, 1, "F.Cu", NETS[0], 0.3))
    if reverse_construction:
        components = tuple(reversed(components))
        anchors = list(reversed(anchors))
        segments = list(reversed(segments))
    layout = BoardLayout(
        placements=tuple((item, float(index)) for index, item in enumerate(components)),
        segments=tuple(segments),
        vias=(),
        width_mm=8,
        height_mm=8,
        parts_row_y_mm=1,
        zones=((NETS[0], "F.Cu", (-1, -1, 5, 1)),) if zone else (),
    )
    graph = build_routed_copper_graph(layout, netlist, tuple(anchors))
    paths = []
    for index, net in enumerate(NETS):
        ordered = None
        if branch and index == 0:
            nodes = {item.node_id: item for item in graph.nodes}
            ordered = tuple(
                edge.edge_id
                for edge in graph.edges
                if edge.net_name == NETS[0]
                and {nodes[edge.start_node_id].x_mm, nodes[edge.end_node_id].x_mm}
                == {Decimal("0"), Decimal("4")}
            )
            assert len(ordered) == 1
        paths.append(
            resolve_copper_path(
                graph,
                DeclaredCopperPathSelection(
                    selection_id=f"selection:{net}",
                    graph_fingerprint=graph.graph_fingerprint,
                    net_name=net,
                    start_anchor_id=ANCHORS[index * 2],
                    end_anchor_id=ANCHORS[index * 2 + 1],
                    ordered_edge_ids=ordered,
                ),
            )
        )
    return graph, tuple(paths)


def _legs(graph, paths, *, vin_parallel: tuple[str, ...] = ()):
    anchors = {item.anchor_id: item for item in graph.terminal_anchors}
    return tuple(
        SwitchingHotLoopLegDeclaration(
            leg_id=f"leg:{index}",
            role_id=f"role:{index}",
            start_anchor_id=ANCHORS[index * 2],
            start_pad_source_id=anchors[ANCHORS[index * 2]].physical_pad_source_id,
            end_anchor_id=ANCHORS[index * 2 + 1],
            end_pad_source_id=anchors[ANCHORS[index * 2 + 1]].physical_pad_source_id,
            net_name=NETS[index],
            path_result_fingerprint=paths[index].result_fingerprint,
            declared_parallel_component_references=vin_parallel if index == 0 else (),
        )
        for index in range(3)
    )


def _transitions(roles=TRANSITION_ROLES):
    return tuple(
        SwitchingHotLoopTerminalTransition(
            transition_id=f"transition:{index}",
            component_reference=ANCHOR_COMPONENTS[index * 2 + 1],
            from_anchor_id=ANCHORS[index * 2 + 1],
            from_pad_source_id=f"pad:{ANCHORS[index * 2 + 1]}",
            to_anchor_id=ANCHORS[((index + 1) % 3) * 2],
            to_pad_source_id=f"pad:{ANCHORS[((index + 1) % 3) * 2]}",
            transition_role=roles[index],
        )
        for index in range(3)
    )


def _evidence(*, pinned: bool = True, revision: str | None = "1") -> EvidenceRef:
    return EvidenceRef(
        kind="standard",
        title="Pinned hot-loop area limit",
        locator="section 1, table 1",
        source_id="source:hot-loop",
        revision=revision,
        local_sha256="a" * 64 if pinned else None,
        source_status="pinned" if pinned else "unpinned",
        locator_status="text_verified",
        applicability_status="confirmed",
        required_conditions=("topology-reviewed",),
    )


def _declaration(
    graph,
    paths,
    *,
    mode="advisory",
    maximum: Fraction | None = None,
    binding_updates=None,
    transition_roles=TRANSITION_ROLES,
    expected_transition_roles=TRANSITION_ROLES,
    vin_parallel: tuple[str, ...] = (),
):
    legs = _legs(graph, paths, vin_parallel=vin_parallel)
    transitions = _transitions(transition_roles)
    threshold = None if maximum is None else ExactRational.build(maximum)
    binding = None
    if mode == "sourced_hard":
        context = switching_hot_loop_context_fingerprint(
            graph_fingerprint=graph.graph_fingerprint,
            board_layout_snapshot_fingerprint=graph.board_layout_snapshot_fingerprint,
            board_netlist_snapshot_fingerprint=graph.board_netlist_snapshot_fingerprint,
            topology_kind="buck",
            legs=legs,
            transitions=transitions,
            limit_id="limit:projected-area",
            mode=mode,
            maximum_projected_area_mm2=threshold,
            intended_consumer="switching hot-loop route acceptance",
            expected_transition_roles=expected_transition_roles,
        )
        fields = {
            "binding_id": "binding:projected-area",
            "evidence": (_evidence(),),
            "claim_id": "limit:projected-area",
            "applicability_record_id": "applicability:reviewed",
            "required_conditions": ("topology-reviewed",),
            "excluded_conditions": (),
            "matched_conditions": ("topology-reviewed",),
            "unmatched_conditions": (),
            "geometry_source_fingerprint": context,
            "reviewer_record_id": "reviewer:one",
            **(binding_updates or {}),
        }
        binding = EvidenceApplicabilityBinding(**fields)
    return SwitchingHotLoopDeclaration(
        declaration_id="declaration:hot-loop",
        topology_kind="buck",
        graph_fingerprint=graph.graph_fingerprint,
        board_layout_snapshot_fingerprint=graph.board_layout_snapshot_fingerprint,
        board_netlist_snapshot_fingerprint=graph.board_netlist_snapshot_fingerprint,
        legs=legs,
        transitions=transitions,
        limit=SwitchingHotLoopLimitAuthority(
            limit_id="limit:projected-area",
            mode=mode,
            intended_consumer="switching hot-loop route acceptance",
            expected_transition_roles=expected_transition_roles,
            maximum_projected_area_mm2=threshold,
            applicability_binding=binding,
        ),
    )


def test_same_one_dimensional_span_retains_distinct_exact_projected_areas() -> None:
    graph, paths = _fixture()
    tall_graph, tall_paths = _fixture(TALL_POINTS)
    first = evaluate_switching_hot_loop(graph, paths, _declaration(graph, paths))
    second = evaluate_switching_hot_loop(
        tall_graph, tall_paths, _declaration(tall_graph, tall_paths)
    )

    assert first.disposition is SemanticDisposition.ADVISORY
    assert second.disposition is SemanticDisposition.ADVISORY
    assert first.metrics is not None and second.metrics is not None
    assert first.metrics.projected_absolute_area_mm2 is not None
    assert second.metrics.projected_absolute_area_mm2 is not None
    assert max(point[0] for point in POINTS) - min(point[0] for point in POINTS) == (
        max(point[0] for point in TALL_POINTS) - min(point[0] for point in TALL_POINTS)
    )
    assert first.metrics.projected_absolute_area_mm2 != second.metrics.projected_absolute_area_mm2
    assert first.metrics.combined_minimum_track_width_mm == Decimal("0.2")
    assert first.metrics.combined_via_count == 0
    assert len(first.metrics.combined_radical_length_terms) >= 1
    assert first.metrics.transition_component_references == ("Q1", "D1", "CIN")
    assert first.metrics.transition_roles == TRANSITION_ROLES
    assert first.metrics.leg_terminal_component_references == (
        ("leg:0", ("CIN", "Q1")),
        ("leg:1", ("D1", "Q1")),
        ("leg:2", ("CIN", "D1")),
    )


def test_branched_leg_rejects_automatic_selection_but_accepts_declared_edge_order() -> None:
    graph, paths = _fixture(branch=True)
    with pytest.raises(ValueError, match="multiple"):
        resolve_copper_path(
            graph,
            DeclaredCopperPathSelection(
                selection_id="selection:auto-ambiguous",
                graph_fingerprint=graph.graph_fingerprint,
                net_name=NETS[0],
                start_anchor_id="a0",
                end_anchor_id="a1",
                ordered_edge_ids=None,
            ),
        )
    result = evaluate_switching_hot_loop(graph, paths, _declaration(graph, paths))
    assert result.disposition is SemanticDisposition.ADVISORY
    assert result.metrics is not None


def test_hard_limit_equality_passes_and_one_exact_unit_above_fails() -> None:
    graph, paths = _fixture()
    advisory = evaluate_switching_hot_loop(graph, paths, _declaration(graph, paths))
    assert advisory.metrics is not None
    area = advisory.metrics.projected_absolute_area_mm2
    assert area is not None and area.fraction() > 1

    equal = evaluate_switching_hot_loop(
        graph, paths, _declaration(graph, paths, mode="sourced_hard", maximum=area.fraction())
    )
    above = evaluate_switching_hot_loop(
        graph,
        paths,
        _declaration(graph, paths, mode="sourced_hard", maximum=area.fraction() - 1),
    )
    assert equal.disposition is SemanticDisposition.PASS
    assert above.disposition is SemanticDisposition.FAIL
    assert above.violation_ids == ("maximum_projected_area_exceeded",)


def test_advisory_threshold_cannot_hard_fail() -> None:
    graph, paths = _fixture()
    result = evaluate_switching_hot_loop(
        graph, paths, _declaration(graph, paths, maximum=Fraction(0))
    )
    assert result.disposition is SemanticDisposition.ADVISORY
    assert result.violation_ids == ("maximum_projected_area_exceeded",)


def test_wrong_switching_transition_membership_fails_hard_policy() -> None:
    graph, paths = _fixture()
    actual_roles = ("low_side_switch", *TRANSITION_ROLES[1:])
    result = evaluate_switching_hot_loop(
        graph,
        paths,
        _declaration(
            graph,
            paths,
            mode="sourced_hard",
            maximum=Fraction(100),
            transition_roles=actual_roles,
        ),
    )

    assert result.disposition is SemanticDisposition.FAIL
    assert "expected_transition_membership_violated" in result.violation_ids


def test_undeclared_parallel_or_bypass_terminal_fails_membership() -> None:
    graph, paths = _fixture(bypass=True)
    result = evaluate_switching_hot_loop(
        graph,
        paths,
        _declaration(graph, paths, mode="sourced_hard", maximum=Fraction(100)),
    )

    assert result.disposition is SemanticDisposition.FAIL
    assert "unexpected_parallel_or_bypass_component:leg:0" in result.violation_ids


def test_reviewed_parallel_terminal_is_context_bound_and_can_pass() -> None:
    graph, paths = _fixture(bypass=True)
    result = evaluate_switching_hot_loop(
        graph,
        paths,
        _declaration(
            graph,
            paths,
            mode="sourced_hard",
            maximum=Fraction(100),
            vin_parallel=("R1",),
        ),
    )

    assert result.disposition is SemanticDisposition.PASS


def test_missing_graph_anchor_for_netlist_terminal_is_unverified() -> None:
    graph, paths = _fixture(bypass=True, omit_bypass_anchor=True)
    result = evaluate_switching_hot_loop(
        graph,
        paths,
        _declaration(graph, paths, mode="sourced_hard", maximum=Fraction(100)),
    )

    assert result.disposition is SemanticDisposition.UNVERIFIED
    assert result.violation_ids == ()
    assert "terminal_inventory_incomplete:leg:0" in result.unverified_reasons


def test_missing_hard_threshold_and_evidence_are_unverified_without_advisory_fallback() -> None:
    graph, paths = _fixture()
    advisory = _declaration(graph, paths)
    hard_without_authority = advisory.model_copy(
        update={
            "limit": SwitchingHotLoopLimitAuthority(
                limit_id="limit:projected-area",
                mode="sourced_hard",
                intended_consumer="switching hot-loop route acceptance",
                expected_transition_roles=TRANSITION_ROLES,
                maximum_projected_area_mm2=None,
                applicability_binding=None,
            )
        }
    )
    result = evaluate_switching_hot_loop(graph, paths, hard_without_authority)
    assert result.disposition is SemanticDisposition.UNVERIFIED
    assert result.unverified_reasons == (
        "hard_limit_evidence_missing",
        "hard_limit_threshold_missing",
    )


@pytest.mark.parametrize(
    "binding_updates, reason",
    (
        ({"claim_id": "limit:wrong"}, "hard_limit_claim_identity_mismatch"),
        ({"geometry_source_fingerprint": "b" * 64}, "hard_limit_context_fingerprint_mismatch"),
        ({"reviewer_record_id": None}, "hard_limit_applicability_incomplete"),
        (
            {
                "required_conditions": ("topology-reviewed", "package-reviewed"),
                "matched_conditions": ("topology-reviewed",),
                "unmatched_conditions": ("package-reviewed",),
            },
            "hard_limit_applicability_incomplete",
        ),
        (
            {"evidence": (_evidence(pinned=False),)},
            "hard_limit_evidence_not_revisioned_pinned_verified_applicable",
        ),
        (
            {"evidence": (_evidence(revision=None),)},
            "hard_limit_evidence_not_revisioned_pinned_verified_applicable",
        ),
    ),
)
def test_incomplete_or_tampered_hard_evidence_is_unverified(binding_updates, reason) -> None:
    graph, paths = _fixture()
    result = evaluate_switching_hot_loop(
        graph,
        paths,
        _declaration(
            graph,
            paths,
            mode="sourced_hard",
            maximum=Fraction(100),
            binding_updates=binding_updates,
        ),
    )
    assert result.disposition is SemanticDisposition.UNVERIFIED
    assert reason in result.unverified_reasons


def test_reversed_path_or_terminal_order_cannot_satisfy_forward_declaration() -> None:
    graph, paths = _fixture()
    forward = _declaration(graph, paths)
    reverse_first = resolve_copper_path(
        graph,
        DeclaredCopperPathSelection(
            selection_id="selection:reverse",
            graph_fingerprint=graph.graph_fingerprint,
            net_name=NETS[0],
            start_anchor_id="a1",
            end_anchor_id="a0",
            ordered_edge_ids=None,
        ),
    )
    with pytest.raises(ValueError, match="path authority is stale"):
        evaluate_switching_hot_loop(graph, (reverse_first, *paths[1:]), forward)
    with pytest.raises(ValueError, match="path authority is stale"):
        evaluate_switching_hot_loop(graph, (paths[1], paths[0], paths[2]), forward)
    wrong_transition = forward.transitions[0].model_copy(update={"to_anchor_id": "c0"})
    with pytest.raises(ValueError, match="terminal transition"):
        evaluate_switching_hot_loop(
            graph,
            paths,
            forward.model_copy(
                update={"transitions": (wrong_transition, *forward.transitions[1:])}
            ),
        )

    wrong_component = forward.transitions[0].model_copy(
        update={"component_reference": "D1"}
    )
    with pytest.raises(ValueError, match="terminal transition"):
        evaluate_switching_hot_loop(
            graph,
            paths,
            forward.model_copy(
                update={"transitions": (wrong_component, *forward.transitions[1:])}
            ),
        )


def test_stale_binding_cannot_authorize_changed_membership_policy() -> None:
    graph, paths = _fixture()
    declaration = _declaration(
        graph,
        paths,
        mode="sourced_hard",
        maximum=Fraction(100),
    )
    changed = declaration.limit.model_copy(
        update={
            "expected_transition_roles": (
                "low_side_switch",
                *TRANSITION_ROLES[1:],
            )
        }
    )
    result = evaluate_switching_hot_loop(
        graph,
        paths,
        declaration.model_copy(update={"limit": changed}),
    )

    assert result.disposition is SemanticDisposition.UNVERIFIED
    assert result.violation_ids == ()
    assert "hard_limit_context_fingerprint_mismatch" in result.unverified_reasons


def test_legacy_hot_loop_schema_fails_closed() -> None:
    graph, paths = _fixture()
    payload = _declaration(graph, paths).model_dump(mode="json")
    payload["schema_version"] = 1
    payload["limit"]["schema_version"] = 1
    payload["limit"].pop("intended_consumer")
    payload["limit"].pop("expected_transition_roles")

    with pytest.raises(ValidationError):
        SwitchingHotLoopDeclaration.model_validate(payload)


def test_three_free_form_role_labels_cannot_alias_only_two_physical_anchors() -> None:
    graph, paths = _fixture()
    declaration = _declaration(graph, paths)
    first = declaration.legs[0]
    aliased_legs = tuple(
        item.model_copy(
            update={
                "start_anchor_id": first.start_anchor_id,
                "start_pad_source_id": first.start_pad_source_id,
                "end_anchor_id": first.end_anchor_id,
                "end_pad_source_id": first.end_pad_source_id,
            }
        )
        for item in declaration.legs
    )
    payload = declaration.model_dump(mode="python")
    payload["legs"] = aliased_legs
    with pytest.raises(ValidationError, match="three distinct physical terminal anchors"):
        SwitchingHotLoopDeclaration.model_validate(payload)


@pytest.mark.parametrize("unknown_kind", ("zone", "contact"))
def test_non_simple_polygon_and_unknown_path_propagate_unverified(unknown_kind: str) -> None:
    graph, paths = _fixture(BOWTIE_POINTS)
    crossing = evaluate_switching_hot_loop(graph, paths, _declaration(graph, paths))
    assert crossing.disposition is SemanticDisposition.UNVERIFIED
    assert crossing.metrics is not None
    assert crossing.metrics.projected_absolute_area_mm2 is None
    assert "projected_polygon_unverified" in crossing.unverified_reasons

    zone_graph, zone_paths = _fixture(**{unknown_kind: True})
    unknown = evaluate_switching_hot_loop(
        zone_graph, zone_paths, _declaration(zone_graph, zone_paths)
    )
    assert unknown.disposition is SemanticDisposition.UNVERIFIED
    assert unknown.metrics is None
    assert "leg_not_exact_connected:leg:0" in unknown.unverified_reasons


def test_construction_order_is_metric_deterministic_and_inputs_are_immutable() -> None:
    graph, paths = _fixture()
    reversed_graph, reversed_paths = _fixture(reverse_construction=True)
    declaration = _declaration(graph, paths)
    graph_before = deepcopy(graph.model_dump(mode="json"))
    paths_before = deepcopy([item.model_dump(mode="json") for item in paths])
    declaration_before = deepcopy(declaration.model_dump(mode="json"))

    first = evaluate_switching_hot_loop(graph, paths, declaration)
    second = evaluate_switching_hot_loop(
        reversed_graph,
        reversed_paths,
        _declaration(reversed_graph, reversed_paths),
    )
    assert first.metrics == second.metrics
    assert graph.model_dump(mode="json") == graph_before
    assert [item.model_dump(mode="json") for item in paths] == paths_before
    assert declaration.model_dump(mode="json") == declaration_before


def test_result_round_trip_replays_and_tamper_is_rejected() -> None:
    graph, paths = _fixture()
    result = evaluate_switching_hot_loop(graph, paths, _declaration(graph, paths))
    assert SwitchingHotLoopEvaluationResult.model_validate_json(result.model_dump_json()) == result
    payload = result.model_dump(mode="json")
    payload["disposition"] = "pass"
    with pytest.raises(ValidationError, match="stale|replay"):
        SwitchingHotLoopEvaluationResult.model_validate(payload)
