from __future__ import annotations

from pcbsmith.kicad.board import (
    BoardComponent,
    BoardNet,
    BoardNetlist,
    compute_board_layout,
)
from pcbsmith.kicad.design_checks import DesignChecksSpec, run_design_checks


def _connector(reference: str) -> BoardComponent:
    return BoardComponent(
        reference=reference,
        value=reference,
        footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
        uuid_path=reference.lower(),
    )


def _smd(reference: str, footprint: str = "Resistor_SMD:R_0603_1608Metric") -> BoardComponent:
    return BoardComponent(
        reference=reference,
        value=reference,
        footprint=footprint,
        uuid_path=reference.lower(),
    )


def test_clean_layout_passes_all_checks() -> None:
    netlist = BoardNetlist(
        components=(_connector("P1"), _smd("R1"), _connector("P2")),
        nets=(
            BoardNet(name="/IN", nodes=(("P1", "1"), ("R1", "1"))),
            BoardNet(name="/OUT", nodes=(("R1", "2"), ("P2", "1"))),
        ),
    )
    layout = compute_board_layout(netlist)

    report = run_design_checks(layout, netlist, DesignChecksSpec())

    assert report.status == "passed"
    assert "connector_edge" in report.checks_run
    assert report.findings == ()


def test_interior_connector_is_a_blocker() -> None:
    # Force an interior connector by making it non-leading and non-trailing:
    # three connectors means the middle ones trail, but a wide middle part
    # pushes the second connector far from both edges only if it is not in
    # the tail group - so build the layout by hand instead.
    from pcbsmith.kicad.board import BoardLayout, _anchor_row

    components = (_connector("P1"), _smd("R1"), _connector("P2"), _smd("R2"))
    placements = _anchor_row(components)
    width = max(anchor + 4 for _, anchor in placements) + 40  # huge board
    layout = BoardLayout(
        placements=placements,
        segments=(),
        vias=(),
        width_mm=width,
        height_mm=20,
    )
    netlist = BoardNetlist(components=components, nets=())

    report = run_design_checks(layout, netlist, DesignChecksSpec())

    assert report.status == "failed"
    assert any(
        finding.rule == "1.1" and finding.where == "P2" and finding.severity == "blocker"
        for finding in report.findings
    )


def test_switching_cluster_flags_interleaved_parts() -> None:
    # Cluster members U1 and D1 separated by many unrelated parts.
    components = (
        _smd("U1"),
        _smd("RX1"),
        _smd("RX2"),
        _smd("RX3"),
        _smd("RX4"),
        _smd("D1"),
    )
    netlist = BoardNetlist(components=components, nets=())
    layout = compute_board_layout(netlist)

    report = run_design_checks(
        layout,
        netlist,
        DesignChecksSpec(switching_cluster_refs=("U1", "D1")),
    )

    assert report.status == "failed"
    assert any(finding.rule == "3.1" for finding in report.findings)


def test_adjacent_switching_cluster_passes() -> None:
    components = (_smd("U1"), _smd("D1"), _smd("RX1"))
    netlist = BoardNetlist(components=components, nets=())
    layout = compute_board_layout(netlist)

    report = run_design_checks(
        layout,
        netlist,
        DesignChecksSpec(switching_cluster_refs=("U1", "D1")),
    )

    assert not [f for f in report.findings if f.rule == "3.1"]


def test_sensitive_net_under_inductor_is_a_warning() -> None:
    components = (
        _smd("U1"),
        _smd("L1", footprint="Inductor_SMD:L_12x12mm_H8mm"),
        _smd("RFB1"),
    )
    # Power nets pin the order U1 - L1 - RFB1, so the FB sense net must span
    # the inductor body, as in the real buck layout.
    nets = (
        BoardNet(name="/SW", nodes=(("U1", "1"), ("L1", "1"))),
        BoardNet(name="/VOUT", nodes=(("L1", "2"), ("RFB1", "2"))),
        BoardNet(name="/FB", nodes=(("U1", "2"), ("RFB1", "1"))),
    )
    netlist = BoardNetlist(components=components, nets=nets)
    layout = compute_board_layout(netlist, frozenset({"SW", "VOUT"}))

    report = run_design_checks(
        layout,
        netlist,
        DesignChecksSpec(
            sensitive_net_names=("FB",),
            inductor_references=("L1",),
        ),
    )

    assert report.status == "needs_human_review"
    assert any(
        finding.rule == "3.3" and finding.severity == "warning"
        for finding in report.findings
    )
