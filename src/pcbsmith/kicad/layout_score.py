"""Layout scorecard: rank candidate layouts by checks-as-fitness.

Track 8.2 (docs/hardening-and-generalization-plan.md): Quilter's
production lesson is that autonomous layout works when candidates are
generated in volume and SCORED BY PHYSICS, not when a single answer is
trusted. PCBSmith already owns the scorer - virtual DRC, the design
checks, trace-current, and creepage rules ARE a fitness function. This
module packages them as one: hard gates (any finding disqualifies) plus
soft quality metrics (copper length, via count, clearance headroom,
packing) for ranking the survivors. The candidate GENERATOR plugs in on
top of this; hand-written layouts get scored by the same yardstick.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from pcbsmith.kicad.board import (
    FOOTPRINT_LIBRARY,
    BoardLayout,
    BoardNetlist,
    placement_rotation,
    placement_y,
)
from pcbsmith.kicad.design_checks import DesignChecksSpec, run_design_checks
from pcbsmith.kicad.library import rotate_offset
from pcbsmith.kicad.virtual_drc import (
    CLEARANCE_MM,
    _collect_items,
    _grid_cells,
    _seg_seg_distance,
    run_virtual_drc,
)

# Soft-cost weight: one via costs as much as this many mm of track.
VIA_TRACK_EQUIV_MM = 5.0


@dataclass(frozen=True)
class LayoutScore:
    """One candidate's report card. Lower sort_key() is better."""

    hard_violations: int
    virtual_drc_findings: tuple[str, ...]
    blocker_findings: tuple[str, ...]
    total_track_mm: float
    via_count: int
    min_copper_margin_mm: float
    parts_bbox_mm2: float
    breakdown: dict[str, float] = field(default_factory=dict)

    @property
    def is_viable(self) -> bool:
        return self.hard_violations == 0

    def sort_key(self) -> tuple[int, float, float]:
        """Viability first, then routing cost, then packing. Margin is
        reported but not ranked on: candidates that pass the gates are
        already legal, and chasing margin fights compaction."""
        routing_cost = self.total_track_mm + VIA_TRACK_EQUIV_MM * self.via_count
        return (self.hard_violations, routing_cost, self.parts_bbox_mm2)

    def as_dict(self) -> dict[str, object]:
        return {
            "viable": self.is_viable,
            "hard_violations": self.hard_violations,
            "total_track_mm": round(self.total_track_mm, 2),
            "via_count": self.via_count,
            "min_copper_margin_mm": round(self.min_copper_margin_mm, 3),
            "parts_bbox_mm2": round(self.parts_bbox_mm2, 1),
            "breakdown": {k: round(v, 3) for k, v in self.breakdown.items()},
        }


def _min_cross_net_margin(layout: BoardLayout, netlist: BoardNetlist) -> float:
    """Smallest cross-net copper gap above the required clearance -
    the layout's electrical headroom. Uses the same stadium model and
    spatial grid as the virtual DRC."""
    items = _collect_items(layout, netlist)
    grid: dict[tuple[int, int], list[int]] = {}
    for index, item in enumerate(items):
        for cell in _grid_cells(item, CLEARANCE_MM):
            grid.setdefault(cell, []).append(index)
    margin = math.inf
    seen: set[tuple[int, int]] = set()
    for cell_items in grid.values():
        for i_pos, index_one in enumerate(cell_items):
            one = items[index_one]
            for index_two in cell_items[i_pos + 1:]:
                pair = (min(index_one, index_two), max(index_one, index_two))
                if pair in seen:
                    continue
                seen.add(pair)
                two = items[index_two]
                if one.net == two.net or one.layer != two.layer:
                    continue
                gap = (
                    _seg_seg_distance(one.a, one.b, two.a, two.b)
                    - one.radius - two.radius - CLEARANCE_MM
                )
                margin = min(margin, gap)
    return margin if margin != math.inf else 0.0


def _parts_bbox_mm2(layout: BoardLayout) -> float:
    xs: list[float] = []
    ys: list[float] = []
    for component, anchor_x in layout.placements:
        spec = FOOTPRINT_LIBRARY[component.footprint]
        rotation = placement_rotation(layout, component.reference)
        anchor_y = placement_y(layout, component.reference)
        if spec.courtyard_hull is not None:
            points: Sequence[tuple[float, float]] = spec.courtyard_hull
        else:
            x1, y1, x2, y2 = spec.fab_rect
            points = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
        for point in points:
            dx, dy = rotate_offset(point[0], point[1], rotation)
            xs.append(anchor_x + dx)
            ys.append(anchor_y + dy)
    if not xs:
        return 0.0
    return (max(xs) - min(xs)) * (max(ys) - min(ys))


def score_layout(
    layout: BoardLayout,
    netlist: BoardNetlist,
    spec: DesignChecksSpec | None = None,
) -> LayoutScore:
    drc_findings = tuple(
        f"{finding.check}: {finding.message}"
        for finding in run_virtual_drc(layout, netlist)
    )
    blockers: tuple[str, ...] = ()
    if spec is not None:
        report = run_design_checks(layout, netlist, spec)
        blockers = tuple(
            f"{finding.rule}: {finding.evidence}"
            for finding in report.findings
            if finding.severity == "blocker"
        )

    total_track = sum(
        math.dist((seg.x1, seg.y1), (seg.x2, seg.y2))
        for seg in layout.segments
    )
    margin = _min_cross_net_margin(layout, netlist)
    bbox = _parts_bbox_mm2(layout)
    return LayoutScore(
        hard_violations=len(drc_findings) + len(blockers),
        virtual_drc_findings=drc_findings,
        blocker_findings=blockers,
        total_track_mm=total_track,
        via_count=len(layout.vias),
        min_copper_margin_mm=margin,
        parts_bbox_mm2=bbox,
        breakdown={
            "track_mm": total_track,
            "via_equiv_mm": VIA_TRACK_EQUIV_MM * len(layout.vias),
            "margin_mm": margin,
            "bbox_mm2": bbox,
        },
    )


def rank_candidates(
    candidates: Sequence[tuple[str, BoardLayout]],
    netlist: BoardNetlist,
    spec: DesignChecksSpec | None = None,
) -> tuple[tuple[str, LayoutScore], ...]:
    """Score every candidate and return them best-first. Non-viable
    candidates sort after every viable one."""
    scored = [
        (name, score_layout(layout, netlist, spec))
        for name, layout in candidates
    ]
    scored.sort(key=lambda pair: pair[1].sort_key())
    return tuple(scored)
