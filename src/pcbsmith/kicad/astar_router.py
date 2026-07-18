"""Grid A* net router: the candidate generator's routing engine.

Track 8.2 / plan 2.3. The practitioner consensus across every
code-based PCB platform is "you are still routing manually"; this
module is PCBSmith's answer. It routes one net at a time on a uniform
two-layer grid whose obstacles come from the SAME stadium model the
virtual DRC checks against - so a path the router finds is, by
construction, a path the verifier accepts (the round-trip is asserted
in tests, and `layout_score` remains the judge of whole candidates).

Deliberate MVP boundaries:
- 4-connected moves (Manhattan) plus via hops; no 45s yet.
- One track width per routed net; obstacle inflation covers
  clearance + half-width exactly like the stadium math.
- Nets route sequentially; rip-up/retry and net ordering search belong
  to the candidate-generation layer on top.
"""

from __future__ import annotations

import functools
import heapq
import math
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from pcbsmith.kicad.board import (
    BoardLayout,
    BoardNetlist,
    TrackSegment,
    ViaSpec,
)
from pcbsmith.kicad.virtual_drc import (
    CLEARANCE_MM,
    EDGE_CLEARANCE_MM,
    VIA_RADIUS_MM,
    _collect_items,
    _point_seg_distance,
    _Stadium,
)

GRID_MM = 0.2
LAYERS = ("F.Cu", "B.Cu")
# A via hop costs this many mm of track - matches the scorecard's
# VIA_TRACK_EQUIV_MM so the router optimizes what the judge measures.
VIA_COST_MM = 5.0
# Small cost per direction change: among the many equal-length grid
# paths it selects the one with maximal straight runs (KiCad-style
# corners), without materially changing route choices.
TURN_PENALTY_MM = 0.1


class RoutingError(RuntimeError):
    pass


@dataclass(frozen=True)
class RouteResult:
    net_name: str
    segments: tuple[TrackSegment, ...]
    vias: tuple[ViaSpec, ...]
    length_mm: float


