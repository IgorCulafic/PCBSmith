from __future__ import annotations

import hashlib
import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.models import SimulationReport
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.corridor_guidance import (
    CorridorGuidanceDisposition,
    CorridorGuidanceReport,
)
from pcbsmith.generation.thermometer import compose_thermometer
from pcbsmith.kicad.aggregate_exact_checker import (
    KICAD_SAVE_ROUNDTRIP_ADAPTER_ID,
    READER_NETLIST_EQUALITY_ADAPTER_ID,
    THERMOMETER_NGSPICE_ADAPTER_ID,
    AggregateCheckStatus,
    AggregateSubcheckApplicability,
    AggregateSubcheckKind,
    AggregateSubcheckRequirement,
    ExternalArtifactSubcheckEvidence,
    KiCadSaveRoundtripSubcheckEvidence,
    MissingSubcheckEvidence,
    ReaderNetlistEqualitySubcheckEvidence,
    StableAggregateExactCheckerPolicy,
    StableAggregateExactCheckEvidence,
    ThermometerNgspiceSubcheckEvidence,
    evaluate_stable_aggregate_exact_check,
    external_subcheck_binding,
)
from pcbsmith.kicad.board import (
    BoardLayout,
    BoardNetlist,
    TrackSegment,
    canonical_kicad_netlist_xml_text,
)
from pcbsmith.kicad.board_serialization import (
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.kicad.design_checks import DesignChecksSpec
from pcbsmith.kicad.negotiated_board import ExactRouteCheckResult
from pcbsmith.kicad.placement_acceptance_manifest import (
    REQUIRED_ACCEPTANCE_PRODUCERS,
    ROUTING_ONLY_ACCEPTANCE_PRODUCERS,
    PlacementAcceptanceManifest,
    PlacementAcceptanceManifestPolicy,
)
from pcbsmith.kicad.placement_detail import PlacementDetailRun
from pcbsmith.kicad.placement_exact import evaluate_placement_exact
from pcbsmith.kicad.placement_routability import board_layout_fingerprint
from pcbsmith.kicad.validate import canonical_kicad_erc_json_text
from pcbsmith.placement_detail_ir import (
    PlacementCandidateDetailRecord,
    PlacementDetailBudget,
    PlacementDetailRunResult,
    PlacementDetailSelectionPolicy,
    PlacementDetailState,
    PlacementMarginRank,
    PlacementParetoEvidence,
    PlacementR2Policy,
    PlacementSelectionReason,
)
from pcbsmith.placement_exact_ir import (
    PlacementExactBudget,
    PlacementExactPolicy,
    PlacementExactRunResult,
)
from pcbsmith.routing_ir import RoutingBudget, RoutingRunResult
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE
from pcbsmith.simulation.ngspice_buck import parse_ngspice_meas_results
from pcbsmith.simulation.ngspice_thermometer import (
    evaluate_thermometer_measurements,
)

PASS_RAW = "i_seg = 5.37e-3\nv_f = 1.85\ni_pwled = 1.45e-3\n"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fp(value: object) -> str:
    return _sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    )


def _aggregate_requirements(
    *,
    include_generic: bool = False,
    routing_only: bool = False,
) -> tuple[AggregateSubcheckRequirement, ...]:
    generic = (
        AggregateSubcheckRequirement(
            subcheck_id="extra-generic",
            subcheck_version="1",
            kind=AggregateSubcheckKind.EXTERNAL_ARTIFACT,
        ),
    ) if include_generic else ()
    return (
        AggregateSubcheckRequirement(
            subcheck_id="design",
            subcheck_version="1",
            kind=AggregateSubcheckKind.DESIGN_CHECKS,
        ),
        *generic,
        AggregateSubcheckRequirement(
            subcheck_id="kicad-roundtrip",
            subcheck_version="1",
            kind=AggregateSubcheckKind.EXTERNAL_ARTIFACT,
            producer_id=KICAD_SAVE_ROUNDTRIP_ADAPTER_ID,
        ),
        AggregateSubcheckRequirement(
            subcheck_id="reader-equality",
            subcheck_version="1",
            kind=AggregateSubcheckKind.EXTERNAL_ARTIFACT,
            producer_id=READER_NETLIST_EQUALITY_ADAPTER_ID,
        ),
        AggregateSubcheckRequirement(
            subcheck_id="thermometer-simulation",
            subcheck_version="1",
            kind=AggregateSubcheckKind.EXTERNAL_ARTIFACT,
            applicability=(
                AggregateSubcheckApplicability.NOT_APPLICABLE
                if routing_only
                else AggregateSubcheckApplicability.REQUIRED
            ),
            producer_id=THERMOMETER_NGSPICE_ADAPTER_ID,
        ),
        AggregateSubcheckRequirement(
            subcheck_id="virtual",
            subcheck_version="1",
            kind=AggregateSubcheckKind.VIRTUAL_DRC,
        ),
    )


