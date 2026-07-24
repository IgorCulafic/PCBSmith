from __future__ import annotations

from dataclasses import replace

import pytest

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
    # A connector counts as reachable near ANY board edge (rule 1.1), so an
    # interior one must sit far from all four: centre it on a large board.
    from pcbsmith.kicad.board import BoardLayout, _anchor_row

    components = (_connector("P1"), _smd("R1"), _connector("P2"), _smd("R2"))
    placements = _anchor_row(components)
    width = max(anchor + 4 for _, anchor in placements) + 40  # huge board
    layout = BoardLayout(
        placements=placements,
        segments=(),
        vias=(),
        width_mm=width,
        height_mm=40,
        part_y_mm=(("P2", 20.0),),
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
        finding.rule == "3.3" and finding.severity == "warning" for finding in report.findings
    )


def _two_pad_layout(segments):
    """R1 at x=5, R2 at x=25 on a bare 30x12 board with given copper."""
    from pcbsmith.kicad.board import BoardLayout

    components = (_smd("R1"), _smd("R2"))
    netlist = BoardNetlist(
        components=components,
        nets=(BoardNet(name="/SIG", nodes=(("R1", "2"), ("R2", "1"))),),
    )
    layout = BoardLayout(
        placements=((components[0], 5.0), (components[1], 25.0)),
        segments=segments,
        vias=(),
        width_mm=30.0,
        height_mm=12.0,
        part_y_mm=(("R1", 6.0), ("R2", 6.0)),
    )
    return layout, netlist


def test_acute_trace_corner_fires_rule_11_1() -> None:
    # Two /SIG tracks meeting at ~45 degrees in open space: an acid trap.
    from pcbsmith.kicad.board import TrackSegment

    segments = (
        TrackSegment(x1=10.0, y1=6.0, x2=15.0, y2=6.0, layer="F.Cu", net_name="/SIG", width_mm=0.4),
        TrackSegment(x1=15.0, y1=6.0, x2=10.0, y2=2.5, layer="F.Cu", net_name="/SIG", width_mm=0.4),
    )
    layout, netlist = _two_pad_layout(segments)
    report = run_design_checks(layout, netlist, DesignChecksSpec(trace_corner_policy="blocker"))
    assert any(
        finding.rule == "11.1" and finding.severity == "blocker" for finding in report.findings
    )


def test_45_and_90_corners_pass_rule_11_1() -> None:
    from pcbsmith.kicad.board import TrackSegment

    segments = (
        # 45-degree chamfer: joint angle 135.
        TrackSegment(x1=8.0, y1=6.0, x2=12.0, y2=6.0, layer="F.Cu", net_name="/SIG", width_mm=0.4),
        TrackSegment(x1=12.0, y1=6.0, x2=15.0, y2=9.0, layer="F.Cu", net_name="/SIG", width_mm=0.4),
        # Second chamfer back to horizontal, then a right angle:
        # both allowed (90 is the channel router's entire output).
        TrackSegment(x1=15.0, y1=9.0, x2=20.0, y2=9.0, layer="F.Cu", net_name="/SIG", width_mm=0.4),
        TrackSegment(x1=20.0, y1=9.0, x2=20.0, y2=5.0, layer="F.Cu", net_name="/SIG", width_mm=0.4),
    )
    layout, netlist = _two_pad_layout(segments)
    report = run_design_checks(layout, netlist, DesignChecksSpec(trace_corner_policy="blocker"))
    assert not [f for f in report.findings if f.rule == "11.1"]


def test_acute_corner_inside_pad_copper_is_exempt() -> None:
    # The same acute joint placed AT R2's pad 1 (teardrop territory).
    from pcbsmith.kicad.board import FOOTPRINT_LIBRARY, TrackSegment

    spec = FOOTPRINT_LIBRARY["Resistor_SMD:R_0603_1608Metric"]
    pad = next(p for p in spec.pads if p.name == "1")
    pad_x, pad_y = 25.0 + pad.x_mm, 6.0 + pad.y_mm
    segments = (
        TrackSegment(
            x1=pad_x - 4.0,
            y1=pad_y,
            x2=pad_x,
            y2=pad_y,
            layer="F.Cu",
            net_name="/SIG",
            width_mm=0.3,
        ),
        TrackSegment(
            x1=pad_x,
            y1=pad_y,
            x2=pad_x - 4.0,
            y2=pad_y - 2.8,
            layer="F.Cu",
            net_name="/SIG",
            width_mm=0.3,
        ),
    )
    layout, netlist = _two_pad_layout(segments)
    report = run_design_checks(layout, netlist, DesignChecksSpec(trace_corner_policy="blocker"))
    assert not [f for f in report.findings if f.rule == "11.1"]


