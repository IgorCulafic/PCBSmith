"""Deterministic geometric design checks over a computed board layout.

Each check encodes a rule from docs/pcb-design-rules.md that was originally
discovered by visual review. Once a visual finding is expressible as geometry
it is promoted here so it never needs eyes again; the model reviewer only
handles what cannot be computed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pcbsmith.circuit.models import DesignReviewReport, ReviewFinding
from pcbsmith.kicad.board import (
    FOOTPRINT_LIBRARY,
    PART_GAP_MM,
    BoardLayout,
    BoardNetlist,
    placement_rotation,
    placement_y,
    rotate_offset,
    rotated_bounds,
)

CONNECTOR_EDGE_ZONE_MM = 6.0
SWITCHING_CLUSTER_SLACK_MM = 6.0
SENSITIVE_INDUCTOR_CLEARANCE_MM = 8.0


@dataclass(frozen=True)
class DesignChecksSpec:
    """Topology-provided parameters for the geometric checks."""

    switching_cluster_refs: tuple[str, ...] = ()
    sensitive_net_names: tuple[str, ...] = ()
    inductor_references: tuple[str, ...] = ()
    # Series LED strings in supply-to-ground order: (resistor, led, led, ...).
    led_strings: tuple[tuple[str, ...], ...] = ()
    # Rule 9.1 keepouts: (center_x, center_y, radius, allowed net names).
    # No zone may intersect the circle; only allowed-net copper may.
    copper_keepouts: tuple[
        tuple[float, float, float, tuple[str, ...]], ...
    ] = ()
    # Rule 5.3: (net name, load current in amps) pairs; every segment of
    # the net must carry the current per IPC-2221 at a 10 C rise.
    net_currents: tuple[tuple[str, float], ...] = ()
    # Rule 7.3: (reference, pad name) pairs that are REVIEWED no-connects
    # (datasheet-documented RESV/unused pins). Any other unconnected pad
    # on a 3+ pin part is a blocker.
    allowed_unconnected_pins: tuple[tuple[str, str], ...] = ()
    # Rule 7.4: (reference, card mpn) pairs; the part's connectivity must
    # honour its component card. Cards also feed 7.3's whitelist.
    component_cards: tuple[tuple[str, str], ...] = ()
    # Net-class map for must_tie pins, e.g. (("GND", "/GND"),).
    tie_nets: tuple[tuple[str, str], ...] = ()
    # Rule 7.5: composition roles present in the circuit, for validating
    # the cards' required support parts.
    composition_roles: tuple[str, ...] = ()
    # Rule 10.1: (barrier_x, gap_mm, primary nets, secondary nets,
    # straddle refs whose pads are exempt - certified isolation parts).
    isolation_barrier: tuple[
        float, float, tuple[str, ...], tuple[str, ...], tuple[str, ...]
    ] | None = None
    # Rule 10.4: pairwise copper clearance between two net GROUPS with no
    # barrier-line geometry - e.g. protective EARTH vs the mains nets,
    # where only the certified line Y-caps may bridge. Each entry is
    # (label, nets_a, nets_b, gap_mm, exempt refs).
    net_group_clearances: tuple[
        tuple[str, tuple[str, ...], tuple[str, ...], float, tuple[str, ...]],
        ...,
    ] = ()
    extra_model_findings: tuple[ReviewFinding, ...] = field(default=())


def run_design_checks(
    layout: BoardLayout,
    netlist: BoardNetlist,
    spec: DesignChecksSpec,
) -> DesignReviewReport:
    checks_run: list[str] = []
    findings: list[ReviewFinding] = []

    checks_run.append("connector_edge")
    findings.extend(_check_connector_edges(layout))

    if spec.switching_cluster_refs:
        checks_run.append("switching_cluster")
        findings.extend(_check_switching_cluster(layout, spec.switching_cluster_refs))

    if spec.sensitive_net_names and spec.inductor_references:
        checks_run.append("sensitive_net_under_inductor")
        findings.extend(
            _check_sensitive_net_under_inductor(
                layout,
                spec.sensitive_net_names,
                spec.inductor_references,
            )
        )

    if spec.led_strings:
        checks_run.append("series_led_polarity")
        findings.extend(_check_series_led_polarity(netlist, spec.led_strings))

    if layout.outline:
        checks_run.append("outline_is_simple")
        findings.extend(_check_outline_is_simple(layout))

    if spec.copper_keepouts:
        checks_run.append("copper_keepout")
        findings.extend(_check_copper_keepouts(layout, spec.copper_keepouts))

    if spec.net_currents:
        checks_run.append("trace_current")
        findings.extend(_check_trace_currents(layout, spec.net_currents))

    allowed_unconnected = set(spec.allowed_unconnected_pins)
    if spec.component_cards:
        from pcbsmith.components import (
            card_contract_findings,
            load_card,
            support_findings,
        )

        checks_run.append("component_card_contract")
        tie_map = dict(spec.tie_nets)
        roles = set(spec.composition_roles)
        for reference, mpn in spec.component_cards:
            card = load_card(mpn)
            findings.extend(
                card_contract_findings(card, reference, netlist, tie_map)
            )
            if roles:
                findings.extend(support_findings(card, reference, roles))
            # The card's reviewed NC pins feed rule 7.3's whitelist.
            allowed_unconnected.update(
                (reference, pin) for pin in card.nc_pins()
            )

    if spec.net_group_clearances:
        checks_run.append("net_group_clearance")
        for group in spec.net_group_clearances:
            findings.extend(_check_net_group_clearance(layout, netlist, group))

    if spec.isolation_barrier is not None:
        checks_run.append("isolation_barrier")
        findings.extend(
            _check_isolation_barrier(layout, netlist, spec.isolation_barrier)
        )

    checks_run.append("ic_pin_connectivity")
    findings.extend(
        _check_ic_pin_connectivity(
            layout, netlist, tuple(sorted(allowed_unconnected))
        )
    )

    findings.extend(spec.extra_model_findings)

    if any(finding.severity == "blocker" for finding in findings):
        status = "failed"
    elif findings:
        status = "needs_human_review"
    else:
        status = "passed"
    return DesignReviewReport(
        status=status,
        checks_run=tuple(checks_run),
        findings=tuple(findings),
    )


def _segments_intersect(
    a1: tuple[float, float],
    a2: tuple[float, float],
    b1: tuple[float, float],
    b2: tuple[float, float],
) -> bool:
    def orient(
        p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]
    ) -> float:
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    d1 = orient(b1, b2, a1)
    d2 = orient(b1, b2, a2)
    d3 = orient(a1, a2, b1)
    d4 = orient(a1, a2, b2)
    return d1 * d2 < 0 and d3 * d4 < 0


def _check_outline_is_simple(layout: BoardLayout) -> tuple[ReviewFinding, ...]:
    # Rule 5.2: a shaped outline must be a simple closed polygon. A single
    # mirrored arc constant once swept the pear outline through the board
    # body and produced 90+ downstream violations; this catches it at the
    # source.
    if layout.outline is None:
        return ()
    points = layout.outline
    count = len(points)
    edges = [(points[i], points[(i + 1) % count]) for i in range(count)]
    for i in range(count):
        for j in range(i + 2, count):
            if i == 0 and j == count - 1:
                continue
            if _segments_intersect(*edges[i], *edges[j]):
                crossing_x = (edges[i][0][0] + edges[j][0][0]) / 2
                crossing_y = (edges[i][0][1] + edges[j][0][1]) / 2
                return (
                    ReviewFinding(
                        rule="5.2",
                        severity="blocker",
                        scope="global",
                        where="outline",
                        evidence=(
                            f"Outline edges {i} and {j} intersect near "
                            f"({crossing_x:.1f}, {crossing_y:.1f})mm; the "
                            "board polygon is self-intersecting."
                        ),
                        suggested_action=(
                            "Fix the outline construction (arc sweep "
                            "direction or splice window) so the polygon is "
                            "simple."
                        ),
                        source="check",
                    ),
                )
    return ()


def _check_copper_keepouts(
    layout: BoardLayout,
    keepouts: tuple[tuple[float, float, float, tuple[str, ...]], ...],
) -> tuple[ReviewFinding, ...]:
    # Rule 9.1: no pour/plane and no foreign copper inside a sensing
    # keepout (a plane under a coil is a shorted turn).
    findings: list[ReviewFinding] = []
    for center_x, center_y, radius, allowed in keepouts:
        for zone_net, _layer, rect in layout.zones:
            x1, y1, x2, y2 = rect
            nearest_x = min(max(center_x, x1), x2)
            nearest_y = min(max(center_y, y1), y2)
            if (nearest_x - center_x) ** 2 + (nearest_y - center_y) ** 2 < radius**2:
                findings.append(
                    ReviewFinding(
                        rule="9.1",
                        severity="blocker",
                        scope="region",
                        where=f"zone {zone_net}",
                        evidence=(
                            f"Zone {zone_net} rect {rect} intersects the "
                            f"copper keepout at ({center_x:g}, {center_y:g}) "
                            f"r={radius:g}mm."
                        ),
                        suggested_action=(
                            "Clip the zone away from the sensing region; a "
                            "plane under a coil acts as a shorted turn."
                        ),
                        source="check",
                    )
                )
        for segment in layout.segments:
            if segment.net_name in allowed:
                continue
            mid_x = (segment.x1 + segment.x2) / 2
            mid_y = (segment.y1 + segment.y2) / 2
            probes = (
                (segment.x1, segment.y1),
                (mid_x, mid_y),
                (segment.x2, segment.y2),
            )
            for x, y in probes:
                if (x - center_x) ** 2 + (y - center_y) ** 2 < radius**2:
                    findings.append(
                        ReviewFinding(
                            rule="9.1",
                            severity="blocker",
                            scope="net",
                            where=segment.net_name,
                            evidence=(
                                f"Track [{segment.net_name}] enters the "
                                f"copper keepout near ({x:.1f}, {y:.1f})mm."
                            ),
                            suggested_action=(
                                "Route around the sensing region or add the "
                                "net to the keepout allow list."
                            ),
                            source="check",
                        )
                    )
                    break
    return tuple(findings)


def _check_ic_pin_connectivity(
    layout: BoardLayout,
    netlist: BoardNetlist,
    allowed_unconnected: tuple[tuple[str, str], ...],
) -> tuple[ReviewFinding, ...]:
    # Rule 7.3: an IC pin that silently misses the netlist is the worst
    # kind of failure - ERC cannot see it (the symbol simply lacks the
    # wire) and DRC cannot see it (no net means no ratsnest). Compare the
    # FOOTPRINT's named pads against the netlist for every 3+ pin part.
    connected = {
        (reference, pin)
        for net in netlist.nets
        for reference, pin in net.nodes
    }
    allowed = set(allowed_unconnected)
    findings: list[ReviewFinding] = []
    for component, _anchor_x in layout.placements:
        spec = FOOTPRINT_LIBRARY[component.footprint]
        named_pads = sorted(
            {pad.name for pad in spec.pads if pad.name},
            key=lambda name: (len(name), name),
        )
        if len(named_pads) < 3:
            continue
        for pad_name in named_pads:
            key = (component.reference, pad_name)
            if key in connected or key in allowed:
                continue
            findings.append(
                ReviewFinding(
                    rule="7.3",
                    severity="blocker",
                    scope="component",
                    where=component.reference,
                    evidence=(
                        f"{component.reference} pad {pad_name} "
                        f"({component.footprint}) is on no net and is not "
                        "on the reviewed no-connect list."
                    ),
                    suggested_action=(
                        "Wire the pin per the datasheet, or add it to "
                        "allowed_unconnected_pins with the datasheet "
                        "locator justifying the no-connect."
                    ),
                    source="check",
                )
            )
    return tuple(findings)


def _check_net_group_clearance(
    layout: BoardLayout,
    netlist: BoardNetlist,
    group: tuple[str, tuple[str, ...], tuple[str, ...], float, tuple[str, ...]],
) -> tuple[ReviewFinding, ...]:
    """Rule 10.4: minimum copper distance between two net groups, with
    the declared bridging parts (certified safety components) exempt."""
    from pcbsmith.kicad.virtual_drc import _collect_items, _seg_seg_distance

    label, nets_a, nets_b, gap_mm, exempt = group
    items = _collect_items(layout, netlist)
    exempt_set = set(exempt)
    group_a = [
        item for item in items
        if item.net in nets_a and item.owner not in exempt_set
    ]
    group_b = [
        item for item in items
        if item.net in nets_b and item.owner not in exempt_set
    ]
    findings: list[ReviewFinding] = []
    worst_distance = 1e9
    worst_pair = None
    for one in group_a:
        for two in group_b:
            distance = (
                _seg_seg_distance(one.a, one.b, two.a, two.b)
                - one.radius - two.radius
            )
            if distance < worst_distance:
                worst_distance = distance
                worst_pair = (one, two)
    if worst_pair is not None and worst_distance < gap_mm:
        one, two = worst_pair
        findings.append(
            ReviewFinding(
                rule="10.4",
                severity="blocker",
                scope="global",
                where=label,
                evidence=(
                    f"Clearance between {one.label} and {two.label} is "
                    f"{worst_distance:.2f}mm; {label} requires >= "
                    f"{gap_mm:g}mm."
                ),
                suggested_action=(
                    "Move the copper apart or route the connection through "
                    "a declared certified bridging part."
                ),
                source="check",
            )
        )
    return tuple(findings)


def _check_isolation_barrier(
    layout: BoardLayout,
    netlist: BoardNetlist,
    barrier: tuple[
        float, float, tuple[str, ...], tuple[str, ...], tuple[str, ...]
    ],
) -> tuple[ReviewFinding, ...]:
    # Rule 10.1: mains isolation. Every piece of primary-net copper must
    # stay >= gap away from every piece of secondary-net copper, except
    # the pads of the declared straddle parts (transformer, optocoupler,
    # Y-capacitor - parts whose internal isolation is a certified rating).
    from pcbsmith.kicad.virtual_drc import (
        _collect_items,
        _seg_seg_distance,
        _Stadium,
    )

    barrier_x, gap_mm, primary_nets, secondary_nets, straddle = barrier
    items = _collect_items(layout, netlist)
    primary = [
        item for item in items
        if item.net in primary_nets and item.owner not in straddle
    ]
    secondary = [
        item for item in items
        if item.net in secondary_nets and item.owner not in straddle
    ]
    findings: list[ReviewFinding] = []
    worst_distance = 1e9
    worst_pair: tuple[_Stadium, _Stadium] | None = None
    for one in primary:
        for two in secondary:
            distance = (
                _seg_seg_distance(one.a, one.b, two.a, two.b)
                - one.radius - two.radius
            )
            if distance < worst_distance:
                worst_distance = distance
                worst_pair = (one, two)
    if worst_pair is not None and worst_distance < gap_mm:
        distance = worst_distance
        one, two = worst_pair
        findings.append(
            ReviewFinding(
                rule="10.1",
                severity="blocker",
                scope="global",
                where="isolation barrier",
                evidence=(
                    f"Creepage between {one.label} and {two.label} is "
                    f"{distance:.2f}mm; the barrier at x={barrier_x:g} "
                    f"requires >= {gap_mm:g}mm."
                ),
                suggested_action=(
                    "Move the copper away from the barrier or route it "
                    "through a certified straddle part."
                ),
                source="check",
            )
        )
    # Also verify side discipline: primary copper stays left of the
    # barrier, secondary right (straddle pads exempt).
    for item, side in (
        *((item, "primary") for item in primary),
        *((item, "secondary") for item in secondary),
    ):
        max_x = max(item.a[0], item.b[0]) + item.radius
        min_x = min(item.a[0], item.b[0]) - item.radius
        if side == "primary" and max_x > barrier_x:
            findings.append(
                ReviewFinding(
                    rule="10.1", severity="blocker", scope="net",
                    where=item.net,
                    evidence=f"{item.label} crosses the barrier "
                    f"(x max {max_x:.1f} > {barrier_x:g}).",
                    suggested_action="Keep primary copper on the primary side.",
                    source="check",
                )
            )
        if side == "secondary" and min_x < barrier_x:
            findings.append(
                ReviewFinding(
                    rule="10.1", severity="blocker", scope="net",
                    where=item.net,
                    evidence=f"{item.label} crosses the barrier "
                    f"(x min {min_x:.1f} < {barrier_x:g}).",
                    suggested_action="Keep secondary copper on the secondary side.",
                    source="check",
                )
            )
    return tuple(findings)


def _check_trace_currents(
    layout: BoardLayout,
    net_currents: tuple[tuple[str, float], ...],
) -> tuple[ReviewFinding, ...]:
    # Rule 5.3: the narrowest segment of a power net limits the whole net.
    from pcbsmith.calculators.electronics import solve_trace_current_capacity

    findings: list[ReviewFinding] = []
    for net_name, current_a in net_currents:
        widths = [
            segment.width_mm
            for segment in layout.segments
            if segment.net_name == net_name
        ]
        if not widths:
            continue
        narrowest_mm = min(widths)
        capacity = solve_trace_current_capacity(
            trace_width_m=narrowest_mm / 1000.0
        )
        capacity_a = float(capacity["outputs"]["capacity_a"])
        if capacity_a < current_a:
            findings.append(
                ReviewFinding(
                    rule="5.3",
                    severity="blocker",
                    scope="net",
                    where=net_name,
                    evidence=(
                        f"The narrowest {net_name} segment is "
                        f"{narrowest_mm:g}mm, good for {capacity_a:.2f}A at "
                        f"a 10C rise (IPC-2221), but the net carries "
                        f"{current_a:g}A."
                    ),
                    suggested_action=(
                        "Widen the net's trace width or reduce the load "
                        "current."
                    ),
                    source="check",
                )
            )
    return tuple(findings)


def _check_connector_edges(layout: BoardLayout) -> tuple[ReviewFinding, ...]:
    # Rule 1.1: connectors belong at ANY board edge (user: they just need to
    # be reachable for soldering and wiring), so all four edges qualify.
    findings: list[ReviewFinding] = []
    for component, anchor_x in layout.placements:
        spec = FOOTPRINT_LIBRARY[component.footprint]
        if not spec.is_connector:
            continue
        rotation = placement_rotation(layout, component.reference)
        anchor_y = placement_y(layout, component.reference)
        pad_positions = [
            rotate_offset(pad.x_mm, pad.y_mm, rotation) for pad in spec.pads
        ]
        pad_xs = [anchor_x + dx for dx, _ in pad_positions]
        pad_ys = [anchor_y + dy for _, dy in pad_positions]
        near_left = min(pad_xs) <= CONNECTOR_EDGE_ZONE_MM
        near_right = max(pad_xs) >= layout.width_mm - CONNECTOR_EDGE_ZONE_MM
        near_top = min(pad_ys) <= CONNECTOR_EDGE_ZONE_MM
        near_bottom = max(pad_ys) >= layout.height_mm - CONNECTOR_EDGE_ZONE_MM
        if not (near_left or near_right or near_top or near_bottom):
            findings.append(
                ReviewFinding(
                    rule="1.1",
                    severity="blocker",
                    scope="component",
                    where=component.reference,
                    evidence=(
                        f"{component.reference} pads sit at x="
                        f"{min(pad_xs):.1f}-{max(pad_xs):.1f}mm, y="
                        f"{min(pad_ys):.1f}-{max(pad_ys):.1f}mm on a "
                        f"{layout.width_mm:.1f}x{layout.height_mm:.1f}mm board, "
                        f"more than {CONNECTOR_EDGE_ZONE_MM:g}mm from every edge."
                    ),
                    suggested_action=(
                        "Move the connector to any board edge where it can be "
                        "reached for soldering and wiring."
                    ),
                    source="check",
                )
            )
    return tuple(findings)


def _check_switching_cluster(
    layout: BoardLayout,
    cluster_refs: tuple[str, ...],
) -> tuple[ReviewFinding, ...]:
    members = [
        (component, anchor_x)
        for component, anchor_x in layout.placements
        if component.reference in cluster_refs
    ]
    if len(members) < 2:
        return ()
    extents = []
    for component, anchor_x in members:
        bounds = rotated_bounds(
            FOOTPRINT_LIBRARY[component.footprint],
            placement_rotation(layout, component.reference),
        )
        extents.append((anchor_x + bounds[0], anchor_x + bounds[1]))
    span = max(right for _, right in extents) - min(left for left, _ in extents)
    budget = (
        sum(right - left for left, right in extents)
        + (len(members) - 1) * PART_GAP_MM
        + SWITCHING_CLUSTER_SLACK_MM
    )
    if span <= budget:
        return ()
    return (
        ReviewFinding(
            rule="3.1",
            severity="blocker",
            scope="region",
            where=", ".join(sorted(cluster_refs)),
            evidence=(
                f"Switching-loop cluster spans {span:.1f}mm but adjacent "
                f"placement needs only {budget:.1f}mm; parts outside the loop "
                "are interleaved into the high di/dt path."
            ),
            suggested_action=(
                "Increase the power-net span weight or pin the cluster "
                "adjacent in the row order."
            ),
            source="check",
        ),
    )


def _check_series_led_polarity(
    netlist: BoardNetlist,
    led_strings: tuple[tuple[str, ...], ...],
) -> tuple[ReviewFinding, ...]:
    """Rule 7.1: series LED strings chain anode-to-cathode, supply to ground.

    Per the KiCad library convention (rule 8.4), LED pin 1 is the CATHODE.
    Current must enter every LED at its anode (pin 2) from the element above
    it in the string; otherwise an LED is reverse-biased and the string never
    lights, even though ERC, DRC, and parity all pass.
    """
    net_by_node = {
        (reference, pin): net for net in netlist.nets for reference, pin in net.nodes
    }
    findings: list[ReviewFinding] = []
    for string in led_strings:
        for upper, lower in zip(string, string[1:], strict=False):
            net = net_by_node.get((lower, "2"))
            upstream = {reference for reference, _ in net.nodes} if net else set()
            if net is None or upper not in upstream:
                findings.append(
                    ReviewFinding(
                        rule="7.1",
                        severity="blocker",
                        scope="net",
                        where=f"{upper} -> {lower}",
                        evidence=(
                            f"The series link from {upper} does not land on "
                            f"{lower} pin 2 (anode); the LED would be "
                            "reverse-biased and the string would stay dark."
                        ),
                        suggested_action=(
                            "Fix the schematic string wiring or symbol "
                            "rotation so current enters every LED at its anode."
                        ),
                        source="check",
                    )
                )
    return tuple(findings)


def _check_sensitive_net_under_inductor(
    layout: BoardLayout,
    sensitive_net_names: tuple[str, ...],
    inductor_references: tuple[str, ...],
) -> tuple[ReviewFinding, ...]:
    sensitive = {name.lstrip("/").upper() for name in sensitive_net_names}
    inductor_bodies = []
    for component, anchor_x in layout.placements:
        if component.reference not in inductor_references:
            continue
        bounds = rotated_bounds(
            FOOTPRINT_LIBRARY[component.footprint],
            placement_rotation(layout, component.reference),
        )
        inductor_bodies.append(
            (
                component.reference,
                anchor_x + bounds[0],
                anchor_x + bounds[1],
                layout.parts_row_y_mm + bounds[3],
            )
        )
    findings: list[ReviewFinding] = []
    for segment in layout.segments:
        if segment.layer != "B.Cu":
            continue
        if segment.net_name.lstrip("/").upper() not in sensitive:
            continue
        seg_left, seg_right = sorted((segment.x1, segment.x2))
        for reference, left, right, body_bottom in inductor_bodies:
            if not (seg_left < right and seg_right > left):
                continue
            clearance = segment.y1 - body_bottom
            if clearance >= SENSITIVE_INDUCTOR_CLEARANCE_MM:
                continue
            findings.append(
                ReviewFinding(
                    rule="3.3",
                    severity="warning",
                    scope="net",
                    where=f"{segment.net_name} under {reference}",
                    evidence=(
                        f"The {segment.net_name} lane on B.Cu passes under "
                        f"{reference} with only {clearance:.1f}mm clearance to "
                        f"the inductor body (rule requires "
                        f"{SENSITIVE_INDUCTOR_CLEARANCE_MM:g}mm); inductor flux "
                        "can couple into the high-impedance node."
                    ),
                    suggested_action=(
                        "Route the sensitive net on a deeper lane or clear of "
                        "the inductor body, or specify a shielded inductor and "
                        "record that evidence."
                    ),
                    source="check",
                )
            )
    return tuple(findings)
