from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pytest
from pydantic import ValidationError

from pcbsmith.circuit.models import KiCadReport
from pcbsmith.kicad.aggregate_exact_checker import (
    KICAD_SAVE_ROUNDTRIP_ADAPTER_ID,
    READER_NETLIST_EQUALITY_ADAPTER_ID,
    AggregateCheckStatus,
    AggregateSubcheckKind,
    AggregateSubcheckRequirement,
    ExternalArtifactSubcheckEvidence,
    KiCadSaveRoundtripSubcheckEvidence,
    ReaderNetlistEqualitySubcheckEvidence,
    StableAggregateExactCheckerPolicy,
    StableAggregateExactCheckEvidence,
    evaluate_stable_aggregate_exact_check,
    external_subcheck_binding,
)
from pcbsmith.kicad.board import (
    BoardLayout,
    BoardNetlist,
    canonical_kicad_netlist_xml_text,
    parse_board_netlist,
)
from pcbsmith.kicad.design_checks import DesignChecksSpec
from pcbsmith.kicad.validate import canonical_kicad_erc_json_text
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

MACHINE_XML = """<export>
  <components>
    <comp ref="R1">
      <value>10k</value><footprint>Resistor_SMD:R_0603_1608Metric</footprint>
      <tstamps>uuid-r1</tstamps>
    </comp>
    <comp ref="R2">
      <value>20k</value><footprint>Resistor_SMD:R_0603_1608Metric</footprint>
      <tstamps>uuid-r2</tstamps>
    </comp>
  </components>
  <nets><net name="/SIG"><node ref="R1" pin="1"/></net></nets>
</export>"""

REORDERED_EQUIVALENT_XML = """<export>
  <components>
    <comp ref="R2">
      <value>20k</value><footprint>Resistor_SMD:R_0603_1608Metric</footprint>
      <tstamps>different-reader-r2</tstamps>
    </comp>
    <comp ref="R1">
      <value>10k</value><footprint>Resistor_SMD:R_0603_1608Metric</footprint>
      <tstamps>different-reader-r1</tstamps>
    </comp>
  </components>
  <nets><net name="/SIG"><node ref="R1" pin="1"/></net></nets>
</export>"""


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


def _inputs() -> tuple[BoardLayout, BoardNetlist]:
    netlist = parse_board_netlist(MACHINE_XML)
    layout = BoardLayout(
        placements=((netlist.components[0], 10.0), (netlist.components[1], 30.0)),
        segments=(),
        vias=(),
        width_mm=40.0,
        height_mm=30.0,
        part_y_mm=(("R1", 15.0), ("R2", 15.0)),
    )
    return layout, netlist


