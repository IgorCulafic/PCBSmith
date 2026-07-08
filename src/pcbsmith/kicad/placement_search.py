"""Placement-candidate search: the last piece of Track 8.2.

Every ingredient exists - `route_board` turns placements into a routed
board, `layout_score` judges it. This module closes the loop: perturb
the placements, pre-gate cheap failures (courtyard overlaps) before
paying for routing, route the survivors, and rank everything with the
scorecard. The base placement is always candidate zero, so the search
can only ever match or improve it. Deterministic under a seed.
"""

from __future__ import annotations

import random
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass

from pcbsmith.kicad.astar_router import RoutingError, route_board
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.layout_score import LayoutScore, score_layout
from pcbsmith.kicad.virtual_drc import (
    _check_courtyards,
    _check_silkscreen,
    _collect_items,
)


def _pre_gate(layout: BoardLayout, netlist: BoardNetlist) -> str:
    """Cheap candidate gate before routing is paid for: courtyards
    and the silkscreen model (labels move with their parts and can
    land on a moved neighbour)."""
    overlaps = _check_courtyards(layout)
    if overlaps:
        return f"courtyards: {overlaps[0].message}"
    silk = _check_silkscreen(layout, _collect_items(layout, netlist))
    if silk:
        return f"silk: {silk[0].message}"
    return ""

Placements = dict[str, tuple[float, float, float]]


@dataclass(frozen=True)
class PlacementCandidate:
    name: str
    placements: Placements
    score: LayoutScore | None
    layout: BoardLayout | None
    rejected: str = ""


def bare_layout(
    netlist: BoardNetlist,
    placements: Mapping[str, tuple[float, float, float]],
    *,
    width_mm: float,
    height_mm: float,
    part_reference_at: tuple[
        tuple[str, tuple[float, float, float]], ...
    ] = (),
) -> BoardLayout:
    """A placements-only BoardLayout ready for route_board."""
    by_ref = {component.reference: component for component in netlist.components}
    ordered = [
        (by_ref[reference], x)
        for reference, (x, _y, _rot) in placements.items()
        if reference in by_ref
    ]
    return BoardLayout(
        placements=tuple(ordered),
        segments=(),
        vias=(),
        width_mm=width_mm,
        height_mm=height_mm,
        part_y_mm=tuple(
            (reference, y) for reference, (_x, y, _rot) in placements.items()
        ),
        part_rotation=tuple(
            (reference, rot)
            for reference, (_x, _y, rot) in placements.items()
            if rot
        ),
        # Label repositioning travels with the parts (footprint-local),
        # so the silk model judges candidates the same way it judges
        # the hand layout.
        part_reference_at=part_reference_at,
    )


def perturb(
    base: Placements,
    movable: Collection[str],
    rng: random.Random,
    *,
    step_mm: float = 1.0,
    max_steps: int = 2,
    board_w: float,
    board_h: float,
    margin_mm: float = 2.0,
) -> Placements:
    """Nudge each movable part by up to max_steps grid steps per axis."""
    result = dict(base)
    for reference in movable:
        if reference not in result:
            continue
        x, y, rot = result[reference]
        x += step_mm * rng.randint(-max_steps, max_steps)
        y += step_mm * rng.randint(-max_steps, max_steps)
        x = min(max(x, margin_mm), board_w - margin_mm)
        y = min(max(y, margin_mm), board_h - margin_mm)
        result[reference] = (x, y, rot)
    return result


def search_placements(
    netlist: BoardNetlist,
    base_placements: Placements,
    *,
    board_w: float,
    board_h: float,
    movable: Collection[str],
    candidates: int = 8,
    seed: int = 0,
    net_widths: dict[str, float] | None = None,
    clearance_groups: Sequence[
        tuple[Collection[str], Collection[str], float, Collection[str]]
    ] = (),
    spec: object | None = None,
    step_mm: float = 1.0,
    max_steps: int = 2,
    proposal_tries: int = 20,
    part_reference_at: tuple[
        tuple[str, tuple[float, float, float]], ...
    ] = (),
    on_progress: Callable[[str], None] | None = None,
) -> tuple[PlacementCandidate, ...]:
    """Generate, route, score, and rank placement candidates.

    Returns candidates best-first; unroutable or overlapping candidates
    sort last with their rejection reason recorded."""
    rng = random.Random(seed)

    def _valid_proposal() -> Placements | None:
        # Dense boards reject most blind nudges; resample until the
        # courtyard gate passes instead of wasting the candidate slot.
        movable_list = sorted(movable)
        for _try in range(proposal_tries):
            # Local-search moves: nudging every part at once rarely
            # survives the gates on a dense board; move one or two.
            chosen = rng.sample(
                movable_list, k=min(len(movable_list), rng.choice((1, 2)))
            )
            proposal = perturb(
                base_placements, chosen, rng,
                step_mm=step_mm, max_steps=max_steps,
                board_w=board_w, board_h=board_h,
            )
            probe = bare_layout(
                netlist, proposal, width_mm=board_w, height_mm=board_h,
                part_reference_at=part_reference_at,
            )
            if not _pre_gate(probe, netlist):
                return proposal
        return None

    proposals: list[tuple[str, Placements]] = [("base", dict(base_placements))]
    for index in range(1, candidates):
        proposal = _valid_proposal()
        if proposal is not None:
            proposals.append((f"cand-{index}", proposal))

    evaluated: list[PlacementCandidate] = []
    for name, placements in proposals:
        layout = bare_layout(
            netlist, placements, width_mm=board_w, height_mm=board_h,
            part_reference_at=part_reference_at,
        )
        rejection = _pre_gate(layout, netlist)
        if rejection:
            evaluated.append(
                PlacementCandidate(
                    name=name, placements=placements, score=None,
                    layout=None, rejected=rejection,
                )
            )
            if on_progress:
                on_progress(f"{name}: rejected ({rejection})")
            continue
        try:
            outcome = route_board(
                layout, netlist,
                net_widths=net_widths,
                clearance_groups=clearance_groups,
            )
        except RoutingError as exc:
            evaluated.append(
                PlacementCandidate(
                    name=name, placements=placements, score=None,
                    layout=None, rejected=f"routing: {exc}",
                )
            )
            continue
        if outcome.failed:
            evaluated.append(
                PlacementCandidate(
                    name=name, placements=placements, score=None,
                    layout=None,
                    rejected=f"unroutable net: {outcome.failed[0]}",
                )
            )
            if on_progress:
                on_progress(f"{name}: unroutable ({outcome.failed[0]})")
            continue
        score = score_layout(outcome.layout, netlist, spec)  # type: ignore[arg-type]
        evaluated.append(
            PlacementCandidate(
                name=name, placements=placements, score=score,
                layout=outcome.layout,
            )
        )
        if on_progress:
            on_progress(
                f"{name}: viable={score.is_viable} "
                f"track={score.total_track_mm:.0f}mm vias={score.via_count}"
            )

    def key(candidate: PlacementCandidate) -> tuple[object, ...]:
        if candidate.score is None:
            return (1, 0.0)
        return (0, candidate.score.sort_key())

    evaluated.sort(key=key)
    return tuple(evaluated)
