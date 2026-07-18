from __future__ import annotations

import json
from dataclasses import replace

import pytest
from pydantic import ValidationError

from pcbsmith.circuit.models import ReviewFinding
from pcbsmith.kicad.aggregate_exact_checker import (
    AggregateCheckStatus,
    AggregateSubcheckApplicability,
    AggregateSubcheckKind,
    AggregateSubcheckRequirement,
    ExternalArtifactSubcheckEvidence,
    ExternalSubcheckFinding,
    StableAggregateExactCheckerPolicy,
    StableAggregateExactCheckEvidence,
    evaluate_stable_aggregate_exact_check,
    external_subcheck_binding,
)
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
)
from pcbsmith.kicad.design_checks import DesignChecksSpec
from pcbsmith.kicad.virtual_drc import VirtualDrcFinding
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile


def _clean_board() -> tuple[BoardLayout, BoardNetlist]:
    return (
        BoardLayout(placements=(), segments=(), vias=(), width_mm=20.0, height_mm=20.0),
        BoardNetlist(components=(), nets=()),
    )


def _requirements(*external_ids: str) -> tuple[AggregateSubcheckRequirement, ...]:
    return (
        AggregateSubcheckRequirement(
            subcheck_id="design",
            subcheck_version="1",
            kind=AggregateSubcheckKind.DESIGN_CHECKS,
        ),
        *(
            AggregateSubcheckRequirement(
                subcheck_id=item,
                subcheck_version="1",
                kind=AggregateSubcheckKind.EXTERNAL_ARTIFACT,
            )
            for item in external_ids
        ),
        AggregateSubcheckRequirement(
            subcheck_id="virtual",
            subcheck_version="1",
            kind=AggregateSubcheckKind.VIRTUAL_DRC,
        ),
    )


def _policy(
    *external_ids: str,
    spec: DesignChecksSpec | None = None,
) -> StableAggregateExactCheckerPolicy:
    return StableAggregateExactCheckerPolicy.build(
        policy_id="unit-stable-aggregate",
        policy_version="1",
        profile=DEFAULT_PCB_RULE_PROFILE,
        design_checks_spec=spec or DesignChecksSpec(),
        subchecks=_requirements(*external_ids),
    )


def _external(
    layout: BoardLayout,
    netlist: BoardNetlist,
    policy: StableAggregateExactCheckerPolicy,
    subcheck_id: str,
    status: AggregateCheckStatus,
    layout_fingerprint: str | None = None,
) -> ExternalArtifactSubcheckEvidence:
    layout_fp, netlist_fp, policy_fp = external_subcheck_binding(layout, netlist, policy)
    findings = (
        ()
        if status is AggregateCheckStatus.PASS
        else (
            ExternalSubcheckFinding.build(
                f"{subcheck_id}-finding",
                f"{subcheck_id} did not establish acceptance",
            ),
        )
    )
    return ExternalArtifactSubcheckEvidence.build(
        subcheck_id=subcheck_id,
        subcheck_version="1",
        status=status,
        findings=findings,
        layout_snapshot_fingerprint=layout_fingerprint or layout_fp,
        netlist_snapshot_fingerprint=netlist_fp,
        policy_fingerprint=policy_fp,
        source_artifact_id=f"artifact:{subcheck_id}",
        source_artifact_sha256="a" * 64,
        tool_id=f"tool:{subcheck_id}",
        tool_version="1.0",
        config={"mode": "unit", "subcheck": subcheck_id},
        result_identity=f"result:{subcheck_id}:001",
    )


def test_all_required_in_process_checks_pass_but_missing_external_blocks() -> None:
    layout, netlist = _clean_board()
    policy = _policy("reader-equality")

    evidence = evaluate_stable_aggregate_exact_check(layout, netlist, policy)

    assert not evidence.aggregate_result.accepted
    by_id = {item.subcheck_id: item for item in evidence.subchecks}
    assert by_id["virtual"].status is AggregateCheckStatus.PASS
    assert by_id["design"].status is AggregateCheckStatus.PASS
    assert by_id["reader-equality"].status is AggregateCheckStatus.UNVERIFIED
    assert evidence.aggregate_result.checker_id == (
        f"unit-stable-aggregate@1:{policy.policy_fingerprint}"
    )
    assert evidence == StableAggregateExactCheckEvidence.model_validate_json(
        evidence.model_dump_json()
    )


