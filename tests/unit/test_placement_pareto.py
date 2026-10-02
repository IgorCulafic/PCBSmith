from __future__ import annotations

from pcbsmith.placement_pareto import (
    BoardSizeFeasibilityAmendment,
    LocalPinAccessEvidence,
    PlacementCandidateDisposition,
    PlacementRoutabilityMetrics,
    build_placement_pareto_set,
)


def _pin_access(
    *,
    owner: str = "U1",
    blockers: tuple[str, ...] = ("C1",),
    blocked_count: int = 0,
) -> LocalPinAccessEvidence:
    return LocalPinAccessEvidence.build(
        evidence_id=f"{owner}-pin-access",
        owner_reference=owner,
        terminal_ids=(f"{owner}:1", f"{owner}:2"),
        blocking_reference_ids=blockers,
        exact_geometry_fingerprints=("a" * 64, "b" * 64),
        blocked_terminal_count=blocked_count,
    )


def _candidate(
    candidate_id: str,
    *,
    hard: tuple[str, ...] = (),
    access: LocalPinAccessEvidence | None = None,
    overflow: int = 0,
    crossings: int = 0,
    loop: float = 3.0,
    wirelength: float = 20.0,
    vias: int = 2,
) -> PlacementRoutabilityMetrics:
    return PlacementRoutabilityMetrics.build(
        candidate_id=candidate_id,
        placement_sha256=(candidate_id[-1] * 64),
        hard_illegal_finding_ids=hard,
        local_pin_access=(access or _pin_access(),),
        coarse_capacity_overflow_units=overflow,
        corridor_overflow_units=0,
        net_crossing_count=crossings,
        terminal_order_inversion_count=0,
        power_return_reservation_conflict_count=0,
        predicted_reference_fragmentation_count=0,
        predicted_unavoidable_slot_length_mm=0.0,
        topology_loop_length_mm=loop,
        access_conflict_count=0,
        estimated_wirelength_mm=wirelength,
        estimated_via_count=vias,
        bounded_probe_unresolved_net_count=0,
    )


def test_decoupler_source_cap_return_loop_is_not_hidden_by_weighted_sum() -> None:
    near = _candidate("candidate-a", loop=2.0, wirelength=18.0)
    far = _candidate("candidate-b", loop=8.0, wirelength=18.0)

    result = build_placement_pareto_set((far, near))

    assert result.retained_candidate_ids == ("candidate-a",)
    by_id = {item.candidate_id: item for item in result.decisions}
    assert by_id["candidate-b"].disposition is PlacementCandidateDisposition.DOMINATED


def test_tqfp_rotation_with_better_escape_and_corridor_cost_is_retained() -> None:
    blocked = _candidate(
        "rotation-0",
        access=_pin_access(blocked_count=4),
        overflow=3,
        crossings=7,
    )
    open_rotation = _candidate(
        "rotation-1",
        access=_pin_access(blocked_count=0),
        overflow=0,
        crossings=2,
    )

    result = build_placement_pareto_set((blocked, open_rotation))
    assert result.retained_candidate_ids == ("rotation-1",)


def test_unrelated_component_change_cannot_rewrite_local_pin_access_evidence() -> None:
    local = _pin_access(owner="U1", blockers=("C1",), blocked_count=1)
    first = _candidate("placement-a", access=local)
    unrelated_moved = _candidate("placement-b", access=local, wirelength=19.0)

    assert first.local_pin_access[0].evidence_fingerprint == (
        unrelated_moved.local_pin_access[0].evidence_fingerprint
    )
    assert first.local_pin_access[0].blocking_reference_ids == ("C1",)


def test_hard_illegal_candidate_is_rejected_before_pareto_selection() -> None:
    illegal = _candidate("candidate-a", hard=("courtyard-overlap",), loop=1.0)
    legal = _candidate("candidate-b", loop=5.0)
    result = build_placement_pareto_set((illegal, legal))

    assert result.retained_candidate_ids == ("candidate-b",)
    assert result.decisions[0].disposition is PlacementCandidateDisposition.HARD_ILLEGAL


def test_board_enlargement_is_never_an_automatic_optimization_action() -> None:
    amendment = BoardSizeFeasibilityAmendment(
        amendment_id="increase-width-for-corridor",
        original_outline_sha256="c" * 64,
        proposed_width_mm=80.0,
        proposed_height_mm=50.0,
        triggering_finding_ids=("corridor-overflow",),
        preserves_required_interface_ids=("usb-edge",),
    )

    assert not amendment.automatic_apply_authorized
    assert amendment.user_or_design_authority_approval_id is None
