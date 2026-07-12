"""Human-readable schematic for the thermometer display (Track 9.1).

Drawn the way MCU boards are read: USB-C entry at the far left (CC
pull-downs under the receptacle, polyfuse feeding the AP2112 LDO, power
LED off the 3.3V output), a VCC rail across the top and a GND rail
under band 1, the ESP32-C3 module at center with its EN RC and strap
pull-ups, the SHT31 sensor and the two OLED display headers with their
I2C pull-up banks on the right, and band 2 below: the two 74HC595
registers cascaded (CAS) driving sixteen labelled LED columns
(SEGk -> Rk -> LKk -> Dk -> GND) in two rows of eight.

Connectivity is validated offline against export_thermometer.INSTANCES
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
from pcbsmith.kicad.export_thermometer import (
    INSTANCES,
    LED,
    POLYFUSE,
    RESISTOR,
    SUPPORTED_TOPOLOGY_ID,
)
from pcbsmith.kicad.reader_schematic import (
    ReaderFlag,
    ReaderInstance,
    ReaderSpec,
    render_reader_schematic,
)
from pcbsmith.kicad.symbols import instance_pin_position_rotated, load_symbol

# The machine schematic's pin->net table is the single source of truth.
PIN_NETS: dict[str, dict[str, str]] = {
    reference: dict(pin_nets)
    for reference, _lib, _x, _y, pin_nets in INSTANCES
}

Point = tuple[float, float]

VCC_RAIL_Y = 53.34
GND_RAIL_Y = 137.16
GND_BUS1_Y = 287.02
GND_BUS2_Y = 340.36
GND_TRUNK_X = 528.32

# LED matrix geometry: two rows of eight columns; row 2 offset half a
# pitch so its feeds thread between row 1's columns.
COL_PITCH = 17.78
ROW1_X0 = 243.84
ROW2_X0 = 252.73


def _col_x(index: int) -> float:
    """Sheet x of LED column ``index`` (1-based, 1..16)."""
    if index <= 8:
        return ROW1_X0 + COL_PITCH * (index - 1)
    return ROW2_X0 + COL_PITCH * (index - 9)


def _tip(lib_id: str, at: Point, rotation: int, pin: str) -> Point:
    x, y = instance_pin_position_rotated(
        load_symbol(lib_id), pin, at, rotation
    )
    return (round(x, 2), round(y, 2))


def _oriented(
    lib_id: str, at: Point, top_pin: str, bottom_pin: str
) -> int:
    """The quarter turn that puts ``top_pin`` above ``bottom_pin`` -
    measured from the symbol, never assumed (LED/polyfuse pin order
    differs per symbol)."""
    for rotation in (0, 90, 180, 270):
        top = _tip(lib_id, at, rotation, top_pin)
        bottom = _tip(lib_id, at, rotation, bottom_pin)
        if top[1] < bottom[1] and abs(top[0] - bottom[0]) < 1e-6:
            return rotation
    raise ValueError(f"No vertical orientation for {lib_id}")


def _west_east(
    lib_id: str, at: Point, west_pin: str, east_pin: str
) -> int:
    for rotation in (0, 90, 180, 270):
        west = _tip(lib_id, at, rotation, west_pin)
        east = _tip(lib_id, at, rotation, east_pin)
        if west[0] < east[0] and abs(west[1] - east[1]) < 1e-6:
            return rotation
    raise ValueError(f"No horizontal orientation for {lib_id}")


def _build_spec() -> ReaderSpec:
    at: dict[str, Point] = {
        "J1": (43.18, 83.82),
        "F1": (86.36, 68.58),
        "U5": (114.3, 71.12),
        "C5": (99.06, 76.2),
        "TP1": (133.35, VCC_RAIL_Y),
        "TP2": (133.35, GND_RAIL_Y),
        "R17": (137.16, 64.77),
        # y 77.47: at 80.01 the cathode pin tip landed exactly ON the
        # DM trunk (y 83.82) - a drawn short the validator caught.
        "D17": (137.16, 77.47),
        "C6": (129.54, 64.77),
        "RCC1": (63.5, 95.25),
        "RCC2": (72.39, 95.25),
        "U1": (190.5, 83.82),
        "REN1": (162.56, 58.42),
        "RS2": (157.48, 58.42),
        "CEN1": (154.94, 71.12),
        "RS1": (160.02, 68.58),
        "C1": (218.44, 64.77),
        "C2": (223.52, 64.77),
        "U4": (247.65, 83.82),
        "C7": (264.16, 64.77),
        "RI1": (269.24, 64.77),
        "RI2": (276.86, 64.77),
        "RI3": (284.48, 64.77),
        "RI4": (292.1, 64.77),
        "J2": (330.2, 96.52),
        "J3": (330.2, 120.65),
        "U2": (170.18, 198.12),
        "U3": (170.18, 264.16),
        "C3": (198.12, 187.96),
        "C4": (205.74, 254.0),
        "ROE1": (134.62, 231.14),
    }
    for index in range(1, 17):
        at[f"R{index}"] = (
            _col_x(index), 226.06 if index <= 8 else 297.18
        )
        at[f"D{index}"] = (
            _col_x(index), 254.0 if index <= 8 else 326.39
        )

    rot: dict[str, int] = {
        "F1": _west_east(POLYFUSE, at["F1"], "1", "2"),
        "D17": _oriented(LED, at["D17"], "2", "1"),  # anode up
        "ROE1": _west_east(RESISTOR, at["ROE1"], "1", "2"),
    }
    for index in range(1, 17):
        rot[f"D{index}"] = _oriented(LED, at[f"D{index}"], "2", "1")

    libs: dict[str, str] = {
        reference: lib_id for reference, lib_id, _x, _y, _p in INSTANCES
    }

    def tip(reference: str, pin: str) -> Point:
        return _tip(
            libs[reference], at[reference], rot.get(reference, 0), pin
        )

    wires: list[tuple[Point, Point]] = []

    def path(*points: Point) -> None:
        wires.extend(
            (points[index], points[index + 1])
            for index in range(len(points) - 1)
        )

    # -- rails --------------------------------------------------------
    # TP1/TP2 pins split the rails on purpose: a test point must sit at
    # a segment endpoint, not mid-wire. Each rail ends exactly at its
    # last tap (318.77: the display headers' VCC riser; the GND trunk):
    # a rail overhang is a dangling endpoint to ERC.
    path((127.0, VCC_RAIL_Y), tip("TP1", "1"), (318.77, VCC_RAIL_Y))
    path((35.56, GND_RAIL_Y), tip("TP2", "1"), (GND_TRUNK_X, GND_RAIL_Y))

    # -- USB entry ----------------------------------------------------
    vbus = tip("J1", "A4")  # A4/A9/B4/B9 share the symbol point
    f1_in, f1_out = tip("F1", "1"), tip("F1", "2")
    u5_in, u5_en = tip("U5", "1"), tip("U5", "3")
    u5_gnd, u5_out = tip("U5", "2"), tip("U5", "5")
    path(vbus, f1_in)
    path(f1_out, u5_in)
    path((104.14, u5_in[1]), (104.14, u5_en[1]), u5_en)
    c5_top, c5_bot = tip("C5", "1"), tip("C5", "2")
    path(c5_top, (c5_top[0], u5_in[1]))
    path(c5_bot, (c5_bot[0], GND_RAIL_Y))
    path(u5_gnd, (u5_gnd[0], GND_RAIL_Y))
    path(u5_out, (127.0, u5_out[1]), (127.0, VCC_RAIL_Y))
    j1_gnd = tip("J1", "A1")
    path(j1_gnd, (j1_gnd[0], GND_RAIL_Y))
    j1_sh = tip("J1", "SH")
    path(j1_sh, (j1_sh[0], GND_RAIL_Y))

    # CC pull-downs: risers drop past the D+/D- rows (crossings, not
    # joins), then step across to the staggered resistor tops.
    cc1, cc2 = tip("J1", "A5"), tip("J1", "B5")
    rcc1_t, rcc1_b = tip("RCC1", "1"), tip("RCC1", "2")
    rcc2_t, rcc2_b = tip("RCC2", "1"), tip("RCC2", "2")
    path(cc1, (62.23, cc1[1]), (62.23, rcc1_t[1]), rcc1_t)
    path(cc2, (59.69, cc2[1]), (59.69, 92.71), (rcc2_t[0], 92.71), rcc2_t)
    path(rcc1_b, (rcc1_b[0], GND_RAIL_Y))
    path(rcc2_b, (rcc2_b[0], GND_RAIL_Y))

    # D-/D+: each pair joins beside the receptacle, then one trunk each
    # to the module's USB pins.
    dm_a, dm_b = tip("J1", "A7"), tip("J1", "B7")
    dp_a, dp_b = tip("J1", "A6"), tip("J1", "B6")
    u1_dm, u1_dp = tip("U1", "13"), tip("U1", "14")
    path(dm_a, (60.96, dm_a[1]), (60.96, dm_b[1]))
    path(dm_b, (60.96, dm_b[1]), (153.67, dm_b[1]),
         (153.67, u1_dm[1]), u1_dm)
    path(dp_a, (63.5, dp_a[1]), (63.5, dp_b[1]))
    path(dp_b, (63.5, dp_b[1]), (151.13, dp_b[1]),
         (151.13, u1_dp[1]), u1_dp)

    # -- power LED and LDO decoupling ----------------------------------
    r17_t, r17_b = tip("R17", "1"), tip("R17", "2")
    d17_a, d17_k = tip("D17", "2"), tip("D17", "1")
    path(r17_t, (r17_t[0], VCC_RAIL_Y))
    path(r17_b, d17_a)
    path(d17_k, (d17_k[0], GND_RAIL_Y))
    for cap in ("C6", "C1", "C2"):
        top, bottom = tip(cap, "1"), tip(cap, "2")
        path(top, (top[0], VCC_RAIL_Y))
        path(bottom, (bottom[0], GND_RAIL_Y))

    # -- ESP32 module ---------------------------------------------------
    u1_vcc, u1_gnd = tip("U1", "1"), tip("U1", "9")
    path(u1_vcc, (u1_vcc[0], VCC_RAIL_Y))
    path(u1_gnd, (u1_gnd[0], GND_RAIL_Y))
    # EN: pull-up + RC, one horizontal with the resistor and cap tapped.
    u1_en = tip("U1", "2")
    ren1_t, ren1_b = tip("REN1", "1"), tip("REN1", "2")
    cen1_t, cen1_b = tip("CEN1", "1"), tip("CEN1", "2")
    path(u1_en, (cen1_t[0], u1_en[1]))
    path(ren1_b, (ren1_b[0], u1_en[1]))
    path(ren1_t, (ren1_t[0], VCC_RAIL_Y))
    path(cen1_t, (cen1_t[0], u1_en[1]))
    path(cen1_b, (cen1_b[0], GND_RAIL_Y))
    # Strap pull-ups IO2/IO8.
    u1_io2, u1_io8 = tip("U1", "16"), tip("U1", "7")
    rs1_t, rs1_b = tip("RS1", "1"), tip("RS1", "2")
    rs2_t, rs2_b = tip("RS2", "1"), tip("RS2", "2")
    path(u1_io2, (rs1_b[0], u1_io2[1]), rs1_b)
    path(rs1_t, (rs1_t[0], VCC_RAIL_Y))
    path(u1_io8, (rs2_b[0], u1_io8[1]), rs2_b)
    path(rs2_t, (rs2_t[0], VCC_RAIL_Y))

    # -- I2C lanes over the rail to the right zone ---------------------
    # (net, U1 pin, west riser x, lane y, east riser x, drop y, header pin)
    lanes = (
        ("SDA1", "3", 172.72, 27.94, 299.72, 101.6, ("J2", "4")),
        ("SCL1", "4", 170.18, 30.48, 302.26, 99.06, ("J2", "3")),
        ("SDA2", "5", 167.64, 33.02, 304.8, 125.73, ("J3", "4")),
        ("SCL2", "6", 163.83, 35.56, 307.34, 123.19, ("J3", "3")),
    )
    for _net, pin, west_x, lane_y, east_x, drop_y, header in lanes:
        start = tip("U1", pin)
        end = tip(*header)
        path(start, (west_x, start[1]), (west_x, lane_y),
             (east_x, lane_y), (east_x, drop_y), end)

    # I2C pull-up bank: staggered join rows so no stub lands on a
    # neighbour's horizontal.
    pullups = (
        ("RI1", 73.66, 299.72), ("RI2", 72.39, 302.26),
        ("RI3", 71.12, 304.8), ("RI4", 69.85, 307.34),
    )
    for reference, join_y, riser_x in pullups:
        top, bottom = tip(reference, "1"), tip(reference, "2")
        path(top, (top[0], VCC_RAIL_Y))
        path(bottom, (bottom[0], join_y), (riser_x, join_y))

    # -- sensor ---------------------------------------------------------
    u4_vdd, u4_vss = tip("U4", "5"), tip("U4", "8")
    u4_sda, u4_scl = tip("U4", "1"), tip("U4", "4")
    u4_addr, u4_r = tip("U4", "2"), tip("U4", "7")
    path(u4_vdd, (u4_vdd[0], VCC_RAIL_Y))
    path(u4_vss, (u4_vss[0], GND_RAIL_Y))
    path(u4_sda, (299.72, u4_sda[1]))
    path(u4_scl, (302.26, u4_scl[1]))
    path(u4_addr, (233.68, u4_addr[1]), (233.68, GND_RAIL_Y))
    path(u4_r, (236.22, u4_r[1]), (236.22, GND_RAIL_Y))
    c7_top, c7_bot = tip("C7", "1"), tip("C7", "2")
    path(c7_top, (u4_vdd[0], c7_top[1]))
    path(c7_bot, (c7_bot[0], GND_RAIL_Y))

    # -- display headers ------------------------------------------------
    j2_gnd, j2_vcc = tip("J2", "1"), tip("J2", "2")
    j3_gnd, j3_vcc = tip("J3", "1"), tip("J3", "2")
    path(j2_gnd, (321.31, j2_gnd[1]), (321.31, GND_RAIL_Y))
    path(j3_gnd, (321.31, j3_gnd[1]))
    path(j3_vcc, (318.77, j3_vcc[1]), (318.77, VCC_RAIL_Y))
    path(j2_vcc, (318.77, j2_vcc[1]))

    # -- band 2: registers ---------------------------------------------
    # Control risers from the module, T-branching at each register row.
    u1_ser = tip("U1", "10")
    u1_srclk, u1_rclk, u1_oe = (
        tip("U1", "18"), tip("U1", "17"), tip("U1", "15")
    )
    u2 = {pin: tip("U2", pin) for pin in PIN_NETS["U2"]}
    u3 = {pin: tip("U3", pin) for pin in PIN_NETS["U3"]}
    path(u1_ser, (142.24, u1_ser[1]), (142.24, u2["14"][1]), u2["14"])
    path(u1_srclk, (144.78, u1_srclk[1]),
         (144.78, u2["11"][1]), u2["11"])
    path((144.78, u2["11"][1]), (144.78, u3["11"][1]), u3["11"])
    path(u1_rclk, (147.32, u1_rclk[1]), (147.32, u2["12"][1]), u2["12"])
    path((147.32, u2["12"][1]), (147.32, u3["12"][1]), u3["12"])
    path(u1_oe, (149.86, u1_oe[1]), (149.86, u2["13"][1]), u2["13"])
    path((149.86, u2["13"][1]), (149.86, u3["13"][1]), u3["13"])
    # OE pull-up taps the riser between the registers.
    roe1_vcc, roe1_oe = tip("ROE1", "1"), tip("ROE1", "2")
    path(roe1_oe, (149.86, roe1_oe[1]))
    path(roe1_vcc, (128.27, roe1_vcc[1]), (128.27, VCC_RAIL_Y))
    # VCC trunk feeding both register banks (16 and the SRCLR pin 10).
    path((215.9, VCC_RAIL_Y), (215.9, 177.8), (215.9, 243.84))
    path(u2["16"], (u2["16"][0], 177.8), (215.9, 177.8))
    path(u2["10"], (153.67, u2["10"][1]), (153.67, 177.8),
         (u2["16"][0], 177.8))
    path(u3["16"], (u3["16"][0], 243.84), (215.9, 243.84))
    path(u3["10"], (153.67, u3["10"][1]), (153.67, 243.84),
         (u3["16"][0], 243.84))
    # Register decoupling.
    c3_top, c3_bot = tip("C3", "1"), tip("C3", "2")
    path(c3_top, (c3_top[0], 177.8))
    path(c3_bot, (c3_bot[0], GND_BUS1_Y))
    c4_top, c4_bot = tip("C4", "1"), tip("C4", "2")
    path(c4_top, (c4_top[0], 243.84))
    path(c4_bot, (c4_bot[0], GND_BUS1_Y))
    # Register grounds: U2 routes around U3's column, U3 drops straight.
    path(u2["8"], (u2["8"][0], 218.44), (135.89, 218.44),
         (135.89, GND_BUS1_Y))
    path(u3["8"], (u3["8"][0], GND_BUS1_Y))
    # The cascade.
    path(u2["9"], (184.15, u2["9"][1]), (184.15, 236.22),
         (151.13, 236.22), (151.13, u3["14"][1]), u3["14"])

    # -- LED matrix ------------------------------------------------------
    path((135.89, GND_BUS1_Y), (GND_TRUNK_X, GND_BUS1_Y))
    path((ROW2_X0, GND_BUS2_Y), (GND_TRUNK_X, GND_BUS2_Y))
    path((GND_TRUNK_X, GND_RAIL_Y), (GND_TRUNK_X, GND_BUS2_Y))
    seg_pins = ("15", "1", "2", "3", "4", "5", "6", "7")
    for index in range(1, 17):
        register = u2 if index <= 8 else u3
        source = register[seg_pins[(index - 1) % 8]]
        column = _col_x(index)
        r_top, r_bot = tip(f"R{index}", "1"), tip(f"R{index}", "2")
        d_a, d_k = tip(f"D{index}", "2"), tip(f"D{index}", "1")
        path(source, (column, source[1]), r_top)
        path(r_bot, d_a)
        path(d_k, (column, GND_BUS1_Y if index <= 8 else GND_BUS2_Y))

    labels: list[tuple[str, Point]] = [
        ("VBUS", (66.04, vbus[1])),
        ("VBUSF", (96.52, u5_in[1])),
        ("VCC", (152.4, VCC_RAIL_Y)),
        ("GND", (48.26, GND_RAIL_Y)),
        ("CC1", (62.23, 85.09)),
        ("CC2", (59.69, 80.01)),
        ("DM", (95.25, dm_b[1])),
        ("DP", (95.25, dp_b[1])),
        ("PWLED", (137.16, 71.12)),
        ("EN", (156.21, u1_en[1])),
        ("IO2", (168.91, u1_io2[1])),
        ("IO8", (165.1, u1_io8[1])),
        ("SDA1", (233.68, 27.94)),
        ("SCL1", (233.68, 30.48)),
        ("SDA2", (233.68, 33.02)),
        ("SCL2", (233.68, 35.56)),
        ("SER", (142.24, 158.75)),
        ("SRCLK", (144.78, 163.83)),
        ("RCLK", (147.32, 168.91)),
        ("OE", (149.86, 173.99)),
        ("CAS", (167.64, 236.22)),
    ]
    for index in range(1, 17):
        seg_pin = seg_pins[(index - 1) % 8]
        seg_y = (u2 if index <= 8 else u3)[seg_pin][1]
        labels.append((f"SEG{index}", (228.6, seg_y)))
        labels.append((f"LK{index}", (
            _col_x(index), 240.03 if index <= 8 else 311.15
        )))

    # Explicit text spots for the crowded regions (SVG review): default
    # field placement collides with wires around the power entry, the
    # EN/strap RC cluster, the pull-up bank, the headers and registers.
    text_at: dict[str, tuple[Point, Point]] = {
        "F1": ((86.36, 63.5), (86.36, 73.66)),
        "C5": ((93.98, 74.93), (93.98, 77.47)),
        "U5": ((114.3, 61.6), (114.3, 82.55)),
        "C6": ((125.73, 63.5), (125.73, 66.04)),
        "R17": ((141.61, 63.5), (141.61, 66.04)),
        "D17": ((141.61, 76.2), (141.61, 78.74)),
        "RCC1": ((59.06, 93.98), (59.06, 96.52)),
        "RCC2": ((76.83, 93.98), (76.83, 96.52)),
        "REN1": ((166.37, 57.15), (166.37, 59.69)),
        "RS2": ((152.4, 57.15), (152.4, 59.69)),
        "RS1": ((166.37, 67.31), (166.37, 69.85)),
        "CEN1": ((150.5, 69.85), (150.5, 72.39)),
        "U4": ((247.65, 71.12), (247.65, 96.52)),
        "J2": ((336.55, 93.98), (341.63, 96.52)),
        "J3": ((336.55, 118.11), (341.63, 120.65)),
        "U2": ((161.29, 179.07), (170.18, 220.98)),
        "U3": ((161.29, 245.11), (170.18, 284.48)),
        "ROE1": ((134.62, 227.33), (134.62, 234.95)),
    }
    instances = tuple(
        ReaderInstance(
            reference=reference,
            lib_id=libs[reference],
            at=at[reference],
            rotation=rot.get(reference, 0),
            in_bom=not reference.startswith("TP"),
            reference_at=text_at.get(reference, (None, None))[0],
            value_at=text_at.get(reference, (None, None))[1],
        )
        for reference, _lib, _x, _y, _p in INSTANCES
    )
    return ReaderSpec(
        instances=instances,
        wires=tuple(wires),
        labels=tuple(labels),
        flags=(
            ReaderFlag("#FLG01", (35.56, GND_RAIL_Y), "GND"),
            ReaderFlag("#FLG02", (c5_top[0], u5_in[1]), "VBUSF"),
        ),
        # Pins the design intentionally leaves open (mirrors the
        # machine schematic's no-connect list).
        no_connects=(
            ("J1", "A8"), ("J1", "B8"),
            ("U1", "8"), ("U1", "11"), ("U1", "12"),
            ("U3", "9"),
            ("U4", "3"), ("U4", "6"),
        ),
        paper="A2",
    )


THERMOMETER_READER_SPEC = _build_spec()


def export_thermometer_reader_schematic(
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
            THERMOMETER_READER_SPEC,
            project_name=project_name,
            pin_nets=PIN_NETS,
        ),
        encoding="utf-8",
    )
    return {
        "project_file": str(project_file),
        "schematic_file": str(schematic_file),
    }


# Referenced by the reader export above; imported for reuse in checks.
__all__ = [
    "PIN_NETS",
    "THERMOMETER_READER_SPEC",
    "export_thermometer_reader_schematic",
]