def test_redundant_covered_track_fires_rule_11_2() -> None:
    # A thin track riding entirely inside a wide same-net track.
    from pcbsmith.kicad.board import TrackSegment

    segments = (
        TrackSegment(x1=8.0, y1=6.0, x2=20.0, y2=6.0, layer="F.Cu", net_name="/SIG", width_mm=1.2),
        TrackSegment(x1=10.0, y1=6.1, x2=16.0, y2=6.1, layer="F.Cu", net_name="/SIG", width_mm=0.3),
    )
    layout, netlist = _two_pad_layout(segments)
    report = run_design_checks(layout, netlist, DesignChecksSpec())
    flagged = [f for f in report.findings if f.rule == "11.2"]
    assert len(flagged) == 1
    assert "(10.00, 6.10)" in flagged[0].evidence


def test_non_covered_parallel_track_passes_rule_11_2() -> None:
    # Same-width parallel tracks offset half a width: the copper areas
    # overlap but NEITHER contains the other - not redundant by 11.2.
    from pcbsmith.kicad.board import TrackSegment

    segments = (
        TrackSegment(x1=8.0, y1=6.0, x2=20.0, y2=6.0, layer="F.Cu", net_name="/SIG", width_mm=0.4),
        TrackSegment(x1=8.0, y1=6.2, x2=20.0, y2=6.2, layer="F.Cu", net_name="/SIG", width_mm=0.4),
    )
    layout, netlist = _two_pad_layout(segments)
    report = run_design_checks(layout, netlist, DesignChecksSpec())
    assert not [f for f in report.findings if f.rule == "11.2"]


def test_trace_craft_exemption_skips_sculpted_nets() -> None:
    # Sculpted copper (sensing coils, traces-as-art) is exempt BY
    # DECLARATION: the same acute joint passes when the net is listed.
    from pcbsmith.kicad.board import TrackSegment

    segments = (
        TrackSegment(x1=10.0, y1=6.0, x2=15.0, y2=6.0, layer="F.Cu", net_name="/SIG", width_mm=0.4),
        TrackSegment(x1=15.0, y1=6.0, x2=10.0, y2=2.5, layer="F.Cu", net_name="/SIG", width_mm=0.4),
    )
    layout, netlist = _two_pad_layout(segments)
    report = run_design_checks(
        layout,
        netlist,
        DesignChecksSpec(trace_craft_exempt_nets=("/SIG",), trace_corner_policy="blocker"),
    )
    assert not [f for f in report.findings if f.rule in ("11.1", "11.2")]


def test_legacy_barrier_is_side_review_not_safety_spacing() -> None:
    from pcbsmith.kicad.board import BoardLayout, TrackSegment

    netlist = BoardNetlist(
        components=(),
        nets=(BoardNet(name="/PRI", nodes=()), BoardNet(name="/SEC", nodes=())),
    )
    layout = BoardLayout(
        placements=(),
        segments=(
            TrackSegment(
                x1=5.0,
                y1=5.0,
                x2=10.0,
                y2=5.0,
                layer="F.Cu",
                net_name="/PRI",
                width_mm=0.4,
            ),
            TrackSegment(
                x1=20.0,
                y1=5.0,
                x2=25.0,
                y2=5.0,
                layer="F.Cu",
                net_name="/SEC",
                width_mm=0.4,
            ),
        ),
        vias=(),
        width_mm=30.0,
        height_mm=10.0,
    )
    spec = DesignChecksSpec(
        isolation_barrier=(15.0, 100.0, ("/PRI",), ("/SEC",), ()),
    )

    report = run_design_checks(layout, netlist, spec)
    assert "barrier_side_review" in report.checks_run
    assert not [finding for finding in report.findings if finding.rule == "geometry.barrier_side"]

    crossed = layout.__class__(
        **{
            **{name: getattr(layout, name) for name in layout.__dataclass_fields__},
            "segments": (
                *layout.segments,
                TrackSegment(
                    x1=16.0,
                    y1=7.0,
                    x2=18.0,
                    y2=7.0,
                    layer="F.Cu",
                    net_name="/PRI",
                    width_mm=0.4,
                ),
            ),
        }
    )
    crossed_report = run_design_checks(crossed, netlist, spec)
    side_findings = [
        finding for finding in crossed_report.findings if finding.rule == "geometry.barrier_side"
    ]
    assert side_findings
    assert all(finding.severity == "warning" for finding in side_findings)
    assert all("does not establish" in finding.evidence for finding in side_findings)