def _aggregate_policy(
    *, include_generic: bool = False, routing_only: bool = False
) -> StableAggregateExactCheckerPolicy:
    return StableAggregateExactCheckerPolicy.build(
        policy_id=(
            "synthetic-routing-only-placement-checker"
            if routing_only
            else "synthetic-all-three-placement-checker"
        ),
        policy_version="2" if routing_only else "1",
        profile=DEFAULT_PCB_RULE_PROFILE,
        design_checks_spec=DesignChecksSpec(),
        subchecks=_aggregate_requirements(
            include_generic=include_generic, routing_only=routing_only
        ),
    )


def _checker_id(policy: StableAggregateExactCheckerPolicy) -> str:
    return f"{policy.policy_id}@{policy.policy_version}:{policy.policy_fingerprint}"


def _reader_xml(netlist: BoardNetlist) -> str:
    component = netlist.components[0]
    net = netlist.nets[0]
    node = net.nodes[0]
    fields = "".join(
        f'<field name="{name}">{value}</field>' for name, value in component.fields
    )
    return f"""<export>
  <components><comp ref="{component.reference}">
    <value>{component.value}</value><footprint>{component.footprint}</footprint>
    <tstamps>{component.uuid_path}</tstamps><fields>{fields}</fields>
  </comp></components>
  <nets><net name="{net.name}"><node ref="{node[0]}" pin="{node[1]}"/></net></nets>
</export>"""


def _simulation_report() -> SimulationReport:
    circuit = _circuit()
    measurements = parse_ngspice_meas_results(PASS_RAW)
    status, findings, retained = evaluate_thermometer_measurements(measurements, circuit)
    return SimulationReport(
        backend="ngspice",
        status=status,  # type: ignore[arg-type]
        command=("ngspice", "-b", "thermometer_led_op.cir"),
        measurements=retained,
        findings=findings,
        raw_output_path="thermometer_led_op.log",
    )


def _circuit():
    intent = classify_circuit_intent("thermometer temperature humidity display pcb")
    return compose_thermometer(intent, select_topology(intent))


