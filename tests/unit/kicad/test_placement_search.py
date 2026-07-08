"""Placement-candidate search (Track 8.2 finale)."""

from __future__ import annotations

from pcbsmith.kicad.board import BoardComponent, BoardNet, BoardNetlist
from pcbsmith.kicad.placement_search import (
    bare_layout,
    search_placements,
)

RESISTOR = "Resistor_SMD:R_0603_1608Metric"


def _netlist() -> BoardNetlist:
    return BoardNetlist(
        components=tuple(
            BoardComponent(reference=f"R{i}", value="1k", footprint=RESISTOR,
                           uuid_path=f"r{i}")
            for i in (1, 2, 3)
        ),
        nets=(
            BoardNet(name="/A", nodes=(("R1", "2"), ("R2", "1"))),
            BoardNet(name="/B", nodes=(("R2", "2"), ("R3", "1"))),
            BoardNet(name="/X", nodes=(("R1", "1"),)),
            BoardNet(name="/Y", nodes=(("R3", "2"),)),
        ),
    )


BASE = {
    "R1": (5.0, 6.0, 0.0),
    "R2": (15.0, 6.0, 0.0),
    # R3 parked far off the natural path: the search should pull it in.
    "R3": (25.0, 16.0, 0.0),
}


def test_search_ranks_base_first_when_nothing_moves() -> None:
    ranked = search_placements(
        _netlist(), BASE, board_w=30.0, board_h=20.0,
        movable=(), candidates=3, seed=1,
    )
    assert ranked[0].name == "base"
    assert ranked[0].score is not None and ranked[0].score.is_viable
    # With no movable parts every candidate is identical.
    costs = {c.score.sort_key() for c in ranked if c.score}
    assert len(costs) == 1


def test_search_finds_an_improvement_and_never_regresses() -> None:
    ranked = search_placements(
        _netlist(), BASE, board_w=30.0, board_h=20.0,
        movable=("R3",), candidates=8, seed=3, max_steps=3,
    )
    best = ranked[0]
    assert best.score is not None and best.score.is_viable
    base = next(c for c in ranked if c.name == "base")
    assert base.score is not None
    # The winner is at least as good as the base placement...
    assert best.score.sort_key() <= base.score.sort_key()
    # ...and with R3 free to move toward R2, strictly better.
    assert best.score.total_track_mm < base.score.total_track_mm


def test_overlapping_candidate_is_rejected_before_routing() -> None:
    # The BASE itself overlaps (R1 on top of R2): it must be rejected
    # at the courtyard pre-gate, while perturbed candidates that hop
    # R1 clear of R2 route and score.
    overlapping = dict(BASE, R1=(14.5, 6.0, 0.0))
    ranked = search_placements(
        _netlist(), overlapping, board_w=30.0, board_h=20.0,
        movable=("R1",), candidates=10, seed=7,
        step_mm=3.0, max_steps=2,
    )
    base = next(c for c in ranked if c.name == "base")
    assert "courtyards" in base.rejected
    assert any(c.score is not None and c.score.is_viable for c in ranked)
    # Rejected candidates rank behind every scored one.
    first_reject = next(i for i, c in enumerate(ranked) if c.rejected)
    assert all(c.score is not None for c in ranked[:first_reject])


def test_bare_layout_carries_rotations() -> None:
    layout = bare_layout(
        _netlist(), {"R1": (5.0, 6.0, 90.0), "R2": (15.0, 6.0, 0.0),
                     "R3": (25.0, 16.0, 0.0)},
        width_mm=30.0, height_mm=20.0,
    )
    assert dict(layout.part_rotation) == {"R1": 90.0}
    assert layout.segments == ()