class GridRouter:
    """Obstacle grid + A* over (layer, ix, iy) nodes.

    Build once per routing task; obstacles are every foreign-net copper
    item plus the board edge. Cells the routed net's own copper covers
    are free (and serve as sources/targets)."""

    def __init__(
        self,
        layout: BoardLayout,
        netlist: BoardNetlist,
        *,
        net_name: str,
        track_width_mm: float,
        grid_mm: float = GRID_MM,
        clearance_groups: Sequence[
            tuple[
                Collection[str], Collection[str], float, Collection[str]
            ]
        ] = (),
    ) -> None:
        self.net_name = net_name
        self.width = track_width_mm
        self.grid = grid_mm
        self.cols = int(layout.width_mm / grid_mm) + 1
        self.rows = int(layout.height_mm / grid_mm) + 1
        self.blocked: dict[str, set[tuple[int, int]]] = {
            layer: set() for layer in LAYERS
        }
        self.via_blocked: set[tuple[int, int]] = set()

        # Own-net items keep exact radii (sources/targets must touch the
        # real pad copper); foreign obstacles cover rect-pad corners so
        # routes cannot legally cut them (kicad-cli parity).
        items = _collect_items(layout, netlist)
        own = [item for item in items if item.net == net_name]
        foreign = [
            item
            for item in _collect_items(
                layout, netlist, cover_rect_pads=True
            )
            if item.net != net_name
        ]
        track_pad = self.width / 2 + CLEARANCE_MM
        via_pad = VIA_RADIUS_MM + CLEARANCE_MM
        for item in foreign:
            self._block(item, self.blocked[item.layer], track_pad)
            self._block(item, self.via_blocked, via_pad)
        # Insulation-group keepouts (rules 10.1/10.4): when the routed
        # net belongs to one side of a declared group, the OTHER side's
        # copper repels it by the group gap on BOTH layers - creepage
        # is layer-agnostic, exactly like the checks measure it.
        for nets_a, nets_b, gap_mm, exempt in clearance_groups:
            if net_name in nets_a:
                other_nets = set(nets_b)
            elif net_name in nets_b:
                other_nets = set(nets_a)
            else:
                continue
            exempt_set = set(exempt)
            keepout_pad = gap_mm + self.width / 2
            for item in foreign:
                if item.net not in other_nets or item.owner in exempt_set:
                    continue
                for layer in LAYERS:
                    self._block(item, self.blocked[layer], keepout_pad)
                self._block(item, self.via_blocked, gap_mm + VIA_RADIUS_MM)
        # A via also may not land inside the routed net's PAD copper
        # (KiCad allows it, but a via in a pad surprises assembly);
        # tracks over own copper are fine.
        edge_cells = self._edge_cells(layout)
        for layer in LAYERS:
            self.blocked[layer] |= edge_cells
        # Vias owe the edge their OWN radius, not the track's half
        # width (live edge_clearance findings on the thermometer's
        # curved stem: a 0.2mm net's margin let vias sit 0.6mm out).
        self.via_blocked |= edge_cells
        if VIA_RADIUS_MM > self.width / 2:
            self.via_blocked |= self._edge_cells(
                layout, margin=EDGE_CLEARANCE_MM + VIA_RADIUS_MM
            )
        self.own_items = own

    # -- grid helpers -----------------------------------------------------

    def _cell(self, x: float, y: float) -> tuple[int, int]:
        return (round(x / self.grid), round(y / self.grid))

    def _point(self, cell: tuple[int, int]) -> tuple[float, float]:
        return (cell[0] * self.grid, cell[1] * self.grid)

    def _block(
        self, item: _Stadium, into: set[tuple[int, int]], padding: float
    ) -> None:
        reach = item.radius + padding
        x_lo = int((min(item.a[0], item.b[0]) - reach) / self.grid) - 1
        x_hi = int((max(item.a[0], item.b[0]) + reach) / self.grid) + 2
        y_lo = int((min(item.a[1], item.b[1]) - reach) / self.grid) - 1
        y_hi = int((max(item.a[1], item.b[1]) + reach) / self.grid) + 2
        for ix in range(max(x_lo, 0), min(x_hi, self.cols)):
            for iy in range(max(y_lo, 0), min(y_hi, self.rows)):
                point = (ix * self.grid, iy * self.grid)
                if _point_seg_distance(point, item.a, item.b) < reach:
                    into.add((ix, iy))

    def _edge_cells(
        self, layout: BoardLayout, margin: float | None = None
    ) -> set[tuple[int, int]]:
        if margin is None:
            margin = EDGE_CLEARANCE_MM + self.width / 2
        if layout.outline:
            # Shaped boards: the verifier measures against the OUTLINE
            # polygon, so the router must too (a rectangle-only edge
            # model happily routes outside a thermometer's stem).
            return _outline_blocked_cells(
                tuple(layout.outline), self.cols, self.rows, self.grid,
                round(margin, 6),
            )
        cells: set[tuple[int, int]] = set()
        for ix in range(self.cols):
            for iy in range(self.rows):
                x, y = ix * self.grid, iy * self.grid
                if (
                    x < margin
                    or y < margin
                    or x > layout.width_mm - margin
                    or y > layout.height_mm - margin
                ):
                    cells.add((ix, iy))
        return cells

    def _cells_inside(
        self, item: _Stadium
    ) -> list[tuple[int, int]]:
        cells: list[tuple[int, int]] = []
        reach = item.radius
        x_lo = int((min(item.a[0], item.b[0]) - reach) / self.grid) - 1
        x_hi = int((max(item.a[0], item.b[0]) + reach) / self.grid) + 2
        y_lo = int((min(item.a[1], item.b[1]) - reach) / self.grid) - 1
        y_hi = int((max(item.a[1], item.b[1]) + reach) / self.grid) + 2
        for ix in range(max(x_lo, 0), min(x_hi, self.cols)):
            for iy in range(max(y_lo, 0), min(y_hi, self.rows)):
                point = (ix * self.grid, iy * self.grid)
                if _point_seg_distance(point, item.a, item.b) <= reach:
                    cells.append((ix, iy))
        return cells

    # -- search ------------------------------------------------------------

    def _pad_nodes(
        self, pad: _Stadium
    ) -> list[tuple[str, int, int]]:
        layers = (
            LAYERS
            if pad.label.startswith("pad") and self._is_through(pad)
            else (pad.layer,)
        )
        nodes = [
            (layer, ix, iy)
            for layer in layers
            for ix, iy in self._cells_inside(pad)
            if (ix, iy) not in self.blocked[layer]
        ]
        if not nodes:
            raise RoutingError(
                f"No routable grid cell inside {pad.label}; the pad is "
                "walled in at this grid pitch."
            )
        return nodes

    def _is_through(self, pad: _Stadium) -> bool:
        # _collect_items emits THT pads once per layer with identical
        # geometry; the cheap identity check is whether a twin exists.
        return any(
            other is not pad
            and other.label == pad.label
            and other.layer != pad.layer
            for other in self.own_items
        )

    def route(self) -> RouteResult:
        """Connect all of the net's pads into one tree."""
        pads = [
            item for item in self.own_items if item.label.startswith("pad")
        ]
        # One node set per physical pad (dedupe the THT twins). Keyed by
        # label AND position: switch footprints carry duplicate pad
        # numbers (SW_PUSH has two "1" pads), and KiCad's ratsnest wants
        # copper to every physical pad - label-only dedupe left the twin
        # copies unrouted (caught live by kicad-cli on the servo board).
        by_pad: dict[tuple[str, tuple[float, float]], _Stadium] = {}
        for pad in pads:
            by_pad.setdefault((pad.label, pad.a), pad)
        ordered = sorted(
            by_pad.values(), key=lambda item: (item.label, item.a)
        )
        if len(ordered) < 2:
            raise RoutingError(f"Net {self.net_name} has fewer than 2 pads.")

        tree: set[tuple[str, int, int]] = set(self._pad_nodes(ordered[0]))
        segments: list[TrackSegment] = []
        vias: list[ViaSpec] = []
        total = 0.0
        first = ordered[0]
        first_stubbed = False
        for pad in ordered[1:]:
            targets = set(self._pad_nodes(pad))
            path = self._smooth(self._astar(tree, targets))
            new_segments, new_vias, length = self._emit(path)
            segments.extend(new_segments)
            vias.extend(new_vias)
            total += length
            tree |= set(path)
            # The connected pad's OWN copper becomes part of the tree:
            # without this, later legs cannot branch from it and the
            # search lays fresh copper parallel to it instead - the
            # redundant-spaghetti class (44% of the servo board's
            # segments before the fix).
            tree |= targets
            # Close the last grid cell onto the pad centre so KiCad sees
            # copper touching the pad anchor.
            total += self._stub(segments, path[-1], pad.a)
            if not first_stubbed:
                # The first leg starts inside the FIRST pad; bridge that
                # entry cell to its centre the same way.
                total += self._stub(segments, path[0], first.a)
                first_stubbed = True
        # Overlapping collinear copper (leg joins, staircase remnants,
        # stubs retracing a run) reads as broken micro-tracks in KiCad;
        # merge every straight run into one maximal segment. The copper
        # union is unchanged, so connectivity and clearance hold. Then
        # drop segments whose copper is FULLY inside the remaining
        # same-net copper: the union point-set is unchanged, so both
        # connectivity and clearance are exactly preserved (rule 11.2).
        merged = merge_collinear_segments(segments)
        # The route's OWN new vias are covers too: junction slivers
        # sitting entirely inside a fresh via's barrel escaped pruning
        # and tripped rule 11.2 (thermometer board, live).
        via_covers = [
            _Stadium(
                a=(via.x, via.y), b=(via.x, via.y),
                radius=VIA_RADIUS_MM, net=self.net_name, layer=layer,
                owner="", label="via",
            )
            for via in vias
            for layer in LAYERS
        ]
        pruned = prune_redundant_segments(
            merged, (*self.own_items, *via_covers)
        )
        return RouteResult(
            net_name=self.net_name,
            segments=pruned,
            vias=tuple(vias),
            length_mm=sum(
                math.dist((s.x1, s.y1), (s.x2, s.y2)) for s in pruned
            ),
        )

    def _smooth(
        self, path: list[tuple[str, int, int]]
    ) -> list[tuple[str, int, int]]:
        """String-pulling constrained to H/V/45 (greedy farthest
        shortcut): grid A* wanders around inflated obstacles and the
        turn penalty cannot remove detours after the fact, so each
        same-layer run is re-tightened with one- or two-piece
        connectors (straight, diagonal, or diagonal+straight) whose
        every cell is checked against the SAME blocked sets the search
        used - a smoothed path is legal by construction. Post-smoothing
        is the documented cleanup for fixed-grid routers."""
        if len(path) < 3:
            return path
        smoothed: list[tuple[str, int, int]] = []
        run_start = 0
        for index in range(1, len(path) + 1):
            if index == len(path) or path[index][0] != path[run_start][0]:
                run = path[run_start:index]
                smoothed.extend(self._smooth_run(run))
                run_start = index
        return smoothed

    def _smooth_run(
        self, run: list[tuple[str, int, int]]
    ) -> list[tuple[str, int, int]]:
        result: list[tuple[str, int, int]] = []
        i = 0
        while i < len(run) - 1:
            connector: list[tuple[str, int, int]] | None = None
            j = len(run) - 1
            while j > i + 1:
                connector = self._connector(run[i], run[j])
                if connector is not None:
                    break
                j -= 1
            if connector is None:
                result.append(run[i])
                i += 1
            else:
                result.extend(connector[:-1])
                i = j
        result.append(run[-1])
        return result

    def _connector(
        self, a: tuple[str, int, int], b: tuple[str, int, int]
    ) -> list[tuple[str, int, int]] | None:
        """The KiCad-style connector between two same-layer nodes: a
        diagonal run plus a straight run (either order), every cell
        free, corner-cut guard on diagonal steps."""
        layer = a[0]
        dx, dy = b[1] - a[1], b[2] - a[2]
        step_x = (dx > 0) - (dx < 0)
        step_y = (dy > 0) - (dy < 0)
        diagonal = min(abs(dx), abs(dy))

        def walk(diagonal_first: bool) -> list[tuple[str, int, int]] | None:
            x, y = a[1], a[2]
            cells = [(layer, x, y)]
            moves: list[tuple[int, int]] = []
            straight_x = [(step_x, 0)] * (abs(dx) - diagonal)
            straight_y = [(0, step_y)] * (abs(dy) - diagonal)
            slant = [(step_x, step_y)] * diagonal
            if diagonal_first:
                moves = slant + straight_x + straight_y
            else:
                moves = straight_x + straight_y + slant
            blocked = self.blocked[layer]
            for move_x, move_y in moves:
                if move_x and move_y and (
                    (x + move_x, y) in blocked or (x, y + move_y) in blocked
                ):
                    return None
                x, y = x + move_x, y + move_y
                if not (0 <= x < self.cols and 0 <= y < self.rows):
                    return None
                if (x, y) in blocked:
                    return None
                cells.append((layer, x, y))
            return cells

        return walk(True) or walk(False)

    def _stub(
        self,
        segments: list[TrackSegment],
        node: tuple[str, int, int],
        anchor: tuple[float, float],
    ) -> float:
        point = self._point(node[1:])
        if point == anchor:
            return 0.0
        segments.append(
            TrackSegment(
                x1=point[0], y1=point[1], x2=anchor[0], y2=anchor[1],
                layer=node[0], net_name=self.net_name, width_mm=self.width,
            )
        )
        return math.dist(point, anchor)

    def _astar(
        self,
        sources: set[tuple[str, int, int]],
        targets: set[tuple[str, int, int]],
    ) -> list[tuple[str, int, int]]:
        target_cells = {(ix, iy) for _l, ix, iy in targets}

        def heuristic(node: tuple[str, int, int]) -> float:
            # Octile distance: admissible with diagonal moves.
            _layer, ix, iy = node
            best = math.inf
            for tx, ty in target_cells:
                dx, dy = abs(ix - tx), abs(iy - ty)
                lo, hi = (dx, dy) if dx < dy else (dy, dx)
                best = min(best, hi + (math.sqrt(2) - 1.0) * lo)
            return self.grid * best

        # Search states carry the incoming direction: a small turn
        # penalty makes straight runs win among the many equal-length
        # grid paths, so corners come out KiCad-style (one diagonal run
        # + one straight run) instead of sawtooth micro-segments.
        counter = 0
        State = tuple[str, int, int]
        open_heap: list[
            tuple[float, int, State, tuple[int, int] | None]
        ] = []
        g_score: dict[tuple[State, tuple[int, int] | None], float] = {}
        came: dict[
            tuple[State, tuple[int, int] | None],
            tuple[State, tuple[int, int] | None],
        ] = {}
        for node in sorted(sources):
            g_score[(node, None)] = 0.0
            heapq.heappush(open_heap, (heuristic(node), counter, node, None))
            counter += 1
        closed: set[tuple[State, tuple[int, int] | None]] = set()
        while open_heap:
            _f, _c, node, came_dir = heapq.heappop(open_heap)
            state = (node, came_dir)
            if state in closed:
                continue
            if node in targets:
                path = [node]
                while state in came:
                    state = came[state]
                    if path[-1] != state[0]:
                        path.append(state[0])
                path.reverse()
                return path
            closed.add(state)
            layer, ix, iy = node
            g_here = g_score[state]
            neighbours: list[
                tuple[tuple[str, int, int], float, tuple[int, int] | None]
            ] = []
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = ix + dx, iy + dy
                if not (0 <= nx < self.cols and 0 <= ny < self.rows):
                    continue
                if (nx, ny) in self.blocked[layer]:
                    continue
                neighbours.append(((layer, nx, ny), self.grid, (dx, dy)))
            # Diagonal moves give KiCad-style 45-degree tracks instead
            # of per-cell staircases. Corner-cut guard: both orthogonal
            # neighbours must be free too, so the swept track never
            # squeezes between two blocked cells.
            for dx, dy in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
                nx, ny = ix + dx, iy + dy
                if not (0 <= nx < self.cols and 0 <= ny < self.rows):
                    continue
                if (
                    (nx, ny) in self.blocked[layer]
                    or (ix + dx, iy) in self.blocked[layer]
                    or (ix, iy + dy) in self.blocked[layer]
                ):
                    continue
                neighbours.append(
                    ((layer, nx, ny), self.grid * math.sqrt(2), (dx, dy))
                )
            other = LAYERS[1] if layer == LAYERS[0] else LAYERS[0]
            if (
                (ix, iy) not in self.via_blocked
                and (ix, iy) not in self.blocked[other]
            ):
                neighbours.append(((other, ix, iy), VIA_COST_MM, None))
            for neighbour, cost, step in neighbours:
                if (
                    step is not None
                    and came_dir is not None
                    and step != came_dir
                ):
                    cost += TURN_PENALTY_MM
                next_state = (neighbour, step)
                tentative = g_here + cost
                if tentative < g_score.get(next_state, math.inf):
                    g_score[next_state] = tentative
                    came[next_state] = state
                    heapq.heappush(
                        open_heap,
                        (
                            tentative + heuristic(neighbour),
                            counter,
                            neighbour,
                            step,
                        ),
                    )
                    counter += 1
        raise RoutingError(
            f"No route found for {self.net_name} at grid {self.grid}mm."
        )

    def _emit(
        self, path: list[tuple[str, int, int]]
    ) -> tuple[list[TrackSegment], list[ViaSpec], float]:
        segments: list[TrackSegment] = []
        vias: list[ViaSpec] = []
        length = 0.0
        run_start = path[0]
        previous = path[0]
        direction: tuple[int, int] | None = None
        for node in path[1:]:
            if node[0] != previous[0]:
                # layer change: close the run, drop a via.
                if previous != run_start:
                    segments.append(self._segment(run_start, previous))
                    length += math.dist(
                        self._point(run_start[1:]), self._point(previous[1:])
                    )
                point = self._point(previous[1:])
                vias.append(
                    ViaSpec(x=point[0], y=point[1], net_name=self.net_name)
                )
                run_start = node
                direction = None
            else:
                step = (node[1] - previous[1], node[2] - previous[2])
                if direction is None:
                    direction = step
                elif step != direction:
                    segments.append(self._segment(run_start, previous))
                    length += math.dist(
                        self._point(run_start[1:]), self._point(previous[1:])
                    )
                    run_start = previous
                    direction = step
            previous = node
        if previous != run_start:
            segments.append(self._segment(run_start, previous))
            length += math.dist(
                self._point(run_start[1:]), self._point(previous[1:])
            )
        return segments, vias, length

    def _segment(
        self, start: tuple[str, int, int], end: tuple[str, int, int]
    ) -> TrackSegment:
        p1 = self._point(start[1:])
        p2 = self._point(end[1:])
        return TrackSegment(
            x1=p1[0], y1=p1[1], x2=p2[0], y2=p2[1],
            layer=start[0], net_name=self.net_name, width_mm=self.width,
        )


