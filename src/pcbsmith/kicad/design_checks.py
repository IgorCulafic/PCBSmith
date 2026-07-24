"""Deterministic geometric design checks over a computed board layout.

Each check encodes a rule from docs/pcb-design-rules.md that was originally
discovered by visual review. Once a visual finding is expressible as geometry
it is promoted here so it never needs eyes again; the model reviewer only
handles what cannot be computed.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal

from pcbsmith.circuit.models import DesignReviewReport, ReviewFinding
from pcbsmith.copper_exposure import (
    CopperExposureResult,
    OuterCopperRegion,
    classify_outer_copper_exposure,
)
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
from pcbsmith.kicad.copper_exposure import collect_outer_copper_regions
from pcbsmith.kicad.mask_apertures import collect_mask_apertures
from pcbsmith.kicad.virtual_drc import (
    _collect_items,
    _iter_physical_holes,
    _PhysicalItemKind,
    _seg_seg_distance,
)
from pcbsmith.kicad.virtual_drc import (
    _Stadium as _PhysicalStadium,
)
from pcbsmith.mask_geometry import (
    ApertureRelation,
    MaskAperture,
    MaskVerification,
    measure_apertures,
)
from pcbsmith.rule_profiles import (
    DEFAULT_PCB_RULE_PROFILE,
    OrdinaryClearanceRequirement,
    PcbRuleProfile,
)

_FAB_EPSILON_MM = 1e-9

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
    copper_keepouts: tuple[tuple[float, float, float, tuple[str, ...]], ...] = ()
    # Rule 5.3: (net name, load current in amps) pairs. The selected
    # profile names the thermal model, copper thickness, and temperature rise.
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
    # Legacy barrier-line placement review: (barrier_x, legacy_gap_mm,
    # left-side nets, right-side nets, straddle refs). ``legacy_gap_mm`` is
    # retained for call/serialization compatibility but is not enforced here.
    # This declaration cannot establish insulation clearance or creepage.
    isolation_barrier: (
        tuple[float, float, tuple[str, ...], tuple[str, ...], tuple[str, ...]] | None
    ) = None
    # Rule 10.4: pairwise copper clearance between two net GROUPS with no
    # barrier-line geometry - e.g. protective EARTH vs the mains nets,
    # where only the certified line Y-caps may bridge. Each entry is
    # (label, nets_a, nets_b, gap_mm, exempt refs).
    net_group_clearances: tuple[
        tuple[str, tuple[str, ...], tuple[str, ...], float, tuple[str, ...]],
        ...,
    ] = ()
    # Rule 11 exemption: nets whose copper is SCULPTED on purpose -
    # sensing coils (section 9), traces-as-art - rather than routed.
    # The trace-craft checks skip them; declaring them here keeps the
    # exemption visible and reviewable instead of silent.
    trace_craft_exempt_nets: tuple[str, ...] = ()
    # Rule 11.1 is policy-scoped, not a universal electrical/fabrication
    # blocker.  Enable it only when a selected craft/fabricator/HV policy
    # declares the applicability and desired disposition.
    trace_corner_policy: Literal["off", "advisory", "blocker"] = "off"
    # Rule 1.1 exemption: connector-footprint parts that carry ON-BOARD
    # modules (display headers) rather than off-board wiring; declared
    # per reference so the exemption is visible.
    connector_edge_exempt_refs: tuple[str, ...] = ()
    # Profile-scoped body-edge exceptions (connectors, breakaways, intentional overhang).
    body_edge_exempt_refs: tuple[str, ...] = ()
    extra_model_findings: tuple[ReviewFinding, ...] = field(default=())


def run_design_checks(
    layout: BoardLayout,
    netlist: BoardNetlist,
    spec: DesignChecksSpec,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
) -> DesignReviewReport:
    checks_run: list[str] = []
    findings: list[ReviewFinding] = []

    checks_run.append("connector_edge")
    findings.extend(_check_connector_edges(layout, spec.connector_edge_exempt_refs))

    body_edge_mm = profile.geometry.minimum_component_body_to_edge_mm
    if body_edge_mm is not None:
        checks_run.append("component_body_to_edge")
        findings.extend(
            _check_component_body_to_edge(
                layout,
                body_edge_mm,
                spec.body_edge_exempt_refs,
            )
        )

    geometry = profile.geometry
    if any(
        value is not None
        for value in (
            geometry.minimum_finished_hole_mm,
            geometry.minimum_annular_ring_mm,
            geometry.minimum_hole_to_hole_web_mm,
        )
    ):
        physical_items = _collect_items(layout, netlist, profile=profile)
        if geometry.minimum_finished_hole_mm is not None:
            checks_run.append("finished_hole")
            findings.extend(
                _check_finished_holes(
                    physical_items,
                    geometry.minimum_finished_hole_mm,
                    profile,
                )
            )
        if geometry.minimum_annular_ring_mm is not None:
            checks_run.append("annular_ring")
            findings.extend(
                _check_annular_rings(
                    layout,
                    physical_items,
                    geometry.minimum_annular_ring_mm,
                    profile,
                )
            )
        if geometry.minimum_hole_to_hole_web_mm is not None:
            checks_run.append("hole_to_hole_web")
            findings.extend(
                _check_hole_to_hole_webs(
                    physical_items,
                    geometry.minimum_hole_to_hole_web_mm,
                    profile,
                )
            )

    exposure_requirements = tuple(
        requirement
        for requirement in profile.fab_spacing.pairwise_clearances
        if requirement.mask_states_a or requirement.mask_states_b
    )
    minimum_mask_web_mm = geometry.minimum_solder_mask_web_mm
    apertures = (
        collect_mask_apertures(layout, netlist, profile)
        if exposure_requirements or minimum_mask_web_mm is not None
        else None
    )
    if exposure_requirements:
        checks_run.append("outer_copper_exposure")
        copper_regions = collect_outer_copper_regions(layout, netlist)
        assert apertures is not None
        findings.extend(
            _check_outer_copper_exposure(
                copper_regions,
                classify_outer_copper_exposure(copper_regions, apertures),
                apertures,
                exposure_requirements,
                profile,
            )
        )
    if minimum_mask_web_mm is not None:
        checks_run.append("solder_mask_web")
        assert apertures is not None
        findings.extend(
            _check_solder_mask_webs(
                apertures,
                minimum_mask_web_mm,
                profile,
            )
        )

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
        findings.extend(_check_trace_currents(layout, spec.net_currents, profile))

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
            findings.extend(card_contract_findings(card, reference, netlist, tie_map))
            if roles:
                findings.extend(support_findings(card, reference, roles))
            # The card's reviewed NC pins feed rule 7.3's whitelist.
            allowed_unconnected.update((reference, pin) for pin in card.nc_pins())

    if spec.net_group_clearances:
        checks_run.append("net_group_clearance")
        for group in spec.net_group_clearances:
            findings.extend(_check_net_group_clearance(layout, netlist, group))

    if spec.isolation_barrier is not None:
        checks_run.append("barrier_side_review")
        findings.extend(_check_barrier_side_discipline(layout, netlist, spec.isolation_barrier))

    checks_run.append("ic_pin_connectivity")
    findings.extend(_check_ic_pin_connectivity(layout, netlist, tuple(sorted(allowed_unconnected))))

    if spec.trace_corner_policy != "off":
        checks_run.append("trace_corner_angle")
        findings.extend(
            _check_trace_corners(
                layout,
                netlist,
                spec.trace_craft_exempt_nets,
                severity=spec.trace_corner_policy,
            )
        )

    checks_run.append("redundant_copper")
    findings.extend(_check_redundant_copper(layout, netlist, spec.trace_craft_exempt_nets))

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
    def orient(p: tuple[float, float], q: tuple[float, float], r: tuple[float, float]) -> float:
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
    connected = {(reference, pin) for net in netlist.nets for reference, pin in net.nodes}
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
    from pcbsmith.kicad.virtual_drc import (
        _collect_items,
        _PhysicalItemKind,
        _seg_seg_distance,
    )

    label, nets_a, nets_b, gap_mm, exempt = group
    items = _collect_items(layout, netlist)
    exempt_set = set(exempt)
    group_a = [
        item
        for item in items
        if (
            item.kind is _PhysicalItemKind.COPPER
            and item.net in nets_a
            and item.owner not in exempt_set
        )
    ]
    group_b = [
        item
        for item in items
        if (
            item.kind is _PhysicalItemKind.COPPER
            and item.net in nets_b
            and item.owner not in exempt_set
        )
    ]
    findings: list[ReviewFinding] = []
    worst_distance = 1e9
    worst_pair = None
    for one in group_a:
        for two in group_b:
            distance = _seg_seg_distance(one.a, one.b, two.a, two.b) - one.radius - two.radius
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


def _check_barrier_side_discipline(
    layout: BoardLayout,
    netlist: BoardNetlist,
    barrier: tuple[float, float, tuple[str, ...], tuple[str, ...], tuple[str, ...]],
) -> tuple[ReviewFinding, ...]:
    """Review a declared placement divider without claiming safety approval.

    Euclidean copper distance is air distance, not creepage. The legacy gap
    value is therefore ignored; qualified air-clearance enforcement belongs
    exclusively to ``PcbRuleProfile.insulation``.
    """
    from pcbsmith.kicad.virtual_drc import _collect_items, _PhysicalItemKind

    barrier_x, _legacy_gap_mm, left_nets, right_nets, straddle = barrier
    items = _collect_items(layout, netlist)
    left = [
        item
        for item in items
        if (
            item.kind is _PhysicalItemKind.COPPER
            and item.net in left_nets
            and item.owner not in straddle
        )
    ]
    right = [
        item
        for item in items
        if (
            item.kind is _PhysicalItemKind.COPPER
            and item.net in right_nets
            and item.owner not in straddle
        )
    ]
    findings: list[ReviewFinding] = []
    for item, side in (
        *((item, "left") for item in left),
        *((item, "right") for item in right),
    ):
        max_x = max(item.a[0], item.b[0]) + item.radius
        min_x = min(item.a[0], item.b[0]) - item.radius
        crossed = (side == "left" and max_x > barrier_x) or (side == "right" and min_x < barrier_x)
        if not crossed:
            continue
        extent = (
            f"x max {max_x:.1f} > {barrier_x:g}"
            if side == "left"
            else f"x min {min_x:.1f} < {barrier_x:g}"
        )
        findings.append(
            ReviewFinding(
                rule="geometry.barrier_side",
                severity="warning",
                scope="net",
                where=item.net,
                evidence=(
                    f"{item.label} crosses the declared {side}-side placement "
                    f"divider ({extent}). This geometry review does not "
                    "establish insulation clearance or creepage."
                ),
                suggested_action=(
                    "Restore the intended side discipline, then evaluate any "
                    "safety spacing through a qualified insulation profile."
                ),
                source="check",
            )
        )
    return tuple(findings)


def _check_trace_currents(
    layout: BoardLayout,
    net_currents: tuple[tuple[str, float], ...],
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
) -> tuple[ReviewFinding, ...]:
    # Rule 5.3: the narrowest segment of a power net limits the whole net.
    from pcbsmith.calculators.electronics import solve_trace_current_capacity

    findings: list[ReviewFinding] = []
    model_id = profile.geometry.trace_thermal_model_id
    if model_id != "legacy_ipc_2221a_external_fit":
        return (
            ReviewFinding(
                rule="5.3",
                severity="warning",
                scope="global",
                where=profile.profile_id,
                evidence=(
                    f"Trace-current model {model_id!r} has no registered deterministic evaluator."
                ),
                suggested_action=(
                    "Register and fixture-test the selected profile-table model "
                    "before treating trace-current capacity as checked."
                ),
                source="check",
            ),
        )
    for net_name, current_a in net_currents:
        widths = [segment.width_mm for segment in layout.segments if segment.net_name == net_name]
        if not widths:
            findings.append(
                ReviewFinding(
                    rule="5.3",
                    severity="warning",
                    scope="net",
                    where=net_name,
                    evidence=(
                        f"No routed track segments were available for declared "
                        f"{net_name} current {current_a:g}A, so trace-current "
                        "capacity was not evaluated. Zones, planes, vias, pads, "
                        "parallel paths, and connector conductors are outside "
                        "this legacy evaluator."
                    ),
                    suggested_action=(
                        "Route and materialize the complete current path, then "
                        "evaluate its narrowest tracks, zones, vias, pads, "
                        "connectors, voltage drop, and thermal context."
                    ),
                    source="check",
                )
            )
            continue
        narrowest_mm = min(widths)
        capacity = solve_trace_current_capacity(
            trace_width_m=narrowest_mm / 1000.0,
            copper_thickness_m=(profile.geometry.outer_copper_thickness_um * 1e-6),
            temperature_rise_c=profile.geometry.trace_temperature_rise_c,
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
                        f"a {profile.geometry.trace_temperature_rise_c:g}C rise "
                        "(legacy IPC-2221A Figure 6-4 external fit), "
                        "but the net carries "
                        f"{current_a:g}A."
                    ),
                    suggested_action=("Widen the net's trace width or reduce the load current."),
                    source="check",
                )
            )
    return tuple(findings)


def _check_component_body_to_edge(
    layout: BoardLayout,
    minimum_mm: float,
    exempt_references: tuple[str, ...],
) -> tuple[ReviewFinding, ...]:
    """Check exact placed fab-body polygons against the board outline."""
    from pcbsmith.kicad.virtual_drc import (
        _body_polys,
        _point_in_polygon,
        _seg_seg_distance,
    )

    outline = layout.outline or (
        (0.0, 0.0),
        (layout.width_mm, 0.0),
        (layout.width_mm, layout.height_mm),
        (0.0, layout.height_mm),
    )
    outline_edges = [
        (outline[index], outline[(index + 1) % len(outline)]) for index in range(len(outline))
    ]
    exempt = set(exempt_references)
    findings: list[ReviewFinding] = []
    for reference, _side, body in _body_polys(layout):
        if reference in exempt:
            continue
        body_edges = [(body[index], body[(index + 1) % len(body)]) for index in range(len(body))]
        outside = any(not _point_in_polygon(point, tuple(outline)) for point in body)
        crossing = any(
            _segments_intersect(*body_edge, *outline_edge)
            for body_edge in body_edges
            for outline_edge in outline_edges
        )
        distance = min(
            _seg_seg_distance(*body_edge, *outline_edge)
            for body_edge in body_edges
            for outline_edge in outline_edges
        )
        if not outside and not crossing and distance >= minimum_mm:
            continue
        condition = (
            "crosses or lies outside the board outline"
            if outside or crossing
            else f"is {distance:.2f}mm from the board edge"
        )
        findings.append(
            ReviewFinding(
                rule="fab.body_to_edge",
                severity="blocker",
                scope="component",
                where=reference,
                evidence=(
                    f"{reference} fab body {condition}; profile requires >= {minimum_mm:g}mm."
                ),
                suggested_action=(
                    "Move the component inward or declare a reviewed connector/"
                    "breakaway/overhang exception for this reference."
                ),
                source="check",
                component_refs=(reference,),
                constraint_ids=("minimum_component_body_to_edge_mm",),
            )
        )
    return tuple(findings)


def _geometry_object_id(item: _PhysicalStadium) -> str:
    return item.parent_source_id or item.source_id


def _geometry_component_refs(*items: _PhysicalStadium) -> tuple[str, ...]:
    return tuple(sorted({item.owner for item in items if item.owner}))


def _geometry_net_refs(*items: _PhysicalStadium) -> tuple[str, ...]:
    return tuple(sorted({item.net for item in items if not item.net.startswith("~")}))


def _mask_component_refs(*apertures: MaskAperture) -> tuple[str, ...]:
    return tuple(sorted({item.owner_ref for item in apertures if item.owner_ref}))


def _check_outer_copper_exposure(
    regions: tuple[OuterCopperRegion, ...],
    results: tuple[CopperExposureResult, ...],
    apertures: tuple[MaskAperture, ...],
    requirements: tuple[OrdinaryClearanceRequirement, ...],
    profile: PcbRuleProfile,
) -> tuple[ReviewFinding, ...]:
    """Report unknown exposure only when it prevents requirement scoping."""
    regions_by_id = {region.source_id: region for region in regions}
    apertures_by_id = {aperture.source_id: aperture for aperture in apertures}
    findings: list[ReviewFinding] = []
    for result in results:
        if result.state != "unknown":
            continue
        region = regions_by_id.get(result.copper_source_id)
        if region is None:
            continue
        requirement_ids: set[str] = set()
        for requirement in requirements:
            if (
                requirement.mask_states_a
                and "unknown" not in requirement.mask_states_a
                and region.net_name in requirement.nets_a
                and (not requirement.roles_a or region.role in requirement.roles_a)
            ):
                requirement_ids.add(requirement.requirement_id)
            if (
                requirement.mask_states_b
                and "unknown" not in requirement.mask_states_b
                and region.net_name in requirement.nets_b
                and (not requirement.roles_b or region.role in requirement.roles_b)
            ):
                requirement_ids.add(requirement.requirement_id)
        if not requirement_ids:
            continue
        sorted_requirement_ids = tuple(sorted(requirement_ids))
        unresolved_ids = tuple(sorted(result.unresolved_aperture_source_ids))
        unresolved_details = tuple(
            f"{source_id} ({apertures_by_id[source_id].unsupported_reason or 'reason unavailable'})"
            if source_id in apertures_by_id
            else f"{source_id} (source unavailable)"
            for source_id in unresolved_ids
        )
        unresolved_text = ", ".join(unresolved_details) if unresolved_details else "none reported"
        findings.append(
            ReviewFinding(
                rule="fab.copper_exposure_unverified",
                severity="warning",
                scope="component" if region.owner_ref is not None else "net",
                where=(f"{region.side.value} outer copper {region.source_id} on {region.net_name}"),
                evidence=(
                    f"Outer copper {region.source_id} has unknown solder-mask exposure; "
                    f"side={region.side.value}, net={region.net_name}, role={region.role}. "
                    f"Unresolved aperture sources: {unresolved_text}. Reason: {result.reason}. "
                    "Exposure scope cannot be decided for ordinary requirements "
                    f"{', '.join(sorted_requirement_ids)}."
                ),
                suggested_action=(
                    "Resolve the relevant solder-mask geometry or explicitly include "
                    "unknown in the reviewed requirement selector before relying on "
                    "exposure-scoped clearance."
                ),
                source="check",
                phase="fabrication_geometry",
                category="solder_mask",
                object_ids=(region.source_id, *unresolved_ids),
                component_refs=((region.owner_ref,) if region.owner_ref is not None else ()),
                net_refs=(region.net_name,),
                constraint_ids=sorted_requirement_ids,
                evidence_refs=profile.fab_spacing.evidence,
            )
        )
    return tuple(findings)


def _mask_pair_scope(first: MaskAperture, second: MaskAperture) -> Literal["component", "region"]:
    if first.owner_ref is not None and first.owner_ref == second.owner_ref:
        return "component"
    return "region"


def _mask_pair_where(first: MaskAperture, second: MaskAperture) -> str:
    return f"{first.side.value} mask: {first.source_id} / {second.source_id}"


def _check_solder_mask_webs(
    apertures: tuple[MaskAperture, ...],
    minimum_mm: float,
    profile: PcbRuleProfile,
) -> tuple[ReviewFinding, ...]:
    """Check exact same-side openings and surface every unverified source."""
    findings: list[ReviewFinding] = []
    seen_unsupported: set[str] = set()
    exact_by_side: dict[str, list[MaskAperture]] = {"front": [], "back": []}

    for aperture in apertures:
        if aperture.verification is MaskVerification.EXACT:
            exact_by_side[aperture.side.value].append(aperture)
            continue
        if aperture.source_id in seen_unsupported:
            continue
        seen_unsupported.add(aperture.source_id)
        reason = aperture.unsupported_reason or (
            "bounded-approximation mask geometry is not accepted by the exact web check"
        )
        findings.append(
            ReviewFinding(
                rule="fab.solder_mask_web_unverified",
                severity="warning",
                scope=(
                    "component"
                    if aperture.owner_ref is not None
                    else "region"
                    if aperture.geometry is not None
                    else "global"
                ),
                where=f"{aperture.side.value} mask aperture {aperture.source_id}",
                evidence=(
                    "Exact solder-mask-web validation is unavailable for this "
                    f"source because {reason}; profile requires >= {minimum_mm:g}mm."
                ),
                suggested_action=(
                    "Resolve the mask process/geometry intent or have the fabricator "
                    "or a human reviewer validate this opening and its neighboring webs."
                ),
                source="check",
                phase="fabrication_geometry",
                category="solder_mask",
                object_ids=(aperture.source_id,),
                component_refs=_mask_component_refs(aperture),
                constraint_ids=("minimum_solder_mask_web_mm",),
                evidence_refs=profile.geometry.evidence,
            )
        )

    for side in ("front", "back"):
        side_apertures = sorted(exact_by_side[side], key=lambda item: item.source_id)
        for index, first in enumerate(side_apertures):
            for second in side_apertures[index + 1 :]:
                measurement = measure_apertures(first, second)
                if measurement.relation is ApertureRelation.IGNORED_SAME_PARENT:
                    continue
                object_ids = tuple(sorted((first.source_id, second.source_id)))
                component_refs = _mask_component_refs(first, second)
                if measurement.relation in {
                    ApertureRelation.TOUCHING,
                    ApertureRelation.OVERLAP,
                }:
                    if (
                        first.merge_group_id is not None
                        and first.merge_group_id == second.merge_group_id
                    ):
                        continue
                    findings.append(
                        ReviewFinding(
                            rule="fab.mask_aperture_merge",
                            severity="blocker",
                            scope=_mask_pair_scope(first, second),
                            where=_mask_pair_where(first, second),
                            evidence=(
                                f"The two {side} mask openings "
                                f"{measurement.relation.value}; they form one connected "
                                "opening without a reviewed common merge group."
                            ),
                            suggested_action=(
                                "Increase spacing or reduce mask expansion, or declare a "
                                "reviewed common merge group for an intentional gang opening."
                            ),
                            source="check",
                            phase="fabrication_geometry",
                            category="solder_mask",
                            object_ids=object_ids,
                            component_refs=component_refs,
                            constraint_ids=("minimum_solder_mask_web_mm",),
                            evidence_refs=profile.geometry.evidence,
                        )
                    )
                    continue
                web_mm = measurement.web_mm
                if web_mm is None or web_mm + _FAB_EPSILON_MM >= minimum_mm:
                    continue
                findings.append(
                    ReviewFinding(
                        rule="fab.solder_mask_web",
                        severity="blocker",
                        scope=_mask_pair_scope(first, second),
                        where=_mask_pair_where(first, second),
                        evidence=(
                            f"Exact {side} solder-mask web is {web_mm:g}mm; profile "
                            f"requires >= {minimum_mm:g}mm."
                        ),
                        suggested_action=(
                            "Increase opening spacing, reduce mask expansion, or select a "
                            "reviewed fabrication profile that supports the resulting web."
                        ),
                        source="check",
                        phase="fabrication_geometry",
                        category="solder_mask",
                        object_ids=object_ids,
                        component_refs=component_refs,
                        constraint_ids=("minimum_solder_mask_web_mm",),
                        evidence_refs=profile.geometry.evidence,
                    )
                )
    return tuple(findings)


def _check_finished_holes(
    items: list[_PhysicalStadium],
    minimum_mm: float,
    profile: PcbRuleProfile,
) -> tuple[ReviewFinding, ...]:
    """Check the minor axis of every unique manufactured PTH/NPTH/via."""
    findings: list[ReviewFinding] = []
    for hole in _iter_physical_holes(items):
        minor_axis_mm = 2 * hole.radius
        if minor_axis_mm + _FAB_EPSILON_MM >= minimum_mm:
            continue
        findings.append(
            ReviewFinding(
                rule="fab.finished_hole",
                severity="blocker",
                scope="component" if hole.owner else "global",
                where=hole.label,
                evidence=(
                    f"{hole.label} has a {minor_axis_mm:g}mm finished minor "
                    f"axis; profile requires >= {minimum_mm:g}mm."
                ),
                suggested_action=(
                    "Increase the finished drill/slot minor axis or select a "
                    "reviewed manufacturing profile that supports it."
                ),
                source="check",
                object_ids=(_geometry_object_id(hole),),
                component_refs=_geometry_component_refs(hole),
                net_refs=_geometry_net_refs(hole),
                constraint_ids=("minimum_finished_hole_mm",),
                evidence_refs=profile.geometry.evidence,
            )
        )
    return tuple(findings)


def _check_hole_to_hole_webs(
    items: list[_PhysicalStadium],
    minimum_mm: float,
    profile: PcbRuleProfile,
) -> tuple[ReviewFinding, ...]:
    """Check exact residual material between unique physical hole stadia."""
    holes = list(_iter_physical_holes(items))
    findings: list[ReviewFinding] = []
    for index, first in enumerate(holes):
        for second in holes[index + 1 :]:
            web_mm = (
                _seg_seg_distance(first.a, first.b, second.a, second.b)
                - first.radius
                - second.radius
            )
            if web_mm + _FAB_EPSILON_MM >= minimum_mm:
                continue
            findings.append(
                ReviewFinding(
                    rule="fab.hole_to_hole_web",
                    severity="blocker",
                    scope=(
                        "component" if first.owner and first.owner == second.owner else "region"
                    ),
                    where=f"{first.label} / {second.label}",
                    evidence=(
                        f"Residual material between {first.label} and "
                        f"{second.label} is {web_mm:g}mm; profile requires "
                        f">= {minimum_mm:g}mm."
                    ),
                    suggested_action=(
                        "Increase hole spacing, reduce the drill/slot axes, or "
                        "use a reviewed manufacturing profile that supports "
                        "the resulting web."
                    ),
                    source="check",
                    object_ids=tuple(
                        sorted(
                            {
                                _geometry_object_id(first),
                                _geometry_object_id(second),
                            }
                        )
                    ),
                    component_refs=_geometry_component_refs(first, second),
                    net_refs=_geometry_net_refs(first, second),
                    constraint_ids=("minimum_hole_to_hole_web_mm",),
                    evidence_refs=profile.geometry.evidence,
                )
            )
    return tuple(findings)


def _stadium_center(item: _PhysicalStadium) -> tuple[float, float]:
    return ((item.a[0] + item.b[0]) / 2, (item.a[1] + item.b[1]) / 2)


def _exact_stadium_containment_margin(
    copper: _PhysicalStadium, hole: _PhysicalStadium
) -> float | None:
    """Minimum boundary margin for concentric, parallel exact stadia."""
    if math.dist(_stadium_center(copper), _stadium_center(hole)) > _FAB_EPSILON_MM:
        return None
    copper_length = math.dist(copper.a, copper.b)
    hole_length = math.dist(hole.a, hole.b)
    if copper_length > _FAB_EPSILON_MM and hole_length > _FAB_EPSILON_MM:
        copper_axis = (
            (copper.b[0] - copper.a[0]) / copper_length,
            (copper.b[1] - copper.a[1]) / copper_length,
        )
        hole_axis = (
            (hole.b[0] - hole.a[0]) / hole_length,
            (hole.b[1] - hole.a[1]) / hole_length,
        )
        cross = copper_axis[0] * hole_axis[1] - copper_axis[1] * hole_axis[0]
        if abs(cross) > _FAB_EPSILON_MM:
            return None
    side_margin = copper.radius - hole.radius
    end_margin = copper_length / 2 + copper.radius - hole_length / 2 - hole.radius
    return min(side_margin, end_margin)


def _check_annular_rings(
    layout: BoardLayout,
    items: list[_PhysicalStadium],
    minimum_mm: float,
    profile: PcbRuleProfile,
) -> tuple[ReviewFinding, ...]:
    """Check exact via/simple-PTH annular containment, warning otherwise."""
    copper_by_parent: dict[str, _PhysicalStadium] = {}
    for item in items:
        if item.kind is not _PhysicalItemKind.COPPER or item.parent_source_id is None:
            continue
        copper_by_parent.setdefault(item.parent_source_id, item)
    pad_by_parent = {
        f"pad:{component.reference}:{pad_index}": pad
        for component, _anchor_x in layout.placements
        for pad_index, pad in enumerate(FOOTPRINT_LIBRARY[component.footprint].pads)
    }
    findings: list[ReviewFinding] = []
    for hole in _iter_physical_holes(items):
        if hole.kind is _PhysicalItemKind.BARE_HOLE:
            continue
        parent_id = _geometry_object_id(hole)
        copper = copper_by_parent.get(parent_id)
        pad = pad_by_parent.get(parent_id)
        unsupported_reason: str | None = None
        if copper is None:
            unsupported_reason = "matching copper geometry was not found"
        elif parent_id.startswith("pad:") and (pad is None or pad.shape not in {"circle", "oval"}):
            shape = "unknown" if pad is None else pad.shape or "unspecified"
            unsupported_reason = f"the PTH pad uses {shape} copper"
        margin_mm = (
            None
            if unsupported_reason is not None or copper is None
            else _exact_stadium_containment_margin(copper, hole)
        )
        if unsupported_reason is None and margin_mm is None:
            unsupported_reason = "the copper and hole are offset or their oval axes are nonparallel"
        if unsupported_reason is not None:
            findings.append(
                ReviewFinding(
                    rule="fab.annular_ring",
                    severity="warning",
                    scope="component" if hole.owner else "global",
                    where=hole.label,
                    evidence=(
                        "Exact annular-ring validation is unsupported because "
                        f"{unsupported_reason}; profile requires >= "
                        f"{minimum_mm:g}mm."
                    ),
                    suggested_action=(
                        "Have the fabricator or a human reviewer validate the "
                        "minimum annular containment for this pad."
                    ),
                    source="check",
                    object_ids=(parent_id,),
                    component_refs=_geometry_component_refs(hole),
                    net_refs=_geometry_net_refs(hole),
                    constraint_ids=("minimum_annular_ring_mm",),
                    evidence_refs=profile.geometry.evidence,
                )
            )
        elif margin_mm is not None and margin_mm + _FAB_EPSILON_MM < minimum_mm:
            findings.append(
                ReviewFinding(
                    rule="fab.annular_ring",
                    severity="blocker",
                    scope="component" if hole.owner else "global",
                    where=hole.label,
                    evidence=(
                        f"{hole.label} has an exact minimum annular containment "
                        f"of {margin_mm:g}mm; profile requires >= "
                        f"{minimum_mm:g}mm."
                    ),
                    suggested_action=(
                        "Increase the copper land or reduce the finished hole/"
                        "slot within the reviewed manufacturing limits."
                    ),
                    source="check",
                    object_ids=(parent_id,),
                    component_refs=_geometry_component_refs(hole),
                    net_refs=_geometry_net_refs(hole),
                    constraint_ids=("minimum_annular_ring_mm",),
                    evidence_refs=profile.geometry.evidence,
                )
            )
    return tuple(findings)


def _check_connector_edges(
    layout: BoardLayout,
    exempt_refs: tuple[str, ...] = (),
) -> tuple[ReviewFinding, ...]:
    # Rule 1.1: connectors belong at ANY board edge (user: they just need to
    # be reachable for soldering and wiring), so all four edges qualify.
    # Headers that carry ON-BOARD modules are exempt by declaration.
    exempt = set(exempt_refs)
    findings: list[ReviewFinding] = []
    for component, anchor_x in layout.placements:
        spec = FOOTPRINT_LIBRARY[component.footprint]
        if not spec.is_connector or component.reference in exempt:
            continue
        rotation = placement_rotation(layout, component.reference)
        anchor_y = placement_y(layout, component.reference)
        pad_positions = [rotate_offset(pad.x_mm, pad.y_mm, rotation) for pad in spec.pads]
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
                "Increase the power-net span weight or pin the cluster adjacent in the row order."
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
    net_by_node = {(reference, pin): net for net in netlist.nets for reference, pin in net.nodes}
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


# Rule 11.1 tolerance: 90-degree corners are legal (the Manhattan
# channel router's whole output); anything meaningfully sharper is an
# acid-trap shape and forbidden per fab practice.
ACUTE_CORNER_DEG = 89.0


def _check_trace_corners(
    layout: BoardLayout,
    netlist: BoardNetlist,
    exempt_nets: tuple[str, ...] = (),
    *,
    severity: Literal["advisory", "blocker"],
) -> tuple[ReviewFinding, ...]:
    """Rule 11.1: no acute (<90 deg) corner where two same-net tracks
    meet OUTSIDE pad/via copper. Sharp interior corners trap etchant
    (thin or broken trace) and are forbidden in fab DRCs; 45-degree
    chamfers (135 deg joints) and right angles pass. Joints whose
    point sits inside same-net pad or via copper are exempt - that is
    teardrop territory, and the pad masks the geometry."""
    import math

    from pcbsmith.kicad.virtual_drc import (
        _collect_items,
        _PhysicalItemKind,
        _PhysicalSourceRole,
        _point_seg_distance,
        _Stadium,
    )

    items = _collect_items(layout, netlist)
    masks: dict[str, list[_Stadium]] = {}
    for item in items:
        if item.kind is _PhysicalItemKind.COPPER and item.source_role in {
            _PhysicalSourceRole.PAD,
            _PhysicalSourceRole.VIA,
        }:
            masks.setdefault(item.net, []).append(item)

    findings: list[ReviewFinding] = []
    ends: dict[
        tuple[str, str, tuple[float, float]],
        list[tuple[float, float]],
    ] = {}
    exempt = set(exempt_nets)
    for segment in layout.segments:
        if segment.net_name in exempt:
            continue
        away_from_start = (
            segment.x2 - segment.x1,
            segment.y2 - segment.y1,
        )
        away_from_end = (
            segment.x1 - segment.x2,
            segment.y1 - segment.y2,
        )
        for point, away in (
            ((segment.x1, segment.y1), away_from_start),
            ((segment.x2, segment.y2), away_from_end),
        ):
            key = (
                segment.net_name,
                segment.layer,
                (round(point[0], 3), round(point[1], 3)),
            )
            ends.setdefault(key, []).append(away)

    for (net, layer, point), aways in sorted(ends.items()):
        if len(aways) < 2:
            continue
        masked = any(
            (item.layer == layer or item.source_role is _PhysicalSourceRole.VIA)
            and _point_seg_distance(point, item.a, item.b) <= item.radius
            for item in masks.get(net, ())
        )
        if masked:
            continue
        worst = 180.0
        for index, one in enumerate(aways):
            for two in aways[index + 1 :]:
                norm = math.hypot(*one) * math.hypot(*two)
                if norm < 1e-12:
                    continue
                cosine = (one[0] * two[0] + one[1] * two[1]) / norm
                angle = math.degrees(math.acos(max(-1.0, min(1.0, cosine))))
                worst = min(worst, angle)
        if worst < ACUTE_CORNER_DEG:
            findings.append(
                ReviewFinding(
                    rule="11.1",
                    severity=severity,
                    scope="net",
                    where=net,
                    evidence=(
                        f"Tracks of {net} meet at {worst:.0f} deg at "
                        f"({point[0]:.2f}, {point[1]:.2f}) on {layer}; "
                        "acute copper corners trap etchant."
                    ),
                    suggested_action=(
                        "Re-route the joint as a 45-degree chamfer or a "
                        "right angle, or move it inside the pad copper."
                    ),
                    source="check",
                )
            )
    return tuple(findings)


def _check_redundant_copper(
    layout: BoardLayout,
    netlist: BoardNetlist,
    exempt_nets: tuple[str, ...] = (),
) -> tuple[ReviewFinding, ...]:
    """Rule 11.2: no track whose copper is entirely inside the union of
    the net's OTHER copper. Redundant copper is routing debris - it
    reads as spaghetti, hides the real topology from reviewers, and
    serves no electrical purpose (the covered region already conducts).
    The router prunes; this check keeps every pipeline honest."""
    from pcbsmith.kicad.astar_router import segment_covered_by
    from pcbsmith.kicad.virtual_drc import (
        _collect_items,
        _PhysicalItemKind,
        _PhysicalSourceRole,
    )

    items = _collect_items(layout, netlist)
    findings: list[ReviewFinding] = []
    exempt = set(exempt_nets)
    for segment in layout.segments:
        if segment.net_name in exempt:
            continue
        covers = [
            (item.a, item.b, item.radius, item.layer)
            for item in items
            if item.kind is _PhysicalItemKind.COPPER
            and item.net == segment.net_name
            and not (
                item.source_role is _PhysicalSourceRole.TRACK
                and item.a == (segment.x1, segment.y1)
                and item.b == (segment.x2, segment.y2)
                and item.layer == segment.layer
            )
        ]
        if segment_covered_by(segment, covers, margin_mm=0.05):
            findings.append(
                ReviewFinding(
                    rule="11.2",
                    severity="blocker",
                    scope="net",
                    where=segment.net_name,
                    evidence=(
                        f"Track of {segment.net_name} from "
                        f"({segment.x1:.2f}, {segment.y1:.2f}) to "
                        f"({segment.x2:.2f}, {segment.y2:.2f}) on "
                        f"{segment.layer} lies entirely inside the net's "
                        "other copper."
                    ),
                    suggested_action=(
                        "Delete the covered track; the remaining copper "
                        "already carries the connection."
                    ),
                    source="check",
                )
            )
    return tuple(findings)
