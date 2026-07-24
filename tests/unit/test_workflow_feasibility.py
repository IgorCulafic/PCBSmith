from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcbsmith.prompt_examiner import AnchorKind, TypedSpatialAnchor
from pcbsmith.workflow_feasibility import (
    FeasibilityOutcome,
    NeckSection,
    ObservedAnchor,
    PlacementEnvelope,
    PreRouteFeasibilityReport,
    PreRouteNetDemand,
    compare_concept_anchors,
    evaluate_pre_route_feasibility,
)

SHA_A = "a" * 64
SHA_B = "b" * 64


def _envelope(
    envelope_id: str = "env.u1",
    polygon: tuple[tuple[float, float], ...] = (
        (1.0, 1.0),
        (2.0, 1.0),
        (2.0, 2.0),
        (1.0, 2.0),
    ),
) -> PlacementEnvelope:
    return PlacementEnvelope(
        envelope_id=envelope_id,
        subject_id=envelope_id.removeprefix("env."),
        polygon=polygon,
        source_geometry_sha256=SHA_A,
    )


def _neck(neck_id: str, *, capacity_units: int = 1) -> NeckSection:
    return NeckSection(
        neck_id=neck_id,
        usable_width_mm=capacity_units * 0.25,
        routing_layers=("F.Cu",),
        capacity_quantum_mm=0.25,
        source_geometry_sha256=SHA_A,
    )


def _demand(name: str, necks: tuple[str, ...]) -> PreRouteNetDemand:
    return PreRouteNetDemand(
        net_name=name,
        terminal_ids=(f"{name}.1", f"{name}.2"),
        trace_width_mm=0.25,
        clearance_mm=0.0,
        candidate_neck_ids=necks,
        net_class_id="signal",
        priority=10,
    )


def _evaluate(
    *,
    envelopes: tuple[PlacementEnvelope, ...] | None = None,
    necks: tuple[NeckSection, ...] = (),
    demands: tuple[PreRouteNetDemand, ...] = (),
    search_state_budget: int = 50_000,
) -> PreRouteFeasibilityReport:
    return evaluate_pre_route_feasibility(
        board_outline=((0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)),
        board_outline_sha256=SHA_A,
        keepout_polygons=(),
        envelopes=(_envelope(),) if envelopes is None else envelopes,
        necks=necks,
        net_demands=demands,
        search_state_budget=search_state_budget,
    )


def test_alternative_necks_are_allocated_once_not_double_counted() -> None:
    report = _evaluate(
        necks=(_neck("neck.a"), _neck("neck.b")),
        demands=(
            _demand("N1", ("neck.a", "neck.b")),
            _demand("N2", ("neck.a", "neck.b")),
        ),
    )

    assert report.outcome is FeasibilityOutcome.READY
    assert report.search_complete
    assert len(report.assignments) == 2
    assert {item.neck_id for item in report.assignments} == {"neck.a", "neck.b"}
    assert not report.failing_nets


def test_exhaustive_capacity_failure_names_net_and_blocker() -> None:
    report = _evaluate(
        necks=(_neck("neck.only"),),
        demands=(
            _demand("N1", ("neck.only",)),
            _demand("N2", ("neck.only",)),
        ),
    )

    assert report.outcome is FeasibilityOutcome.BLOCKED
    assert report.search_complete
    assert len(report.assignments) == 1
    assert len(report.failing_nets) == 1
    assert report.failing_nets[0].blocker_ids
    assert len(report.failing_nets[0].next_actions) >= 2


def test_search_budget_exhaustion_is_unverified_not_false_blocker() -> None:
    report = _evaluate(
        necks=(_neck("neck.a"), _neck("neck.b")),
        demands=(
            _demand("N1", ("neck.a", "neck.b")),
            _demand("N2", ("neck.a", "neck.b")),
        ),
        search_state_budget=1,
    )

    assert report.outcome is FeasibilityOutcome.UNVERIFIED
    assert not report.search_complete
    assert report.search_states_explored == 1


def test_uncontained_placement_blocks_before_routing() -> None:
    outside = _envelope(
        polygon=((9.5, 9.5), (10.5, 9.5), (10.5, 10.5), (9.5, 10.5))
    )
    report = _evaluate(envelopes=(outside,))

    assert report.outcome is FeasibilityOutcome.BLOCKED
    assert report.uncontained_envelope_ids == ("env.u1",)


def test_center_anchor_uses_zero_offset_and_tolerance() -> None:
    approved = TypedSpatialAnchor(
        anchor_id="anchor.usb.center",
        kind=AnchorKind.CENTER,
        subject_ids=("J1",),
        reference_id="board.top_edge",
        axis="x",
        tolerance_mm=0.1,
        source_span_ids=("span.usb",),
    )
    conformant = ObservedAnchor(
        anchor_id=approved.anchor_id,
        subject_ids=("J1",),
        kind=AnchorKind.CENTER,
        observed_value_mm=0.05,
        evidence_sha256=SHA_B,
    )
    drifted = conformant.model_copy(update={"observed_value_mm": 0.2})

    good = compare_concept_anchors(
        approved_concept_sha256=SHA_A,
        observed_design_sha256=SHA_B,
        approved=(approved,),
        observed=(conformant,),
    )
    bad = compare_concept_anchors(
        approved_concept_sha256=SHA_A,
        observed_design_sha256=SHA_B,
        approved=(approved,),
        observed=(drifted,),
    )

    assert good.conformant
    assert not bad.conformant
    assert bad.records[0].state == "drifted"


def test_feasibility_fingerprint_rejects_tampering() -> None:
    report = _evaluate()
    payload = report.model_dump(mode="json")
    payload["board_area_mm2"] = 999.0

    with pytest.raises(ValidationError, match="fingerprint is stale"):
        PreRouteFeasibilityReport.model_validate(payload)