def _aggregate(
    *,
    policy: StableAggregateExactCheckerPolicy | None = None,
    include_generic: bool = False,
    include_simulation: bool = True,
) -> tuple[StableAggregateExactCheckEvidence, BoardLayout, BoardNetlist]:
    from tests.unit.kicad.test_aggregate_kicad_roundtrip_adapter import (
        _board_inputs,
        _roundtrip_authority,
    )

    authority = _roundtrip_authority()
    layout, netlist = _board_inputs(authority)
    retained_policy = policy or _aggregate_policy(include_generic=include_generic)
    xml = _reader_xml(netlist)
    roundtrip = KiCadSaveRoundtripSubcheckEvidence.build(
        subcheck_id="kicad-roundtrip",
        subcheck_version="1",
        layout=layout,
        netlist=netlist,
        policy=retained_policy,
        roundtrip_authority=authority,
    )
    reader = ReaderNetlistEqualitySubcheckEvidence.build(
        subcheck_id="reader-equality",
        subcheck_version="1",
        layout=layout,
        netlist=netlist,
        policy=retained_policy,
        machine_schematic_artifact_id="machine:synthetic.kicad_sch",
        machine_schematic_text="synthetic machine schematic artifact\n",
        machine_schematic_artifact_sha256=_sha256("synthetic machine schematic artifact\n"),
        reader_schematic_artifact_id="reader:synthetic.kicad_sch",
        reader_schematic_text="synthetic reader schematic artifact\n",
        reader_schematic_artifact_sha256=_sha256("synthetic reader schematic artifact\n"),
        machine_netlist_xml_text=canonical_kicad_netlist_xml_text(xml),
        reader_netlist_xml_text=canonical_kicad_netlist_xml_text(xml),
        tool_id="kicad-cli",
        tool_version="10.0-nonlive-fixture",
        config_identity="reader-equality-v1",
        config={"fixture": True},
        machine_erc_report_json=canonical_kicad_erc_json_text(
            json.dumps({"sheets": [{"violations": []}]})
        ),
        reader_erc_report_json=canonical_kicad_erc_json_text(
            json.dumps({"sheets": [{"violations": []}]})
        ),
        machine_erc_report=_erc_report("machine.kicad_sch"),
        reader_erc_report=_erc_report("reader.kicad_sch"),
    )
    supplied: tuple[
        ExternalArtifactSubcheckEvidence
        | KiCadSaveRoundtripSubcheckEvidence
        | ReaderNetlistEqualitySubcheckEvidence
        | ThermometerNgspiceSubcheckEvidence,
        ...,
    ] = (roundtrip, reader)
    if include_simulation:
        simulation = ThermometerNgspiceSubcheckEvidence.build(
            subcheck_id="thermometer-simulation",
            subcheck_version="1",
            layout=layout,
            netlist=netlist,
            policy=retained_policy,
            circuit=_circuit(),
            circuit_artifact_id="circuit:synthetic-thermometer.json",
            circuit_artifact_sha256="c" * 64,
            raw_output_text=PASS_RAW,
            raw_output_artifact_id="ngspice:synthetic.log",
            simulation_report=_simulation_report(),
            tool_version="ngspice-46-nonlive-fixture",
            config={"batch": True},
        )
        supplied = (*supplied, simulation)
    if include_generic:
        layout_fp, netlist_fp, policy_fp = external_subcheck_binding(
            layout, netlist, retained_policy
        )
        generic = ExternalArtifactSubcheckEvidence.build(
            subcheck_id="extra-generic",
            subcheck_version="1",
            status=AggregateCheckStatus.PASS,
            findings=(),
            layout_snapshot_fingerprint=layout_fp,
            netlist_snapshot_fingerprint=netlist_fp,
            policy_fingerprint=policy_fp,
            source_artifact_id="generic:extra",
            source_artifact_sha256="d" * 64,
            tool_id="generic",
            tool_version="1",
            config={"extra": True},
            result_identity="generic-extra-result",
        )
        supplied = (*supplied, generic)
    aggregate = evaluate_stable_aggregate_exact_check(
        layout, netlist, retained_policy, tuple(reversed(supplied))
    )
    assert aggregate.aggregate_result.accepted
    return aggregate, layout, netlist


def _erc_report(schematic: str):
    from pcbsmith.circuit.models import KiCadReport

    return KiCadReport(
        status="passed",
        command=("kicad-cli", "sch", "erc"),
        schematic_file=schematic,
        erc_report=f"{schematic}.erc.json",
    )


