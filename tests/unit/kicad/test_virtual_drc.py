from __future__ import annotations

from tests.unit.kicad.test_clover_board import MOTTO
from tests.unit.kicad.test_clover_board import _netlist as clover_netlist
from tests.unit.kicad.test_metal_detector_board import _netlist as detector_netlist
from tests.unit.kicad.test_pear_board import _netlist as pear_netlist

from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    TrackSegment,
    ViaSpec,
)
from pcbsmith.kicad.clover_board import compute_clover_board_layout
from pcbsmith.kicad.design_checks import DesignChecksSpec, run_design_checks
from pcbsmith.kicad.metal_detector_board import compute_detector_board_layout
from pcbsmith.kicad.pear_board import compute_pear_board_layout
from pcbsmith.kicad.virtual_drc import run_virtual_drc

RESISTOR = "Resistor_SMD:R_0603_1608Metric"


def _resistor(reference: str) -> BoardComponent:
    return BoardComponent(
        reference=reference, value="1k", footprint=RESISTOR,
        uuid_path=reference.lower(),
    )


def _two_part_netlist() -> BoardNetlist:
    return BoardNetlist(
        components=(_resistor("R1"), _resistor("R2")),
        nets=(
            BoardNet(name="/A", nodes=(("R1", "1"), ("R2", "1"))),
            BoardNet(name="/B", nodes=(("R1", "2"), ("R2", "2"))),
        ),
    )


def _layout(**overrides: object) -> BoardLayout:
    netlist = _two_part_netlist()
    base = dict(
        placements=tuple((component, 10.0 + 10.0 * i) for i, component in
                         enumerate(netlist.components)),
        segments=(),
        vias=(),
        width_mm=50.0,
        height_mm=30.0,
        part_y_mm=(("R1", 15.0), ("R2", 15.0)),
    )
    base.update(overrides)
    return BoardLayout(**base)  # type: ignore[arg-type]


def test_clean_challenge_boards_have_zero_findings() -> None:
    assert run_virtual_drc(
        compute_detector_board_layout(detector_netlist()), detector_netlist()
    ) == ()
    assert run_virtual_drc(
        compute_pear_board_layout(pear_netlist()), pear_netlist()
    ) == ()
    assert run_virtual_drc(
        compute_clover_board_layout(clover_netlist(), MOTTO), clover_netlist()
    ) == ()


def test_cross_net_track_short_is_flagged() -> None:
    layout = _layout(
        segments=(
            TrackSegment(x1=5.0, y1=5.0, x2=45.0, y2=5.0,
                         layer="F.Cu", net_name="/A", width_mm=0.3),
            TrackSegment(x1=25.0, y1=2.0, x2=25.0, y2=8.0,
                         layer="F.Cu", net_name="/B", width_mm=0.3),
        ),
    )
    findings = run_virtual_drc(layout, _two_part_netlist())
    assert any(
        finding.check == "copper_clearance" and "short" in finding.message
        for finding in findings
    )


def test_same_net_and_cross_layer_tracks_are_not_flagged() -> None:
    layout = _layout(
        segments=(
            TrackSegment(x1=5.0, y1=5.0, x2=45.0, y2=5.0,
                         layer="F.Cu", net_name="/A", width_mm=0.3),
            TrackSegment(x1=25.0, y1=2.0, x2=25.0, y2=8.0,
                         layer="F.Cu", net_name="/A", width_mm=0.3),
            TrackSegment(x1=25.0, y1=2.0, x2=25.0, y2=8.0,
                         layer="B.Cu", net_name="/B", width_mm=0.3),
        ),
    )
    assert run_virtual_drc(layout, _two_part_netlist()) == ()


def test_track_grazing_a_foreign_pad_is_flagged() -> None:
    # R1 pads sit at x 10 +/- 0.825, y 15. A /B track 0.25mm from the
    # pad-1 (/A) copper violates the 0.2mm clearance... but a 0.5mm one
    # does not.
    tight = _layout(
        segments=(
            TrackSegment(x1=5.0, y1=15.55, x2=15.0, y2=15.55,
                         layer="F.Cu", net_name="/B", width_mm=0.2),
        ),
    )
    findings = run_virtual_drc(tight, _two_part_netlist())
    assert any(finding.check == "copper_clearance" for finding in findings)

    roomy = _layout(
        segments=(
            TrackSegment(x1=5.0, y1=16.3, x2=15.0, y2=16.3,
                         layer="F.Cu", net_name="/B", width_mm=0.2),
        ),
    )
    assert run_virtual_drc(roomy, _two_part_netlist()) == ()


def test_courtyard_overlap_is_flagged() -> None:
    layout = _layout(
        placements=tuple(
            (component, 10.0 + 1.2 * i)
            for i, component in enumerate(_two_part_netlist().components)
        ),
    )
    findings = run_virtual_drc(layout, _two_part_netlist())
    assert any(finding.check == "courtyard_overlap" for finding in findings)


