from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.component_review_execution import (
    ReviewAttemptStatus,
    execute_project_component_reviews,
)
from pcbsmith.evidence.component_pin_evidence import (
    ComponentPinEvidence,
    DatasheetPackageEvidence,
    DatasheetPinEvidence,
)
from pcbsmith.evidence.models import EvidenceLocator
from pcbsmith.kicad.board import BoardComponent, BoardNet, BoardNetlist
from pcbsmith.kicad.board_serialization import canonical_board_netlist_snapshot_json
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.schematic_review_ir import (
    ComponentReviewResult,
    ReviewApplicability,
    ReviewRunOutcome,
)
from pcbsmith.semantic_ir import SemanticDisposition


def _component(reference: str, value: str) -> BoardComponent:
    return BoardComponent(
        reference=reference,
        value=value,
        footprint="Package_QFP:TQFP-4_4x4mm_P0.8mm",
        uuid_path=stable_kicad_uuid("component-review-execution", reference),
    )


def _netlist() -> BoardNetlist:
    return BoardNetlist(
        components=(
            _component("U1", "IC-A"),
            _component("U2", "IC-B"),
            _component("R1", "10k"),
        ),
        nets=(
            BoardNet(name="+3V3", nodes=(("U1", "1"), ("U2", "1"))),
            BoardNet(name="GND", nodes=(("U1", "2"), ("U2", "2"))),
            BoardNet(name="BUS", nodes=(("U1", "3"), ("U2", "3"), ("R1", "1"))),
            BoardNet(name="RESET", nodes=(("U1", "4"), ("R1", "2"))),
        ),
    )


def _pin_evidence(part_number: str) -> ComponentPinEvidence:
    locator = EvidenceLocator(
        local_file=f"datasheets/{part_number}.pdf",
        page=2,
    )
    return ComponentPinEvidence(
        manufacturer="Example",
        part_number=part_number,
        source_sha256="a" * 64,
        source_local_path=f"datasheets/{part_number}.pdf",
        extraction_status="human_reviewed",
        package=DatasheetPackageEvidence(
            package_name="TQFP-4",
            exact_variant=part_number,
            pin_count=4,
            locator=locator,
        ),
        pins=(
            DatasheetPinEvidence(
                number="1",
                name="VDD",
                electrical_role="supply",
                locator=locator,
            ),
            DatasheetPinEvidence(
                number="2",
                name="GND",
                electrical_role="ground",
                locator=locator,
            ),
            DatasheetPinEvidence(
                number="3",
                name="IO",
                electrical_role="signal",
                locator=locator,
            ),
            DatasheetPinEvidence(
                number="4",
                name="RESET",
                electrical_role="configuration",
                locator=locator,
            ),
        ),
    )


def _pass_result(request) -> ComponentReviewResult:
    if request.obligation.applicability is ReviewApplicability.UNRESOLVED:
        return ComponentReviewResult(
            obligation_id=request.obligation.obligation_id,
            disposition=SemanticDisposition.UNVERIFIED,
            rationale="fixture unresolved",
            evidence_query_count=0,
            evidence_query_budget=request.evidence_query_budget,
        )
    return ComponentReviewResult(
        obligation_id=request.obligation.obligation_id,
        disposition=SemanticDisposition.PASS,
        rationale="fixture evidence-backed pass",
        check_ids=(f"fixture:{request.obligation.area.value}",),
        evidence=(
            EvidenceRef(
                kind="datasheet",
                title="Fixture component datasheet",
                source_id="fixture-datasheet",
                locator="page 2",
                local_sha256="a" * 64,
                source_status="pinned",
                locator_status="text_verified",
                applicability_status="confirmed",
            ),
        ),
        evidence_query_count=1,
        evidence_query_budget=request.evidence_query_budget,
    )


def _fixture_source() -> EvidenceRef:
    return EvidenceRef(
        kind="datasheet",
        title="Fixture component datasheet",
        source_id="fixture-datasheet",
        locator="page 2",
        local_sha256="a" * 64,
        source_status="pinned",
        locator_status="text_verified",
        applicability_status="confirmed",
    )


def test_runner_closes_every_ic_obligation_and_bounds_neighbor_evidence() -> None:
    requests = []

    def reviewer(request):
        requests.append(request)
        return _pass_result(request)

    execution = execute_project_component_reviews(
        project_id="fixture-project",
        board_revision="r001",
        netlist=_netlist(),
        pin_evidence_by_reference={
            "U1": _pin_evidence("IC-A"),
            "U2": _pin_evidence("IC-B"),
        },
        reviewer=reviewer,
    )

    assert execution.required_component_references == ("U1", "U2")
    assert execution.missing_pin_evidence_references == ()
    assert execution.outcome is ReviewRunOutcome.COMPLETE
    assert execution.ready_for_routing
    assert len(execution.manifests) == 2
    assert all(
        set(reference for reference, _value in request.neighbor_pin_evidence_fingerprints)
        <= set(request.obligation.neighbor_component_references)
        for request in requests
    )
    assert execution.evidence_query_count <= execution.evidence_query_budget