def _detail_run(layout: BoardLayout) -> PlacementDetailRun:
    candidate = _sha256("synthetic accepted placement candidate")
    graph_fp = _sha256("synthetic corridor graph")
    plan_fp = _sha256("synthetic corridor plan")
    guide_fp = _sha256("synthetic corridor guide")
    routing_budget = RoutingBudget(
        max_passes=4,
        max_expansions=20,
        max_expansions_per_net=10,
        max_stagnant_passes=2,
        max_exact_check_rejections=0,
    )
    routing = RoutingRunResult(
        producer="synthetic-r2-authority",
        budget=routing_budget,
        success=True,
        route_order=("/LOCAL",),
    )
    guidance = CorridorGuidanceReport(
        disposition=CorridorGuidanceDisposition.APPLIED,
        plan_fingerprint=plan_fp,
        graph_fingerprint=graph_fp,
        guide_fingerprint=guide_fp,
        guided_net_names=("/LOCAL",),
        routing_run_fingerprint=routing.semantic_fingerprint(),
    )
    from pcbsmith.kicad.placement_exact import placement_route_geometry_fingerprint

    record = PlacementCandidateDetailRecord(
        candidate_fingerprint=candidate,
        detail_input_fingerprint=_sha256("synthetic detail input"),
        selected=True,
        state=PlacementDetailState.ROUTED_UNCHECKED,
        r3_evaluations_consumed=1,
        r2_evaluations_consumed=1,
        corridor_graph_fingerprint=graph_fp,
        corridor_plan_fingerprint=plan_fp,
        guidance=guidance,
        routing_run=routing,
        materialized_layout_fingerprint=board_layout_fingerprint(layout),
        route_geometry_fingerprint=placement_route_geometry_fingerprint(
            layout, frozenset({"/LOCAL"})
        ),
        algorithmic_success=True,
        zero_overuse=True,
        routed_unchecked=True,
    )
    selection = PlacementDetailSelectionPolicy(coarse_failure_exploration_quota=0)
    budget = PlacementDetailBudget(
        max_selected_candidates=1,
        max_corridor_evaluations=1,
        max_routing_evaluations=1,
    )
    r2_policy = PlacementR2Policy(
        target_nets=("/LOCAL",),
        max_passes=4,
        max_expansions=20,
        max_expansions_per_net=10,
        max_stagnant_passes=2,
    )
    pareto = PlacementParetoEvidence(
        candidate_fingerprint=candidate,
        primary_vector=(0, 0, 0, 0, 0, 0, 0, 0, 0),
        hpwl_total_um=0,
        minimum_margin_rank=PlacementMarginRank.UNKNOWN,
        minimum_terminal_margin_um=None,
        corridor_allocation_fingerprint=plan_fp,
        portal_overflow_bucket=1,
        base_candidate=True,
        coarse_failure=False,
        pareto_front_index=0,
        selected=True,
        selection_reason=PlacementSelectionReason.BASE,
    )
    components = {
        "input_catalog_fingerprint": _sha256("synthetic detail catalog"),
        "selection_policy_fingerprint": selection.semantic_fingerprint(),
        "budget_fingerprint": budget.semantic_fingerprint(),
        "r2_policy_fingerprint": r2_policy.semantic_fingerprint(),
        "profile_fingerprint": _sha256("synthetic profile"),
    }
    result = PlacementDetailRunResult(
        **components,
        input_fingerprint=_fp(
            {
                "schema_id": "pcbsmith-placement-detail-input",
                "schema_version": 1,
                **components,
            }
        ),
        selection_policy=selection,
        budget=budget,
        r2_policy=r2_policy,
        pareto_evidence=(pareto,),
        selected_candidate_fingerprints=(candidate,),
        candidate_records=(record,),
        corridor_evaluations_consumed=1,
        routing_evaluations_consumed=1,
    )
    return PlacementDetailRun(result=result, routed_layouts=((candidate, layout),))


def _exact_result(
    layout: BoardLayout,
    netlist: BoardNetlist,
    checker_id: str,
    *,
    findings: tuple[str, ...] = (),
) -> PlacementExactRunResult:
    detail = _detail_run(layout)
    candidate = detail.result.candidate_records[0].candidate_fingerprint
    run = evaluate_placement_exact(
        detail,
        netlists_by_candidate_fingerprint={candidate: netlist},
        policy=PlacementExactPolicy(checker_id=checker_id),
        budget=PlacementExactBudget(max_exact_checks=1),
        checker=lambda _layout, _netlist: ExactRouteCheckResult(
            True, checker_id, findings
        ),
    )
    return run.result


def _fixture() -> tuple[
    PlacementAcceptanceManifest,
    PlacementExactRunResult,
    StableAggregateExactCheckEvidence,
]:
    aggregate, layout, netlist = _aggregate()
    exact = _exact_result(layout, netlist, aggregate.aggregate_result.checker_id)
    manifest = PlacementAcceptanceManifest.build(
        manifest_policy=PlacementAcceptanceManifestPolicy.build(),
        placement_exact_result=exact,
        aggregate_evidence=aggregate,
    )
    return manifest, exact, aggregate


def _routing_only_fixture() -> tuple[
    PlacementAcceptanceManifest,
    PlacementExactRunResult,
    StableAggregateExactCheckEvidence,
]:
    policy = _aggregate_policy(routing_only=True)
    aggregate, layout, netlist = _aggregate(policy=policy, include_simulation=False)
    exact = _exact_result(layout, netlist, aggregate.aggregate_result.checker_id)
    manifest = PlacementAcceptanceManifest.build(
        manifest_policy=PlacementAcceptanceManifestPolicy.build(routing_only=True),
        placement_exact_result=exact,
        aggregate_evidence=aggregate,
    )
    return manifest, exact, aggregate


def _refingerprint(payload: dict[str, object]) -> None:
    value = dict(payload)
    value.pop("manifest_fingerprint", None)
    payload["manifest_fingerprint"] = _fp(value)


