"""Human-readable schematic for the offline flyback (Track 9.1).

Drawn the way switch-mode supplies are read: mains entry at the far
left (terminal, fusible resistor, MOV/X2 across the line, line Y-caps
to the earth pad), the bridge feeding an HVP top rail and HVM bottom
rail, the RCD clamp above the transformer primary, the UCC28881 below
with its housekeeping (CV1, RP1), the transformer at center as the
isolation boundary, then the secondary: Schottky into a 3V3 top rail /
GNDS bottom rail, output filter, the LMV431 + divider feedback, and
the optocoupler straddling back to the switcher's FB pin. The barrier
Y-cap CY1 bridges HVM and GNDS in the bottom rail line.

Connectivity is validated offline against export_flyback.INSTANCES
(the machine pin->net table) and re-proven live by kicad-cli ERC plus
netlist-export equality - two drawings, one truth.
"""

from __future__ import annotations

from pathlib import Path

from pcbsmith.circuit.models import CircuitObject
from pcbsmith.kicad.export_divider_highpass_led import (
    _render_project,
    _validate_project_name,
)
from pcbsmith.kicad.export_flyback import (
    _CUSTOM_SYMBOLS,
    BRIDGE,
    CAP_POLARIZED,
    CAPACITOR,
    CONNECTOR,
    CONNECTOR_1P,
    DIODE,
    INSTANCES,
    OPTO,
    RESISTOR,
    SCHOTTKY,
    SUPPORTED_TOPOLOGY_ID,
    TESTPOINT,
    VARISTOR,
    _custom_pin_positions,
    _custom_symbol_library_entry,
)
from pcbsmith.kicad.reader_schematic import (
    CustomReaderSymbol,
    ReaderInstance,
    ReaderSpec,
    render_reader_schematic,
)

# The machine schematic's pin->net table is the single source of truth.
PIN_NETS: dict[str, dict[str, str]] = {
    reference: dict(pin_nets) for reference, _lib, _x, pin_nets in INSTANCES
}


def _customs() -> tuple[CustomReaderSymbol, ...]:
    return tuple(
        CustomReaderSymbol(
            lib_id=lib_id,
            pins=tuple(
                (number, x, y)
                for number, (x, y, _angle) in
                _custom_pin_positions(lib_id).items()
            ),
            library_entry=_custom_symbol_library_entry(lib_id, description),
        )
        for lib_id, description in _CUSTOM_SYMBOLS
    )


UCC28881, LMV431, TRANSFORMER = (lib for lib, _d in _CUSTOM_SYMBOLS)

HVP_RAIL_Y = 40.64
HVM_RAIL_Y = 127.0
ACL_BUS_Y = 50.8
N_BUS_Y = 101.6
EARTH_BUS_Y = 115.57