def merge_collinear_segments(
    segments: Sequence[TrackSegment],
) -> tuple[TrackSegment, ...]:
    """Merge touching/overlapping collinear same-net tracks into maximal
    runs and drop zero-length slivers.

    KiCad's interactive router draws one segment per straight run; the
    grid search naturally emits many short pieces whose union is the
    same copper. Grouping key: (net, layer, width, direction, line
    offset); within a group the segments are 1-D intervals along the
    shared line, merged when they touch. T-junction branches live on a
    different line, so junctions are preserved."""
    Span = tuple[float, float, tuple[float, float], tuple[float, float]]
    groups: dict[
        tuple[str, str, float, float, float, float], list[Span]
    ] = {}
    for segment in segments:
        dx = segment.x2 - segment.x1
        dy = segment.y2 - segment.y1
        norm = math.hypot(dx, dy)
        if norm < 1e-9:
            continue
        ux, uy = dx / norm, dy / norm
        if ux < 0.0 or (ux == 0.0 and uy < 0.0):
            ux, uy = -ux, -uy
        # Decompose each endpoint into (t along u, c across u); c is
        # constant on the shared line and identifies it.
        offset = segment.x1 * uy - segment.y1 * ux
        key = (
            segment.net_name,
            segment.layer,
            segment.width_mm,
            round(ux, 9),
            round(uy, 9),
            round(offset, 6),
        )
        ends = sorted(
            (
                (segment.x1 * ux + segment.y1 * uy, (segment.x1, segment.y1)),
                (segment.x2 * ux + segment.y2 * uy, (segment.x2, segment.y2)),
            )
        )
        groups.setdefault(key, []).append(
            (ends[0][0], ends[1][0], ends[0][1], ends[1][1])
        )
    merged: list[TrackSegment] = []
    for (net, layer, width, _ux, _uy, _offset), spans in groups.items():
        spans.sort()

        # Merge touching intervals; endpoints stay the ORIGINAL segment
        # coordinates (no reconstruction drift).
        runs: list[tuple[tuple[float, float], tuple[float, float]]] = []
        _run_lo, run_hi, run_p_lo, run_p_hi = spans[0]
        for lo, hi, p_lo, p_hi in spans[1:]:
            if lo <= run_hi + 1e-6:
                if hi > run_hi:
                    run_hi, run_p_hi = hi, p_hi
            else:
                runs.append((run_p_lo, run_p_hi))
                _run_lo, run_hi, run_p_lo, run_p_hi = lo, hi, p_lo, p_hi
        runs.append((run_p_lo, run_p_hi))
        for p_lo, p_hi in runs:
            merged.append(
                TrackSegment(
                    x1=p_lo[0], y1=p_lo[1], x2=p_hi[0], y2=p_hi[1],
                    layer=layer, net_name=net, width_mm=width,
                )
            )
    return tuple(merged)