def test_synthetic_all_three_producer_manifest_fires_and_replays() -> None:
    manifest, exact, aggregate = _fixture()

    assert aggregate.aggregate_result.accepted
    assert len(exact.accepted_candidate_fingerprints) == 1
    assert manifest.accepted_candidate_fingerprint == exact.accepted_candidate_fingerprints[0]
    assert tuple(
        (item.subcheck_id, item.subcheck_version, item.producer_id)
        for item in manifest.manifest_policy.required_producers
    ) == tuple(
        (item.subcheck_id, item.subcheck_version, item.producer_id)
        for item in REQUIRED_ACCEPTANCE_PRODUCERS
    )
    assert not manifest.circuit_board_equivalence_claimed
    assert "no thermometer readiness" in manifest.authority_scope_note
    assert manifest == PlacementAcceptanceManifest.model_validate_json(
        manifest.model_dump_json()
    )


def test_build_and_input_order_are_deterministic() -> None:
    first, exact, aggregate = _fixture()
    second = PlacementAcceptanceManifest.build(
        manifest_policy=PlacementAcceptanceManifestPolicy.build(),
        placement_exact_result=PlacementExactRunResult.model_validate_json(
            exact.model_dump_json()
        ),
        aggregate_evidence=StableAggregateExactCheckEvidence.model_validate_json(
            aggregate.model_dump_json()
        ),
    )
    assert first == second
    assert first.manifest_fingerprint == second.manifest_fingerprint


@pytest.mark.parametrize(
    "field, expected",
    (
        ("accepted_candidate_fingerprint", "selected accepted candidate"),
        ("accepted_candidate_record_fingerprint", "candidate record fingerprint"),
        ("detail_record_fingerprint", "detail record fingerprint"),
        ("routing_run_fingerprint", "routing run fingerprint"),
        ("guidance_fingerprint", "guidance fingerprint"),
        ("corridor_graph_fingerprint", "corridor graph fingerprint"),
        ("corridor_plan_fingerprint", "corridor plan fingerprint"),
        ("corridor_guide_fingerprint", "corridor guide fingerprint"),
        ("route_geometry_fingerprint", "route geometry"),
        ("materialized_layout_fingerprint", "materialized layout"),
        ("netlist_fingerprint", "netlist"),
        ("placement_exact_result_fingerprint", "exact result fingerprint"),
        ("aggregate_evidence_fingerprint", "aggregate evidence fingerprint"),
        ("aggregate_policy_fingerprint", "aggregate policy fingerprint"),
        ("manifest_policy_fingerprint", "manifest policy fingerprint"),
        ("manifest_fingerprint", "manifest fingerprint"),
    ),
)
def test_retained_cross_binding_and_manifest_fingerprint_tampering_rejects(
    field: str, expected: str
) -> None:
    payload = json.loads(_fixture()[0].model_dump_json())
    payload[field] = "0" * 64
    if field != "manifest_fingerprint":
        _refingerprint(payload)

    with pytest.raises(ValidationError) as caught:
        PlacementAcceptanceManifest.model_validate(payload)
    assert expected in str(caught.value)


def test_different_layout_netlist_checker_and_route_geometry_are_rejected() -> None:
    aggregate, layout, netlist = _aggregate()
    changed_layout = replace(
        layout,
        segments=(
            *layout.segments,
            TrackSegment(1.0, 1.0, 2.0, 1.0, "F.Cu", "/LOCAL", 0.2),
        ),
    )
    changed_exact = _exact_result(
        changed_layout, netlist, aggregate.aggregate_result.checker_id
    )
    with pytest.raises(ValidationError, match="aggregate layout differs"):
        PlacementAcceptanceManifest.build(
            manifest_policy=PlacementAcceptanceManifestPolicy.build(),
            placement_exact_result=changed_exact,
            aggregate_evidence=aggregate,
        )

    changed_netlist = replace(netlist, nets=())
    wrong_netlist_exact = _exact_result(
        layout, changed_netlist, aggregate.aggregate_result.checker_id
    )
    with pytest.raises(ValidationError, match="aggregate netlist differs"):
        PlacementAcceptanceManifest.build(
            manifest_policy=PlacementAcceptanceManifestPolicy.build(),
            placement_exact_result=wrong_netlist_exact,
            aggregate_evidence=aggregate,
        )

    wrong_checker = _exact_result(layout, netlist, "different-checker")
    with pytest.raises(ValidationError, match="checker identities differ"):
        PlacementAcceptanceManifest.build(
            manifest_policy=PlacementAcceptanceManifestPolicy.build(),
            placement_exact_result=wrong_checker,
            aggregate_evidence=aggregate,
        )


