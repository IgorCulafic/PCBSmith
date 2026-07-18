from __future__ import annotations

import hashlib
import json
from copy import deepcopy

import pytest
from pydantic import ValidationError

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.models import CircuitObject, SimulationReport
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.thermometer import compose_thermometer
from pcbsmith.kicad.aggregate_exact_checker import (
    READER_NETLIST_EQUALITY_ADAPTER_ID,
    THERMOMETER_LED_BRANCH_MODEL_SCOPE_ID,
    THERMOMETER_NGSPICE_ADAPTER_ID,
    AggregateCheckStatus,
    AggregateSubcheckKind,
    AggregateSubcheckRequirement,
    ExternalArtifactSubcheckEvidence,
    StableAggregateExactCheckerPolicy,
    StableAggregateExactCheckEvidence,
    ThermometerNgspiceSubcheckEvidence,
    evaluate_stable_aggregate_exact_check,
    external_subcheck_binding,
)
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.design_checks import DesignChecksSpec
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE
from pcbsmith.simulation.ngspice_buck import parse_ngspice_meas_results
from pcbsmith.simulation.ngspice_thermometer import (
    MODEL_NOTE,
    evaluate_thermometer_measurements,
    render_thermometer_netlist,
)

PASS_RAW = """ngspice fixture output
i_seg = 5.37e-3
v_f = 1.85
i_pwled = 1.45e-3
"""
PASS_RAW_REORDERED = """ngspice fixture output
i_pwled = 1.45e-3
i_seg = 5.37e-3
v_f = 1.85
"""


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fingerprint(value: object) -> str:
    return _sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    )


def _circuit() -> CircuitObject:
    intent = classify_circuit_intent("thermometer temperature humidity display pcb")
    return compose_thermometer(intent, select_topology(intent))


def _inputs() -> tuple[BoardLayout, BoardNetlist]:
    return (
        BoardLayout(placements=(), segments=(), vias=(), width_mm=20.0, height_mm=20.0),
        BoardNetlist(components=(), nets=()),
    )


def _requirements(
    producer_id: str | None = THERMOMETER_NGSPICE_ADAPTER_ID,
) -> tuple[AggregateSubcheckRequirement, ...]:
    return (
        AggregateSubcheckRequirement(
            subcheck_id="design",
            subcheck_version="1",
            kind=AggregateSubcheckKind.DESIGN_CHECKS,
        ),
        AggregateSubcheckRequirement(
            subcheck_id="thermometer-simulation",
            subcheck_version="1",
            kind=AggregateSubcheckKind.EXTERNAL_ARTIFACT,
            producer_id=producer_id,
        ),
        AggregateSubcheckRequirement(
            subcheck_id="virtual",
            subcheck_version="1",
            kind=AggregateSubcheckKind.VIRTUAL_DRC,
        ),
    )


def _policy(
    producer_id: str | None = THERMOMETER_NGSPICE_ADAPTER_ID,
    *,
    version: str = "1",
) -> StableAggregateExactCheckerPolicy:
    return StableAggregateExactCheckerPolicy.build(
        policy_id="unit-thermometer-simulation-aggregate",
        policy_version=version,
        profile=DEFAULT_PCB_RULE_PROFILE,
        design_checks_spec=DesignChecksSpec(),
        subchecks=_requirements(producer_id),
    )


def _completed_report(
    raw_output: str,
    circuit: CircuitObject | None = None,
) -> SimulationReport:
    retained_circuit = circuit or _circuit()
    measurements = parse_ngspice_meas_results(raw_output)
    status, findings, evaluated = evaluate_thermometer_measurements(
        measurements, retained_circuit
    )
    return SimulationReport(
        backend="ngspice",
        status=status,  # type: ignore[arg-type]
        command=("ngspice", "-b", "thermometer_led_op.cir"),
        measurements=evaluated,
        findings=findings,
        raw_output_path="thermometer_led_op.log",
    )