def _requirements(
    producer_id: str | None = READER_NETLIST_EQUALITY_ADAPTER_ID,
) -> tuple[AggregateSubcheckRequirement, ...]:
    return (
        AggregateSubcheckRequirement(
            subcheck_id="design",
            subcheck_version="1",
            kind=AggregateSubcheckKind.DESIGN_CHECKS,
        ),
        AggregateSubcheckRequirement(
            subcheck_id="reader-equality",
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
    producer_id: str | None = READER_NETLIST_EQUALITY_ADAPTER_ID,
    *,
    version: str = "1",
) -> StableAggregateExactCheckerPolicy:
    return StableAggregateExactCheckerPolicy.build(
        policy_id="unit-reader-netlist-aggregate",
        policy_version=version,
        profile=DEFAULT_PCB_RULE_PROFILE,
        design_checks_spec=DesignChecksSpec(),
        subchecks=_requirements(producer_id),
    )


def _report(
    status: str = "passed", findings: tuple[str, ...] = ()
) -> KiCadReport:
    return KiCadReport(
        status=status,  # type: ignore[arg-type]
        command=("kicad-cli", "sch", "erc"),
        schematic_file="fixture.kicad_sch",
        erc_report="fixture-erc.json",
        findings=findings,
    )


def _erc_json(report: KiCadReport) -> str:
    violations = []
    for finding in report.findings:
        severity, separator, description = finding.partition(": ")
        if not separator:
            severity, description = "error", finding
        violations.append({"severity": severity, "description": description})
    return canonical_kicad_erc_json_text(
        json.dumps({"date": "volatile", "sheets": [{"violations": violations}]})
    )


def _adapter(
    *,
    reader_xml: str = MACHINE_XML,
    machine_report: KiCadReport | None = None,
    reader_report: KiCadReport | None = None,
    layout: BoardLayout | None = None,
    netlist: BoardNetlist | None = None,
    policy: StableAggregateExactCheckerPolicy | None = None,
) -> ReaderNetlistEqualitySubcheckEvidence:
    default_layout, default_netlist = _inputs()
    retained_machine_report = machine_report or _report()
    retained_reader_report = reader_report or _report()
    machine_schematic_text = "fixture machine schematic artifact\n"
    reader_schematic_text = "fixture reader schematic artifact\n"
    return ReaderNetlistEqualitySubcheckEvidence.build(
        subcheck_id="reader-equality",
        subcheck_version="1",
        layout=layout or default_layout,
        netlist=netlist or default_netlist,
        policy=policy or _policy(),
        machine_schematic_artifact_id="machine:fixture.kicad_sch",
        machine_schematic_text=machine_schematic_text,
        machine_schematic_artifact_sha256=_sha256(machine_schematic_text),
        reader_schematic_artifact_id="reader:fixture.kicad_sch",
        reader_schematic_text=reader_schematic_text,
        reader_schematic_artifact_sha256=_sha256(reader_schematic_text),
        machine_netlist_xml_text=canonical_kicad_netlist_xml_text(MACHINE_XML),
        reader_netlist_xml_text=canonical_kicad_netlist_xml_text(reader_xml),
        tool_id="kicad-cli",
        tool_version="10.0-nonlive-fixture",
        config_identity="reader-equality-config-v1",
        config={"erc_exit_code_gate": True, "netlist_format": "xml"},
        machine_erc_report_json=_erc_json(retained_machine_report),
        reader_erc_report_json=_erc_json(retained_reader_report),
        machine_erc_report=retained_machine_report,
        reader_erc_report=retained_reader_report,
    )


def _refingerprint(payload: dict[str, object]) -> None:
    value = dict(payload)
    value.pop("evidence_fingerprint", None)
    payload["evidence_fingerprint"] = _fingerprint(value)


def test_exact_pass_replays_inside_full_aggregate() -> None:
    layout, netlist = _inputs()
    policy = _policy()
    adapter = _adapter(layout=layout, netlist=netlist, policy=policy)

    assert adapter.status is AggregateCheckStatus.PASS
    assert adapter.comparison_findings == ()
    assert adapter.findings == ()
    assert adapter == ReaderNetlistEqualitySubcheckEvidence.model_validate_json(
        adapter.model_dump_json()
    )

    aggregate = evaluate_stable_aggregate_exact_check(layout, netlist, policy, (adapter,))
    assert aggregate.aggregate_result.accepted
    assert aggregate == StableAggregateExactCheckEvidence.model_validate_json(
        aggregate.model_dump_json()
    )


def test_equivalent_reader_xml_order_is_semantic_not_byte_equivalence() -> None:
    first = _adapter()
    reordered = _adapter(reader_xml=REORDERED_EQUIVALENT_XML)

    assert reordered.status is AggregateCheckStatus.PASS
    assert reordered.comparison_findings == ()
    assert reordered.reader_netlist_xml_text != first.reader_netlist_xml_text
    assert reordered.reader_netlist_xml_sha256 != first.reader_netlist_xml_sha256
    assert (
        reordered.reader_netlist_snapshot_json
        != reordered.machine_netlist_snapshot_json
    )
    assert reordered.evidence_fingerprint != first.evidence_fingerprint


def test_netlist_xml_canonicalization_removes_only_volatile_host_context() -> None:
    first = MACHINE_XML.replace(
        "<export>",
        '<export><design><source>C:\\one\\fixture.kicad_sch</source>'
        "<date>2026-01-01T00:00:00</date></design>",
    ).replace(
        "<value>10k</value>",
        '<value>10k</value><property name="Sheetfile" value="C:\\one\\fixture.kicad_sch"/>',
    )
    second = first.replace("C:\\one", "D:\\two").replace(
        "2026-01-01T00:00:00", "2027-02-02T03:04:05"
    )

    canonical = canonical_kicad_netlist_xml_text(first)
    assert canonical == canonical_kicad_netlist_xml_text(second)
    assert "fixture.kicad_sch" in canonical
    assert "<date>" not in canonical
    assert parse_board_netlist(canonical) == parse_board_netlist(MACHINE_XML)


@pytest.mark.parametrize(
    "reader_xml, expected_text",
    (
        (MACHINE_XML.replace('ref="R2"', 'ref="R3"'), "R2"),
        (MACHINE_XML.replace("<value>10k</value>", "<value>11k</value>"), "R1 differs"),
        (
            MACHINE_XML.replace(
                "Resistor_SMD:R_0603_1608Metric",
                "Capacitor_SMD:C_0603_1608Metric",
                1,
            ),
            "R1 differs",
        ),
        (MACHINE_XML.replace('ref="R1" pin="1"', 'ref="R1" pin="2"'), "Net /SIG"),
    ),
)
def test_component_value_footprint_and_net_node_mismatches_fail(
    reader_xml: str, expected_text: str
) -> None:
    adapter = _adapter(reader_xml=reader_xml)

    assert adapter.status is AggregateCheckStatus.FAIL
    assert any(expected_text in finding for finding in adapter.comparison_findings)
    assert adapter.findings


@pytest.mark.parametrize("side", ("machine", "reader"))
def test_explicit_erc_failure_and_passed_report_findings_fail(side: str) -> None:
    for report in (
        _report("failed", ("error: blocking ERC finding",)),
        _report("passed", ("error: blocking ERC finding",)),
    ):
        if report.status == "passed":
            with pytest.raises(ValueError, match="status or findings differ"):
                _adapter(
                    machine_report=report if side == "machine" else _report(),
                    reader_report=report if side == "reader" else _report(),
                )
            continue
        adapter = _adapter(
            machine_report=report if side == "machine" else _report(),
            reader_report=report if side == "reader" else _report(),
        )
        assert adapter.status is AggregateCheckStatus.FAIL
        assert any(finding.finding_id.startswith(side) for finding in adapter.findings)


@pytest.mark.parametrize(
    "status", ("unavailable", "not_run", "needs_human_review", "warning")
)
def test_unavailable_pending_human_or_warning_erc_cannot_authorize(status: str) -> None:
    with pytest.raises(ValueError, match="status or findings differ"):
        _adapter(reader_report=_report(status, (f"error: {status} detail",)))


def test_pass_status_is_replayed_from_retained_erc_json_without_paths() -> None:
    adapter = _adapter(reader_report=KiCadReport(status="passed"))

    assert adapter.status is AggregateCheckStatus.PASS
    assert adapter.reader_erc_report == KiCadReport(status="passed")


def test_machine_parsed_netlist_must_equal_exact_aggregate_netlist() -> None:
    layout, netlist = _inputs()
    wrong = replace(netlist, nets=())

    with pytest.raises(ValueError, match="machine parsed netlist differs"):
        _adapter(layout=layout, netlist=wrong)

    adapter = _adapter()
    with pytest.raises(ValueError, match="stale aggregate inputs|differs from aggregate"):
        evaluate_stable_aggregate_exact_check(layout, wrong, _policy(), (adapter,))


def test_policy_must_explicitly_reserve_reader_producer() -> None:
    with pytest.raises(ValueError, match="explicit policy producer"):
        _adapter(policy=_policy(None))

    with pytest.raises(ValueError, match="explicit policy producer"):
        _adapter(policy=_policy(KICAD_SAVE_ROUNDTRIP_ADAPTER_ID))


def test_generic_evidence_cannot_impersonate_reader_adapter() -> None:
    layout, netlist = _inputs()
    policy = _policy()
    layout_fp, netlist_fp, policy_fp = external_subcheck_binding(layout, netlist, policy)
    generic = ExternalArtifactSubcheckEvidence.build(
        subcheck_id="reader-equality",
        subcheck_version="1",
        status=AggregateCheckStatus.PASS,
        findings=(),
        layout_snapshot_fingerprint=layout_fp,
        netlist_snapshot_fingerprint=netlist_fp,
        policy_fingerprint=policy_fp,
        source_artifact_id="generic:attempt",
        source_artifact_sha256="c" * 64,
        tool_id="generic",
        tool_version="1",
        config={"attempt": "impersonation"},
        result_identity="generic-result",
    )

    with pytest.raises(ValueError, match="generic external evidence cannot fulfill"):
        evaluate_stable_aggregate_exact_check(layout, netlist, policy, (generic,))


def test_roundtrip_adapter_cannot_impersonate_reader_adapter() -> None:
    from tests.unit.kicad.test_aggregate_kicad_roundtrip_adapter import (
        _board_inputs,
        _roundtrip_authority,
    )

    authority = _roundtrip_authority()
    layout, netlist = _board_inputs(authority)
    roundtrip_policy = StableAggregateExactCheckerPolicy.build(
        policy_id="roundtrip-source",
        policy_version="1",
        profile=DEFAULT_PCB_RULE_PROFILE,
        design_checks_spec=DesignChecksSpec(),
        subchecks=_requirements(KICAD_SAVE_ROUNDTRIP_ADAPTER_ID),
    )
    roundtrip = KiCadSaveRoundtripSubcheckEvidence.build(
        subcheck_id="reader-equality",
        subcheck_version="1",
        layout=layout,
        netlist=netlist,
        policy=roundtrip_policy,
        roundtrip_authority=authority,
    )
    reader_policy = StableAggregateExactCheckerPolicy.build(
        policy_id="reader-target",
        policy_version="1",
        profile=DEFAULT_PCB_RULE_PROFILE,
        design_checks_spec=DesignChecksSpec(),
        subchecks=_requirements(READER_NETLIST_EQUALITY_ADAPTER_ID),
    )

    with pytest.raises(ValueError, match="KiCad roundtrip evidence requires"):
        evaluate_stable_aggregate_exact_check(layout, netlist, reader_policy, (roundtrip,))


def test_duplicate_specialized_evidence_is_rejected() -> None:
    adapter = _adapter()

    with pytest.raises(ValueError, match="duplicate external"):
        evaluate_stable_aggregate_exact_check(*_inputs(), _policy(), (adapter, adapter))


@pytest.mark.parametrize(
    "field, replacement, expected",
    (
        ("machine_netlist_xml_sha256", "0" * 64, "XML checksum"),
        ("reader_schematic_artifact_sha256", "0" * 64, "schematic artifact checksum"),
        ("tool_version", "10.1-tampered", "evidence fingerprint"),
        ("config_identity", "tampered-config", "evidence fingerprint"),
        ("config_sha256", "0" * 64, "config checksum"),
        ("layout_snapshot_fingerprint", "0" * 64, "evidence fingerprint"),
        ("policy_fingerprint", "0" * 64, "evidence fingerprint"),
        ("producer_id", KICAD_SAVE_ROUNDTRIP_ADAPTER_ID, "literal_error"),
    ),
)
def test_identity_hash_context_tool_config_and_producer_tampering_is_rejected(
    field: str, replacement: object, expected: str
) -> None:
    payload = json.loads(_adapter().model_dump_json())
    payload[field] = replacement

    with pytest.raises(ValidationError) as caught:
        ReaderNetlistEqualitySubcheckEvidence.model_validate(payload)
    assert expected in str(caught.value)


def test_parser_snapshot_erc_and_derived_result_tampering_rejects_even_if_refingerprinted() -> None:
    base = json.loads(_adapter(reader_xml=REORDERED_EQUIVALENT_XML).model_dump_json())

    snapshot = deepcopy(base)
    snapshot["reader_netlist_snapshot_json"] = snapshot["machine_netlist_snapshot_json"]
    snapshot["reader_netlist_snapshot_fingerprint"] = snapshot[
        "machine_netlist_snapshot_fingerprint"
    ]
    _refingerprint(snapshot)
    with pytest.raises(ValidationError, match="reader netlist XML differs"):
        ReaderNetlistEqualitySubcheckEvidence.model_validate(snapshot)

    erc = deepcopy(base)
    erc["machine_erc_report"]["status"] = "failed"
    _refingerprint(erc)
    with pytest.raises(ValidationError, match="status or findings differ"):
        ReaderNetlistEqualitySubcheckEvidence.model_validate(erc)

    schematic = deepcopy(base)
    schematic["machine_schematic_text"] += "tampered"
    _refingerprint(schematic)
    with pytest.raises(ValidationError, match="schematic artifact checksum"):
        ReaderNetlistEqualitySubcheckEvidence.model_validate(schematic)

    erc_json = deepcopy(base)
    erc_json["machine_erc_report_json"] = canonical_kicad_erc_json_text(
        json.dumps(
            {
                "sheets": [
                    {
                        "violations": [
                            {"severity": "error", "description": "invented pass"}
                        ]
                    }
                ]
            }
        )
    )
    erc_json["machine_erc_report_sha256"] = _sha256(
        erc_json["machine_erc_report_json"]
    )
    _refingerprint(erc_json)
    with pytest.raises(ValidationError, match="status or findings differ"):
        ReaderNetlistEqualitySubcheckEvidence.model_validate(erc_json)

    status = deepcopy(base)
    status["status"] = "fail"
    _refingerprint(status)
    with pytest.raises(ValidationError, match="status or findings differ"):
        ReaderNetlistEqualitySubcheckEvidence.model_validate(status)

    comparison = deepcopy(base)
    comparison["comparison_findings"] = ["invented finding"]
    _refingerprint(comparison)
    with pytest.raises(ValidationError, match="comparison findings differ"):
        ReaderNetlistEqualitySubcheckEvidence.model_validate(comparison)

    messages = deepcopy(base)
    messages["findings"] = [
        {
            "finding_id": "invented",
            "message": "invented",
            "finding_fingerprint": _fingerprint(
                {"finding_id": "invented", "message": "invented"}
            ),
        }
    ]
    _refingerprint(messages)
    with pytest.raises(ValidationError, match="status or findings differ"):
        ReaderNetlistEqualitySubcheckEvidence.model_validate(messages)


def test_aggregate_json_replay_rejects_nested_specialized_tampering() -> None:
    aggregate = evaluate_stable_aggregate_exact_check(*_inputs(), _policy(), (_adapter(),))
    payload = json.loads(aggregate.model_dump_json())
    specialized = next(
        item
        for item in payload["subchecks"]
        if item["evidence_kind"] == "reader_netlist_equality"
    )
    specialized["reader_netlist_xml_sha256"] = "0" * 64
    _refingerprint(specialized)
    outer = dict(payload)
    outer.pop("evidence_fingerprint")
    payload["evidence_fingerprint"] = _fingerprint(outer)

    with pytest.raises(ValidationError, match="XML checksum"):
        StableAggregateExactCheckEvidence.model_validate(payload)
