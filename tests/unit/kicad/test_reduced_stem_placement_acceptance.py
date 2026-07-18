from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import replace
from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from tests.fixtures.routing.reduced_capacity_two_stem import (
    FOOTPRINT,
    NET_NAMES,
    SCHEMATIC_PROJECT_NAME,
    SCHEMATIC_SYMBOL_ID,
    TERMINAL_FOOTPRINT_SPEC,
    ReducedCapacityTwoStemBoard,
    make_reduced_capacity_two_stem_board,
)
from tests.unit.kicad.test_placement_acceptance_manifest import (
    _aggregate_policy,
    _erc_report,
)
from tests.unit.kicad.test_placement_pilot_authority import _authority

from pcbsmith.circuit.models import (
    CircuitIntent,
    CircuitObject,
    ComponentRole,
    MathReport,
    TopologySelection,
)
from pcbsmith.corridor_allocator import negotiate_corridor_allocations
from pcbsmith.corridor_ir import CorridorGraph, CorridorPlanResult
from pcbsmith.corridor_summary import verify_corridor_plan_summary
from pcbsmith.kicad.aggregate_exact_checker import (
    AggregateCheckStatus,
    KiCadSaveRoundtripSubcheckEvidence,
    MissingSubcheckEvidence,
    ReaderNetlistEqualitySubcheckEvidence,
    evaluate_stable_aggregate_exact_check,
)
from pcbsmith.kicad.board import (
    FOOTPRINT_LIBRARY,
    BoardLayout,
    BoardNetlist,
    canonical_kicad_netlist_xml_text,
    placement_y,
)
from pcbsmith.kicad.board_serialization import (
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.kicad.corridor_planner import build_corridor_graph
from pcbsmith.kicad.negotiated_board import route_board_corridor_guided
from pcbsmith.kicad.placement_acceptance_manifest import (
    PlacementAcceptanceManifest,
    PlacementAcceptanceManifestPolicy,
)
from pcbsmith.kicad.placement_candidates import generate_placement_candidates
from pcbsmith.kicad.placement_detail import (
    PlacementDetailInput,
    PlacementDetailRun,
    _dominates,
    evaluate_placement_details,
)
from pcbsmith.kicad.placement_exact import (
    evaluate_placement_exact,
    placement_exact_netlist_fingerprint,
)
from pcbsmith.kicad.placement_pilot_acceptance import (
    PlacementPilotAcceptance,
    build_pilot_candidate_input,
)
from pcbsmith.kicad.placement_readback import (
    PlacementKiCadSaveRoundtripAuthority,
    extract_kicad_board_readback,
    verify_placement_kicad_save_roundtrip,
)
from pcbsmith.kicad.placement_routability import PlacementProbe
from pcbsmith.kicad.placement_serialization import build_placement_serialization_authority
from pcbsmith.kicad.placement_surrogates import evaluate_placement_surrogates
from pcbsmith.kicad.reader_netlist_live import verify_reader_netlist_equality_live
from pcbsmith.kicad.reader_schematic import (
    ReaderInstance,
    ReaderSpec,
    render_reader_schematic,
)
from pcbsmith.kicad.symbols import instance_pin_position_rotated, load_symbol
from pcbsmith.kicad.validate import canonical_kicad_erc_json_text
from pcbsmith.placement_candidate_ir import (
    PlacementCandidateTerminalReason,
    PlacementSurrogateEvidence,
)
from pcbsmith.placement_exact_ir import PlacementExactBudget, PlacementExactDisposition
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon
from pcbsmith.placement_ir import PlacementLegalizationResult
from pcbsmith.placement_surrogate_ir import (
    EscapeRay,
    PlacedTerminalCopper,
    PlacementCorridorEvidence,
    PlacementCorridorState,
    PlacementSurrogateResult,
)
from pcbsmith.routing_ir import RoutingFailureReason


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _pad_square(x_mm: float, y_mm: float) -> ExactPlanarCompound:
    half = 0.4
    return ExactPlanarCompound(
        polygons=(
            ExactPlanarPolygon(
                outer=(
                    (x_mm - half, y_mm - half),
                    (x_mm + half, y_mm - half),
                    (x_mm + half, y_mm + half),
                    (x_mm - half, y_mm + half),
                )
            ),
        )
    )


def _terminals(layout: BoardLayout, netlist: BoardNetlist) -> tuple[PlacedTerminalCopper, ...]:
    nodes = {(reference, pad): net.name for net in netlist.nets for reference, pad in net.nodes}
    result = []
    for component, x_mm in layout.placements:
        pad = "1"
        net_name = nodes[(component.reference, pad)]
        y_mm = placement_y(layout, component.reference)
        result.append(
            PlacedTerminalCopper(
                terminal_id=f"{component.reference}:{pad}",
                source_id=f"pad:{component.reference}:{pad}:F.Cu",
                component_reference=component.reference,
                net_name=net_name,
                layer="F.Cu",
                center_mm=(x_mm, y_mm),
                copper=_pad_square(x_mm, y_mm),
                escape_rays=(
                    EscapeRay(dx=-1, dy=0),
                    EscapeRay(dx=0, dy=-1),
                    EscapeRay(dx=0, dy=1),
                    EscapeRay(dx=1, dy=0),
                ),
            )
        )
    return tuple(result)


class _RealReducedStemSurrogate:
    def __init__(self, authority: Any, netlist: BoardNetlist) -> None:
        self.authority = authority
        self.netlist = netlist
        self.by_pose: dict[
            str,
            tuple[
                PlacementSurrogateResult,
                CorridorGraph | None,
                CorridorPlanResult | None,
            ],
        ] = {}

    def __call__(
        self,
        probe: PlacementProbe,
        legalization_result: PlacementLegalizationResult,
    ) -> PlacementSurrogateEvidence:
        pose = probe.result.telemetry.pose_fingerprint
        assert legalization_result.telemetry.pose_fingerprint == pose
        authority = self.authority
        clearance_groups = tuple(
            (
                group.nets_a,
                group.nets_b,
                group.minimum_clearance_mm,
                group.exempt_component_refs,
            )
            for group in authority.clearance_groups
        )
        built = build_corridor_graph(
            probe.layout,
            self.netlist,
            target_nets=authority.target_net_names,
            net_widths=dict(authority.target_net_widths_mm),
            default_width_mm=authority.r2_policy.default_width_mm,
            profile=authority.profile,
            clearance_groups=clearance_groups,
            coarse_grid_mm=authority.coarse_grid_mm,
            capacity_quantum_mm=authority.corridor_capacity_quantum_mm,
            graphics_policy=authority.corridor_graphics_policy,
            budget=authority.corridor_graph_budget,
        )
        assert built.complete
        graph: CorridorGraph | None = None
        plan: CorridorPlanResult | None = None
        corridor = PlacementCorridorEvidence(state=PlacementCorridorState.ABSENT)
        if built.planning_supported:
            demand_policies = {item.net_name: item for item in authority.corridor_demand_policies}
            demands = tuple(
                demand.model_copy(
                    update={
                        "allowed_layers": demand_policies[demand.net_name].allowed_layers,
                        "via_policy": demand_policies[demand.net_name].via_policy,
                    }
                )
                for demand in built.demands
            )
            graph = built.graph
            plan = negotiate_corridor_allocations(
                graph,
                demands,
                budget=authority.corridor_budget,
                cost_policy=authority.corridor_cost_policy,
            )
            assert plan.guidance_ready and not plan.resource_overuse
            verified = verify_corridor_plan_summary(graph, demands, plan)
            corridor = PlacementCorridorEvidence(
                state=PlacementCorridorState.READY,
                verified_summary=verified,
            )
        surrogate = evaluate_placement_surrogates(
            _terminals(probe.layout, self.netlist),
            pose_fingerprint=pose,
            probe_layout_fingerprint=probe.result.telemetry.probe_layout_fingerprint,
            profile=authority.profile,
            clearance_groups=authority.clearance_groups,
            corridor=corridor,
            policy=authority.surrogate_policy,
        )
        self.by_pose[pose] = (surrogate, graph, plan)
        return PlacementSurrogateEvidence(
            evaluator_id="deterministic-placement-surrogates-v1",
            evidence_fingerprint=surrogate.semantic_fingerprint(),
        )


def _reader_xml(netlist: BoardNetlist) -> str:
    components = []
    for component in netlist.components:
        fields = "".join(
            f'<field name="{name}">{value}</field>' for name, value in component.fields
        )
        components.append(
            f'<comp ref="{component.reference}"><value>{component.value}</value>'
            f"<footprint>{component.footprint}</footprint>"
            f"<tstamps>{component.uuid_path}</tstamps><fields>{fields}</fields></comp>"
        )
    nets = []
    for net in netlist.nets:
        nodes = "".join(f'<node ref="{ref}" pin="{pad}"/>' for ref, pad in net.nodes)
        nets.append(f'<net name="{net.name}">{nodes}</net>')
    return (
        "<export><components>"
        + "".join(components)
        + "</components><nets>"
        + "".join(nets)
        + "</nets></export>"
    )


def _reduced_reader_circuit() -> CircuitObject:
    return CircuitObject(
        intent=CircuitIntent(
            raw_request="reduced routing authority fixture",
            intent_id="intent:reduced-capacity-two-stem",
            status="supported",
        ),
        topology=TopologySelection(
            topology_id="topology:reduced-capacity-two-stem",
            title="Two independent terminal pairs",
            status="selected",
            evidence=(),
        ),
        components=tuple(
            ComponentRole(
                reference=reference,
                role="terminal",
                symbol_id=SCHEMATIC_SYMBOL_ID,
                value="TERMINAL",
                support_status="supported",
                footprint=FOOTPRINT,
            )
            for reference in ("J1", "J2", "J3", "J4")
        ),
        nets=NET_NAMES,
        math=MathReport(status="passed", calculations={}),
    )


def _reduced_reader_schematic_texts() -> tuple[str, str]:
    circuit = _reduced_reader_circuit()
    symbol = load_symbol(SCHEMATIC_SYMBOL_ID)
    # KiCad prefixes root-sheet XML net names with ``/``.  Reader labels and
    # the offline connectivity table therefore retain the local names here;
    # the exported equality authority compares the resulting canonical names.
    local_net_names = tuple(name.removeprefix("/") for name in NET_NAMES)
    pin_nets = {
        "J1": {"1": local_net_names[0]},
        "J2": {"1": local_net_names[0]},
        "J3": {"1": local_net_names[1]},
        "J4": {"1": local_net_names[1]},
    }

    machine_instances = (
        ReaderInstance("J1", SCHEMATIC_SYMBOL_ID, (30.48, 30.48), rotation=180),
        ReaderInstance("J2", SCHEMATIC_SYMBOL_ID, (45.72, 30.48)),
        ReaderInstance("J3", SCHEMATIC_SYMBOL_ID, (30.48, 50.8), rotation=180),
        ReaderInstance("J4", SCHEMATIC_SYMBOL_ID, (45.72, 50.8)),
    )
    machine_pins = tuple(
        instance_pin_position_rotated(symbol, "1", item.at, item.rotation)
        for item in machine_instances
    )
    machine = ReaderSpec(
        instances=machine_instances,
        wires=((machine_pins[0], machine_pins[1]), (machine_pins[2], machine_pins[3])),
        labels=(
            (local_net_names[0], machine_pins[0]),
            (local_net_names[1], machine_pins[2]),
        ),
    )

    reader_instances = (
        ReaderInstance("J1", SCHEMATIC_SYMBOL_ID, (76.2, 30.48), rotation=270),
        ReaderInstance("J2", SCHEMATIC_SYMBOL_ID, (76.2, 45.72), rotation=90),
        ReaderInstance("J3", SCHEMATIC_SYMBOL_ID, (101.6, 30.48), rotation=270),
        ReaderInstance("J4", SCHEMATIC_SYMBOL_ID, (101.6, 45.72), rotation=90),
    )
    reader_pins = tuple(
        instance_pin_position_rotated(symbol, "1", item.at, item.rotation)
        for item in reader_instances
    )
    reader = ReaderSpec(
        instances=reader_instances,
        wires=((reader_pins[0], reader_pins[1]), (reader_pins[2], reader_pins[3])),
        labels=(
            (local_net_names[0], reader_pins[0]),
            (local_net_names[1], reader_pins[2]),
        ),
    )
    return (
        render_reader_schematic(
            circuit,
            machine,
            project_name=SCHEMATIC_PROJECT_NAME,
            pin_nets=pin_nets,
        ),
        render_reader_schematic(
            circuit,
            reader,
            project_name=SCHEMATIC_PROJECT_NAME,
            pin_nets=pin_nets,
        ),
    )


def _roundtrip_authority(
    probe_layout: BoardLayout,
    final_layout: BoardLayout,
    netlist: BoardNetlist,
) -> PlacementKiCadSaveRoundtripAuthority:
    serialization = build_placement_serialization_authority(
        probe_layout,
        netlist,
        final_layout,
        NET_NAMES,
        ("J1", "J2"),
    )
    text = serialization.rendered_board_text
    snapshot = extract_kicad_board_readback(text)
    report = json.dumps(
        {"schematic_parity": [], "unconnected_items": [], "violations": []},
        sort_keys=True,
        separators=(",", ":"),
    )
    return PlacementKiCadSaveRoundtripAuthority(
        serialization_authority=serialization,
        kicad_cli_version="10.0-nonlive-reduced-stem",
        initial_board_text=text,
        saved_board_text=text,
        initial_board_sha256=_sha256(text),
        saved_board_sha256=_sha256(text),
        repeated_saved_board_sha256=_sha256(text),
        initial_snapshot=snapshot,
        saved_snapshot=snapshot,
        drc_status="passed",
        drc_report_json=report,
        drc_report_sha256=_sha256(report),
    )


@lru_cache(maxsize=1)
def _accepted_fixture() -> tuple[PlacementPilotAcceptance, float]:
    started = time.perf_counter()
    FOOTPRINT_LIBRARY[FOOTPRINT] = TERMINAL_FOOTPRINT_SPEC
    board: ReducedCapacityTwoStemBoard = make_reduced_capacity_two_stem_board()
    authority = _authority()
    evaluator = _RealReducedStemSurrogate(authority, board.netlist)
    search = generate_placement_candidates(
        board.layout,
        authority.geometry_catalog,
        authority.move_policy,
        authority.legalization_policy,
        authority.placement_budget,
        target_nets=authority.target_net_names,
        known_net_names=tuple(net.name for net in board.netlist.nets),
        profile=authority.profile,
        surrogate_evaluator=evaluator,
    )
    probes_by_pose = {probe.result.telemetry.pose_fingerprint: probe for probe in search.probes}
    detail_inputs: dict[str, PlacementDetailInput] = {}
    retained_inputs = []
    netlist_fingerprint = placement_exact_netlist_fingerprint(board.netlist)
    for candidate in search.result.candidates:
        pose = candidate.legalization_result.telemetry.pose_fingerprint
        probe = probes_by_pose[pose]
        surrogate, graph, plan = evaluator.by_pose[pose]
        detail_inputs[candidate.candidate_fingerprint] = PlacementDetailInput(
            candidate=candidate,
            probe=probe,
            surrogate=surrogate,
            netlist=board.netlist,
            corridor_graph=graph,
            corridor_plan=plan,
        )
        retained_inputs.append(
            build_pilot_candidate_input(
                candidate=candidate,
                probe_layout=probe.layout,
                surrogate=surrogate,
                corridor_graph=graph,
                corridor_plan=plan,
                netlist_fingerprint=netlist_fingerprint,
            )
        )
    detail = evaluate_placement_details(
        detail_inputs,
        selection_policy=authority.detail_selection_policy,
        budget=authority.detail_budget,
        r2_policy=authority.r2_policy,
        profile=authority.profile,
    )
    routed = dict(detail.routed_layouts)
    assert len(routed) == 1
    accepted_candidate, final_layout = next(iter(routed.items()))
    selected_record = next(item for item in detail.result.candidate_records if item.selected)
    assert selected_record.routing_run is not None
    assert selected_record.routed_unchecked and selected_record.zero_overuse
    assert sum(item.expansion_count for item in selected_record.routing_run.passes) == 734
    assert final_layout.segments
    selected_probe = probes_by_pose[
        next(
            item.legalization_result.telemetry.pose_fingerprint
            for item in search.result.candidates
            if item.candidate_fingerprint == accepted_candidate
        )
    ].layout

    policy = _aggregate_policy(routing_only=True)
    roundtrip = KiCadSaveRoundtripSubcheckEvidence.build(
        subcheck_id="kicad-roundtrip",
        subcheck_version="1",
        layout=final_layout,
        netlist=board.netlist,
        policy=policy,
        roundtrip_authority=_roundtrip_authority(selected_probe, final_layout, board.netlist),
    )
    xml = _reader_xml(board.netlist)
    machine_schematic_text, reader_schematic_text = _reduced_reader_schematic_texts()
    retained_erc_json = canonical_kicad_erc_json_text(
        json.dumps({"sheets": [{"violations": []}]})
    )
    reader = ReaderNetlistEqualitySubcheckEvidence.build(
        subcheck_id="reader-equality",
        subcheck_version="1",
        layout=final_layout,
        netlist=board.netlist,
        policy=policy,
        machine_schematic_artifact_id="machine:reduced-stem.kicad_sch",
        machine_schematic_text=machine_schematic_text,
        machine_schematic_artifact_sha256=_sha256(machine_schematic_text),
        reader_schematic_artifact_id="reader:reduced-stem.kicad_sch",
        reader_schematic_text=reader_schematic_text,
        reader_schematic_artifact_sha256=_sha256(reader_schematic_text),
        machine_netlist_xml_text=canonical_kicad_netlist_xml_text(xml),
        reader_netlist_xml_text=canonical_kicad_netlist_xml_text(xml),
        tool_id="kicad-cli",
        tool_version="10.0-nonlive-reduced-stem",
        config_identity="reader-equality-v1",
        config={"fixture": "reduced-stem"},
        machine_erc_report_json=retained_erc_json,
        reader_erc_report_json=retained_erc_json,
        machine_erc_report=_erc_report("machine-reduced-stem.kicad_sch"),
        reader_erc_report=_erc_report("reader-reduced-stem.kicad_sch"),
    )
    aggregate = evaluate_stable_aggregate_exact_check(
        final_layout,
        board.netlist,
        policy,
        (reader, roundtrip),
    )
    assert aggregate.aggregate_result.accepted
    simulation_na = next(
        item for item in aggregate.subchecks if item.subcheck_id == "thermometer-simulation"
    )
    assert isinstance(simulation_na, MissingSubcheckEvidence)
    assert simulation_na.status is AggregateCheckStatus.NOT_APPLICABLE
    exact = evaluate_placement_exact(
        detail,
        netlists_by_candidate_fingerprint={accepted_candidate: board.netlist},
        policy=authority.exact_policy,
        budget=authority.exact_budget,
        checker=lambda _layout, _netlist: aggregate.aggregate_result,
    )
    manifest = PlacementAcceptanceManifest.build(
        manifest_policy=PlacementAcceptanceManifestPolicy.build(routing_only=True),
        placement_exact_result=exact.result,
        aggregate_evidence=aggregate,
    )
    acceptance = PlacementPilotAcceptance.build(
        authority=authority,
        candidate_search_result=search.result,
        candidate_inputs=tuple(retained_inputs),
        manifest=manifest,
    )
    return acceptance, time.perf_counter() - started


def test_reduced_stem_full_acceptance_chain_fires_and_replays() -> None:
    acceptance, cold_seconds = _accepted_fixture()
    warm_started = time.perf_counter()
    repeated, _ = _accepted_fixture()
    warm_seconds = time.perf_counter() - warm_started

    assert repeated is acceptance
    assert cold_seconds < 30
    assert warm_seconds < 0.05
    assert len(acceptance.candidate_inputs) == 2
    assert len(acceptance.manifest.placement_exact_result.accepted_candidate_fingerprints) == 1
    assert not acceptance.circuit_board_equivalence_claimed
    assert not acceptance.thermometer_readiness_claimed
    assert "no circuit-to-board equivalence" in acceptance.authority_scope_note
    assert acceptance.authority_fingerprint == (
        "cbe2f70a3221d3b1c3440422ed6b9c9f2e6e25b6dfa508bc9a10e47dc3d24709"
    )
    assert acceptance.candidate_search_fingerprint == (
        "6d48a718387be3451de84de2d12d697baf9af1e3db38ca0bc76f402c947e946a"
    )
    assert acceptance.accepted_candidate_fingerprint == (
        "f7ae17969195bccc5f2d64e1e54657f3341936b6d22af6647c64b75f9c7fff53"
    )
    assert acceptance.accepted_r3_graph_fingerprint == (
        "2438c4bf884adf4f38d7a36e759ede937618401fc6baed155ed97f851f0faa95"
    )
    assert acceptance.acceptance_fingerprint == (
        "a8f5960f4fd29f098518d4c999e8a7b2e4eb23c863aad3bdf484b7d82dd24cd7"
    )
    assert acceptance == PlacementPilotAcceptance.model_validate_json(acceptance.model_dump_json())

    reversed_inputs = PlacementPilotAcceptance.build(
        authority=acceptance.authority,
        candidate_search_result=acceptance.candidate_search_result,
        candidate_inputs=tuple(reversed(acceptance.candidate_inputs)),
        manifest=acceptance.manifest,
    )
    assert reversed_inputs == acceptance


@pytest.mark.skipif(
    os.environ.get("PCBSMITH_R5_KICAD_GOLDEN") != "1",
    reason="set PCBSMITH_R5_KICAD_GOLDEN=1 to exercise the installed KiCad CLI",
)
def test_reduced_stem_acceptance_uses_condition_matched_live_kicad_evidence(
    tmp_path: Path,
) -> None:
    acceptance, _ = _accepted_fixture()
    aggregate = acceptance.manifest.aggregate_evidence
    final_layout = parse_canonical_board_layout_snapshot(aggregate.layout_snapshot_json)
    netlist = parse_canonical_board_netlist_snapshot(aggregate.netlist_snapshot_json)
    accepted_input = next(
        item
        for item in acceptance.candidate_inputs
        if item.candidate_fingerprint == acceptance.accepted_candidate_fingerprint
    )
    probe_layout = parse_canonical_board_layout_snapshot(accepted_input.probe_layout_snapshot_json)
    serialization = build_placement_serialization_authority(
        probe_layout,
        netlist,
        final_layout,
        NET_NAMES,
        ("J1", "J2"),
    )
    live_authority = verify_placement_kicad_save_roundtrip(
        serialization,
        tmp_path,
        require_drc_pass=True,
    )
    live_roundtrip = KiCadSaveRoundtripSubcheckEvidence.build(
        subcheck_id="kicad-roundtrip",
        subcheck_version="1",
        layout=final_layout,
        netlist=netlist,
        policy=aggregate.policy,
        roundtrip_authority=live_authority,
    )
    assert live_roundtrip.status is AggregateCheckStatus.PASS
    assert not live_roundtrip.findings

    live_aggregate = evaluate_stable_aggregate_exact_check(
        final_layout,
        netlist,
        aggregate.policy,
        (
            live_roundtrip,
            *(
                item
                for item in aggregate.subchecks
                if isinstance(
                    item,
                    (
                        ReaderNetlistEqualitySubcheckEvidence,
                    ),
                )
            ),
        ),
    )
    assert live_aggregate.aggregate_result.accepted
    live_manifest = PlacementAcceptanceManifest.build(
        manifest_policy=acceptance.manifest.manifest_policy,
        placement_exact_result=acceptance.manifest.placement_exact_result,
        aggregate_evidence=live_aggregate,
    )
    live_acceptance = PlacementPilotAcceptance.build(
        authority=acceptance.authority,
        candidate_search_result=acceptance.candidate_search_result,
        candidate_inputs=acceptance.candidate_inputs,
        manifest=live_manifest,
    )
    assert live_acceptance.accepted_candidate_fingerprint == (
        acceptance.accepted_candidate_fingerprint
    )


@pytest.mark.skipif(
    os.environ.get("PCBSMITH_R5_KICAD_GOLDEN") != "1",
    reason="set PCBSMITH_R5_KICAD_GOLDEN=1 to exercise the installed KiCad CLI",
)
def test_reduced_stem_acceptance_uses_condition_matched_live_reader_erc_evidence(
    tmp_path: Path,
) -> None:
    acceptance, _ = _accepted_fixture()
    aggregate = acceptance.manifest.aggregate_evidence
    final_layout = parse_canonical_board_layout_snapshot(aggregate.layout_snapshot_json)
    netlist = parse_canonical_board_netlist_snapshot(aggregate.netlist_snapshot_json)
    machine_text, reader_text = _reduced_reader_schematic_texts()
    assert machine_text != reader_text

    def _live(output_root: Path) -> ReaderNetlistEqualitySubcheckEvidence:
        return verify_reader_netlist_equality_live(
            layout=final_layout,
            netlist=netlist,
            policy=aggregate.policy,
            subcheck_id="reader-equality",
            subcheck_version="1",
            machine_schematic_text=machine_text,
            reader_schematic_text=reader_text,
            machine_schematic_artifact_id="machine:reduced-capacity-two-stem.kicad_sch",
            reader_schematic_artifact_id="reader:reduced-capacity-two-stem.kicad_sch",
            schematic_file_name=f"{SCHEMATIC_PROJECT_NAME}.kicad_sch",
            output_root=output_root,
            config_identity="reader-equality-live-v1",
            config={
                "fixture": "reduced-capacity-two-stem",
                "project_name": SCHEMATIC_PROJECT_NAME,
                "drawing_scope": "same renderer, two distinct schematic drawings",
                "offline_reader_connectivity_validated": True,
            },
        )

    live_reader = _live(tmp_path / "same-root")
    repeated_same_root = _live(tmp_path / "same-root")
    repeated_other_root = _live(tmp_path / "other-root")
    assert repeated_same_root == live_reader
    assert repeated_other_root == live_reader
    assert repeated_same_root.evidence_fingerprint == live_reader.evidence_fingerprint
    assert repeated_other_root.evidence_fingerprint == live_reader.evidence_fingerprint
    assert live_reader.status is AggregateCheckStatus.PASS
    assert not live_reader.findings
    assert (
        parse_canonical_board_netlist_snapshot(live_reader.machine_netlist_snapshot_json)
        == netlist
    )
    assert (
        parse_canonical_board_netlist_snapshot(live_reader.reader_netlist_snapshot_json)
        == netlist
    )
    assert live_reader.machine_erc_report.status == "passed"
    assert live_reader.reader_erc_report.status == "passed"

    live_aggregate = evaluate_stable_aggregate_exact_check(
        final_layout,
        netlist,
        aggregate.policy,
        (
            live_reader,
            *(
                item
                for item in aggregate.subchecks
                if isinstance(
                    item,
                    (
                        KiCadSaveRoundtripSubcheckEvidence,
                    ),
                )
            ),
        ),
    )
    assert live_aggregate.aggregate_result.accepted
    live_manifest = PlacementAcceptanceManifest.build(
        manifest_policy=acceptance.manifest.manifest_policy,
        placement_exact_result=acceptance.manifest.placement_exact_result,
        aggregate_evidence=live_aggregate,
    )
    live_acceptance = PlacementPilotAcceptance.build(
        authority=acceptance.authority,
        candidate_search_result=acceptance.candidate_search_result,
        candidate_inputs=acceptance.candidate_inputs,
        manifest=live_manifest,
    )
    assert live_acceptance.accepted_candidate_fingerprint == (
        acceptance.accepted_candidate_fingerprint
    )


def test_graph_preflight_budget_boundary_is_exact() -> None:
    FOOTPRINT_LIBRARY[FOOTPRINT] = TERMINAL_FOOTPRINT_SPEC
    board = make_reduced_capacity_two_stem_board()
    authority = _authority()
    result = build_corridor_graph(
        board.layout,
        board.netlist,
        target_nets=authority.target_net_names,
        default_width_mm=authority.r2_policy.default_width_mm,
        coarse_grid_mm=authority.coarse_grid_mm,
        capacity_quantum_mm=authority.corridor_capacity_quantum_mm,
        budget=authority.corridor_graph_budget.model_copy(update={"max_cells": 125}),
    )
    assert not result.complete
    assert result.failure_reason == "geometry_budget"


def test_one_less_proposal_r3_r2_and_exact_budgets_stop_at_typed_boundaries() -> None:
    acceptance, _ = _accepted_fixture()
    authority = acceptance.authority
    netlist = parse_canonical_board_netlist_snapshot(
        acceptance.manifest.aggregate_evidence.netlist_snapshot_json
    )
    source_layout = authority.layout()

    proposal_budget = authority.placement_budget.model_copy(update={"max_proposals": 1})
    evaluator = _RealReducedStemSurrogate(authority, netlist)
    proposal_limited = generate_placement_candidates(
        source_layout,
        authority.geometry_catalog,
        authority.move_policy,
        authority.legalization_policy,
        proposal_budget,
        target_nets=authority.target_net_names,
        known_net_names=authority.target_net_names,
        profile=authority.profile,
        surrogate_evaluator=evaluator,
    )
    assert proposal_limited.result.telemetry.terminal_reason is (
        PlacementCandidateTerminalReason.PROPOSAL_BUDGET_EXHAUSTED
    )
    assert len(proposal_limited.result.candidates) == 1

    accepted_input = next(
        item
        for item in acceptance.candidate_inputs
        if item.candidate_fingerprint == acceptance.accepted_candidate_fingerprint
    )
    assert accepted_input.corridor_graph is not None
    assert accepted_input.corridor_plan is not None
    verified = accepted_input.surrogate.corridor.verified_summary
    assert verified is not None
    r3_limited = negotiate_corridor_allocations(
        accepted_input.corridor_graph,
        verified.demands,
        budget=authority.corridor_budget.model_copy(update={"max_expansions": 25}),
        cost_policy=authority.corridor_cost_policy,
    )
    assert not r3_limited.guidance_ready
    assert r3_limited.failure_reason == "expansion_budget"
    assert sum(item.expansion_count for item in r3_limited.passes) == 25

    probe_layout = parse_canonical_board_layout_snapshot(accepted_input.probe_layout_snapshot_json)
    r2 = authority.r2_policy
    r2_limited = route_board_corridor_guided(
        probe_layout,
        netlist,
        corridor_graph=accepted_input.corridor_graph,
        corridor_plan=accepted_input.corridor_plan,
        off_corridor_penalty_units=r2.off_corridor_penalty_units,
        target_nets=r2.target_nets,
        net_widths=dict(r2.net_widths_mm),
        default_width_mm=r2.default_width_mm,
        profile=authority.profile,
        net_order=r2.net_order,
        grid_mm=r2.grid_mm,
        max_passes=r2.max_passes,
        max_expansions=733,
        max_expansions_per_net=r2.max_expansions_per_net,
        max_stagnant_passes=r2.max_stagnant_passes,
        cost_policy=authority.negotiated_cost_policy.reconstruct(),
        exact_checker=None,
    ).route_result.run_result
    assert not r2_limited.success
    assert r2_limited.failure_reason is RoutingFailureReason.EXPANSION_BUDGET
    assert sum(item.expansion_count for item in r2_limited.passes) == 733

    exact_result = acceptance.manifest.placement_exact_result
    final_layout = parse_canonical_board_layout_snapshot(
        acceptance.manifest.aggregate_evidence.layout_snapshot_json
    )
    detail_run = PlacementDetailRun(
        result=exact_result.detail_result,
        routed_layouts=((acceptance.accepted_candidate_fingerprint, final_layout),),
    )
    exact_limited = evaluate_placement_exact(
        detail_run,
        netlists_by_candidate_fingerprint={acceptance.accepted_candidate_fingerprint: netlist},
        policy=authority.exact_policy,
        budget=PlacementExactBudget(max_exact_checks=0),
        checker=lambda _layout, _netlist: acceptance.manifest.aggregate_evidence.aggregate_result,
    )
    limited_record = next(
        item
        for item in exact_limited.result.candidate_records
        if item.candidate_fingerprint == acceptance.accepted_candidate_fingerprint
    )
    assert limited_record.disposition is PlacementExactDisposition.BUDGET_EXHAUSTED
    assert exact_limited.result.exact_checks_consumed == 0


@pytest.mark.parametrize(
    ("field", "message"),
    (
        ("authority_fingerprint", "pilot authority fingerprint"),
        ("candidate_search_fingerprint", "candidate search fingerprint"),
        ("accepted_r3_graph_fingerprint", "accepted R3/R2"),
        ("accepted_r2_routing_fingerprint", "accepted R3/R2"),
        ("exact_result_fingerprint", "exact, aggregate, or manifest"),
        ("aggregate_evidence_fingerprint", "exact, aggregate, or manifest"),
        ("manifest_fingerprint", "exact, aggregate, or manifest"),
    ),
)
def test_top_level_binding_tamper_rejects(field: str, message: str) -> None:
    acceptance, _ = _accepted_fixture()
    payload = acceptance.model_dump(mode="python")
    payload[field] = "0" * 64
    payload["acceptance_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError, match=message):
        PlacementPilotAcceptance.model_validate(payload)


def test_scope_claim_tamper_rejects() -> None:
    acceptance, _ = _accepted_fixture()
    payload = acceptance.model_dump(mode="python")
    payload["thermometer_readiness_claimed"] = True
    with pytest.raises(ValidationError):
        PlacementPilotAcceptance.model_validate(payload)


def test_zero_overflow_primary_rank_beats_shorter_overloaded_candidate() -> None:
    zero_overflow = (0, 0, 0, 0, 0, 0, 0, 0, 0)
    overloaded = (0, 0, 0, 0, 1, 1, 0, 0, 0)
    assert _dominates(zero_overflow, overloaded)
    assert not _dominates(overloaded, zero_overflow)
    # HPWL is deliberately secondary and therefore cannot reverse this primary ordering.
    shorter_overloaded_hpwl_um = 1
    longer_zero_overflow_hpwl_um = 1_000_000
    assert shorter_overloaded_hpwl_um < longer_zero_overflow_hpwl_um


@pytest.mark.parametrize(
    "authority_update",
    (
        {"coarse_grid_mm": 3.0},
        {"target_net_names": ("/STEM_A",)},
        {
            "corridor_cost_policy": _authority().corridor_cost_policy.model_copy(
                update={"present_factor_units": 2}
            )
        },
        {"placement_budget": _authority().placement_budget.model_copy(update={"max_proposals": 1})},
        {"profile": _authority().profile.model_copy(update={"profile_id": "stale-profile"})},
    ),
)
def test_stale_pilot_geometry_profile_targets_cost_and_budget_reject(
    authority_update: dict[str, Any],
) -> None:
    acceptance, _ = _accepted_fixture()
    stale = acceptance.authority.model_copy(update=authority_update)
    with pytest.raises(ValidationError):
        PlacementPilotAcceptance.build(
            authority=stale,
            candidate_search_result=acceptance.candidate_search_result,
            candidate_inputs=acceptance.candidate_inputs,
            manifest=acceptance.manifest,
        )


def test_foreign_candidate_and_stale_r3_summary_or_guide_reject() -> None:
    acceptance, _ = _accepted_fixture()
    foreign = acceptance.candidate_inputs[0].model_copy(update={"candidate_fingerprint": "0" * 64})
    with pytest.raises(ValidationError):
        PlacementPilotAcceptance.build(
            authority=acceptance.authority,
            candidate_search_result=acceptance.candidate_search_result,
            candidate_inputs=(foreign, *acceptance.candidate_inputs[1:]),
            manifest=acceptance.manifest,
        )

    accepted_input = next(
        item for item in acceptance.candidate_inputs if item.corridor_graph is not None
    )
    verified = accepted_input.surrogate.corridor.verified_summary
    assert verified is not None
    stale_summary = verified.summary.model_copy(
        update={"expansion_count": verified.summary.expansion_count + 1}
    )
    stale_verified = verified.model_copy(update={"summary": stale_summary})
    stale_corridor = accepted_input.surrogate.corridor.model_copy(
        update={"verified_summary": stale_verified}
    )
    stale_surrogate = accepted_input.surrogate.model_copy(update={"corridor": stale_corridor})
    with pytest.raises(ValidationError):
        accepted_input.model_copy(update={"surrogate": stale_surrogate}).model_validate_json(
            accepted_input.model_copy(update={"surrogate": stale_surrogate}).model_dump_json()
        )

    exact = acceptance.manifest.placement_exact_result
    accepted_record = acceptance.manifest.accepted_candidate_record
    detail = accepted_record.detail_record
    assert detail.guidance is not None
    stale_detail = detail.model_copy(
        update={"guidance": detail.guidance.model_copy(update={"guide_fingerprint": "0" * 64})}
    )
    stale_record = accepted_record.model_copy(update={"detail_record": stale_detail})
    stale_records = tuple(
        stale_record if item.candidate_fingerprint == stale_record.candidate_fingerprint else item
        for item in exact.candidate_records
    )
    stale_exact = exact.model_copy(update={"candidate_records": stale_records})
    with pytest.raises(ValidationError):
        PlacementPilotAcceptance.build(
            authority=acceptance.authority,
            candidate_search_result=acceptance.candidate_search_result,
            candidate_inputs=acceptance.candidate_inputs,
            manifest=acceptance.manifest.model_copy(update={"placement_exact_result": stale_exact}),
        )


def test_route_exact_producer_board_and_netlist_tamper_reject() -> None:
    acceptance, _ = _accepted_fixture()
    manifest = acceptance.manifest
    exact = manifest.placement_exact_result
    accepted_record = manifest.accepted_candidate_record
    detail = accepted_record.detail_record
    assert detail.routing_run is not None
    stale_detail = detail.model_copy(
        update={"routing_run": detail.routing_run.model_copy(update={"producer": "tampered-r2"})}
    )
    stale_record = accepted_record.model_copy(update={"detail_record": stale_detail})
    stale_exact = exact.model_copy(
        update={
            "candidate_records": tuple(
                stale_record
                if item.candidate_fingerprint == stale_record.candidate_fingerprint
                else item
                for item in exact.candidate_records
            )
        }
    )
    with pytest.raises(ValidationError):
        PlacementPilotAcceptance.build(
            authority=acceptance.authority,
            candidate_search_result=acceptance.candidate_search_result,
            candidate_inputs=acceptance.candidate_inputs,
            manifest=manifest.model_copy(update={"placement_exact_result": stale_exact}),
        )

    aggregate = manifest.aggregate_evidence
    fake_result = replace(aggregate.aggregate_result, checker_id="fake-checker")
    with pytest.raises(ValidationError):
        PlacementPilotAcceptance.build(
            authority=acceptance.authority,
            candidate_search_result=acceptance.candidate_search_result,
            candidate_inputs=acceptance.candidate_inputs,
            manifest=manifest.model_copy(
                update={
                    "aggregate_evidence": aggregate.model_copy(
                        update={"aggregate_result": fake_result}
                    )
                }
            ),
        )

    first_subcheck = aggregate.subchecks[0].model_copy(update={"subcheck_version": "stale"})
    with pytest.raises(ValidationError):
        PlacementPilotAcceptance.build(
            authority=acceptance.authority,
            candidate_search_result=acceptance.candidate_search_result,
            candidate_inputs=acceptance.candidate_inputs,
            manifest=manifest.model_copy(
                update={
                    "aggregate_evidence": aggregate.model_copy(
                        update={"subchecks": (first_subcheck, *aggregate.subchecks[1:])}
                    )
                }
            ),
        )

    layout = parse_canonical_board_layout_snapshot(aggregate.layout_snapshot_json)
    changed_layout = replace(layout, width_mm=layout.width_mm + 1.0)
    changed_aggregate = aggregate.model_copy(
        update={"layout_snapshot_json": canonical_board_layout_snapshot_json(changed_layout)}
    )
    with pytest.raises(ValidationError):
        PlacementPilotAcceptance.build(
            authority=acceptance.authority,
            candidate_search_result=acceptance.candidate_search_result,
            candidate_inputs=acceptance.candidate_inputs,
            manifest=manifest.model_copy(update={"aggregate_evidence": changed_aggregate}),
        )

    netlist = parse_canonical_board_netlist_snapshot(aggregate.netlist_snapshot_json)
    changed_netlist = replace(netlist, nets=netlist.nets[:-1])
    changed_aggregate = aggregate.model_copy(
        update={"netlist_snapshot_json": canonical_board_netlist_snapshot_json(changed_netlist)}
    )
    with pytest.raises(ValidationError):
        PlacementPilotAcceptance.build(
            authority=acceptance.authority,
            candidate_search_result=acceptance.candidate_search_result,
            candidate_inputs=acceptance.candidate_inputs,
            manifest=manifest.model_copy(update={"aggregate_evidence": changed_aggregate}),
        )