def test_retry_budget_is_shared_and_duplicate_evidence_is_normalized() -> None:
    requests_by_obligation = {}

    def reviewer(request):
        requests_by_obligation.setdefault(
            request.obligation.obligation_id,
            [],
        ).append(request)
        if request.attempt == 1:
            return ComponentReviewResult(
                obligation_id="schematic-review:U1:wrong",
                disposition=SemanticDisposition.PASS,
                rationale="deliberately wrong first submission",
                check_ids=("fixture:wrong",),
                evidence_query_count=3,
                evidence_query_budget=request.evidence_query_budget,
            )
        source = _fixture_source()
        return ComponentReviewResult(
            obligation_id=request.obligation.obligation_id,
            disposition=SemanticDisposition.PASS,
            rationale="second bounded submission",
            check_ids=("fixture:pass",),
            evidence=(source, source),
            evidence_query_count=1,
            evidence_query_budget=request.evidence_query_budget,
        )

    execution = execute_project_component_reviews(
        project_id="fixture-project",
        board_revision="r001",
        netlist=_netlist(),
        pin_evidence_by_reference={
            "U1": _pin_evidence("IC-A"),
            "U2": _pin_evidence("IC-B"),
        },
        reviewer=reviewer,
    )

    assert execution.ready_for_routing
    assert all(
        [request.evidence_query_budget for request in requests] == [4, 1]
        for requests in requests_by_obligation.values()
    )
    assert all(
        len(result.evidence) <= 1 for manifest in execution.manifests for result in manifest.results
    )


def test_no_submission_retries_then_recovers_as_unverified() -> None:
    execution = execute_project_component_reviews(
        project_id="fixture-project",
        board_revision="r001",
        netlist=BoardNetlist(
            components=(_component("U1", "IC-A"),),
            nets=(
                BoardNet(name="+3V3", nodes=(("U1", "1"),)),
                BoardNet(name="GND", nodes=(("U1", "2"),)),
            ),
        ),
        pin_evidence_by_reference={"U1": _pin_evidence("IC-A")},
        reviewer=lambda _request: None,
        max_attempts=2,
    )

    assert execution.outcome is ReviewRunOutcome.UNVERIFIED
    assert not execution.ready_for_routing
    statuses = {trace.status for trace in execution.traces}
    assert ReviewAttemptStatus.NO_SUBMISSION in statuses
    assert ReviewAttemptStatus.CONSERVATIVE_RECOVERY in statuses
    assert all(manifest.trace_ids for manifest in execution.manifests)


def test_reviewer_exception_is_isolated_and_missing_pin_evidence_blocks() -> None:
    calls = 0

    def reviewer(request):
        nonlocal calls
        calls += 1
        if request.neighborhood.component_reference == "U1":
            raise RuntimeError("fixture reviewer failure")
        return _pass_result(request)

    execution = execute_project_component_reviews(
        project_id="fixture-project",
        board_revision="r001",
        netlist=_netlist(),
        pin_evidence_by_reference={"U1": _pin_evidence("IC-A")},
        reviewer=reviewer,
        max_attempts=1,
    )

    assert calls > 0
    assert execution.outcome is ReviewRunOutcome.BLOCKED
    assert execution.missing_pin_evidence_references == ("U2",)
    assert any(trace.status is ReviewAttemptStatus.EXCEPTION for trace in execution.traces)
    assert not execution.ready_for_routing


def test_invalid_cross_obligation_submission_is_recovered_conservatively() -> None:
    def reviewer(request):
        return ComponentReviewResult(
            obligation_id="schematic-review:U1:wrong",
            disposition=SemanticDisposition.PASS,
            rationale="wrong obligation",
            check_ids=("fixture:wrong",),
            evidence_query_count=0,
            evidence_query_budget=request.evidence_query_budget,
        )

    execution = execute_project_component_reviews(
        project_id="fixture-project",
        board_revision="r001",
        netlist=BoardNetlist(
            components=(_component("U1", "IC-A"),),
            nets=(BoardNet(name="+3V3", nodes=(("U1", "1"),)),),
        ),
        pin_evidence_by_reference={"U1": _pin_evidence("IC-A")},
        reviewer=reviewer,
        max_attempts=1,
    )

    assert execution.outcome is ReviewRunOutcome.UNVERIFIED
    assert ReviewAttemptStatus.INVALID in {trace.status for trace in execution.traces}


def test_component_review_cli_executes_exact_request(tmp_path: Path) -> None:
    from pcbsmith.cli import main

    request = tmp_path / "request.json"
    output = tmp_path / "execution.json"
    request.write_text(
        json.dumps(
            {
                "project_id": "fixture-project",
                "board_revision": "r001",
                "board_netlist_snapshot_json": (
                    canonical_board_netlist_snapshot_json(BoardNetlist(components=(), nets=()))
                ),
                "pin_evidence_by_reference": {},
                "results_by_obligation": {},
            }
        ),
        encoding="utf-8",
    )

    assert (
        main(
            [
                "component-review-execute",
                str(request),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    execution = json.loads(output.read_text(encoding="utf-8"))
    assert execution["ready_for_routing"] is True