def test_same_checker_and_acceptance_with_different_findings_is_rejected() -> None:
    aggregate, layout, netlist = _aggregate()
    exact = _exact_result(
        layout,
        netlist,
        aggregate.aggregate_result.checker_id,
        findings=(_sha256("self-consistent extra exact finding"),),
    )

    with pytest.raises(ValidationError, match="differs from aggregate exact result"):
        PlacementAcceptanceManifest.build(
            manifest_policy=PlacementAcceptanceManifestPolicy.build(),
            placement_exact_result=exact,
            aggregate_evidence=aggregate,
        )


def test_extra_generic_policy_and_missing_specialized_producer_are_rejected() -> None:
    aggregate, layout, netlist = _aggregate(include_generic=True)
    exact = _exact_result(layout, netlist, aggregate.aggregate_result.checker_id)
    with pytest.raises(ValidationError, match="manifest acceptance phase"):
        PlacementAcceptanceManifest.build(
            manifest_policy=PlacementAcceptanceManifestPolicy.build(),
            placement_exact_result=exact,
            aggregate_evidence=aggregate,
        )

    missing_policy = StableAggregateExactCheckerPolicy.build(
        policy_id="missing-simulation",
        policy_version="1",
        profile=DEFAULT_PCB_RULE_PROFILE,
        design_checks_spec=DesignChecksSpec(),
        subchecks=tuple(
            item
            for item in _aggregate_requirements()
            if item.subcheck_id != "thermometer-simulation"
        ),
    )
    missing, layout, netlist = _aggregate(
        policy=missing_policy,
        include_simulation=False,
    )
    missing_exact = _exact_result(layout, netlist, missing.aggregate_result.checker_id)
    with pytest.raises(ValidationError, match="manifest acceptance phase"):
        PlacementAcceptanceManifest.build(
            manifest_policy=PlacementAcceptanceManifestPolicy.build(),
            placement_exact_result=missing_exact,
            aggregate_evidence=missing,
        )


def test_generic_and_specialized_producer_substitution_cannot_satisfy_policy() -> None:
    aggregate, layout, netlist = _aggregate()
    policy = aggregate.policy
    layout_fp, netlist_fp, policy_fp = external_subcheck_binding(layout, netlist, policy)
    generic = ExternalArtifactSubcheckEvidence.build(
        subcheck_id="thermometer-simulation",
        subcheck_version="1",
        status=AggregateCheckStatus.PASS,
        findings=(),
        layout_snapshot_fingerprint=layout_fp,
        netlist_snapshot_fingerprint=netlist_fp,
        policy_fingerprint=policy_fp,
        source_artifact_id="generic:substitute",
        source_artifact_sha256="e" * 64,
        tool_id="generic",
        tool_version="1",
        config={"substitute": True},
        result_identity="generic-substitute",
    )
    retained = tuple(
        item
        for item in aggregate.subchecks
        if isinstance(
            item,
            (KiCadSaveRoundtripSubcheckEvidence, ReaderNetlistEqualitySubcheckEvidence),
        )
    )
    with pytest.raises(ValueError, match="generic external evidence cannot fulfill"):
        evaluate_stable_aggregate_exact_check(layout, netlist, policy, (*retained, generic))

    reader = next(
        item
        for item in aggregate.subchecks
        if isinstance(item, ReaderNetlistEqualitySubcheckEvidence)
    )
    payload = json.loads(reader.model_dump_json())
    payload["subcheck_id"] = "thermometer-simulation"
    evidence_payload = dict(payload)
    evidence_payload.pop("evidence_fingerprint")
    payload["evidence_fingerprint"] = _fp(evidence_payload)
    substitute = ReaderNetlistEqualitySubcheckEvidence.model_validate(payload)
    with pytest.raises(ValueError, match="reader-netlist evidence requires"):
        evaluate_stable_aggregate_exact_check(layout, netlist, policy, (*retained, substitute))


def test_duplicate_specialized_aggregate_evidence_is_rejected() -> None:
    aggregate, layout, netlist = _aggregate()
    specialized = tuple(
        item
        for item in aggregate.subchecks
        if isinstance(
            item,
            (
                KiCadSaveRoundtripSubcheckEvidence,
                ReaderNetlistEqualitySubcheckEvidence,
                ThermometerNgspiceSubcheckEvidence,
            ),
        )
    )

    with pytest.raises(ValueError, match="duplicate external"):
        evaluate_stable_aggregate_exact_check(
            layout,
            netlist,
            aggregate.policy,
            (*specialized, specialized[0]),
        )