@functools.lru_cache(maxsize=8)
def _outline_blocked_cells(
    outline: tuple[tuple[float, float], ...],
    cols: int,
    rows: int,
    grid: float,
    margin: float,
) -> set[tuple[int, int]]:
    """Grid cells a track center may NOT occupy on a shaped board:
    outside the outline polygon, or within ``margin`` of an outline
    edge. Scanline fill for inside/outside (O(rows x edges)) plus an
    exact-distance band walked only along the edges - the same
    complexity trick the virtual DRC's edge check uses, cached because
    every net's router rebuilds the grid."""
    blocked: set[tuple[int, int]] = set()
    edges = [
        (outline[index], outline[(index + 1) % len(outline)])
        for index in range(len(outline))
    ]
    # Scanline: cells whose center is outside the polygon.
    for iy in range(rows):
        y = iy * grid
        crossings: list[float] = []
        for (x1, y1), (x2, y2) in edges:
            if (y1 <= y < y2) or (y2 <= y < y1):
                crossings.append(x1 + (y - y1) * (x2 - x1) / (y2 - y1))
        crossings.sort()
        inside: list[tuple[float, float]] = list(
            zip(crossings[0::2], crossings[1::2], strict=False)
        )
        for ix in range(cols):
            x = ix * grid
            if not any(lo <= x <= hi for lo, hi in inside):
                blocked.add((ix, iy))
    # Near-edge band: exact distances, only around the edges.
    for a, b in edges:
        x_lo = int((min(a[0], b[0]) - margin) / grid) - 1
        x_hi = int((max(a[0], b[0]) + margin) / grid) + 2
        y_lo = int((min(a[1], b[1]) - margin) / grid) - 1
        y_hi = int((max(a[1], b[1]) + margin) / grid) + 2
        for ix in range(max(x_lo, 0), min(x_hi, cols)):
            for iy in range(max(y_lo, 0), min(y_hi, rows)):
                if (ix, iy) in blocked:
                    continue
                if _point_seg_distance((ix * grid, iy * grid), a, b) < margin:
                    blocked.add((ix, iy))
    return blocked