FLYBACK_READER_SPEC = ReaderSpec(
    customs=_customs(),
    instances=(
        # -- mains entry ------------------------------------------------
        ReaderInstance(
            "J1", CONNECTOR, (24.13, 63.5),
            reference_at=(26.67, 58.42), value_at=(28.58, 71.12),
        ),
        ReaderInstance(
            "RF1", RESISTOR, (40.64, 50.8), rotation=90,
            reference_at=(40.64, 46.99), value_at=(40.64, 54.61),
        ),
        ReaderInstance(
            "RV1", VARISTOR, (55.88, 76.2),
            reference_at=(51.44, 71.12), value_at=(48.9, 85.09),
        ),
        ReaderInstance(
            "CX1", CAPACITOR, (66.04, 76.2),
            reference_at=(69.85, 71.12), value_at=(72.39, 80.01),
        ),
        ReaderInstance(
            "CY2", CAPACITOR, (77.47, 107.95),
            reference_at=(73.03, 106.68), value_at=(66.04, 110.49),
        ),
        ReaderInstance(
            "CY3", CAPACITOR, (90.17, 107.95),
            reference_at=(94.62, 106.68), value_at=(99.06, 110.49),
        ),
        ReaderInstance(
            "E1", CONNECTOR_1P, (26.67, 115.57), in_bom=False,
            reference_at=(29.21, 111.76), value_at=(29.85, 119.38),
        ),
        # -- rectifier and bus ------------------------------------------
        ReaderInstance(
            "BR1", BRIDGE, (115.57, 76.2),
            reference_at=(115.57, 88.9), value_at=(115.57, 91.44),
        ),
        ReaderInstance(
            "CB1", CAP_POLARIZED, (132.08, 80.01),
            reference_at=(129.54, 71.12), value_at=(127.0, 68.58),
        ),
        ReaderInstance(
            "D5", DIODE, (140.97, 80.01), rotation=270,
            reference_at=(144.78, 76.2), value_at=(146.05, 78.74),
        ),
        ReaderInstance(
            "TP1", TESTPOINT, (198.12, 36.83), in_bom=False,
            reference_at=(198.12, 34.29), value_at=(198.12, 31.75),
        ),
        # -- RCD clamp above the transformer primary --------------------
        ReaderInstance(
            "RC1", RESISTOR, (167.64, 52.07),
            reference_at=(163.83, 50.8), value_at=(160.02, 53.34),
        ),
        ReaderInstance(
            "CC1", CAPACITOR, (176.53, 52.07),
            reference_at=(180.34, 50.8), value_at=(184.15, 53.34),
        ),
        ReaderInstance(
            "D6", DIODE, (171.45, 68.58), rotation=270,
            reference_at=(175.9, 66.68), value_at=(177.17, 69.85),
        ),
        # -- the switcher and housekeeping -------------------------------
        ReaderInstance(
            "U1", UCC28881, (147.32, 99.06),
            reference_at=(147.32, 89.54), value_at=(147.32, 110.49),
        ),
        ReaderInstance(
            "CV1", CAPACITOR, (125.73, 111.76),
            reference_at=(121.92, 109.22), value_at=(120.65, 111.76),
        ),
        ReaderInstance(
            "RP1", RESISTOR, (144.78, 119.38),
            reference_at=(148.59, 118.11), value_at=(149.23, 120.65),
        ),
        # -- the isolation boundary ---------------------------------------
        ReaderInstance(
            "T1", TRANSFORMER, (223.52, 68.58),
            reference_at=(223.52, 57.79), value_at=(223.52, 82.55),
        ),
        ReaderInstance(
            "U2", OPTO, (198.12, 110.49), rotation=180,
            reference_at=(198.12, 100.33), value_at=(198.12, 120.65),
        ),
        ReaderInstance(
            "CY1", CAPACITOR, (228.6, 127.0), rotation=90,
            reference_at=(228.6, 121.92), value_at=(228.6, 133.35),
        ),
        # -- secondary --------------------------------------------------
        ReaderInstance(
            "D7", SCHOTTKY, (250.19, 40.64), rotation=180,
            reference_at=(250.19, 36.83), value_at=(250.19, 45.72),
        ),
        ReaderInstance(
            "CO1", CAP_POLARIZED, (261.62, 83.82),
            reference_at=(257.81, 78.74), value_at=(254.0, 92.71),
        ),
        ReaderInstance(
            "CO2", CAPACITOR, (270.51, 83.82),
            reference_at=(274.32, 78.74), value_at=(275.59, 81.28),
        ),
        ReaderInstance(
            "U3", LMV431, (317.5, 95.25),
            reference_at=(323.85, 91.44), value_at=(324.49, 99.06),
        ),
        ReaderInstance(
            "RFB1", RESISTOR, (344.17, 72.39),
            reference_at=(348.62, 71.12), value_at=(349.25, 73.66),
        ),
        ReaderInstance(
            "RFB2", RESISTOR, (344.17, 88.9),
            reference_at=(348.62, 87.63), value_at=(349.25, 90.17),
        ),
        ReaderInstance(
            "CF1", CAPACITOR, (353.06, 72.39),
            reference_at=(357.51, 68.58), value_at=(356.87, 66.04),
        ),
        ReaderInstance(
            "RO1", RESISTOR, (287.02, 99.06),
            reference_at=(291.47, 97.79), value_at=(292.1, 100.33),
        ),
        ReaderInstance(
            "RO2", RESISTOR, (209.55, 109.22), rotation=180,
            reference_at=(214.63, 108.71), value_at=(215.27, 111.25),
        ),
        ReaderInstance(
            "TP2", TESTPOINT, (355.6, 123.19), in_bom=False,
            reference_at=(359.41, 121.92), value_at=(355.6, 118.11),
        ),
        ReaderInstance(
            "J2", CONNECTOR, (378.46, 80.01),
            reference_at=(378.46, 74.93), value_at=(378.46, 88.9),
        ),
    ),
    wires=(
        # L: terminal wraps up into the fusible resistor.
        ((19.05, 63.5), (16.51, 63.5)),
        ((16.51, 63.5), (16.51, ACL_BUS_Y)),
        ((16.51, ACL_BUS_Y), (36.83, ACL_BUS_Y)),
        # N: terminal wraps down into the N bus feeding the bridge.
        ((19.05, 66.04), (13.97, 66.04)),
        ((13.97, 66.04), (13.97, N_BUS_Y)),
        ((13.97, N_BUS_Y), (109.22, N_BUS_Y)),
        ((109.22, N_BUS_Y), (109.22, 83.82)),
        ((109.22, 83.82), (115.57, 83.82)),
        # ACL: post-fuse live bus into the bridge.
        ((44.45, ACL_BUS_Y), (110.49, ACL_BUS_Y)),
        ((110.49, ACL_BUS_Y), (110.49, 68.58)),
        ((110.49, 68.58), (115.57, 68.58)),
        # Line protection between ACL and N.
        ((55.88, 72.39), (55.88, ACL_BUS_Y)),
        ((55.88, 80.01), (55.88, N_BUS_Y)),
        ((66.04, 72.39), (66.04, ACL_BUS_Y)),
        ((66.04, 80.01), (66.04, N_BUS_Y)),
        # Line Y-caps to the earth bus (CY2's riser CROSSES the N bus).
        ((77.47, 104.14), (77.47, ACL_BUS_Y)),
        ((77.47, 111.76), (77.47, EARTH_BUS_Y)),
        ((90.17, 104.14), (90.17, N_BUS_Y)),
        ((90.17, 111.76), (90.17, EARTH_BUS_Y)),
        ((21.59, EARTH_BUS_Y), (90.17, EARTH_BUS_Y)),
        # Bridge out: HVP top rail, HVM bottom rail.
        ((123.19, 76.2), (127.0, 76.2)),
        ((127.0, 76.2), (127.0, HVP_RAIL_Y)),
        ((127.0, HVP_RAIL_Y), (215.9, HVP_RAIL_Y)),
        ((107.95, 76.2), (105.41, 76.2)),
        ((105.41, 76.2), (105.41, HVM_RAIL_Y)),
        ((105.41, HVM_RAIL_Y), (215.9, HVM_RAIL_Y)),
        # Bulk, TVS, HV test point.
        ((132.08, 76.2), (132.08, HVP_RAIL_Y)),
        ((132.08, 83.82), (132.08, HVM_RAIL_Y)),
        ((140.97, 76.2), (140.97, HVP_RAIL_Y)),
        ((140.97, 83.82), (140.97, HVM_RAIL_Y)),
        ((198.12, 36.83), (198.12, HVP_RAIL_Y)),
        # RCD clamp: RC1 || CC1 from HVP down to the clamp node, D6 to SW.
        ((167.64, 48.26), (167.64, HVP_RAIL_Y)),
        ((167.64, 55.88), (167.64, 63.5)),
        ((176.53, 48.26), (176.53, HVP_RAIL_Y)),
        ((176.53, 55.88), (176.53, 63.5)),
        ((167.64, 63.5), (176.53, 63.5)),
        ((171.45, 64.77), (171.45, 63.5)),
        ((171.45, 72.39), (171.45, 73.66)),
        # SW: drain rise, clamp diode, transformer primary return.
        ((165.1, 73.66), (215.9, 73.66)),
        ((157.48, 102.87), (165.1, 102.87)),
        ((165.1, 102.87), (165.1, 73.66)),
        # HVIN straight up to the HVP rail.
        ((157.48, 95.25), (160.02, 95.25)),
        ((160.02, 95.25), (160.02, HVP_RAIL_Y)),
        # Switcher grounds join and drop to HVM.
        ((137.16, 95.25), (134.62, 95.25)),
        ((137.16, 97.79), (134.62, 97.79)),
        ((134.62, 95.25), (134.62, HVM_RAIL_Y)),
        # VDD: bypass cap and the opto collector.
        ((137.16, 102.87), (130.81, 102.87)),
        ((130.81, 102.87), (125.73, 102.87)),
        ((125.73, 102.87), (125.73, 107.95)),
        ((125.73, 115.57), (125.73, HVM_RAIL_Y)),
        ((130.81, 102.87), (130.81, 105.41)),
        ((130.81, 105.41), (184.15, 105.41)),
        ((184.15, 105.41), (184.15, 113.03)),
        ((184.15, 113.03), (190.5, 113.03)),
        # FB: switcher pin, pull-down, opto emitter.
        ((137.16, 100.33), (129.54, 100.33)),
        ((129.54, 100.33), (129.54, 115.57)),
        ((129.54, 115.57), (144.78, 115.57)),
        ((144.78, 115.57), (185.42, 115.57)),
        ((185.42, 115.57), (185.42, 107.95)),
        ((185.42, 107.95), (190.5, 107.95)),
        ((144.78, 123.19), (144.78, HVM_RAIL_Y)),
        # Transformer primary from the rails.
        ((215.9, HVP_RAIL_Y), (215.9, 63.5)),
        # Secondary: rectifier into the 3V3 rail, GNDS return rail.
        ((231.14, 63.5), (241.3, 63.5)),
        ((241.3, 63.5), (241.3, HVP_RAIL_Y)),
        ((241.3, HVP_RAIL_Y), (246.38, HVP_RAIL_Y)),
        ((254.0, HVP_RAIL_Y), (368.3, HVP_RAIL_Y)),
        ((231.14, 73.66), (241.3, 73.66)),
        ((241.3, 73.66), (241.3, HVM_RAIL_Y)),
        ((241.3, HVM_RAIL_Y), (365.76, HVM_RAIL_Y)),
        # The barrier Y-cap bridges HVM and GNDS in the rail line.
        ((224.79, HVM_RAIL_Y), (215.9, HVM_RAIL_Y)),
        ((232.41, HVM_RAIL_Y), (241.3, HVM_RAIL_Y)),
        # Output filter.
        ((261.62, 80.01), (261.62, HVP_RAIL_Y)),
        ((261.62, 87.63), (261.62, HVM_RAIL_Y)),
        ((270.51, 80.01), (270.51, HVP_RAIL_Y)),
        ((270.51, 87.63), (270.51, HVM_RAIL_Y)),
        # Opto drive: RO1 from 3V3, LED row, RO2 across the LED.
        ((287.02, 95.25), (287.02, HVP_RAIL_Y)),
        ((287.02, 102.87), (287.02, 113.03)),
        ((205.74, 113.03), (209.55, 113.03)),
        ((209.55, 113.03), (287.02, 113.03)),
        ((209.55, 105.41), (209.55, 104.14)),
        ((209.55, 104.14), (213.36, 104.14)),
        # OPK: opto cathode across to the LMV431 cathode (routed ABOVE
        # the output caps' plates - through their wire crossings, never
        # their bodies).
        ((205.74, 107.95), (213.36, 107.95)),
        ((213.36, 107.95), (213.36, 77.47)),
        ((213.36, 77.47), (317.5, 77.47)),
        ((317.5, 77.47), (317.5, 90.17)),
        # LMV431 anode to GNDS; REF from the divider bus.
        ((317.5, 100.33), (317.5, HVM_RAIL_Y)),
        ((312.42, 95.25), (306.07, 95.25)),
        ((306.07, 95.25), (306.07, 82.55)),
        ((306.07, 82.55), (353.06, 82.55)),
        # Divider and the DNP compensation option.
        ((344.17, 68.58), (344.17, HVP_RAIL_Y)),
        ((344.17, 76.2), (344.17, 82.55)),
        ((344.17, 85.09), (344.17, 82.55)),
        ((344.17, 92.71), (344.17, HVM_RAIL_Y)),
        ((353.06, 68.58), (353.06, HVP_RAIL_Y)),
        ((353.06, 76.2), (353.06, 82.55)),
        # Test point and the output terminal.
        ((355.6, 123.19), (355.6, HVM_RAIL_Y)),
        ((368.3, HVP_RAIL_Y), (368.3, 80.01)),
        ((368.3, 80.01), (373.38, 80.01)),
        ((373.38, 82.55), (365.76, 82.55)),
        ((365.76, 82.55), (365.76, HVM_RAIL_Y)),
    ),
    labels=(
        ("L", (27.94, ACL_BUS_Y)),
        ("N", (48.26, N_BUS_Y)),
        ("ACL", (95.25, ACL_BUS_Y)),
        ("EARTH", (45.72, EARTH_BUS_Y)),
        ("HVP", (152.4, HVP_RAIL_Y)),
        ("HVM", (180.34, HVM_RAIL_Y)),
        ("SW", (190.5, 73.66)),
        ("CLAMP", (172.72, 63.5)),
        ("VDD", (170.18, 105.41)),
        ("FB", (158.75, 115.57)),
        ("SEC", (236.22, 63.5)),
        ("3V3", (298.45, HVP_RAIL_Y)),
        ("GNDS", (300.99, HVM_RAIL_Y)),
        ("FBS", (325.12, 82.55)),
        ("OPK", (256.54, 77.47)),
        ("LEDA", (247.65, 113.03)),
    ),
    paper="A3",
)


def export_flyback_reader_schematic(
    circuit: CircuitObject,
    output_dir: Path,
    *,
    project_name: str,
) -> dict[str, str]:
    """Write ``<name>-reader.kicad_sch`` (+ project file) next to the
    machine schematic. Raises if the drawing's wire connectivity does
    not reproduce the machine pin->net table."""
    if circuit.topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported circuit for KiCad export")
    project_name = _validate_project_name(project_name) + "-reader"

    output_dir.mkdir(parents=True, exist_ok=True)
    project_file = output_dir / f"{project_name}.kicad_pro"
    schematic_file = output_dir / f"{project_name}.kicad_sch"
    project_file.write_text(_render_project(), encoding="utf-8")
    schematic_file.write_text(
        render_reader_schematic(
            circuit,
            FLYBACK_READER_SPEC,
            project_name=project_name,
            pin_nets=PIN_NETS,
        ),
        encoding="utf-8",
    )
    return {
        "project_file": str(project_file),
        "schematic_file": str(schematic_file),
    }