def _adapter(
    *,
    raw_output: str = PASS_RAW,
    report: SimulationReport | None = None,
    circuit: CircuitObject | None = None,
    layout: BoardLayout | None = None,
    netlist: BoardNetlist | None = None,
    policy: StableAggregateExactCheckerPolicy | None = None,
) -> ThermometerNgspiceSubcheckEvidence:
    default_layout, default_netlist = _inputs()
    retained_circuit = circuit or _circuit()
    return ThermometerNgspiceSubcheckEvidence.build(
        subcheck_id="thermometer-simulation",
        subcheck_version="1",
        layout=layout or default_layout,
        netlist=netlist or default_netlist,
        policy=policy or _policy(),
        circuit=retained_circuit,
        circuit_artifact_id="circuit:thermometer.json",
        circuit_artifact_sha256="a" * 64,
        raw_output_text=raw_output,
        raw_output_artifact_id="ngspice:thermometer_led_op.log",
        simulation_report=report or _completed_report(raw_output, retained_circuit),
        tool_version="ngspice-46-nonlive-fixture",
        config={"batch": True, "netlist_filename": "thermometer_led_op.cir"},
    )


def _refingerprint(payload: dict[str, object]) -> None:
    value = dict(payload)
    value.pop("evidence_fingerprint", None)
    payload["evidence_fingerprint"] = _fingerprint(value)


def test_exact_pass_replays_in_full_aggregate_without_board_equivalence_claim() -> None:
    layout, netlist = _inputs()
    policy = _policy()
    adapter = _adapter(layout=layout, netlist=netlist, policy=policy)

    assert adapter.status is AggregateCheckStatus.PASS
    assert adapter.parsed_measurements == {
        "i_pwled": 0.00145,
        "i_seg": 0.00537,
        "v_f": 1.85,
    }
    assert adapter.findings == ()
    assert adapter == ThermometerNgspiceSubcheckEvidence.model_validate_json(
        adapter.model_dump_json()
    )

    aggregate = evaluate_stable_aggregate_exact_check(layout, netlist, policy, (adapter,))
    assert aggregate.aggregate_result.accepted
    assert aggregate == StableAggregateExactCheckEvidence.model_validate_json(
        aggregate.model_dump_json()
    )


def test_led_branch_model_scope_and_explicit_exclusions_are_retained() -> None:
    adapter = _adapter()

    assert adapter.model_scope_id == THERMOMETER_LED_BRANCH_MODEL_SCOPE_ID
    assert adapter.model_scope_note == MODEL_NOTE
    assert "LED branch" in adapter.model_scope_note
    assert "MCU/radio" in adapter.model_scope_note
    assert "sensor" in adapter.model_scope_note
    assert "regulator" in adapter.model_scope_note
    assert "NOT SPICE-simulated" in adapter.model_scope_note
    assert adapter.spice_netlist_text == render_thermometer_netlist(_circuit())


@pytest.mark.parametrize(
    "raw_output, expected",
    (
        (
            "i_seg = 30e-3\nv_f = 1.85\ni_pwled = 1.45e-3\n",
            "Segment LED current",
        ),
        ("i_seg = 5.37e-3\nv_f = 2.8\ni_pwled = 1.45e-3\n", "forward voltage"),
        ("i_seg = 5.37e-3\nv_f = 1.85\n", "expected .meas"),
    ),
)
def test_threshold_and_missing_measure_failures_are_replay_derived(
    raw_output: str, expected: str
) -> None:
    adapter = _adapter(raw_output=raw_output)

    assert adapter.status is AggregateCheckStatus.FAIL
    assert any(expected in finding for finding in adapter.simulation_report.findings)
    assert adapter.findings
    aggregate = evaluate_stable_aggregate_exact_check(*_inputs(), _policy(), (adapter,))
    assert not aggregate.aggregate_result.accepted


@pytest.mark.parametrize("status", ("unavailable", "not_run", "warning"))
def test_unavailable_not_run_and_warning_without_results_are_unverified(status: str) -> None:
    report = SimulationReport(
        backend="ngspice",
        status=status,  # type: ignore[arg-type]
        findings=(f"{status} fixture",),
    )
    adapter = _adapter(raw_output="", report=report)

    assert adapter.status is AggregateCheckStatus.UNVERIFIED
    assert adapter.parsed_measurements == {}
    assert adapter.findings