def test_nested_specialized_tamper_is_rejected_before_manifest_composition() -> None:
    payload = json.loads(_fixture()[0].model_dump_json())
    specialized = next(
        item
        for item in payload["aggregate_evidence"]["subchecks"]
        if item["evidence_kind"] == "kicad_save_roundtrip"
    )
    specialized["layout_snapshot_fingerprint"] = "0" * 64
    specialized_payload = dict(specialized)
    specialized_payload.pop("evidence_fingerprint")
    specialized["evidence_fingerprint"] = _fp(specialized_payload)
    aggregate_payload = dict(payload["aggregate_evidence"])
    aggregate_payload.pop("evidence_fingerprint")
    payload["aggregate_evidence"]["evidence_fingerprint"] = _fp(aggregate_payload)
    _refingerprint(payload)

    with pytest.raises(ValidationError, match="layout binding is stale"):
        PlacementAcceptanceManifest.model_validate(payload)


def test_subcheck_fingerprint_and_no_equivalence_scope_are_tamper_evident() -> None:
    payload = json.loads(_fixture()[0].model_dump_json())
    payload["aggregate_subcheck_fingerprints"][0][2] = "0" * 64
    _refingerprint(payload)
    with pytest.raises(ValidationError, match="subcheck fingerprints are stale"):
        PlacementAcceptanceManifest.model_validate(payload)

    equivalence = json.loads(_fixture()[0].model_dump_json())
    equivalence["circuit_board_equivalence_claimed"] = True
    _refingerprint(equivalence)
    with pytest.raises(ValidationError, match="literal_error"):
        PlacementAcceptanceManifest.model_validate(equivalence)


def test_nonaccepted_or_multiple_accepted_exact_results_are_rejected() -> None:
    aggregate, layout, netlist = _aggregate()
    detail = _detail_run(layout)
    candidate = detail.result.candidate_records[0].candidate_fingerprint
    rejected = evaluate_placement_exact(
        detail,
        netlists_by_candidate_fingerprint={candidate: netlist},
        policy=PlacementExactPolicy(checker_id=aggregate.aggregate_result.checker_id),
        budget=PlacementExactBudget(max_exact_checks=1),
        checker=lambda _layout, _netlist: ExactRouteCheckResult(
            False, aggregate.aggregate_result.checker_id, (_sha256("reject"),)
        ),
    ).result
    with pytest.raises(ValueError, match="exactly one accepted"):
        PlacementAcceptanceManifest.build(
            manifest_policy=PlacementAcceptanceManifestPolicy.build(),
            placement_exact_result=rejected,
            aggregate_evidence=aggregate,
        )


def test_manifest_policy_missing_extra_or_changed_producers_is_invalid() -> None:
    policy = PlacementAcceptanceManifestPolicy.build()
    for requirements in (
        REQUIRED_ACCEPTANCE_PRODUCERS[:-1],
        (*REQUIRED_ACCEPTANCE_PRODUCERS, REQUIRED_ACCEPTANCE_PRODUCERS[0]),
    ):
        payload = json.loads(policy.model_dump_json())
        payload["required_producers"] = [item.model_dump(mode="json") for item in requirements]
        policy_payload = dict(payload)
        policy_payload.pop("policy_fingerprint")
        payload["policy_fingerprint"] = _fp(policy_payload)
        with pytest.raises(ValidationError, match="producers differ from its acceptance phase"):
            PlacementAcceptanceManifestPolicy.model_validate(payload)


def test_routing_only_v2_requires_two_live_producer_slots_and_typed_simulation_na() -> None:
    manifest, _, aggregate = _routing_only_fixture()
    simulation = next(
        item for item in aggregate.subchecks if item.subcheck_id == "thermometer-simulation"
    )

    assert manifest.manifest_policy.policy_version == "2"
    assert manifest.manifest_policy.required_producers == ROUTING_ONLY_ACCEPTANCE_PRODUCERS
    assert isinstance(simulation, MissingSubcheckEvidence)
    assert simulation.status is AggregateCheckStatus.NOT_APPLICABLE
    assert simulation.reason == "policy explicitly declares this external subcheck not applicable"
    assert simulation.finding_fingerprint is None
    assert sum(
        isinstance(
            item,
            (KiCadSaveRoundtripSubcheckEvidence, ReaderNetlistEqualitySubcheckEvidence),
        )
        for item in aggregate.subchecks
    ) == 2
    assert not any(
        isinstance(item, ThermometerNgspiceSubcheckEvidence) for item in aggregate.subchecks
    )
    assert manifest == PlacementAcceptanceManifest.model_validate_json(manifest.model_dump_json())