def test_profile_scoped_body_to_edge_check_and_explicit_exemption() -> None:
    from pcbsmith.kicad.board import BoardLayout
    from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

    resistor = _smd("R1")
    netlist = BoardNetlist(components=(resistor,), nets=())
    layout = BoardLayout(
        placements=((resistor, 1.0),),
        segments=(),
        vias=(),
        width_mm=20.0,
        height_mm=12.0,
        part_y_mm=(("R1", 6.0),),
    )
    geometry = DEFAULT_PCB_RULE_PROFILE.geometry.model_copy(
        update={"minimum_component_body_to_edge_mm": 1.5}
    )
    profile = DEFAULT_PCB_RULE_PROFILE.model_copy(update={"geometry": geometry})

    blocked = run_design_checks(layout, netlist, DesignChecksSpec(), profile)
    findings = [finding for finding in blocked.findings if finding.rule == "fab.body_to_edge"]
    assert "component_body_to_edge" in blocked.checks_run
    assert len(findings) == 1
    assert findings[0].component_refs == ("R1",)

    exempt = run_design_checks(
        layout,
        netlist,
        DesignChecksSpec(body_edge_exempt_refs=("R1",)),
        profile,
    )
    assert not [finding for finding in exempt.findings if finding.rule == "fab.body_to_edge"]


def test_trace_checks_use_source_roles_when_labels_are_misleading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pcbsmith.kicad import virtual_drc
    from pcbsmith.kicad.board import BoardLayout, TrackSegment, ViaSpec
    from pcbsmith.kicad.virtual_drc import _Stadium
    from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile

    original_collect = virtual_drc._collect_items

    def relabel(
        layout_arg: BoardLayout,
        netlist_arg: BoardNetlist,
        *,
        cover_rect_pads: bool = False,
        profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    ) -> list[_Stadium]:
        return [
            replace(item, label=f"diagnostic text only {index}")
            for index, item in enumerate(
                original_collect(
                    layout_arg,
                    netlist_arg,
                    cover_rect_pads=cover_rect_pads,
                    profile=profile,
                )
            )
        ]

    monkeypatch.setattr(virtual_drc, "_collect_items", relabel)

    acute_segments = (
        TrackSegment(
            x1=10.0,
            y1=6.0,
            x2=15.0,
            y2=6.0,
            layer="B.Cu",
            net_name="/SIG",
            width_mm=0.4,
        ),
        TrackSegment(
            x1=15.0,
            y1=6.0,
            x2=10.0,
            y2=2.5,
            layer="B.Cu",
            net_name="/SIG",
            width_mm=0.4,
        ),
    )
    via_layout, netlist = _two_pad_layout(acute_segments)
    via_layout = replace(
        via_layout,
        vias=(ViaSpec(x=15.0, y=6.0, net_name="/SIG"),),
    )
    via_report = run_design_checks(via_layout, netlist, DesignChecksSpec())
    assert not [finding for finding in via_report.findings if finding.rule == "11.1"]

    parallel_segments = (
        TrackSegment(
            x1=8.0,
            y1=6.0,
            x2=20.0,
            y2=6.0,
            layer="F.Cu",
            net_name="/SIG",
            width_mm=0.4,
        ),
        TrackSegment(
            x1=8.0,
            y1=6.2,
            x2=20.0,
            y2=6.2,
            layer="F.Cu",
            net_name="/SIG",
            width_mm=0.4,
        ),
    )
    parallel_layout, netlist = _two_pad_layout(parallel_segments)
    parallel_report = run_design_checks(
        parallel_layout,
        netlist,
        DesignChecksSpec(),
    )
    assert not [finding for finding in parallel_report.findings if finding.rule == "11.2"]