def test_failed_tool_run_without_replayable_results_is_unverified() -> None:
    report = SimulationReport(
        backend="ngspice",
        status="failed",
        command=("ngspice", "-b", "thermometer_led_op.cir"),
        findings=("ngspice process exited before measurements",),
        raw_output_path="thermometer_led_op.log",
    )
    adapter = _adapter(raw_output="fatal error before analysis\n", report=report)

    assert adapter.status is AggregateCheckStatus.UNVERIFIED


def test_measurement_line_order_is_semantic_while_raw_bytes_remain_truthful() -> None:
    first = _adapter()
    reordered = _adapter(raw_output=PASS_RAW_REORDERED)

    assert reordered.status is AggregateCheckStatus.PASS
    assert reordered.parsed_measurements == first.parsed_measurements
    assert reordered.raw_output_text != first.raw_output_text
    assert reordered.raw_output_sha256 != first.raw_output_sha256
    assert reordered.evidence_fingerprint != first.evidence_fingerprint
    assert reordered == _adapter(raw_output=PASS_RAW_REORDERED)


def test_policy_must_explicitly_reserve_simulation_producer() -> None:
    with pytest.raises(ValueError, match="explicit policy producer"):
        _adapter(policy=_policy(None))

    with pytest.raises(ValueError, match="explicit policy producer"):
        _adapter(policy=_policy(READER_NETLIST_EQUALITY_ADAPTER_ID))


def test_generic_evidence_cannot_impersonate_simulation_adapter() -> None:
    layout, netlist = _inputs()
    policy = _policy()
    layout_fp, netlist_fp, policy_fp = external_subcheck_binding(layout, netlist, policy)
    generic = ExternalArtifactSubcheckEvidence.build(
        subcheck_id="thermometer-simulation",
        subcheck_version="1",
        status=AggregateCheckStatus.PASS,
        findings=(),
        layout_snapshot_fingerprint=layout_fp,
        netlist_snapshot_fingerprint=netlist_fp,
        policy_fingerprint=policy_fp,
        source_artifact_id="generic:attempt",
        source_artifact_sha256="b" * 64,
        tool_id="generic",
        tool_version="1",
        config={"attempt": "impersonation"},
        result_identity="generic-result",
    )

    with pytest.raises(ValueError, match="generic external evidence cannot fulfill"):
        evaluate_stable_aggregate_exact_check(layout, netlist, policy, (generic,))


def test_reader_adapter_cannot_impersonate_simulation_adapter() -> None:
    from tests.unit.kicad.test_aggregate_reader_netlist_equality_adapter import (
        _adapter as reader_adapter,
    )
    from tests.unit.kicad.test_aggregate_reader_netlist_equality_adapter import (
        _inputs as reader_inputs,
    )

    layout, netlist = reader_inputs()
    supplied_payload = json.loads(reader_adapter().model_dump_json())
    supplied_payload["subcheck_id"] = "thermometer-simulation"
    _refingerprint(supplied_payload)
    from pcbsmith.kicad.aggregate_exact_checker import (
        ReaderNetlistEqualitySubcheckEvidence,
    )

    supplied = ReaderNetlistEqualitySubcheckEvidence.model_validate(supplied_payload)
    policy = StableAggregateExactCheckerPolicy.build(
        policy_id="thermometer-simulation-target",
        policy_version="1",
        profile=DEFAULT_PCB_RULE_PROFILE,
        design_checks_spec=DesignChecksSpec(),
        subchecks=_requirements(THERMOMETER_NGSPICE_ADAPTER_ID),
    )

    with pytest.raises(ValueError, match="reader-netlist evidence requires"):
        evaluate_stable_aggregate_exact_check(layout, netlist, policy, (supplied,))


