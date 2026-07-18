from __future__ import annotations

from dataclasses import replace

import pytest

from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.hole_geometry import HoleGeometry, HolePlating, HoleShape
from pcbsmith.kicad.board import (
    FOOTPRINT_LIBRARY,
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    ViaSpec,
)
from pcbsmith.kicad.design_checks import DesignChecksSpec, run_design_checks
from pcbsmith.kicad.library import PadSpec
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile

_TEST_FOOTPRINT = "Test:FabricationGeometry"
_BASE_FOOTPRINT = "Resistor_SMD:R_0603_1608Metric"


def _profile(**limits: float) -> PcbRuleProfile:
    evidence = EvidenceRef(
        kind="manufacturer_capability",
        title="Test fabrication process",
        locator="geometry table",
        source_id="test-fab-process-v1",
    )
    geometry = DEFAULT_PCB_RULE_PROFILE.geometry.model_copy(
        update={**limits, "evidence": (evidence,)}
    )
    return DEFAULT_PCB_RULE_PROFILE.model_copy(update={"geometry": geometry})


def _pad_layout(
    monkeypatch: pytest.MonkeyPatch,
    pad: PadSpec,
    *,
    vias: tuple[ViaSpec, ...] = (),
) -> tuple[BoardLayout, BoardNetlist]:
    monkeypatch.setitem(
        FOOTPRINT_LIBRARY,
        _TEST_FOOTPRINT,
        replace(
            FOOTPRINT_LIBRARY[_BASE_FOOTPRINT],
            pads=(pad,),
            board_only=True,
            is_connector=False,
        ),
    )
    component = BoardComponent(
        reference="J1",
        value="geometry probe",
        footprint=_TEST_FOOTPRINT,
        uuid_path="geometry-probe",
    )
    nodes = (("J1", "1"),) if pad.name else ()
    nets = (BoardNet(name="/PAD", nodes=nodes),) if nodes else ()
    netlist = BoardNetlist(components=(component,), nets=nets)
    return (
        BoardLayout(
            placements=((component, 5.0),),
            segments=(),
            vias=vias,
            width_mm=20.0,
            height_mm=12.0,
            part_y_mm=(("J1", 5.0),),
        ),
        netlist,
    )


def _plated_pad(
    *,
    shape: str = "oval",
    copper_width: float = 1.0,
    copper_height: float = 1.0,
    hole_width: float = 0.4,
    hole_height: float = 0.4,
    hole_rotation: float = 0.0,
    offset_x: float = 0.0,
) -> PadSpec:
    return PadSpec(
        name="1",
        x_mm=0.0,
        y_mm=0.0,
        kind="tht",
        width_mm=copper_width,
        height_mm=copper_height,
        angle_deg=0.0,
        shape=shape,
        hole=HoleGeometry(
            shape=(HoleShape.ROUND if hole_width == hole_height else HoleShape.OVAL),
            width_mm=hole_width,
            height_mm=hole_height,
            rotation_deg=hole_rotation,
            plating=HolePlating.PLATED,
            offset_x_mm=offset_x,
        ),
    )


def test_default_profile_does_not_run_optional_fabrication_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, netlist = _pad_layout(monkeypatch, _plated_pad(hole_width=0.1, hole_height=0.1))

    report = run_design_checks(layout, netlist, DesignChecksSpec())

    assert "finished_hole" not in report.checks_run
    assert "annular_ring" not in report.checks_run
    assert "hole_to_hole_web" not in report.checks_run
    assert not [finding for finding in report.findings if finding.rule.startswith("fab.")]


