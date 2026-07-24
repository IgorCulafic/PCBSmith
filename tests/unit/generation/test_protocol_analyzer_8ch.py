"""Regression checks for the reduced eight-channel protocol analyzer."""

from __future__ import annotations

from pathlib import Path

import pytest

from pcbsmith.generation.protocol_analyzer_8ch import compose_protocol_analyzer_8ch
from pcbsmith.kicad.export_protocol_analyzer_8ch import INSTANCES, NO_CONNECTS
from pcbsmith.kicad.protocol_analyzer_8ch_r002_board import (
    BOARD_H,
    BOARD_W,
    MOUNTING_HOLES,
    PLACEMENTS,
    SWITCH_FOOTPRINT,
    register_protocol_analyzer_r002_assets,
)
from pcbsmith.kicad.symbols import load_symbol


def test_component_schematic_and_placement_authorities_are_complete() -> None:
    circuit = compose_protocol_analyzer_8ch()
    component_refs = [component.reference for component in circuit.components]
    instance_refs = [reference for reference, *_rest in INSTANCES]

    assert len(component_refs) == 58
    assert len(component_refs) == len(set(component_refs))
    assert len(instance_refs) == len(set(instance_refs))
    assert set(component_refs) == set(instance_refs)
    assert set(component_refs) == set(PLACEMENTS)
    assert circuit.intent.assumptions["board_width_mm"] == BOARD_W
    assert circuit.intent.assumptions["board_height_mm"] == BOARD_H
    assert MOUNTING_HOLES == (
        ("H1", 4.0, 4.0),
        ("H2", 66.0, 4.0),
        ("H3", 4.0, 38.0),
        ("H4", 66.0, 38.0),
    )
    switch_footprints = {
        component.footprint
        for component in circuit.components
        if component.reference in {"SW1", "SW2"}
    }
    assert switch_footprints == {SWITCH_FOOTPRINT}
    assert PLACEMENTS["J1"] == (35.0, 4.8, 0.0)
    assert PLACEMENTS["J2"] == (2.0, 8.8, 0.0)
    assert PLACEMENTS["SW1"] == (68.0, 14.0, 90.0)
    assert PLACEMENTS["SW2"] == (68.0, 28.0, 90.0)


def test_every_schematic_pin_is_connected_or_explicitly_no_connect() -> None:
    for reference, lib_id, _x, _y, pin_nets in INSTANCES:
        symbol_pins = {pin.number for pin in load_symbol(lib_id).pins}
        accounted_for = set(pin_nets) | set(NO_CONNECTS.get(reference, ()))
        assert accounted_for == symbol_pins, (
            reference,
            sorted(symbol_pins - accounted_for),
            sorted(accounted_for - symbol_pins),
        )


def test_capture_and_vtarget_math_matches_declared_architecture() -> None:
    circuit = compose_protocol_analyzer_8ch()
    calculations = circuit.math.calculations

    assert circuit.intent.assumptions["channel_count"] == 8.0
    assert circuit.intent.assumptions["required_sample_rate_msps"] == 10.0
    assert circuit.intent.assumptions["stretch_sample_rate_msps"] == 20.0
    assert calculations["capture_buffer_bytes"] == 131_072.0
    assert calculations["capture_duration_ms_at_10_msps"] == pytest.approx(13.1072)
    assert calculations["capture_duration_ms_at_20_msps"] == pytest.approx(6.5536)
    assert calculations["vtarget_adc_v_at_5v5"] < 3.3


def test_input_header_is_ground_interleaved_and_target_power_is_monitor_only() -> None:
    j2 = next(instance for instance in INSTANCES if instance[0] == "J2")
    pin_nets = j2[4]

    for channel in range(8):
        assert pin_nets[str(channel * 2 + 1)] == f"CH{channel}_RAW"
        assert pin_nets[str(channel * 2 + 2)] == "GND"
    assert pin_nets["17"] == "VTARGET_RAW"
    assert pin_nets["18"] == "GND"
    assert pin_nets["19"] == "TRIG_RAW"
    assert pin_nets["20"] == "GND"
    assert all(net != "3V3" for net in pin_nets.values())


def test_high_risk_parts_retain_pinned_primary_evidence() -> None:
    by_ref = {
        component.reference: component
        for component in compose_protocol_analyzer_8ch().components
    }

    for reference in ("U1", "U4", "U6", "U7", "U9"):
        evidence = by_ref[reference].evidence
        assert evidence
        assert all(item.kind == "manufacturer_document" for item in evidence)
        assert all(item.source_status == "pinned" for item in evidence)
        assert all(item.local_sha256 for item in evidence)


def test_r002_side_switch_assets_are_project_local_and_explicitly_proxy(
    tmp_path: Path,
) -> None:
    register_protocol_analyzer_r002_assets(tmp_path)

    footprint = (
        tmp_path
        / "PCBSmith_Protocol.pretty"
        / "Alps_SKRTLAE010_RightAngle.kicad_mod"
    ).read_text(encoding="utf-8")
    model = (
        tmp_path / "models" / "alps-skrtlae010-right-angle-proxy.wrl"
    ).read_text(encoding="ascii")
    table = (tmp_path / "fp-lib-table").read_text(encoding="utf-8")

    assert '${KIPRJMOD}/models/alps-skrtlae010-right-angle-proxy.wrl' in footprint
    assert footprint.count("(model ") == 1
    assert "visual proxy" in model
    assert "supplier CAD" in model
    assert 'name "PCBSmith_Protocol"' in table