def test_save_roundtrip_adapter_cannot_impersonate_simulation_adapter() -> None:
    from tests.unit.kicad.test_aggregate_kicad_roundtrip_adapter import (
        _adapter as roundtrip_adapter,
    )
    from tests.unit.kicad.test_aggregate_kicad_roundtrip_adapter import (
        _board_inputs,
        _roundtrip_authority,
    )
    from tests.unit.kicad.test_aggregate_kicad_roundtrip_adapter import (
        _policy as roundtrip_policy,
    )

    authority = _roundtrip_authority()
    layout, netlist = _board_inputs(authority)
    payload = json.loads(roundtrip_adapter(authority, roundtrip_policy()).model_dump_json())
    payload["subcheck_id"] = "thermometer-simulation"
    _refingerprint(payload)
    from pcbsmith.kicad.aggregate_exact_checker import KiCadSaveRoundtripSubcheckEvidence

    supplied = KiCadSaveRoundtripSubcheckEvidence.model_validate(payload)
    policy = StableAggregateExactCheckerPolicy.build(
        policy_id="thermometer-simulation-target",
        policy_version="1",
        profile=DEFAULT_PCB_RULE_PROFILE,
        design_checks_spec=DesignChecksSpec(),
        subchecks=_requirements(THERMOMETER_NGSPICE_ADAPTER_ID),
    )

    with pytest.raises(ValueError, match="KiCad roundtrip evidence requires"):
        evaluate_stable_aggregate_exact_check(layout, netlist, policy, (supplied,))


def test_duplicate_and_extra_specialized_evidence_are_rejected() -> None:
    adapter = _adapter()
    with pytest.raises(ValueError, match="duplicate external"):
        evaluate_stable_aggregate_exact_check(*_inputs(), _policy(), (adapter, adapter))

    payload = json.loads(adapter.model_dump_json())
    payload["subcheck_id"] = "extra-simulation"
    _refingerprint(payload)
    extra = ThermometerNgspiceSubcheckEvidence.model_validate(payload)
    with pytest.raises(ValueError, match="extra policy-unknown"):
        evaluate_stable_aggregate_exact_check(*_inputs(), _policy(), (extra,))


@pytest.mark.parametrize(
    "field, replacement, expected",
    (
        ("circuit_artifact_sha256", "0" * 64, "evidence fingerprint"),
        ("circuit_snapshot_sha256", "0" * 64, "snapshot checksum"),
        ("spice_netlist_sha256", "0" * 64, "netlist checksum"),
        ("raw_output_sha256", "0" * 64, "output checksum"),
        ("raw_output_artifact_sha256", "0" * 64, "artifact checksum"),
        ("tool_version", "ngspice-47-tampered", "evidence fingerprint"),
        ("config_json", '{"batch":false}', "config checksum"),
        ("config_sha256", "0" * 64, "config checksum"),
        ("layout_snapshot_fingerprint", "0" * 64, "evidence fingerprint"),
        ("policy_fingerprint", "0" * 64, "evidence fingerprint"),
        ("producer_id", READER_NETLIST_EQUALITY_ADAPTER_ID, "literal_error"),
        ("supported_topology_id", "other", "literal_error"),
        ("model_scope_id", "other", "literal_error"),
        ("model_scope_note", "all subsystems simulated", "model-scope note"),
        ("evidence_fingerprint", "0" * 64, "evidence fingerprint"),
    ),
)
def test_identity_context_hash_topology_scope_tool_and_config_tampering_is_rejected(
    field: str, replacement: object, expected: str
) -> None:
    payload = json.loads(_adapter().model_dump_json())
    payload[field] = replacement

    with pytest.raises(ValidationError) as caught:
        ThermometerNgspiceSubcheckEvidence.model_validate(payload)
    assert expected in str(caught.value)


