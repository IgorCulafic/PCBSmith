"""Offline flyback board: mains primary, isolated 3.3 V secondary.

Two-layer, 88 x 50 mm (r002, reference-driven: integrated bridge and a
single 450 V bulk can shrink the primary). The PRIMARY half carries the
mains input with its EMI/safety front end (X2 cap, line Y-caps, earth
pad), bridge, bulk, switcher, and clamp - through-hole where the
voltages are highest. The SECONDARY half carries the SMD low-voltage
output and feedback. Between them runs a machine-checked ISOLATION
BARRIER at x = 56 with >= 6.4 mm creepage (rule 10.1), crossed
only by the three parts built to cross it: the transformer (15 mm row
spacing), the optocoupler, and the Y-capacitor (10 mm pitch disc).

No copper pours anywhere: every net is an explicit trace so the creepage
analysis stays exact. The barrier is drawn on the silkscreen with a
warning, per the reference article's practice.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from pcbsmith.kicad.board import (
    BOARD_SHEET_ORIGIN_MM,
    BoardComponent,
    BoardGenerationError,
    BoardLayout,
    BoardNetlist,
    export_kicad_netlist_xml,
    parse_board_netlist,
    render_board_from_layout,
)
from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult, find_kicad_cli
from pcbsmith.kicad.shaped_board import (
    NetLookup,
    Router,
    placed_pad,
    silk_line,
    silk_text,
)

BOARD_W = 88.0
BOARD_H = 50.0
BARRIER_X = 56.0
ISOLATION_GAP_MM = 6.4
PRIMARY_MAX_X = BARRIER_X - ISOLATION_GAP_MM / 2  # 52.8
SECONDARY_MIN_X = BARRIER_X + ISOLATION_GAP_MM / 2  # 59.2

PRIMARY_NETS = ("/L", "/N", "/ACL", "/HVP", "/HVM", "/SW", "/CLAMP", "/VDD", "/FB")
EARTH_NETS = ("/EARTH",)
SECONDARY_NETS = ("/SEC", "/3V3", "/GNDS", "/FBS", "/OPK", "/LEDA")
STRADDLE_REFS = ("T1", "U2", "CY1")

HV_W = 0.8   # mains/bus traces
SIG_W = 0.4

# (x, y, rotation)
PLACEMENTS: dict[str, tuple[float, float, float]] = {
    "J1": (6.0, 8.0, 0.0),
    "E1": (3.5, 17.0, 0.0),
    "CY2": (15.0, 24.0, 180.0),
    "CY3": (15.0, 31.0, 180.0),
    "RF1": (18.0, 4.0, 0.0),
    "CX1": (32.5, 13.0, 180.0),
    "RV1": (41.5, 7.5, 180.0),
    "BR1": (26.5, 24.0, 180.0),
    "CB1": (31.0, 32.0, 180.0),
    "D5": (37.0, 25.0, 90.0),
    "TP1": (36.2, 15.0, 0.0),
    "U1": (18.0, 37.8, 0.0),
    "CV1": (11.0, 40.0, 180.0),
    "RP1": (11.0, 35.5, 0.0),
    "RC1": (28.0, 46.5, 0.0),
    "CC1": (41.0, 41.0, 180.0),
    "D6": (44.5, 39.7, 90.0),
    "T1": (43.0, 16.0, 270.0),
    "U2": (61.0, 8.0, 180.0),
    "CY1": (52.5, 45.0, 0.0),
    "D7": (66.0, 31.0, 180.0),
    "CO1": (69.5, 22.0, 90.0),
    "CO2": (70.5, 34.5, 270.0),
    "U3": (76.0, 19.0, 0.0),
    "RFB1": (80.0, 34.0, 270.0),
    "RFB2": (83.0, 34.0, 90.0),
    "RO1": (63.3, 21.0, 90.0),
    "RO2": (64.5, 6.5, 0.0),
    "TP2": (65.0, 14.0, 0.0),
    "CF1": (81.5, 28.0, 90.0),
    "J2": (78.0, 42.0, 0.0),
}


# Footprint-local (x, y, total angle) for reference labels whose default
# spot lands on a neighbour's silk or pads in this dense layout.
REFERENCE_AT: dict[str, tuple[float, float, float]] = {
    "E1": (0.0, 3.3, 0.0),      # placed (3.5, 20.3), below the pad
    "CY3": (-3.5, 0.0, 0.0),    # placed (18.5, 31.0), east of the disc
    "CX1": (7.5, 2.5, 0.0),     # placed (25.0, 10.5), over its own body
    "RP1": (-3.5, 0.0, 0.0),    # placed (7.5, 35.5), west of the resistor
    "RC1": (-4.0, -1.6, 0.0),  # placed (24.0, 44.9), west of the body
    "D6": (0.0, 2.8, 0.0),      # placed (47.3, 39.7), east of the diode
    "CC1": (0.0, 3.6, 0.0),     # placed (41.0, 37.4), above its own silk
    "RO1": (3.5, 0.0, 0.0),     # placed (63.3, 17.5), off the T1 body edge
    "CO1": (7.0, 0.0, 0.0),     # placed (69.5, 15.0), off RO1's pads
    "CV1": (0.0, 1.8, 0.0),     # placed (11.0, 38.2), off RC1's body
    "RFB1": (-5.4, 2.5, 0.0),   # placed (77.5, 28.6), west of CF1
    "RFB2": (3.6, 0.0, 0.0),    # placed (83.0, 30.4), a row below RFB1's
    "CF1": (4.3, 0.0, 0.0),     # placed (81.5, 23.7), clear of the 3V3 bus
    "J2": (-7.0, -2.0, 0.0),    # placed (71.0, 40.0), off RFB1's pads
}


def flyback_silk_graphics(origin: float) -> tuple[str, ...]:
    graphics: list[str] = []
    # Dashed isolation boundary, drawn only where the straddle parts
    # (U2, T1, CY1) and the ISOLATION label leave silkscreen room.
    for y1, y2 in ((2.0, 3.5), (9.9, 11.0), (36.2, 38.1), (40.9, 41.9)):
        graphics.append(
            silk_line((BARRIER_X, y1), (BARRIER_X, y2), origin, width=0.4)
        )
    graphics.append(silk_text("HV", (33.0, 8.0), origin, size=1.6))
    graphics.append(silk_text("ISOLATION", (61.0, 39.5), origin, size=1.0))
    graphics.append(silk_text("3V3", (85.0, 20.0), origin, size=1.6))
    graphics.append(silk_text("DANGER", (11.0, 15.2), origin, size=1.2))
    graphics.append(silk_text("120 VAC", (10.5, 19.0), origin, size=1.2))
    graphics.append(silk_text("EARTH", (8.2, 17.0), origin, size=0.8))
    return tuple(graphics)


def compute_flyback_board_layout(netlist: BoardNetlist) -> BoardLayout:
    by_ref = {component.reference: component for component in netlist.components}
    nets = NetLookup(netlist)

    placements: list[tuple[BoardComponent, float]] = []
    part_y: list[tuple[str, float]] = []
    part_rotation: list[tuple[str, float]] = []
    for reference, (x, y, rotation) in PLACEMENTS.items():
        if reference not in by_ref:
            raise BoardGenerationError(f"Netlist is missing {reference}.")
        placements.append((by_ref[reference], x))
        part_y.append((reference, y))
        if rotation:
            part_rotation.append((reference, rotation))

    def pad(reference: str, pin: str) -> tuple[float, float]:
        x, y, rotation = PLACEMENTS[reference]
        return placed_pad(
            by_ref[reference].footprint, pin, anchor=(x, y), rotation=rotation
        )

    def pad_for(reference: str, net_name: str) -> tuple[float, float]:
        return pad(reference, nets.pin_on(reference, net_name))

    router = Router()

    # ---- Primary side ----
    j1_l, j1_n = pad("J1", "1"), pad("J1", "2")
    nets.expect("J1", "1", "/L")
    rf1_l = pad_for("RF1", "/L")
    rf1_acl = pad_for("RF1", "/ACL")
    router.path("/L", (j1_l, (j1_l[0], 4.0), rf1_l), layer="F.Cu", width=HV_W)

    rv1_acl = pad_for("RV1", "/ACL")
    rv1_n = pad_for("RV1", "/N")
    cx1_acl = pad_for("CX1", "/ACL")
    cx1_n = pad_for("CX1", "/N")
    br1_hvp = pad("BR1", "1")
    br1_hvm = pad("BR1", "2")
    br1_acl = pad("BR1", "3")
    br1_n = pad("BR1", "4")
    nets.expect("BR1", "1", "/HVP")

    # N: terminal -> X2 cap -> (back) MOV and bridge and N-side Y cap.
    router.path("/N", (j1_n, (13.0, 11.0), cx1_n), layer="F.Cu", width=HV_W)
    router.path("/N", (rv1_n, (20.0, 6.0), j1_n), layer="B.Cu", width=HV_W)
    router.path(
        "/N", (cx1_n, (16.8, 17.0), (17.0, 21.0), br1_n),
        layer="B.Cu", width=HV_W,
    )
    cy3_n = pad_for("CY3", "/N")
    router.path("/N", (br1_n, (16.5, 28.5), cy3_n), layer="B.Cu", width=HV_W)

    # ACL: post-fuse live to the MOV, X2, bridge, and L-side Y cap.
    router.path("/ACL", (rf1_acl, (38.5, 5.0), rv1_acl), layer="F.Cu", width=HV_W)
    router.path("/ACL", (rf1_acl, (31.0, 8.0), cx1_acl), layer="F.Cu", width=HV_W)
    router.path(
        "/ACL", (cx1_acl, (21.0, 17.5), br1_acl), layer="F.Cu", width=HV_W
    )
    cy2_acl = pad_for("CY2", "/ACL")
    router.path("/ACL", (br1_acl, (16.5, 21.5), cy2_acl), layer="F.Cu", width=HV_W)

    # EARTH: wire pad up the west edge to both line Y caps.
    e1_earth = pad_for("E1", "/EARTH")
    cy2_earth = pad_for("CY2", "/EARTH")
    cy3_earth = pad_for("CY3", "/EARTH")
    router.path(
        "/EARTH", (e1_earth, (3.5, 24.0), cy2_earth), layer="F.Cu", width=HV_W
    )
    router.path(
        "/EARTH", ((3.5, 24.0), (3.5, 31.0), cy3_earth),
        layer="F.Cu", width=HV_W,
    )

    # HVP: bridge + -> bulk +, TVS, test point, transformer, HVIN, clamp.
    cb1_p = pad_for("CB1", "/HVP")
    cb1_m = pad_for("CB1", "/HVM")
    d5_k = pad_for("D5", "/HVP")
    d5_a = pad_for("D5", "/HVM")
    t1_hvp = pad("T1", "1")
    nets.expect("T1", "1", "/HVP")
    u1_hvin = pad("U1", "5")
    u1_drain = pad("U1", "8")
    rc1_hvp = pad_for("RC1", "/HVP")
    tp1 = pad("TP1", "1")
    router.path(
        "/HVP", (br1_hvp, (28.5, 27.5), cb1_p), layer="F.Cu", width=HV_W
    )
    router.path(
        "/HVP",
        (d5_k, (38.9, 25.0), (38.9, 18.5), t1_hvp),
        layer="F.Cu", width=HV_W,
    )
    router.path(
        "/HVP", ((38.9, 18.5), tp1), layer="F.Cu", width=HV_W
    )
    router.path(
        "/HVP", (cb1_p, (35.0, 29.5), d5_k), layer="F.Cu", width=HV_W
    )

    # HVIN and the clamp source dive to the back at the test point's
    # through-hole and resurface next to the switcher.
    router.path(
        "/HVP",
        (tp1, (30.0, 34.0), (24.5, 37.5), (23.6, 38.9)),
        layer="B.Cu", width=HV_W,
    )
    router.via("/HVP", 23.6, 38.9)
    router.path(
        "/HVP", ((23.6, 38.9), (u1_hvin[0] + 2.1, u1_hvin[1]), u1_hvin),
        layer="F.Cu", width=HV_W,
    )
    router.path(
        "/HVP", ((23.6, 38.9), (24.0, 40.5), (25.5, 44.0), rc1_hvp),
        layer="F.Cu", width=HV_W,
    )
    router.via("/HVP", 39.5, 41.5)
    router.path(
        "/HVP", ((30.0, 34.0), (38.0, 40.5), (39.5, 41.5)),
        layer="B.Cu", width=HV_W,
    )


    # HVM: bridge - -> bulk -, TVS return, controller ground, CV1, Y-cap.
    u1_gnd1, u1_gnd2 = pad("U1", "1"), pad("U1", "2")
    cy1_hvm = pad_for("CY1", "/HVM")
    router.path(
        "/HVM", (br1_hvm, (24.0, 20.5), (24.0, 29.0), cb1_m),
        layer="F.Cu", width=HV_W,
    )
    router.path(
        "/HVM", (br1_hvm, (31.0, 18.2), (35.5, 20.5), d5_a),
        layer="F.Cu", width=SIG_W,
    )
    router.path(
        "/HVM", (cb1_m, (20.0, 33.5), (16.4, 34.8), u1_gnd1),
        layer="F.Cu", width=SIG_W,
    )
    router.path("/HVM", (u1_gnd1, u1_gnd2), layer="F.Cu", width=SIG_W)
    rp1_hvm = pad_for("RP1", "/HVM")
    router.path("/HVM", (rp1_hvm, (13.5, 35.7), u1_gnd1),
                layer="F.Cu", width=SIG_W)
    cv1_hvm = pad_for("CV1", "/HVM")
    router.via("/HVM", 12.0, 33.5)
    router.path(
        "/HVM", ((12.0, 33.5), (14.0, 34.5), (16.4, 34.8)),
        layer="F.Cu", width=SIG_W,
    )
    router.path(
        "/HVM", ((12.0, 33.5), (12.0, 43.5), (14.0, 45.0)),
        layer="B.Cu", width=SIG_W,
    )
    router.via("/HVM", 14.0, 45.0)
    router.path(
        "/HVM", (cv1_hvm, (12.0, 42.8), (14.0, 45.0)),
        layer="F.Cu", width=SIG_W,
    )
    router.path(
        "/HVM",
        ((14.0, 45.0), (15.0, 48.3), (44.0, 48.3), (50.0, 47.0), cy1_hvm),
        layer="B.Cu", width=SIG_W,
    )

    # Clamp: HVP -> RC1 || CC1 -> CLAMP -> D6 -> SW.
    rc1_cl = pad_for("RC1", "/CLAMP")
    cc1_hvp = pad_for("CC1", "/HVP")
    cc1_cl = pad_for("CC1", "/CLAMP")
    d6_cl = pad_for("D6", "/CLAMP")
    d6_sw = pad_for("D6", "/SW")
    router.path("/HVP", ((39.5, 41.5), cc1_hvp), layer="F.Cu", width=HV_W)
    router.path(
        "/CLAMP",
        (rc1_cl, (43.5, 44.0), (36.0, 44.3), (32.0, 42.5), cc1_cl),
        layer="F.Cu", width=SIG_W,
    )
    router.path("/CLAMP", ((43.5, 44.0), d6_cl), layer="F.Cu", width=SIG_W)

    # SW: transformer primary return, clamp diode, drain (the drain lane
    # threads between the bulk can's pads).
    t1_sw = pad("T1", "4")
    router.path("/SW", (t1_sw, (43.8, 34.0), d6_sw), layer="F.Cu", width=SIG_W)
    router.path(
        "/SW",
        (t1_sw, (39.5, 33.8), (35.0, 34.6), (25.0, 35.3),
         (u1_drain[0] + 1.2, u1_drain[1]), u1_drain),
        layer="F.Cu", width=HV_W,
    )

    # VDD and FB housekeeping to the optocoupler.
    u1_vdd = pad("U1", "4")
    u1_fb = pad("U1", "3")
    cv1_vdd = pad_for("CV1", "/VDD")
    u2_vdd = pad("U2", "4")
    u2_fb = pad("U2", "3")
    rp1_fb = pad_for("RP1", "/FB")
    router.path(
        "/VDD", (u1_vdd, (13.5, u1_vdd[1]), cv1_vdd),
        layer="F.Cu", width=SIG_W,
    )
    router.via("/VDD", 13.8, 41.3)
    router.path("/VDD", (cv1_vdd, (13.8, 41.3)), layer="F.Cu", width=SIG_W)
    router.path(
        "/VDD",
        ((13.8, 41.3), (24.0, 43.0), (33.0, 44.6), (38.0, 45.0),
         (43.0, 44.8), (46.5, 43.0), (47.5, 37.0), (47.5, 20.0),
         (46.0, 9.7), (52.0, 9.0), u2_vdd),
        layer="B.Cu", width=SIG_W,
    )
    router.path(
        "/FB",
        (rp1_fb, (10.225, u1_fb[1]), u1_fb),
        layer="F.Cu", width=SIG_W,
    )
    router.via("/FB", 10.0, 18.5)
    router.path(
        "/FB", (rp1_fb, (10.0, 33.0), (10.0, 18.5)),
        layer="F.Cu", width=SIG_W,
    )
    router.path(
        "/FB",
        ((10.0, 18.5), (13.0, 12.0), (13.0, 9.0), (20.0, 7.5),
         (30.0, 7.0), (36.5, 8.0), (43.0, 10.0), (48.0, 7.0), u2_fb),
        layer="B.Cu", width=SIG_W,
    )

    # ---- Secondary side ----
    t1_sec = pad("T1", "5")
    t1_gnds = pad("T1", "8")
    d7_sec = pad_for("D7", "/SEC")
    d7_3v3 = pad_for("D7", "/3V3")
    router.path("/SEC", (t1_sec, d7_sec), layer="F.Cu", width=HV_W)

    # 3V3 bus along y=31, GNDS bus along y=16.
    router.path("/3V3", (d7_3v3, (81.5, 31.0)), layer="F.Cu", width=HV_W)
    router.path("/GNDS", (t1_gnds, (84.5, 16.0)), layer="F.Cu", width=HV_W)
    tp2 = pad("TP2", "1")
    router.path("/GNDS", (tp2, (tp2[0], 16.0)), layer="F.Cu", width=SIG_W)

    # Output filter: CO1 between the buses, CO2 south of the 3V3 bus.
    co1_3v3 = pad_for("CO1", "/3V3")
    co1_gnds = pad_for("CO1", "/GNDS")
    router.path("/3V3", (co1_3v3, (co1_3v3[0], 31.0)), layer="F.Cu", width=SIG_W)
    router.path("/GNDS", (co1_gnds, (co1_gnds[0], 16.0)), layer="F.Cu", width=SIG_W)
    co2_3v3 = pad_for("CO2", "/3V3")
    co2_gnds = pad_for("CO2", "/GNDS")
    router.path("/3V3", (co2_3v3, (co2_3v3[0], 31.0)), layer="F.Cu", width=SIG_W)
    router.path("/GNDS", (co2_gnds, (co2_gnds[0], 45.0)), layer="F.Cu", width=SIG_W)

    # Feedback divider south-east; FBS reaches the LMV431 over the back.
    rfb1_3v3 = pad_for("RFB1", "/3V3")
    rfb1_fbs = pad_for("RFB1", "/FBS")
    rfb2_fbs = pad_for("RFB2", "/FBS")
    rfb2_gnds = pad_for("RFB2", "/GNDS")
    router.path("/3V3", (rfb1_3v3, (rfb1_3v3[0], 31.0)), layer="F.Cu", width=SIG_W)
    router.path(
        "/FBS",
        (rfb1_fbs, (80.0, 36.0), (83.0, 36.0), rfb2_fbs),
        layer="F.Cu", width=SIG_W,
    )
    router.path("/GNDS", (rfb2_gnds, (84.5, 33.0)), layer="F.Cu", width=SIG_W)

    u3_k = pad("U3", "1")
    u3_ref = pad("U3", "2")
    u3_a = pad("U3", "3")
    router.via("/FBS", 78.2, 21.5)
    router.path("/FBS", (u3_ref, (78.2, 21.5)), layer="F.Cu", width=SIG_W)
    router.via("/FBS", 79.3, 37.3)
    router.path("/FBS", ((78.2, 21.5), (79.3, 37.3)), layer="B.Cu", width=SIG_W)
    router.path("/FBS", ((79.3, 37.3), (80.0, 36.0)), layer="F.Cu", width=SIG_W)
    # The DNP compensation cap parks beside the divider: its 3V3 stub
    # tees the bus, its FBS stub joins the LMV431 REF via.
    cf1_3v3 = pad_for("CF1", "/3V3")
    cf1_fbs = pad_for("CF1", "/FBS")
    router.path("/3V3", (cf1_3v3, (cf1_3v3[0], 31.0)), layer="F.Cu", width=SIG_W)
    router.path(
        "/FBS", (cf1_fbs, (80.5, 24.0), (78.2, 21.5)),
        layer="F.Cu", width=SIG_W,
    )
    router.path("/GNDS", (u3_a, (77.5, 17.0), (77.5, 16.0)),
                layer="F.Cu", width=SIG_W)
    u2_opk = pad("U2", "2")
    u2_leda = pad("U2", "1")
    router.via("/OPK", 71.3, 17.4)
    router.path("/OPK", (u3_k, (71.3, 17.4)), layer="F.Cu", width=SIG_W)
    router.path("/OPK", ((71.3, 17.4), u2_opk), layer="B.Cu", width=SIG_W)

    # Opto drive: RO1 series resistor, RO2 across the LED.
    ro1_3v3 = pad_for("RO1", "/3V3")
    ro1_leda = pad_for("RO1", "/LEDA")
    ro2_leda = pad_for("RO2", "/LEDA")
    ro2_opk = pad_for("RO2", "/OPK")
    router.path(
        "/3V3", (ro1_3v3, (63.3, 26.0), (65.5, 29.0), (69.0, 31.0)),
        layer="F.Cu", width=SIG_W,
    )
    router.via("/LEDA", 63.9, 19.0)
    router.path("/LEDA", (ro1_leda, (63.9, 19.0)), layer="F.Cu", width=SIG_W)
    router.path("/LEDA", ((63.9, 19.0), u2_leda), layer="B.Cu", width=SIG_W)
    router.path("/LEDA", (ro2_leda, (62.0, 7.5), u2_leda),
                layer="F.Cu", width=SIG_W)
    router.path("/OPK", (ro2_opk, (65.5, 5.0), (62.0, 4.8), u2_opk),
                layer="F.Cu", width=SIG_W)

    # Y-capacitor secondary leg and the output terminal.
    cy1_gnds = pad_for("CY1", "/GNDS")
    j2_3v3 = pad_for("J2", "/3V3")
    j2_gnds = pad_for("J2", "/GNDS")
    router.path(
        "/GNDS",
        (cy1_gnds, (80.0, 45.0), j2_gnds),
        layer="F.Cu", width=SIG_W,
    )
    router.path("/3V3", (j2_3v3, (j2_3v3[0], 31.0)), layer="F.Cu", width=HV_W)
    router.path("/GNDS", (j2_gnds, (84.5, 40.0), (84.5, 16.0)),
                layer="F.Cu", width=HV_W)

    return BoardLayout(
        placements=tuple(placements),
        segments=tuple(router.segments),
        vias=tuple(router.vias),
        width_mm=BOARD_W,
        height_mm=BOARD_H,
        part_y_mm=tuple(part_y),
        part_rotation=tuple(part_rotation),
        zones=(),
        graphics=flyback_silk_graphics(BOARD_SHEET_ORIGIN_MM),
        part_reference_at=tuple(REFERENCE_AT.items()),
    )


def generate_flyback_board(
    *,
    schematic_file: Path,
    board_file: Path,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> tuple[BoardNetlist, BoardLayout]:
    netlist_file = export_kicad_netlist_xml(schematic_file, finder=finder, runner=runner)
    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    layout = compute_flyback_board_layout(netlist)
    board_file.write_text(render_board_from_layout(netlist, layout), encoding="utf-8")
    return netlist, layout
