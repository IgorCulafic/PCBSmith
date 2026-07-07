"""Layout scorecard (Track 8.2 foundation): checks-as-fitness."""

from __future__ import annotations

from tests.unit.kicad.test_flyback_board import _netlist

from pcbsmith.kicad.board import TrackSegment
from pcbsmith.kicad.flyback_board import compute_flyback_board_layout
from pcbsmith.kicad.layout_score import rank_candidates, score_layout


def _with_extra_segment(layout, segment):
    return layout.__class__(
        **{
            **{
                key: getattr(layout, key)
                for key in layout.__dataclass_fields__
            },
            "segments": (*layout.segments, segment),
        }
    )


def test_flyback_layout_scores_viable() -> None:
    netlist = _netlist()
    layout = compute_flyback_board_layout(netlist)
    score = score_layout(layout, netlist)
    assert score.is_viable
    assert score.total_track_mm > 100.0
    assert score.via_count >= 5
    # Headroom exists but is finite on a dense board.
    assert 0.0 < score.min_copper_margin_mm < 5.0
    assert score.parts_bbox_mm2 > 1000.0


def test_shorted_candidate_ranks_after_viable_one() -> None:
    netlist = _netlist()
    good = compute_flyback_board_layout(netlist)
    # A track through foreign pads: hard violations, longer copper.
    bad = _with_extra_segment(
        good,
        TrackSegment(x1=5.0, y1=8.0, x2=80.0, y2=8.0,
                     layer="F.Cu", net_name="/HVP", width_mm=0.4),
    )
    ranked = rank_candidates((("bad", bad), ("good", good)), netlist)
    assert [name for name, _ in ranked] == ["good", "bad"]
    assert ranked[0][1].is_viable
    assert not ranked[1][1].is_viable


def test_extra_detour_costs_ranking_but_stays_viable() -> None:
    netlist = _netlist()
    good = compute_flyback_board_layout(netlist)
    # A legal but pointless same-net stub in free space.
    detour = _with_extra_segment(
        good,
        TrackSegment(x1=33.0, y1=2.0, x2=36.0, y2=2.0,
                     layer="F.Cu", net_name="/L", width_mm=0.4),
    )
    ranked = rank_candidates((("detour", detour), ("good", good)), netlist)
    assert ranked[0][0] == "good"
    assert ranked[1][1].is_viable  # still legal, just worse