def test_copper_near_the_edge_is_flagged() -> None:
    layout = _layout(
        vias=(ViaSpec(x=0.4, y=15.0, net_name="/A"),),
    )
    findings = run_virtual_drc(layout, _two_part_netlist())
    assert any(finding.check == "edge_clearance" for finding in findings)


def test_copper_outside_the_outline_is_flagged() -> None:
    layout = _layout(
        outline=((5.0, 5.0), (45.0, 5.0), (45.0, 25.0), (5.0, 25.0)),
        part_y_mm=(("R1", 15.0), ("R2", 15.0)),
        segments=(
            TrackSegment(x1=46.0, y1=15.0, x2=48.0, y2=15.0,
                         layer="F.Cu", net_name="/A", width_mm=0.3),
        ),
    )
    findings = run_virtual_drc(layout, _two_part_netlist())
    assert any("outside" in finding.message for finding in findings)


def test_design_check_flags_self_intersecting_outline() -> None:
    layout = _layout(
        outline=((5.0, 5.0), (45.0, 25.0), (45.0, 5.0), (5.0, 25.0)),
    )
    report = run_design_checks(layout, _two_part_netlist(), DesignChecksSpec())
    assert "outline_is_simple" in report.checks_run
    assert any(finding.rule == "5.2" for finding in report.findings)
    assert report.status == "failed"


def test_design_check_flags_zone_and_track_in_a_keepout() -> None:
    spec = DesignChecksSpec(
        copper_keepouts=((25.0, 15.0, 8.0, ("/A",)),),
    )
    offender = _layout(
        zones=(("/GND", "B.Cu", (5.0, 5.0, 45.0, 25.0)),),
        segments=(
            TrackSegment(x1=20.0, y1=15.0, x2=30.0, y2=15.0,
                         layer="B.Cu", net_name="/B", width_mm=0.3),
        ),
    )
    report = run_design_checks(offender, _two_part_netlist(), spec)
    nine_one = [f for f in report.findings if f.rule == "9.1"]
    assert any(f.scope == "region" for f in nine_one)  # the zone
    assert any(f.scope == "net" for f in nine_one)     # the /B track
    assert report.status == "failed"

    allowed = _layout(
        segments=(
            TrackSegment(x1=20.0, y1=15.0, x2=30.0, y2=15.0,
                         layer="B.Cu", net_name="/A", width_mm=0.3),
        ),
    )
    report = run_design_checks(allowed, _two_part_netlist(), spec)
    assert not [f for f in report.findings if f.rule == "9.1"]


def test_design_check_flags_an_undersized_power_trace() -> None:
    from pcbsmith.kicad.board import TrackSegment as _Seg

    spec = DesignChecksSpec(net_currents=(("/A", 3.0),))
    layout = _layout(
        segments=(
            _Seg(x1=5.0, y1=5.0, x2=45.0, y2=5.0,
                 layer="F.Cu", net_name="/A", width_mm=0.3),
        ),
    )
    report = run_design_checks(layout, _two_part_netlist(), spec)
    assert any(finding.rule == "5.3" for finding in report.findings)
    assert report.status == "failed"

    roomy = DesignChecksSpec(net_currents=(("/A", 0.5),))
    report = run_design_checks(layout, _two_part_netlist(), roomy)
    assert not [finding for finding in report.findings if finding.rule == "5.3"]


def test_design_check_flags_a_forgotten_ic_pin() -> None:
    from pcbsmith.kicad.board import BoardComponent as _Component

    transistor = _Component(
        reference="Q1", value="MMBT3904",
        footprint="Package_TO_SOT_SMD:SOT-23", uuid_path="q1",
    )
    # Pin 3 (collector) is silently missing from every net.
    netlist = BoardNetlist(
        components=(transistor,),
        nets=(
            BoardNet(name="/B", nodes=(("Q1", "1"),)),
            BoardNet(name="/E", nodes=(("Q1", "2"),)),
        ),
    )
    layout = BoardLayout(
        placements=((transistor, 25.0),),
        segments=(), vias=(), width_mm=50.0, height_mm=30.0,
        part_y_mm=(("Q1", 15.0),),
    )
    report = run_design_checks(layout, netlist, DesignChecksSpec())
    hits = [f for f in report.findings if f.rule == "7.3"]
    assert hits and "pad 3" in hits[0].evidence
    assert report.status == "failed"

    reviewed = DesignChecksSpec(allowed_unconnected_pins=(("Q1", "3"),))
    report = run_design_checks(layout, netlist, reviewed)
    assert not [f for f in report.findings if f.rule == "7.3"]