def test_replay_rejects_circuit_netlist_raw_report_and_result_tampering() -> None:
    base = json.loads(_adapter().model_dump_json())

    circuit = deepcopy(base)
    circuit["circuit_snapshot_json"] = circuit["circuit_snapshot_json"].replace(
        '"topology_id":"thermometer_env_display"', '"topology_id":"other"', 1
    )
    circuit["circuit_snapshot_sha256"] = _sha256(circuit["circuit_snapshot_json"])
    _refingerprint(circuit)
    with pytest.raises(ValidationError, match="unsupported topology"):
        ThermometerNgspiceSubcheckEvidence.model_validate(circuit)

    netlist = deepcopy(base)
    netlist["spice_netlist_text"] += "* invented\n"
    netlist["spice_netlist_sha256"] = _sha256(netlist["spice_netlist_text"])
    _refingerprint(netlist)
    with pytest.raises(ValidationError, match="differs from circuit replay"):
        ThermometerNgspiceSubcheckEvidence.model_validate(netlist)

    raw = deepcopy(base)
    raw["raw_output_text"] = raw["raw_output_text"].replace("5.37e-3", "30e-3")
    raw_hash = _sha256(raw["raw_output_text"])
    raw["raw_output_sha256"] = raw_hash
    raw["raw_output_artifact_sha256"] = raw_hash
    _refingerprint(raw)
    with pytest.raises(ValidationError, match="measurements differ"):
        ThermometerNgspiceSubcheckEvidence.model_validate(raw)

    report = deepcopy(base)
    report["simulation_report"]["status"] = "failed"
    _refingerprint(report)
    with pytest.raises(ValidationError, match="status or findings differ"):
        ThermometerNgspiceSubcheckEvidence.model_validate(report)

    report_measurements = deepcopy(base)
    report_measurements["simulation_report"]["measurements"]["i_seg"] = 0.03
    _refingerprint(report_measurements)
    with pytest.raises(ValidationError, match="report measurements differ"):
        ThermometerNgspiceSubcheckEvidence.model_validate(report_measurements)

    measurements = deepcopy(base)
    measurements["parsed_measurements"]["i_seg"] = 0.03
    _refingerprint(measurements)
    with pytest.raises(ValidationError, match="parsed measurements differ"):
        ThermometerNgspiceSubcheckEvidence.model_validate(measurements)

    status = deepcopy(base)
    status["status"] = "fail"
    _refingerprint(status)
    with pytest.raises(ValidationError, match="status or findings differ"):
        ThermometerNgspiceSubcheckEvidence.model_validate(status)

    finding = deepcopy(base)
    finding["findings"] = [
        {
            "finding_id": "invented",
            "message": "invented",
            "finding_fingerprint": _fingerprint(
                {"finding_id": "invented", "message": "invented"}
            ),
        }
    ]
    _refingerprint(finding)
    with pytest.raises(ValidationError, match="status or findings differ"):
        ThermometerNgspiceSubcheckEvidence.model_validate(finding)


def test_stale_aggregate_and_policy_bindings_reject_after_self_consistent_refingerprint() -> None:
    adapter_payload = json.loads(_adapter().model_dump_json())
    adapter_payload["layout_snapshot_fingerprint"] = "0" * 64
    _refingerprint(adapter_payload)
    stale_layout = ThermometerNgspiceSubcheckEvidence.model_validate(adapter_payload)
    with pytest.raises(ValueError, match="stale aggregate inputs"):
        evaluate_stable_aggregate_exact_check(*_inputs(), _policy(), (stale_layout,))

    policy_payload = json.loads(_adapter().model_dump_json())
    policy_payload["policy_fingerprint"] = "0" * 64
    _refingerprint(policy_payload)
    stale_policy = ThermometerNgspiceSubcheckEvidence.model_validate(policy_payload)
    with pytest.raises(ValueError, match="stale aggregate inputs"):
        evaluate_stable_aggregate_exact_check(*_inputs(), _policy(), (stale_policy,))


def test_aggregate_json_replay_rejects_nested_raw_tampering() -> None:
    aggregate = evaluate_stable_aggregate_exact_check(*_inputs(), _policy(), (_adapter(),))
    payload = json.loads(aggregate.model_dump_json())
    specialized = next(
        item
        for item in payload["subchecks"]
        if item["evidence_kind"] == "thermometer_ngspice"
    )
    specialized["raw_output_sha256"] = "0" * 64
    _refingerprint(specialized)
    outer = dict(payload)
    outer.pop("evidence_fingerprint")
    payload["evidence_fingerprint"] = _fingerprint(outer)

    with pytest.raises(ValidationError, match="output checksum"):
        StableAggregateExactCheckEvidence.model_validate(payload)