def test_routing_only_v2_rejects_fake_simulation_and_v1_phase_misuse() -> None:
    routing_manifest, routing_exact, routing_aggregate = _routing_only_fixture()
    full_manifest, full_exact, full_aggregate = _fixture()
    simulation = next(
        item
        for item in full_aggregate.subchecks
        if isinstance(item, ThermometerNgspiceSubcheckEvidence)
    )
    supplied = tuple(
        item
        for item in routing_aggregate.subchecks
        if isinstance(
            item,
            (KiCadSaveRoundtripSubcheckEvidence, ReaderNetlistEqualitySubcheckEvidence),
        )
    )
    with pytest.raises(ValueError, match="policy-inapplicable"):
        evaluate_stable_aggregate_exact_check(
            parse_canonical_board_layout_snapshot(routing_aggregate.layout_snapshot_json),
            parse_canonical_board_netlist_snapshot(routing_aggregate.netlist_snapshot_json),
            routing_aggregate.policy,
            (*supplied, simulation),
        )
    with pytest.raises(ValidationError, match="manifest acceptance phase"):
        PlacementAcceptanceManifest.build(
            manifest_policy=PlacementAcceptanceManifestPolicy.build(),
            placement_exact_result=routing_exact,
            aggregate_evidence=routing_aggregate,
        )
    with pytest.raises(ValidationError, match="manifest acceptance phase"):
        PlacementAcceptanceManifest.build(
            manifest_policy=PlacementAcceptanceManifestPolicy.build(routing_only=True),
            placement_exact_result=full_exact,
            aggregate_evidence=full_aggregate,
        )
    assert routing_manifest.manifest_policy.policy_version == "2"
    assert full_manifest.manifest_policy.policy_version == "1"


def test_routing_only_v2_rejects_missing_or_tampered_na_record_and_wrong_policy() -> None:
    _, _, routing_aggregate = _routing_only_fixture()
    payload = json.loads(routing_aggregate.model_dump_json())
    simulation = next(
        item for item in payload["subchecks"] if item["subcheck_id"] == "thermometer-simulation"
    )
    simulation["reason"] = "wrong routing phase"
    outer = dict(payload)
    outer.pop("evidence_fingerprint")
    payload["evidence_fingerprint"] = _fp(outer)
    with pytest.raises(ValidationError):
        StableAggregateExactCheckEvidence.model_validate(payload)

    requirements_without_simulation = tuple(
        item
        for item in _aggregate_requirements(routing_only=True)
        if item.subcheck_id != "thermometer-simulation"
    )
    policy_without_simulation = StableAggregateExactCheckerPolicy.build(
        policy_id="synthetic-routing-only-missing-na",
        policy_version="2",
        profile=DEFAULT_PCB_RULE_PROFILE,
        design_checks_spec=DesignChecksSpec(),
        subchecks=requirements_without_simulation,
    )
    aggregate, layout, netlist = _aggregate(
        policy=policy_without_simulation, include_simulation=False
    )
    exact = _exact_result(layout, netlist, aggregate.aggregate_result.checker_id)
    with pytest.raises(ValidationError, match="manifest acceptance phase"):
        PlacementAcceptanceManifest.build(
            manifest_policy=PlacementAcceptanceManifestPolicy.build(routing_only=True),
            placement_exact_result=exact,
            aggregate_evidence=aggregate,
        )

    routing_policy = PlacementAcceptanceManifestPolicy.build(routing_only=True)
    wrong_policy = json.loads(routing_policy.model_dump_json())
    wrong_policy["policy_id"] = "r5-wrong-routing-phase"
    policy_payload = dict(wrong_policy)
    policy_payload.pop("policy_fingerprint")
    wrong_policy["policy_fingerprint"] = _fp(policy_payload)
    with pytest.raises(ValidationError, match="supported acceptance phase"):
        PlacementAcceptanceManifestPolicy.model_validate(wrong_policy)