def test_virtual_connectivity_finding_blocks_exact_acceptance() -> None:
    components = tuple(
        BoardComponent(
            reference=reference,
            value="1k",
            footprint="Resistor_SMD:R_0603_1608Metric",
            uuid_path=reference.lower(),
        )
        for reference in ("R1", "R2")
    )
    netlist = BoardNetlist(
        components=components,
        nets=(BoardNet(name="/OPEN", nodes=(("R1", "1"), ("R2", "1"))),),
    )
    layout = BoardLayout(
        placements=((components[0], 10.0), (components[1], 30.0)),
        segments=(),
        vias=(),
        width_mm=40.0,
        height_mm=20.0,
        part_y_mm=(("R1", 10.0), ("R2", 10.0)),
    )

    evidence = evaluate_stable_aggregate_exact_check(layout, netlist, _policy())

    virtual = next(item for item in evidence.subchecks if item.subcheck_id == "virtual")
    assert virtual.status is AggregateCheckStatus.FAIL
    assert "pad_connectivity" in virtual.result_json
    assert not evidence.aggregate_result.accepted


def test_design_finding_blocks_exact_acceptance() -> None:
    layout, netlist = _clean_board()
    finding = ReviewFinding(
        rule="unit-design",
        severity="blocker",
        scope="global",
        where="board",
        evidence="unit fixture finding",
        suggested_action="fix the unit fixture",
        source="check",
    )
    evidence = evaluate_stable_aggregate_exact_check(
        layout,
        netlist,
        _policy(spec=DesignChecksSpec(extra_model_findings=(finding,))),
    )

    design = next(item for item in evidence.subchecks if item.subcheck_id == "design")
    assert design.status is AggregateCheckStatus.FAIL
    assert "unit fixture finding" in design.result_json
    assert not evidence.aggregate_result.accepted


@pytest.mark.parametrize("status", [AggregateCheckStatus.FAIL, AggregateCheckStatus.UNVERIFIED])
def test_exact_supplied_external_failure_or_pending_blocks(
    status: AggregateCheckStatus,
) -> None:
    layout, netlist = _clean_board()
    policy = _policy("kicad-drc")
    supplied = _external(layout, netlist, policy, "kicad-drc", status)

    evidence = evaluate_stable_aggregate_exact_check(layout, netlist, policy, (supplied,))

    assert not evidence.aggregate_result.accepted
    assert len(evidence.aggregate_result.finding_fingerprints) == 1
    assert evidence.aggregate_result.finding_fingerprints[0] != (
        supplied.findings[0].finding_fingerprint
    )


def test_exact_external_pass_accepts_only_when_every_required_check_passes() -> None:
    layout, netlist = _clean_board()
    policy = _policy("reader-equality", "kicad-drc")
    reader = _external(layout, netlist, policy, "reader-equality", AggregateCheckStatus.PASS)
    kicad = _external(layout, netlist, policy, "kicad-drc", AggregateCheckStatus.PASS)

    first = evaluate_stable_aggregate_exact_check(layout, netlist, policy, (reader, kicad))
    reversed_input = evaluate_stable_aggregate_exact_check(
        layout, netlist, policy, (kicad, reader)
    )

    assert first.aggregate_result.accepted
    assert first.aggregate_result.finding_fingerprints == ()
    assert first == reversed_input


def test_explicitly_inapplicable_external_check_is_retained_without_blocking() -> None:
    layout, netlist = _clean_board()
    requirements = (
        *_requirements(),
        AggregateSubcheckRequirement(
            subcheck_id="simulation",
            subcheck_version="1",
            kind=AggregateSubcheckKind.EXTERNAL_ARTIFACT,
            applicability=AggregateSubcheckApplicability.NOT_APPLICABLE,
        ),
    )
    policy = StableAggregateExactCheckerPolicy.build(
        policy_id="unit-stable-aggregate",
        policy_version="1",
        profile=DEFAULT_PCB_RULE_PROFILE,
        design_checks_spec=DesignChecksSpec(),
        subchecks=requirements,
    )

    evidence = evaluate_stable_aggregate_exact_check(layout, netlist, policy)

    assert evidence.aggregate_result.accepted
    simulation = next(item for item in evidence.subchecks if item.subcheck_id == "simulation")
    assert simulation.status is AggregateCheckStatus.NOT_APPLICABLE


def test_stale_duplicate_extra_and_in_process_replacement_evidence_reject() -> None:
    layout, netlist = _clean_board()
    policy = _policy("reader-equality")
    reader = _external(layout, netlist, policy, "reader-equality", AggregateCheckStatus.PASS)

    with pytest.raises(ValueError, match="duplicate external"):
        evaluate_stable_aggregate_exact_check(layout, netlist, policy, (reader, reader))

    extra = _external(layout, netlist, policy, "unknown", AggregateCheckStatus.PASS)
    with pytest.raises(ValueError, match="extra policy-unknown"):
        evaluate_stable_aggregate_exact_check(layout, netlist, policy, (extra,))

    replacement = _external(layout, netlist, policy, "virtual", AggregateCheckStatus.PASS)
    with pytest.raises(ValueError, match="replace an in-process"):
        evaluate_stable_aggregate_exact_check(layout, netlist, policy, (replacement,))

    stale = _external(
        layout,
        netlist,
        policy,
        "reader-equality",
        AggregateCheckStatus.PASS,
        layout_fingerprint="b" * 64,
    )
    with pytest.raises(ValueError, match="stale aggregate inputs"):
        evaluate_stable_aggregate_exact_check(layout, netlist, policy, (stale,))