def test_sealed_pour_cell_with_a_stranded_via_is_flagged() -> None:
    # A thick foreign-net ring walls off a corner of the GND zone with a
    # GND via inside: the fill strands it.
    ring = [
        TrackSegment(x1=x1, y1=y1, x2=x2, y2=y2,
                     layer="B.Cu", net_name="/A", width_mm=1.0)
        for x1, y1, x2, y2 in (
            (2.0, 10.0, 15.0, 10.0),   # horizontal wall from the left edge
            (15.0, 10.0, 15.0, 2.0),   # vertical wall to the top edge
        )
    ]
    layout = _layout(
        segments=tuple(ring),
        vias=(ViaSpec(x=7.0, y=6.0, net_name="/GND"),),
        zones=(("/GND", "B.Cu", (1.5, 1.5, 48.5, 28.5)),),
    )
    netlist = BoardNetlist(
        components=_two_part_netlist().components,
        nets=(
            *_two_part_netlist().nets,
            BoardNet(name="/GND", nodes=()),
        ),
    )
    findings = run_virtual_drc(layout, netlist)
    pour = [f for f in findings if f.check == "pour_connectivity"]
    assert pour and "sealed off" in pour[0].message

    # The same geometry with the via OUTSIDE the pocket stays clean.
    fine = _layout(
        segments=tuple(ring),
        vias=(ViaSpec(x=30.0, y=20.0, net_name="/GND"),),
        zones=(("/GND", "B.Cu", (1.5, 1.5, 48.5, 28.5)),),
    )
    assert not [
        f for f in run_virtual_drc(fine, netlist)
        if f.check == "pour_connectivity"
    ]


def test_circle_courtyards_measure_as_dense_hulls() -> None:
    """A radial cap's F.CrtYd is a circle; the hull must track it (a
    naive parse degenerates to a line and the bbox overreaches corners)."""
    from pcbsmith.kicad.library import load_footprint

    spec = load_footprint(
        "Capacitor_THT:CP_Radial_D10.0mm_P5.00mm"
    ).spec
    hull = spec.courtyard_hull
    assert hull is not None and len(hull) >= 12
    xs = [x for x, _ in hull]
    ys = [y for _, y in hull]
    # Centre (2.5, 0), radius 5.25 per the footprint file.
    assert abs(min(xs) - (2.5 - 5.25)) < 0.05
    assert abs(max(xs) - (2.5 + 5.25)) < 0.05
    assert abs(min(ys) + 5.25) < 0.05
    assert abs(max(ys) - 5.25) < 0.05
    # The hull is round, not square: the corner point (as far toward the
    # bbox corner as possible) stays well inside the bbox corner.
    corner_reach = max((x - 2.5) + abs(y) for x, y in hull)
    assert corner_reach < 5.25 * 1.5  # a square bbox would reach 2r


def test_silk_reference_label_collision_is_flagged() -> None:
    """Two 0603s stacked so R1's default reference label (1.43mm above
    its body) lands inside R2's body must trip the silk model."""
    netlist = _two_part_netlist()
    layout = _layout(
        placements=tuple(
            (component, 10.0) for component in netlist.components
        ),
        part_y_mm=(("R1", 15.0), ("R2", 12.8)),
        segments=(
            TrackSegment(x1=9.2, y1=15.0, x2=9.2, y2=12.8,
                         layer="F.Cu", net_name="/A"),
            TrackSegment(x1=10.8, y1=15.0, x2=10.8, y2=12.8,
                         layer="F.Cu", net_name="/B"),
        ),
    )
    findings = run_virtual_drc(layout, netlist)
    assert any(
        finding.check == "silk_overlap" and "reference label R1" in finding.message
        for finding in findings
    ), findings


def test_board_silk_text_over_pad_is_flagged() -> None:
    from pcbsmith.kicad.board import BOARD_SHEET_ORIGIN_MM
    from pcbsmith.kicad.shaped_board import silk_text

    netlist = _two_part_netlist()
    layout = _layout(
        graphics=(silk_text("HV", (10.0, 15.0), BOARD_SHEET_ORIGIN_MM, size=1.6),),
    )
    findings = run_virtual_drc(layout, netlist)
    assert any(finding.check == "silk_over_pad" for finding in findings), findings


def test_board_silk_line_through_body_is_flagged() -> None:
    from pcbsmith.kicad.board import BOARD_SHEET_ORIGIN_MM
    from pcbsmith.kicad.shaped_board import silk_line

    netlist = _two_part_netlist()
    layout = _layout(
        graphics=(
            silk_line((10.0, 13.0), (10.0, 17.0), BOARD_SHEET_ORIGIN_MM,
                      width=0.4),
        ),
    )
    findings = run_virtual_drc(layout, netlist)
    assert any(
        finding.check == "silk_overlap" and "crosses the body" in finding.message
        for finding in findings
    ), findings