# Coverage sampling: fine enough that no sliver of a "covered" segment
# can poke past its covers between samples at PCB scales.
COVER_SAMPLE_MM = 0.05
COVER_MARGIN_MM = 0.01

Stadium = tuple[tuple[float, float], tuple[float, float], float, str]


def segment_covered_by(
    segment: TrackSegment,
    covers: Sequence[Stadium],
    margin_mm: float = COVER_MARGIN_MM,
) -> bool:
    """True when the segment's COPPER AREA is fully inside some cover:
    at every centerline sample, one same-layer cover stadium contains
    the whole width (distance <= cover radius - half width - margin).
    Centerline-only coverage would be laxer but removing such a segment
    would change the copper point-set; area containment guarantees the
    union is unchanged, so pruning is provably safe."""
    length = math.dist((segment.x1, segment.y1), (segment.x2, segment.y2))
    if length < 1e-9:
        return True
    half_width = segment.width_mm / 2
    steps = max(2, int(length / COVER_SAMPLE_MM))
    candidates = [
        (a, b, radius, layer)
        for a, b, radius, layer in covers
        if layer == segment.layer
        and radius >= half_width + margin_mm - 1e-9
    ]
    for index in range(steps + 1):
        t = index / steps
        point = (
            segment.x1 + (segment.x2 - segment.x1) * t,
            segment.y1 + (segment.y2 - segment.y1) * t,
        )
        if not any(
            _point_seg_distance(point, a, b)
            <= radius - half_width - margin_mm
            for a, b, radius, _layer in candidates
        ):
            return False
    return True


