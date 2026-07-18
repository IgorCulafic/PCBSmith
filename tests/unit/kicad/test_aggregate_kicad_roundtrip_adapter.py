from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import replace

import pytest
from pydantic import ValidationError
from tests.unit.kicad.test_placement_readback import _clean_shaped_authority

from pcbsmith.kicad.aggregate_exact_checker import (
    KICAD_SAVE_ROUNDTRIP_ADAPTER_ID,
    AggregateCheckStatus,
    AggregateSubcheckKind,
    AggregateSubcheckRequirement,
    ExternalArtifactSubcheckEvidence,
    KiCadSaveRoundtripSubcheckEvidence,
    StableAggregateExactCheckerPolicy,
    StableAggregateExactCheckEvidence,
    evaluate_stable_aggregate_exact_check,
    external_subcheck_binding,
)
from pcbsmith.kicad.board import BoardLayout, BoardNet, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.kicad.design_checks import DesignChecksSpec
from pcbsmith.kicad.placement_readback import (
    PlacementKiCadSaveRoundtripAuthority,
    extract_kicad_board_readback,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_fingerprint(value: object) -> str:
    text = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return _sha256(text)


def _roundtrip_authority() -> PlacementKiCadSaveRoundtripAuthority:
    serialization = _clean_shaped_authority()
    text = serialization.rendered_board_text
    snapshot = extract_kicad_board_readback(text)
    report = json.dumps(
        {"schematic_parity": [], "unconnected_items": [], "violations": []},
        sort_keys=True,
        separators=(",", ":"),
    )
    return PlacementKiCadSaveRoundtripAuthority(
        serialization_authority=serialization,
        kicad_cli_version="10.0-nonlive-fixture",
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


def _board_inputs(
    authority: PlacementKiCadSaveRoundtripAuthority,
) -> tuple[BoardLayout, BoardNetlist]:
    serialization = authority.serialization_authority
    return (
        parse_canonical_board_layout_snapshot(serialization.final_layout_snapshot_json),
        parse_canonical_board_netlist_snapshot(serialization.source_netlist_snapshot_json),
    )


def _requirements(
    *,
    producer_id: str | None = KICAD_SAVE_ROUNDTRIP_ADAPTER_ID,
    include_generic: bool = False,
) -> tuple[AggregateSubcheckRequirement, ...]:
    generic = (
        AggregateSubcheckRequirement(
            subcheck_id="reader",
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
        AggregateSubcheckRequirement(
            subcheck_id="kicad-roundtrip",
            subcheck_version="1",
            kind=AggregateSubcheckKind.EXTERNAL_ARTIFACT,
            producer_id=producer_id,
        ),
        *generic,
        AggregateSubcheckRequirement(
            subcheck_id="virtual",
            subcheck_version="1",
            kind=AggregateSubcheckKind.VIRTUAL_DRC,
        ),
    )


def _policy(
    *,
    producer_id: str | None = KICAD_SAVE_ROUNDTRIP_ADAPTER_ID,
    include_generic: bool = False,
    policy_version: str = "1",
) -> StableAggregateExactCheckerPolicy:
    return StableAggregateExactCheckerPolicy.build(
        policy_id="unit-kicad-roundtrip-aggregate",
        policy_version=policy_version,
        profile=DEFAULT_PCB_RULE_PROFILE,
        design_checks_spec=DesignChecksSpec(),
        subchecks=_requirements(producer_id=producer_id, include_generic=include_generic),
    )


def _adapter(
    authority: PlacementKiCadSaveRoundtripAuthority,
    policy: StableAggregateExactCheckerPolicy,
) -> KiCadSaveRoundtripSubcheckEvidence:
    layout, netlist = _board_inputs(authority)
    return KiCadSaveRoundtripSubcheckEvidence.build(
        subcheck_id="kicad-roundtrip",
        subcheck_version="1",
        layout=layout,
        netlist=netlist,
        policy=policy,
        roundtrip_authority=authority,
    )


def _generic(
    layout: BoardLayout,
    netlist: BoardNetlist,
    policy: StableAggregateExactCheckerPolicy,
    subcheck_id: str,
) -> ExternalArtifactSubcheckEvidence:
    layout_fp, netlist_fp, policy_fp = external_subcheck_binding(layout, netlist, policy)
    return ExternalArtifactSubcheckEvidence.build(
        subcheck_id=subcheck_id,
        subcheck_version="1",
        status=AggregateCheckStatus.PASS,
        findings=(),
        layout_snapshot_fingerprint=layout_fp,
        netlist_snapshot_fingerprint=netlist_fp,
        policy_fingerprint=policy_fp,
        source_artifact_id=f"artifact:{subcheck_id}",
        source_artifact_sha256="a" * 64,
        tool_id="unit-generic-external",
        tool_version="1",
        config={"fixture": subcheck_id},
        result_identity=f"result:{subcheck_id}",
    )


def _refingerprint_adapter_payload(payload: dict[str, object]) -> None:
    fingerprint_payload = dict(payload)
    fingerprint_payload.pop("evidence_fingerprint", None)
    payload["evidence_fingerprint"] = _canonical_fingerprint(fingerprint_payload)


def _refingerprint_aggregate_payload(payload: dict[str, object]) -> None:
    fingerprint_payload = dict(payload)
    fingerprint_payload.pop("evidence_fingerprint", None)
    payload["evidence_fingerprint"] = _canonical_fingerprint(fingerprint_payload)


def _specialized_payload(payload: dict[str, object]) -> dict[str, object]:
    subchecks = payload["subchecks"]
    assert isinstance(subchecks, list)
    specialized = next(
        item
        for item in subchecks
        if isinstance(item, dict) and item.get("evidence_kind") == "kicad_save_roundtrip"
    )
    return specialized


def test_clean_roundtrip_adapter_passes_and_full_aggregate_replays() -> None:
    authority = _roundtrip_authority()
    layout, netlist = _board_inputs(authority)
    policy = _policy()
    adapter = _adapter(authority, policy)

    assert adapter.status is AggregateCheckStatus.PASS
    assert adapter.findings == ()
    assert adapter == KiCadSaveRoundtripSubcheckEvidence.model_validate_json(
        adapter.model_dump_json()
    )

    aggregate = evaluate_stable_aggregate_exact_check(layout, netlist, policy, (adapter,))

    assert aggregate.aggregate_result.accepted
    assert aggregate == StableAggregateExactCheckEvidence.model_validate_json(
        aggregate.model_dump_json()
    )


def test_failed_drc_and_disabled_required_gate_derive_blocking_statuses() -> None:
    clean = _roundtrip_authority()
    failed_payload = clean.model_dump(mode="json")
    failed_payload["require_drc_pass"] = False
    failed_payload["drc_status"] = "failed"
    failed_payload["drc_findings"] = ["clearance violation", "unconnected item"]
    failed = PlacementKiCadSaveRoundtripAuthority.model_validate(failed_payload)

    failed_adapter = _adapter(failed, _policy())

    assert failed_adapter.status is AggregateCheckStatus.FAIL
    assert {item.finding_id for item in failed_adapter.findings} == {
        "kicad-drc-findings",
        "kicad-drc-status",
    }

    disabled_payload = clean.model_dump(mode="json")
    disabled_payload["require_drc_pass"] = False
    disabled = PlacementKiCadSaveRoundtripAuthority.model_validate(disabled_payload)
    disabled_adapter = _adapter(disabled, _policy())

    assert disabled_adapter.status is AggregateCheckStatus.UNVERIFIED
    assert tuple(item.finding_id for item in disabled_adapter.findings) == (
        "kicad-required-gate-disabled",
    )


def test_wrong_aggregate_layout_netlist_and_policy_are_rejected() -> None:
    authority = _roundtrip_authority()
    layout, netlist = _board_inputs(authority)
    policy = _policy()
    adapter = _adapter(authority, policy)

    wrong_layout = replace(layout, width_mm=layout.width_mm + 1.0)
    with pytest.raises(ValueError, match="final layout differs"):
        evaluate_stable_aggregate_exact_check(wrong_layout, netlist, policy, (adapter,))

    wrong_netlist = BoardNetlist(
        components=netlist.components,
        nets=(*netlist.nets, BoardNet(name="/EXTRA", nodes=())),
    )
    with pytest.raises(ValueError, match="netlist differs"):
        evaluate_stable_aggregate_exact_check(layout, wrong_netlist, policy, (adapter,))

    changed_policy = _policy(policy_version="2")
    with pytest.raises(ValueError, match="stale aggregate inputs or policy"):
        evaluate_stable_aggregate_exact_check(layout, netlist, changed_policy, (adapter,))


def test_generic_and_specialized_evidence_cannot_impersonate_each_other() -> None:
    authority = _roundtrip_authority()
    layout, netlist = _board_inputs(authority)
    specialized_policy = _policy()
    generic = _generic(layout, netlist, specialized_policy, "kicad-roundtrip")

    with pytest.raises(ValueError, match="generic external evidence cannot fulfill"):
        evaluate_stable_aggregate_exact_check(
            layout,
            netlist,
            specialized_policy,
            (generic,),
        )

    generic_policy = _policy(producer_id=None)
    specialized = _adapter(authority, generic_policy)
    with pytest.raises(ValueError, match="explicit policy producer identity"):
        evaluate_stable_aggregate_exact_check(
            layout,
            netlist,
            generic_policy,
            (specialized,),
        )

    in_process_replacement = specialized.model_copy(
        update={"subcheck_id": "virtual"}
    )
    in_process_payload = in_process_replacement.model_dump(mode="json")
    _refingerprint_adapter_payload(in_process_payload)
    in_process_replacement = KiCadSaveRoundtripSubcheckEvidence.model_validate(
        in_process_payload
    )
    with pytest.raises(ValueError, match="replace an in-process"):
        evaluate_stable_aggregate_exact_check(
            layout,
            netlist,
            generic_policy,
            (in_process_replacement,),
        )


def test_adapter_and_aggregate_are_deterministic_under_supplied_input_reversal() -> None:
    authority = _roundtrip_authority()
    layout, netlist = _board_inputs(authority)
    policy = _policy(include_generic=True)
    adapter = _adapter(authority, policy)
    reader = _generic(layout, netlist, policy, "reader")

    first = evaluate_stable_aggregate_exact_check(layout, netlist, policy, (adapter, reader))
    reversed_input = evaluate_stable_aggregate_exact_check(
        layout,
        netlist,
        policy,
        (reader, adapter),
    )

    assert first == reversed_input
    assert first.aggregate_result.accepted


@pytest.mark.parametrize("field_name", ["status", "findings", "producer_id"])
def test_status_findings_and_adapter_identity_tamper_reject(field_name: str) -> None:
    adapter = _adapter(_roundtrip_authority(), _policy())
    payload = adapter.model_dump(mode="json")
    if field_name == "status":
        payload["status"] = "fail"
    elif field_name == "findings":
        payload["findings"] = [
            {
                "finding_id": "forged",
                "message": "forged adapter finding",
                "finding_fingerprint": _canonical_fingerprint(
                    {"finding_id": "forged", "message": "forged adapter finding"}
                ),
            }
        ]
    else:
        payload["producer_id"] = "forged-adapter"
    _refingerprint_adapter_payload(payload)

    with pytest.raises(ValidationError):
        KiCadSaveRoundtripSubcheckEvidence.model_validate(payload)


def test_roundtrip_and_adapter_fingerprint_tamper_reject() -> None:
    adapter = _adapter(_roundtrip_authority(), _policy())
    payload = adapter.model_dump(mode="json")
    authority_payload = payload["roundtrip_authority"]
    assert isinstance(authority_payload, dict)
    authority_payload["require_drc_pass"] = False
    _refingerprint_adapter_payload(payload)

    with pytest.raises(ValidationError, match="status or findings differ from replay"):
        KiCadSaveRoundtripSubcheckEvidence.model_validate(payload)

    fingerprint_payload = adapter.model_dump(mode="json")
    fingerprint_payload["evidence_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError, match="fingerprint is stale"):
        KiCadSaveRoundtripSubcheckEvidence.model_validate(fingerprint_payload)


def test_full_aggregate_json_replay_rejects_every_adapter_binding_tamper() -> None:
    authority = _roundtrip_authority()
    layout, netlist = _board_inputs(authority)
    policy = _policy()
    adapter = _adapter(authority, policy)
    aggregate = evaluate_stable_aggregate_exact_check(layout, netlist, policy, (adapter,))
    original = aggregate.model_dump(mode="json")

    board_payload = deepcopy(original)
    changed_layout = replace(layout, width_mm=layout.width_mm + 1.0)
    changed_layout_json = canonical_board_layout_snapshot_json(changed_layout)
    board_payload["layout_snapshot_json"] = changed_layout_json
    board_payload["layout_snapshot_fingerprint"] = board_layout_snapshot_fingerprint(
        changed_layout_json
    )
    _refingerprint_aggregate_payload(board_payload)
    with pytest.raises(ValidationError, match="final layout differs"):
        StableAggregateExactCheckEvidence.model_validate(board_payload)

    netlist_payload = deepcopy(original)
    changed_netlist = BoardNetlist(
        components=netlist.components,
        nets=(*netlist.nets, BoardNet(name="/EXTRA", nodes=())),
    )
    changed_netlist_json = canonical_board_netlist_snapshot_json(changed_netlist)
    netlist_payload["netlist_snapshot_json"] = changed_netlist_json
    netlist_payload["netlist_snapshot_fingerprint"] = board_netlist_snapshot_fingerprint(
        changed_netlist_json
    )
    _refingerprint_aggregate_payload(netlist_payload)
    with pytest.raises(ValidationError, match="netlist differs"):
        StableAggregateExactCheckEvidence.model_validate(netlist_payload)

    policy_payload = deepcopy(original)
    policy_payload["policy"] = _policy(policy_version="2").model_dump(mode="json")
    _refingerprint_aggregate_payload(policy_payload)
    with pytest.raises(ValidationError, match="stale aggregate inputs or policy"):
        StableAggregateExactCheckEvidence.model_validate(policy_payload)

    roundtrip_payload = deepcopy(original)
    specialized = _specialized_payload(roundtrip_payload)
    nested_authority = specialized["roundtrip_authority"]
    assert isinstance(nested_authority, dict)
    nested_authority["require_drc_pass"] = False
    _refingerprint_adapter_payload(specialized)
    _refingerprint_aggregate_payload(roundtrip_payload)
    with pytest.raises(ValidationError, match="status or findings differ from replay"):
        StableAggregateExactCheckEvidence.model_validate(roundtrip_payload)

    status_payload = deepcopy(original)
    specialized = _specialized_payload(status_payload)
    specialized["status"] = "fail"
    _refingerprint_adapter_payload(specialized)
    _refingerprint_aggregate_payload(status_payload)
    with pytest.raises(ValidationError, match="status or findings differ from replay"):
        StableAggregateExactCheckEvidence.model_validate(status_payload)

    adapter_id_payload = deepcopy(original)
    specialized = _specialized_payload(adapter_id_payload)
    specialized["producer_id"] = "forged-adapter"
    _refingerprint_adapter_payload(specialized)
    _refingerprint_aggregate_payload(adapter_id_payload)
    with pytest.raises(ValidationError):
        StableAggregateExactCheckEvidence.model_validate(adapter_id_payload)

    nested_fingerprint_payload = deepcopy(original)
    specialized = _specialized_payload(nested_fingerprint_payload)
    specialized["evidence_fingerprint"] = "0" * 64
    _refingerprint_aggregate_payload(nested_fingerprint_payload)
    with pytest.raises(ValidationError, match="fingerprint is stale"):
        StableAggregateExactCheckEvidence.model_validate(nested_fingerprint_payload)

    outer_fingerprint_payload = deepcopy(original)
    outer_fingerprint_payload["evidence_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError, match="fingerprint is stale"):
        StableAggregateExactCheckEvidence.model_validate(outer_fingerprint_payload)


def test_full_aggregate_json_replay_rejects_recomputed_finding_message_tamper() -> None:
    clean = _roundtrip_authority()
    failed_payload = clean.model_dump(mode="json")
    failed_payload["require_drc_pass"] = False
    failed_payload["drc_status"] = "failed"
    failed_payload["drc_findings"] = ["clearance violation"]
    failed = PlacementKiCadSaveRoundtripAuthority.model_validate(failed_payload)
    layout, netlist = _board_inputs(failed)
    policy = _policy()
    adapter = _adapter(failed, policy)
    aggregate = evaluate_stable_aggregate_exact_check(layout, netlist, policy, (adapter,))
    payload = aggregate.model_dump(mode="json")
    specialized = _specialized_payload(payload)
    findings = specialized["findings"]
    assert isinstance(findings, list) and findings
    finding = findings[0]
    assert isinstance(finding, dict)
    finding["message"] = "forged but internally fingerprinted message"
    finding["finding_fingerprint"] = _canonical_fingerprint(
        {"finding_id": finding["finding_id"], "message": finding["message"]}
    )
    _refingerprint_adapter_payload(specialized)
    _refingerprint_aggregate_payload(payload)

    with pytest.raises(ValidationError, match="status or findings differ from replay"):
        StableAggregateExactCheckEvidence.model_validate(payload)