def test_policy_result_messages_checker_id_and_fingerprint_tamper_reject() -> None:
    layout, netlist = _clean_board()
    policy = _policy("reader-equality")
    reader = _external(layout, netlist, policy, "reader-equality", AggregateCheckStatus.PASS)
    evidence = evaluate_stable_aggregate_exact_check(layout, netlist, policy, (reader,))
    payload = evidence.model_dump(mode="json")

    policy_payload = json.loads(json.dumps(payload))
    policy_payload["policy"]["policy_id"] = "changed-policy"
    with pytest.raises(ValidationError, match="policy fingerprint is stale"):
        StableAggregateExactCheckEvidence.model_validate(policy_payload)

    message_payload = json.loads(json.dumps(payload))
    design = next(
        item for item in message_payload["subchecks"] if item["subcheck_id"] == "design"
    )
    design["result_json"] = design["result_json"].replace("connector_edge", "other_check")
    with pytest.raises(ValidationError, match="checksum is stale"):
        StableAggregateExactCheckEvidence.model_validate(message_payload)

    checker_payload = json.loads(json.dumps(payload))
    checker_payload["aggregate_result"]["checker_id"] = "forged"
    with pytest.raises(ValidationError, match="differs from deterministic replay"):
        StableAggregateExactCheckEvidence.model_validate(checker_payload)

    fp_payload = json.loads(json.dumps(payload))
    fp_payload["evidence_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError, match="fingerprint is stale"):
        StableAggregateExactCheckEvidence.model_validate(fp_payload)


def test_external_result_cannot_be_a_boolean_or_tampered_message() -> None:
    layout, netlist = _clean_board()
    policy = _policy("simulation")
    failed = _external(layout, netlist, policy, "simulation", AggregateCheckStatus.FAIL)
    payload = failed.model_dump(mode="json")

    payload["result_json"] = "true"
    with pytest.raises(ValidationError, match="noncanonical or stale"):
        ExternalArtifactSubcheckEvidence.model_validate(payload)

    payload = failed.model_dump(mode="json")
    payload["findings"][0]["message"] = "changed external finding"
    with pytest.raises(ValidationError, match="finding fingerprint is stale"):
        ExternalArtifactSubcheckEvidence.model_validate(payload)


def test_input_objects_are_isolated_and_retained_snapshots_do_not_follow_changes() -> None:
    layout, netlist = _clean_board()
    evidence = evaluate_stable_aggregate_exact_check(layout, netlist, _policy())

    changed = replace(layout, width_mm=21.0)

    assert changed != layout
    assert evidence.layout_snapshot_json != evaluate_stable_aggregate_exact_check(
        changed, netlist, _policy()
    ).layout_snapshot_json
    assert StableAggregateExactCheckEvidence.model_validate_json(
        evidence.model_dump_json()
    ) == evidence


def test_mutating_in_process_check_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, netlist = _clean_board()

    def mutating_virtual(
        checked: BoardLayout,
        _netlist: BoardNetlist,
        _profile: PcbRuleProfile,
    ) -> tuple[VirtualDrcFinding, ...]:
        object.__setattr__(checked, "width_mm", 99.0)
        return ()

    monkeypatch.setattr(
        "pcbsmith.kicad.aggregate_exact_checker.run_virtual_drc",
        mutating_virtual,
    )

    with pytest.raises(ValueError, match="mutated its retained BoardLayout"):
        evaluate_stable_aggregate_exact_check(layout, netlist, _policy())

    assert layout.width_mm == 20.0


def test_mutating_retained_policy_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, netlist = _clean_board()
    policy = _policy()

    def mutating_virtual(
        _layout: BoardLayout,
        _netlist: BoardNetlist,
        checked_profile: PcbRuleProfile,
    ) -> tuple[VirtualDrcFinding, ...]:
        object.__setattr__(checked_profile, "profile_id", "mutated-profile")
        return ()

    monkeypatch.setattr(
        "pcbsmith.kicad.aggregate_exact_checker.run_virtual_drc",
        mutating_virtual,
    )

    with pytest.raises(ValueError, match="mutated its retained checker policy"):
        evaluate_stable_aggregate_exact_check(layout, netlist, policy)

    assert policy.profile.profile_id == DEFAULT_PCB_RULE_PROFILE.profile_id