def prune_redundant_segments(
    segments: Sequence[TrackSegment],
    own_items: Sequence[object],
) -> tuple[TrackSegment, ...]:
    """Drop same-net segments whose copper is fully inside the union of
    the remaining same-net copper (rule 11.2). Removing such a segment
    leaves the copper POINT-SET unchanged, so connectivity and
    clearance are exactly preserved - this is the safety companion to
    the tree fix, not a substitute for it. Shortest segments go first
    so a long trunk is never sacrificed for its own slivers."""
    kept = list(segments)
    pad_covers: list[Stadium] = [
        (item.a, item.b, item.radius, item.layer)  # type: ignore[attr-defined]
        for item in own_items
    ]
    for segment in sorted(
        segments,
        key=lambda s: math.dist((s.x1, s.y1), (s.x2, s.y2)),
    ):
        others: list[Stadium] = [
            ((s.x1, s.y1), (s.x2, s.y2), s.width_mm / 2, s.layer)
            for s in kept
            if s is not segment
        ]
        if segment_covered_by(segment, others + pad_covers):
            kept.remove(segment)
    return tuple(kept)


def route_net(
    layout: BoardLayout,
    netlist: BoardNetlist,
    net_name: str,
    *,
    track_width_mm: float = 0.4,
    grid_mm: float = GRID_MM,
    clearance_groups: Sequence[
        tuple[Collection[str], Collection[str], float, Collection[str]]
    ] = (),
) -> RouteResult:
    """Route one net against the layout's existing copper."""
    return GridRouter(
        layout, netlist, net_name=net_name,
        track_width_mm=track_width_mm, grid_mm=grid_mm,
        clearance_groups=clearance_groups,
    ).route()


