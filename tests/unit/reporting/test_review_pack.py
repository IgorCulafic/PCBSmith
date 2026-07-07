"""Review pack (Track 8.1): deterministic reviewer artifacts."""

from __future__ import annotations

from pcbsmith.circuit.models import ComponentRole
from pcbsmith.reporting.review_pack import (
    TestStep,
    bom_consolidation_notes,
    render_block_diagram,
    render_fmea,
    render_pin_tables,
    render_review_pack,
    render_test_plan,
)


def _part(
    reference: str,
    role: str = "generic",
    value: str = "1k",
    footprint: str = "Resistor_SMD:R_0603_1608Metric",
) -> ComponentRole:
    return ComponentRole(
        reference=reference, role=role, symbol_id="stdlib:R", value=value,
        support_status="needs_datasheet_review", footprint=footprint,
    )


def test_block_diagram_buses_busy_nets_and_labels_pairs() -> None:
    components = [_part(f"R{i}") for i in range(1, 6)]
    pin_nets = {
        "R1": {"1": "/BUS", "2": "/A"},
        "R2": {"1": "/BUS", "2": "/A"},
        "R3": {"1": "/BUS"},
        "R4": {"1": "/BUS"},
        "R5": {"1": "/X"},
    }
    diagram = render_block_diagram(components, pin_nets)
    # /BUS has 4 members -> a bus node; /A has 2 -> a labeled edge.
    assert "BUS((/BUS))" in diagram
    assert "R1 ---|/A| R2" in diagram
    assert "```mermaid" in diagram


def test_pin_tables_render_card_pins() -> None:
    tables = render_pin_tables((("U1", "UCC28881"),))
    assert "U1 - UCC28881" in tables
    assert "| 8 | DRAIN |" in tables


def test_fmea_covers_known_roles_and_falls_back() -> None:
    fmea = render_fmea(
        [
            _part("BR1", role="bridge_rectifier"),
            _part("Z9", role="never_seen_role"),
        ]
    )
    assert "One diode open" in fmea
    assert "Human review required" in fmea


def test_test_plan_renders_steps() -> None:
    plan = render_test_plan(
        (TestStep(name="Bus", procedure="Probe TP1", expected="160VDC"),)
    )
    assert "| 1 | Bus | Probe TP1 | 160VDC |" in plan
    assert render_test_plan(()) == "_No test plan defined for this topology._"


def test_flyback_test_steps_carry_calculator_values() -> None:
    from pcbsmith.calculators.electronics import solve_offline_flyback
    from pcbsmith.generation.flyback import flyback_test_steps

    outputs = solve_offline_flyback(
        vac_min_v=108.0, vac_max_v=132.0, vout_v=3.3, iout_a=0.5
    )["outputs"]
    steps = flyback_test_steps(outputs)
    text = render_test_plan(steps)
    assert "3.31 V +/- 3%" in text
    assert "144-187 VDC" in text  # vdc_min .. vdc_peak_max, one place each
    assert "ISOLATION TRANSFORMER" in text


def test_bom_consolidation_flags_and_scoping() -> None:
    notes = bom_consolidation_notes(
        [
            # Same value, different SMD footprints -> flagged.
            _part("C1", value="100nF",
                  footprint="Capacitor_SMD:C_0603_1608Metric"),
            _part("C2", value="100nF",
                  footprint="Capacitor_SMD:C_0805_2012Metric"),
            # Near values in the same footprint -> flagged.
            _part("R1", value="2k"),
            _part("R2", value="2.2k"),
            # THT and unparseable values are out of scope.
            _part("CX1", value="100nF X2 275VAC",
                  footprint="Capacitor_THT:C_Rect_L18.0mm_W7.0mm_P15.00mm_FKS3_FKP3"),
            _part("CF1", value="DNP",
                  footprint="Capacitor_SMD:C_0603_1608Metric"),
        ]
    )
    assert any("C1" in note and "C2" in note for note in notes)
    assert any("R1" in note and "R2" in note for note in notes)
    assert not any("CX1" in note or "CF1" in note for note in notes)


def test_full_pack_assembles() -> None:
    pack = render_review_pack(
        project_name="Unit",
        components=[_part("R1")],
        pin_nets={"R1": {"1": "/A", "2": "/B"}},
        test_steps=(TestStep(name="s", procedure="p", expected="e"),),
        notes=("note one",),
    )
    for heading in (
        "## Block diagram", "## Test plan", "## FMEA",
        "## Pin functions", "## BOM consolidation",
    ):
        assert heading in pack
    assert "note one" in pack


def test_pin_nets_from_netlist_roundtrip() -> None:
    from pcbsmith.kicad.board import BoardNet, BoardNetlist
    from pcbsmith.reporting.review_pack import pin_nets_from_netlist

    netlist = BoardNetlist(
        components=(),
        nets=(
            BoardNet(name="/A", nodes=(("R1", "1"), ("R2", "2"))),
            BoardNet(name="/B", nodes=(("R1", "2"),)),
        ),
    )
    assert pin_nets_from_netlist(netlist) == {
        "R1": {"1": "/A", "2": "/B"},
        "R2": {"2": "/A"},
    }


def test_buck_test_steps_carry_calculator_values() -> None:
    from pcbsmith.calculators.electronics import solve_lm2596_buck
    from pcbsmith.generation.lm2596_buck import buck_test_steps

    outputs = solve_lm2596_buck(
        input_voltage_min_v=8.0, input_voltage_nominal_v=12.0,
        input_voltage_max_v=16.0, output_voltage_v=5.0, load_current_a=1.0,
    )["outputs"]
    text = render_test_plan(buck_test_steps(outputs))
    assert "5.03 V +/- 3%" in text
    assert "150 kHz" in text
    assert "Current-limit" in text


def test_mpu_test_steps_are_static_and_complete() -> None:
    from pcbsmith.generation.mpu6050 import mpu6050_test_steps

    text = render_test_plan(mpu6050_test_steps())
    assert "0x68" in text
    assert "WHO_AM_I" in text


def test_fmea_has_curated_rows_for_buck_and_flyback_roles() -> None:
    from pcbsmith.reporting.review_pack import ROLE_FMEA

    for role in (
        "buck_regulator", "catch_diode", "power_inductor",
        "flyback_switcher", "line_y_capacitor", "imu_sensor",
        "matrix_led", "divider_top",
    ):
        assert ROLE_FMEA.get(role), f"missing curated FMEA for {role}"
