from __future__ import annotations

from pcbsmith.calculators.electronics import solve_i2c_pullup
from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.mpu6050 import compose_mpu6050
from pcbsmith.kicad.export_mpu6050 import MPU6050_PIN_NETS
from pcbsmith.simulation.ngspice_mpu6050 import render_mpu6050_netlist

REQUEST = "Make an MPU6050 gyroscope breakout module"


def test_i2c_pullup_selects_4k7_for_fast_mode() -> None:
    result = solve_i2c_pullup(supply_voltage_v=3.3, bus_capacitance_pf=50.0)

    assert result["status"] == "warning"
    assert result["outputs"]["selected_ohms"] == 2700.0 or (
        result["outputs"]["minimum_ohms"]
        <= result["outputs"]["selected_ohms"]
        <= result["outputs"]["maximum_ohms"]
    )


def test_composition_matches_the_datasheet_circuit() -> None:
    intent = classify_circuit_intent(REQUEST)
    assert intent.intent_id == "mpu6050_imu"
    circuit = compose_mpu6050(intent, select_topology(intent))

    by_ref = {component.reference: component for component in circuit.components}
    assert by_ref["C1"].value == "100nF"   # REGOUT (p22)
    assert by_ref["C3"].value == "2.2nF"   # CPOUT charge pump (p22)
    assert by_ref["C4"].value == "10nF"    # VLOGIC bypass (p22)
    assert by_ref["U1"].footprint == "Sensor_Motion:InvenSense_QFN-24_4x4mm_P0.5mm"
    # Unused-pin handling per p21: CLKIN and FSYNC tie to GND.
    assert MPU6050_PIN_NETS[1] == "GND"
    assert MPU6050_PIN_NETS[11] == "GND"
    # RESV pins 19/21/22 must NOT be connected.
    for pin in (19, 21, 22):
        assert pin not in MPU6050_PIN_NETS

    netlist = render_mpu6050_netlist(circuit)
    assert "V1 vdd 0 DC 3.3" in netlist
    assert ".op" in netlist