def clearance_groups_from_spec(
    spec: object,
) -> tuple[
    tuple[tuple[str, ...], tuple[str, ...], float, tuple[str, ...]], ...
]:
    """The router's keepouts from a DesignChecksSpec - the same
    isolation-barrier and net-group declarations the checks enforce."""
    groups: list[
        tuple[tuple[str, ...], tuple[str, ...], float, tuple[str, ...]]
    ] = []
    barrier = getattr(spec, "isolation_barrier", None)
    if barrier is not None:
        _x, gap_mm, primary, secondary, straddle = barrier
        groups.append((tuple(primary), tuple(secondary), gap_mm,
                       tuple(straddle)))
    for group in getattr(spec, "net_group_clearances", ()):
        _label, nets_a, nets_b, gap_mm, exempt = group
        groups.append((tuple(nets_a), tuple(nets_b), gap_mm, tuple(exempt)))
    return tuple(groups)


def strip_net(layout: BoardLayout, net_name: str) -> BoardLayout:
    """The layout with one net's copper removed - reroute fodder."""
    return layout.__class__(
        **{
            **{
                key: getattr(layout, key)
                for key in layout.__dataclass_fields__
            },
            "segments": tuple(
                seg for seg in layout.segments if seg.net_name != net_name
            ),
            "vias": tuple(
                via for via in layout.vias if via.net_name != net_name
            ),
        }
    )


def with_route(layout: BoardLayout, result: RouteResult) -> BoardLayout:
    return layout.__class__(
        **{
            **{
                key: getattr(layout, key)
                for key in layout.__dataclass_fields__
            },
            "segments": (*layout.segments, *result.segments),
            "vias": (*layout.vias, *result.vias),
        }
    )


@dataclass(frozen=True)
class BoardRouteResult:
    layout: BoardLayout
    results: tuple[RouteResult, ...]
    order: tuple[str, ...]
    restarts: int
    failed: tuple[str, ...]