def test_exact_fabrication_limits_flag_unique_structured_violations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pad = _plated_pad(
        copper_width=0.5,
        copper_height=0.5,
        hole_width=0.2,
        hole_height=0.2,
    )
    vias = (
        ViaSpec(x=10.0, y=5.0, net_name="/V1", size_mm=0.5, drill_mm=0.3),
        ViaSpec(x=10.5, y=5.0, net_name="/V2", size_mm=0.6, drill_mm=0.3),
    )
    layout, netlist = _pad_layout(monkeypatch, pad, vias=vias)
    profile = _profile(
        minimum_finished_hole_mm=0.25,
        minimum_annular_ring_mm=0.12,
        minimum_hole_to_hole_web_mm=0.25,
    )

    report = run_design_checks(layout, netlist, DesignChecksSpec(), profile)

    finished = [f for f in report.findings if f.rule == "fab.finished_hole"]
    annular = [f for f in report.findings if f.rule == "fab.annular_ring"]
    webs = [f for f in report.findings if f.rule == "fab.hole_to_hole_web"]
    assert len(finished) == 1
    assert finished[0].object_ids == ("pad:J1:0",)
    assert finished[0].component_refs == ("J1",)
    assert finished[0].constraint_ids == ("minimum_finished_hole_mm",)
    assert finished[0].evidence_refs == profile.geometry.evidence
    assert len([f for f in annular if f.severity == "blocker"]) == 1
    assert len(webs) == 1
    assert webs[0].object_ids == ("via:0", "via:1")
    assert webs[0].constraint_ids == ("minimum_hole_to_hole_web_mm",)
    assert report.status == "failed"


def test_round_via_and_concentric_simple_pth_pass_exact_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layout, netlist = _pad_layout(
        monkeypatch,
        _plated_pad(
            copper_width=1.2,
            copper_height=0.8,
            hole_width=0.6,
            hole_height=0.3,
        ),
        vias=(ViaSpec(x=12.0, y=5.0, net_name="/VIA", size_mm=0.6, drill_mm=0.3),),
    )
    profile = _profile(
        minimum_finished_hole_mm=0.25,
        minimum_annular_ring_mm=0.12,
        minimum_hole_to_hole_web_mm=0.3,
    )

    report = run_design_checks(layout, netlist, DesignChecksSpec(), profile)

    assert not [finding for finding in report.findings if finding.rule.startswith("fab.")]


def test_npth_slot_uses_minor_axis_and_is_excluded_from_annular_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pad = PadSpec(
        name="",
        x_mm=0.0,
        y_mm=0.0,
        kind="npth",
        width_mm=1.0,
        height_mm=0.2,
        shape="oval",
        hole=HoleGeometry(
            shape=HoleShape.OVAL,
            width_mm=1.0,
            height_mm=0.2,
            plating=HolePlating.NON_PLATED,
        ),
    )
    layout, netlist = _pad_layout(monkeypatch, pad)
    profile = _profile(
        minimum_finished_hole_mm=0.25,
        minimum_annular_ring_mm=0.12,
    )

    report = run_design_checks(layout, netlist, DesignChecksSpec(), profile)

    finished = [f for f in report.findings if f.rule == "fab.finished_hole"]
    assert len(finished) == 1
    assert "0.2mm finished minor axis" in finished[0].evidence
    assert not [f for f in report.findings if f.rule == "fab.annular_ring"]


@pytest.mark.parametrize(
    "pad, expected_reason",
    (
        (_plated_pad(shape="rect"), "uses rect copper"),
        (_plated_pad(offset_x=0.1), "offset or their oval axes"),
        (
            _plated_pad(
                copper_width=1.2,
                copper_height=0.8,
                hole_width=0.6,
                hole_height=0.3,
                hole_rotation=90.0,
            ),
            "offset or their oval axes",
        ),
    ),
)
def test_unsupported_pth_annular_geometry_requires_review(
    monkeypatch: pytest.MonkeyPatch,
    pad: PadSpec,
    expected_reason: str,
) -> None:
    layout, netlist = _pad_layout(monkeypatch, pad)

    report = run_design_checks(
        layout,
        netlist,
        DesignChecksSpec(),
        _profile(minimum_annular_ring_mm=0.12),
    )

    findings = [f for f in report.findings if f.rule == "fab.annular_ring"]
    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert expected_reason in findings[0].evidence
    assert findings[0].object_ids == ("pad:J1:0",)
    assert findings[0].constraint_ids == ("minimum_annular_ring_mm",)
    assert report.status == "needs_human_review"
