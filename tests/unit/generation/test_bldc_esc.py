"""BLDC ESC R001 circuit-authority and package-identity checks."""

from __future__ import annotations

from pathlib import Path

from pcbsmith.generation.bldc_esc import compose_bldc_esc
from pcbsmith.kicad.bldc_esc_board import BOARD_H, BOARD_W
from pcbsmith.kicad.bldc_esc_models import (
    HEATSINK_BASE_BOTTOM_MM,
    HEATSINK_FIN_HEIGHT_MM,
    HEATSINK_LENGTH_MM,
    HEATSINK_WIDTH_MM,
    TIM_THICKNESS_MM,
    generate_bldc_esc_proxy_models,
    generate_bldc_esc_r002_mechanical_models,
)
from pcbsmith.kicad.export_bldc_esc import (
    DRV_PIN_NETS,
    INSTANCES,
    _mosfet_nets,
    _power_footprints,
)


def test_component_and_schematic_instances_are_one_to_one() -> None:
    circuit = compose_bldc_esc()
    component_refs = [component.reference for component in circuit.components]
    instance_refs = [reference for reference, *_rest in INSTANCES]

    assert len(component_refs) == 117
    assert len(component_refs) == len(set(component_refs))
    assert len(instance_refs) == len(set(instance_refs))
    assert set(component_refs) == set(instance_refs)
    assert circuit.intent.assumptions["board_width_mm"] == BOARD_W
    assert circuit.intent.assumptions["board_height_mm"] == BOARD_H


def test_driver_uses_charge_pump_not_invented_phase_bootstraps() -> None:
    assert DRV_PIN_NETS["1"] == "DRV_CPL"
    assert DRV_PIN_NETS["2"] == "DRV_CPH"
    assert DRV_PIN_NETS["5"] == "DRV_VCP"
    assert DRV_PIN_NETS["40"] == "DRV_VGLS"
    assert not any("BOOT" in net or "BST_" in net for net in DRV_PIN_NETS.values())

    refs = {component.reference for component in compose_bldc_esc().components}
    assert {"CCP1", "CVCP1", "CVGLS1"} <= refs
    assert not any(reference.startswith("CBOOT") for reference in refs)


def test_tolt_pin_map_preserves_all_package_connections() -> None:
    high_side = _mosfet_nets(1)
    low_side = _mosfet_nets(2)

    assert all(high_side[str(pin)] == "PHASE_U" for pin in range(1, 8))
    assert high_side["8"] == "GATE_UH"
    assert all(high_side[str(pin)] == "BAT_P" for pin in range(9, 17))
    assert all(low_side[str(pin)] == "USHUNT_H" for pin in range(1, 8))
    assert low_side["8"] == "GATE_UL"
    assert all(low_side[str(pin)] == "PHASE_U" for pin in range(9, 17))


def test_shunt_footprint_is_two_terminal_with_kelvin_routing_role() -> None:
    circuit = compose_bldc_esc()
    by_ref = {component.reference: component for component in circuit.components}
    assert all(
        by_ref[f"RSH{index}"].role == "phase_shunt_with_kelvin_routing" for index in range(1, 4)
    )

    footprint = _power_footprints()["Vishay_WSLP2726"]
    assert footprint.count('(pad "1"') == 1
    assert footprint.count('(pad "2"') == 1
    assert '(pad "3"' not in footprint
    assert '(pad "4"' not in footprint


def test_rta_land_rows_use_datasheet_5_8_mm_center_span() -> None:
    footprint = _power_footprints()["Texas_RTA0040B_WQFN-40-1EP"]
    assert '(pad "1" smd rect (at -2.9000 2.2500)' in footprint
    assert '(pad "11" smd rect (at -2.2500 2.9000)' in footprint
    assert '(pad "21" smd rect (at 2.9000 -2.2500)' in footprint
    assert '(pad "31" smd rect (at 2.2500 -2.9000)' in footprint


def test_custom_body_envelopes_do_not_use_pad_crossing_silkscreen() -> None:
    footprints = _power_footprints()

    for footprint in footprints.values():
        assert '(fp_text reference "REF**"' in footprint
        assert '(layer "F.SilkS")' in footprint

    bulk = footprints["KEMET_A781_10x12.4mm_AntiVibration"]
    assert "(fp_circle (center 0 0) (end 5.2 0)" in bulk
    assert '(layer "F.Fab"))' in bulk
    assert '(layer "F.SilkS"))' in bulk  # pad-clear polarity mark remains
    tolt = footprints["Infineon_PG-HDSOP-16_TOLT"]
    assert "(start -5.15 -7.6) (end 5.15 7.6)" in tolt
    assert '(fill none) (layer "F.Fab"))' in tolt


def test_dc_link_schematic_bank_uses_non_overlapping_rows() -> None:
    bank = {
        reference: (x, y)
        for reference, _lib, x, y, _nets in INSTANCES
        if reference.startswith("CHF") or (reference.startswith("CB") and reference[2:].isdigit())
    }

    assert len(bank) == 14
    assert len(set(bank.values())) == 14
    assert {y for reference, (_x, y) in bank.items() if reference.startswith("CB")} == {
        25.4,
        50.8,
    }


def test_high_risk_parts_keep_pinned_manufacturer_evidence() -> None:
    circuit = compose_bldc_esc()
    by_ref = {component.reference: component for component in circuit.components}

    for reference in ("U1", "U2", "U3", "U4", "D1", "Q1", "RSH1", "CB1", "J1"):
        evidence = by_ref[reference].evidence
        assert evidence
        assert all(item.kind == "manufacturer_document" for item in evidence)
        assert all(item.source_status == "pinned" for item in evidence)
        assert all(item.local_sha256 for item in evidence)


def test_review_proxy_models_are_explicitly_marked_non_authoritative(tmp_path: Path) -> None:
    generated = generate_bldc_esc_proxy_models(tmp_path)

    assert {
        "drv8353-rta-envelope.wrl",
        "iptc011n08-tolt-envelope.wrl",
        "a781-10x12p4-envelope.wrl",
        "lm5164-dda-envelope.wrl",
        "tlv767-drb-envelope.wrl",
    } <= generated.keys()
    for path in generated.values():
        text = path.read_text(encoding="ascii")
        assert "datasheet-envelope proxy" in text
        assert "not exact assembly CAD" in text


def test_r002_mechanical_models_are_dimensioned_and_non_authoritative(tmp_path: Path) -> None:
    generated = generate_bldc_esc_r002_mechanical_models(tmp_path)

    assert HEATSINK_WIDTH_MM == 42.0
    assert HEATSINK_LENGTH_MM == 82.0
    assert HEATSINK_BASE_BOTTOM_MM == 2.6
    assert HEATSINK_FIN_HEIGHT_MM == 9.0
    assert TIM_THICKNESS_MM == 0.3
    assert {
        "bldc-r002-heatsink-envelope.wrl",
        "bldc-r002-isolating-tim-envelope.wrl",
        "bldc-r002-clamp-standoff-envelope.wrl",
    } <= generated.keys()
    assert "not a selected heatsink" in generated[
        "bldc-r002-heatsink-envelope.wrl"
    ].read_text(encoding="ascii")
    assert "material is not selected" in generated[
        "bldc-r002-isolating-tim-envelope.wrl"
    ].read_text(encoding="ascii")
    assert "exact hardware is not selected" in generated[
        "bldc-r002-clamp-standoff-envelope.wrl"
    ].read_text(encoding="ascii")