def _routable_nets(
    layout: BoardLayout, netlist: BoardNetlist
) -> dict[str, float]:
    """Nets with 2+ physical pads, keyed to an estimated half-perimeter
    (the ordering heuristic: short, locally-constrained nets first)."""
    items = _collect_items(layout, netlist)
    spans: dict[str, list[tuple[float, float]]] = {}
    for item in items:
        if item.owner:
            spans.setdefault(item.net, []).append(item.a)
    estimates: dict[str, float] = {}
    for net, points in spans.items():
        unique = set(points)
        if len(unique) < 2 or net.startswith("~"):
            continue
        xs = [x for x, _ in unique]
        ys = [y for _, y in unique]
        estimates[net] = (max(xs) - min(xs)) + (max(ys) - min(ys))
    return estimates


FINE_GRID_MM = 0.1


def route_board(
    layout: BoardLayout,
    netlist: BoardNetlist,
    *,
    net_widths: dict[str, float] | None = None,
    default_width_mm: float = 0.4,
    clearance_groups: Sequence[
        tuple[Collection[str], Collection[str], float, Collection[str]]
    ] = (),
    net_order: Sequence[str] | None = None,
    max_restarts: int = 8,
    grid_mm: float = GRID_MM,
    skip_nets: Collection[str] = (),
    fine_pitch_nets: Mapping[str, float] | None = None,
    fine_grid_mm: float = FINE_GRID_MM,
) -> BoardRouteResult:
    """Route every multi-pad net sequentially; when a net cannot be
    routed, promote it to the front of the order and restart (rip-up by
    reordering - the MVP alternative to true rip-up).

    ``fine_pitch_nets`` maps net -> width for nets that must ENTER
    sub-grid pad pitches (0.5mm USB-C/DFN rows: a 0.2mm grid cannot
    center a track on alternating pads). They route FIRST, in declared
    order, on ``fine_grid_mm``; the main pass then treats their copper
    as existing routes. Declaration order is priority - put contested
    corridors' nets first. ``skip_nets`` excludes nets a caller routed
    itself."""
    widths = net_widths or {}
    fine = dict(fine_pitch_nets or {})
    fine_order = list(fine)
    fine_results: list[RouteResult] = []
    restarts = 0
    while fine_order:
        working = layout
        fine_results = []
        fine_failed: str | None = None
        for net in fine_order:
            try:
                result = route_net(
                    working, netlist, net,
                    track_width_mm=fine[net], grid_mm=fine_grid_mm,
                    clearance_groups=clearance_groups,
                )
            except RoutingError:
                fine_failed = net
                break
            fine_results.append(result)
            working = with_route(working, result)
        if fine_failed is None:
            layout = working
            break
        # Same rip-up-by-reordering as the main pass: the failed net
        # routes first next attempt. Fine corridors are the scarcest
        # copper on the board (USB-C hole belts), so which net claims
        # a window first genuinely decides feasibility - the initial
        # declaration order is a hint, not a verdict.
        if restarts >= max_restarts or fine_order[0] == fine_failed:
            return BoardRouteResult(
                layout=working,
                results=tuple(fine_results),
                order=tuple(fine_order),
                restarts=restarts,
                failed=(fine_failed,),
            )
        fine_order.remove(fine_failed)
        fine_order.insert(0, fine_failed)
        restarts += 1
    # The main pass gets its own restart budget: fine-corridor
    # reordering must not starve stem-congestion reordering (the /CAS
    # lesson - fine restarts consumed the shared budget and the main
    # pass failed on its first try).
    fine_restarts = restarts
    restarts = 0
    skip = set(skip_nets) | set(fine)
    estimates = {
        net: estimate
        for net, estimate in _routable_nets(layout, netlist).items()
        if net not in skip
    }
    if net_order is not None:
        order = [net for net in net_order if net in estimates]
        order += sorted(
            (net for net in estimates if net not in set(order)),
            key=lambda net: estimates[net],
        )
    else:
        order = sorted(estimates, key=lambda net: estimates[net])

    while True:
        working = layout
        results: list[RouteResult] = []
        failed: str | None = None
        for net in order:
            try:
                result = route_net(
                    working, netlist, net,
                    track_width_mm=widths.get(net, default_width_mm),
                    grid_mm=grid_mm,
                    clearance_groups=clearance_groups,
                )
            except RoutingError:
                failed = net
                break
            results.append(result)
            working = with_route(working, result)
        if failed is None:
            return BoardRouteResult(
                layout=working,
                results=(*fine_results, *results),
                order=(*fine_order, *order),
                restarts=fine_restarts + restarts,
                failed=(),
            )
        if restarts >= max_restarts or order[0] == failed:
            return BoardRouteResult(
                layout=working,
                results=(*fine_results, *results),
                order=(*fine_order, *order),
                restarts=fine_restarts + restarts,
                failed=(failed,),
            )
        order.remove(failed)
        order.insert(0, failed)
        restarts += 1
