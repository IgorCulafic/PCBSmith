"""Synthetic native-loop fixtures; no board qualification is implied."""

from decimal import Decimal

import pytest

from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    TrackSegment,
    render_board_from_layout,
)
from pcbsmith.production_decoupling import (
    RoutedEngineeringSource,
    execute_native_loops,
    read_engineering_source,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE


def fixture(tmp_path):
    parts = tuple(
        BoardComponent(
            reference=r,
            value="fixture",
            footprint="Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
            uuid_path=r,
        )
        for r in ("C1", "U1")
    )
    netlist = BoardNetlist(
        components=parts,
        nets=(
            BoardNet("VDD", (("C1", "1"), ("U1", "1"))),
            BoardNet("GND", (("C1", "2"), ("U1", "2"))),
        ),
    )
    layout = BoardLayout(
        placements=((parts[0], 5), (parts[1], 25)),
        part_y_mm=(("C1", 5), ("U1", 10)),
        width_mm=42,
        height_mm=20,
        segments=(
            TrackSegment(5, 5, 25, 10, "F.Cu", "VDD", 0.8),
            TrackSegment(15.16, 5, 35.16, 10, "B.Cu", "GND", 0.8),
        ),
        vias=(),
    )
    board = tmp_path / "fixture.kicad_pcb"
    board.write_text(render_board_from_layout(netlist, layout), encoding="utf-8")
    source = RoutedEngineeringSource.model_validate(
        dict(
            project_id="fixture",
            revision="1",
            reviewer_record_id="synthetic-test",
            rationale="Explicit synthetic fixture limits",
            loops=[
                dict(
                    declaration_id="decoupling.U1",
                    capacitor_reference="C1",
                    load_reference="U1",
                    load_power_pin="1",
                    load_return_pin="2",
                    power_net_name="VDD",
                    return_net_name="GND",
                    maximum_via_count=2,
                    minimum_track_width_mm="0.8",
                    maximum_projected_loop_area_mm2="100",
                    require_dedicated=True,
                    rationale="Synthetic limits",
                )
            ],
        )
    )
    return board, layout, netlist, source


def test_executes_real_native_pad_and_copper_paths(tmp_path):
    board, layout, netlist, source = fixture(tmp_path)
    (result,) = execute_native_loops(
        board=board,
        layout=layout,
        netlist=netlist,
        profile=DEFAULT_PCB_RULE_PROFILE,
        source=source,
        source_sha256="a" * 64,
    )
    assert result.disposition.value == "pass"
    assert result.metrics.combined_via_count == 2
    assert float(result.metrics.projected_loop_area_mm2.fraction()) == pytest.approx(50.8)
    assert result.metrics.combined_minimum_track_width_mm == Decimal("0.8")


def test_cannot_pass_a_loop_that_exceeds_reviewed_limit(tmp_path):
    board, layout, netlist, source = fixture(tmp_path)
    source = source.model_copy(
        update={
            "loops": (
                source.loops[0].model_copy(
                    update={"maximum_projected_loop_area_mm2": Decimal("1")}
                ),
            )
        }
    )
    (result,) = execute_native_loops(
        board=board,
        layout=layout,
        netlist=netlist,
        profile=DEFAULT_PCB_RULE_PROFILE,
        source=source,
        source_sha256="a" * 64,
    )
    assert result.disposition.value == "fail"
    assert "maximum_projected_loop_area_exceeded" in result.violation_ids


def test_rejects_stale_native_geometry_and_wrong_role(tmp_path):
    board, layout, netlist, source = fixture(tmp_path)
    board.write_text(
        board.read_text(encoding="utf-8").replace("(start 25 25)", "(start 26 25)"),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="detached layout"):
        execute_native_loops(
            board=board,
            layout=layout,
            netlist=netlist,
            profile=DEFAULT_PCB_RULE_PROFILE,
            source=source,
            source_sha256="a" * 64,
        )


def test_source_bytes_are_pinned_before_evaluation(tmp_path):
    _, _, _, source = fixture(tmp_path)
    p = tmp_path / "policy.json"
    p.write_text(source.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="source changed"):
        read_engineering_source(p, "0" * 64, "fixture", ())


def test_distinct_physical_switch_pads_are_not_merged(tmp_path):
    from pcbsmith.kicad.routed_copper_graph import build_routed_copper_graph
    from pcbsmith.production_decoupling import native_terminal_anchors

    part = BoardComponent("SW1", "switch", "Button_Switch_THT:SW_PUSH_6mm", "SW1")
    netlist = BoardNetlist(
        components=(part,),
        nets=(BoardNet("VDD", (("SW1", "1"),)), BoardNet("GND", (("SW1", "2"),))),
    )
    layout = BoardLayout(
        placements=((part, 5),),
        part_y_mm=(("SW1", 5),),
        width_mm=20,
        height_mm=20,
        segments=(),
        vias=(),
    )
    board = tmp_path / "switch.kicad_pcb"
    board.write_text(render_board_from_layout(netlist, layout), encoding="utf-8")
    anchors = native_terminal_anchors(board, netlist)
    assert len(anchors) == 4
    assert len({a.physical_pad_source_id for a in anchors}) == 4
    graph = build_routed_copper_graph(layout, netlist, anchors, resolve_point_contacts=True)
    # Only actual vertical pad barrels, never invented copper across the switch.
    assert len(graph.edges) == 4
    assert all(e.kind == "via" for e in graph.edges)


def test_wrong_net_on_an_additional_physical_pad_is_rejected(tmp_path):
    from pcbsmith.production_decoupling import native_terminal_anchors

    part = BoardComponent("SW1", "switch", "Button_Switch_THT:SW_PUSH_6mm", "SW1")
    netlist = BoardNetlist(
        components=(part,),
        nets=(BoardNet("VDD", (("SW1", "1"),)), BoardNet("GND", (("SW1", "2"),))),
    )
    layout = BoardLayout(
        placements=((part, 5),),
        part_y_mm=(("SW1", 5),),
        width_mm=20,
        height_mm=20,
        segments=(),
        vias=(),
    )
    board = tmp_path / "switch.kicad_pcb"
    text = render_board_from_layout(netlist, layout)
    import re

    match = list(re.finditer(r'\(net(?: \d+)? "VDD"\)', text))[-1]
    board.write_text(
        text[: match.start()] + match.group().replace("VDD", "GND") + text[match.end() :],
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="net mismatch"):
        native_terminal_anchors(board, netlist)


def test_envelope_is_explicit_and_over_bound_is_inconclusive(tmp_path):
    from pcbsmith.decoupling_loop_ir import DecouplingLoopEvaluationResult

    board, layout, netlist, source = fixture(tmp_path)
    for limit, disposition in (("50.8", "pass"), ("50.799", "unverified")):
        revised = source.model_copy(
            update={
                "loops": (
                    source.loops[0].model_copy(
                        update={
                            "maximum_projected_loop_area_mm2": Decimal(limit),
                            "projected_area_method": "conservative_envelope",
                        }
                    ),
                )
            }
        )
        (result,) = execute_native_loops(
            board=board,
            layout=layout,
            netlist=netlist,
            profile=DEFAULT_PCB_RULE_PROFILE,
            source=revised,
            source_sha256="b" * 64,
        )
        assert result.disposition.value == disposition
        assert result.metrics.projected_envelope_area_mm2.fraction() == Decimal("50.8")
        if disposition == "unverified":
            assert result.unverified_reasons == ("projected_envelope_bound_inconclusive",)
            assert result.violation_ids == ()
        tampered = result.model_dump(mode="json")
        tampered["metrics"]["projected_envelope_area_mm2"]["numerator"] = 1
        with pytest.raises(ValueError):
            DecouplingLoopEvaluationResult.model_validate(tampered)


def test_hull_handles_crossing_projection_and_exact_fractions():
    from fractions import Fraction as F

    from pcbsmith.kicad.decoupling_loop import _convex_envelope_area

    # Bow tie: shoelace signed cancellation is not used as an acceptance area.
    points = ((F(0), F(0)), (F(1, 3), F(1, 3)), (F(0), F(1, 3)), (F(1, 3), F(0)))
    assert _convex_envelope_area(points).fraction() == F(1, 9)
    assert _convex_envelope_area(points + points).fraction() == F(1, 9)
    assert _convex_envelope_area(((F(0), F(0)), (F(1), F(1)), (F(2), F(2)))) is None


def test_revision_cannot_change_limits_terminals_or_predecessor(tmp_path):
    import hashlib

    from pcbsmith.production_decoupling import read_envelope_revision

    _, _, _, source = fixture(tmp_path)
    revised = source.model_copy(
        update={
            "revision": "2",
            "loops": (
                source.loops[0].model_copy(
                    update={"projected_area_method": "conservative_envelope"}
                ),
            ),
        }
    )
    payload = dict(
        retained_result_sha256="a" * 64,
        candidate_board_sha256="b" * 64,
        predecessor_source_sha256="c" * 64,
        authorization_reference="Explicit test decision",
        source=revised.model_dump(mode="json"),
    )
    import json

    path = tmp_path / "revision.json"

    def read(value):
        path.write_text(json.dumps(value), encoding="utf-8")
        return read_envelope_revision(
            path,
            hashlib.sha256(path.read_bytes()).hexdigest(),
            original=source,
            original_sha256="c" * 64,
            retained_result_sha256="a" * 64,
        )

    assert read(payload).source == revised
    for key, value in (("maximum_projected_loop_area_mm2", "1000"), ("load_power_pin", "2")):
        changed = json.loads(json.dumps(payload))
        changed["source"]["loops"][0][key] = value
        with pytest.raises(ValueError, match="only the area method"):
            read(changed)
    payload["retained_result_sha256"] = "d" * 64
    with pytest.raises(ValueError, match="predecessor mismatch"):
        read(payload)
