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
