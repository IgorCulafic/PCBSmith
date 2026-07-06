"""Offline flyback board: mains primary, isolated 3.3 V secondary.

Two-layer, 92 x 50 mm. The PRIMARY half (x < 54.8) carries the mains
input, bridge, bulk, switcher, and clamp - through-hole where the
voltages are highest. The SECONDARY half (x > 61.2) carries the SMD
low-voltage output and feedback. Between them runs a machine-checked
ISOLATION BARRIER at x = 58 with >= 6.4 mm creepage (rule 10.1), crossed
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

BOARD_W = 92.0
BOARD_H = 50.0
BARRIER_X = 58.0
ISOLATION_GAP_MM = 6.4
PRIMARY_MAX_X = BARRIER_X - ISOLATION_GAP_MM / 2  # 54.8
SECONDARY_MIN_X = BARRIER_X + ISOLATION_GAP_MM / 2  # 61.2

PRIMARY_NETS = ("/L", "/N", "/ACL", "/HVP", "/HVM", "/SW", "/CLAMP", "/VDD", "/FB")
SECONDARY_NETS = ("/SEC", "/3V3", "/GNDS", "/FBS", "/OPK", "/LEDA")
STRADDLE_REFS = ("T1", "U2", "CY1")

HV_W = 0.8   # mains/bus traces
SIG_W = 0.4

# (x, y, rotation)
PLACEMENTS: dict[str, tuple[float, float, float]] = {
    "J1": (6.0, 8.0, 0.0),
    "RF1": (18.0, 4.0, 0.0),
    "RV1": (47.0, 8.0, 180.0),
    "D1": (16.0, 12.0, 0.0),
    "D2": (16.0, 18.0, 0.0),
    "D3": (16.0, 24.0, 0.0),
    "D4": (16.0, 30.0, 0.0),
    "CB1": (33.5, 11.0, 270.0),
    "CB2": (33.5, 27.0, 90.0),
    "D5": (37.0, 32.5, 0.0),
    "U1": (28.0, 38.0, 0.0),
    "CV1": (21.0, 40.0, 180.0),
    "RC1": (8.0, 44.0, 0.0),
    "CC1": (31.0, 44.5, 0.0),
    "D6": (48.0, 39.7, 90.0),
    "T1": (45.0, 16.0, 270.0),
    "U2": (63.0, 8.0, 180.0),
    "CY1": (54.5, 45.0, 0.0),
    "D7": (68.0, 31.0, 180.0),
    "CO1": (71.5, 22.0, 90.0),
    "CO2": (72.5, 34.5, 270.0),
    "U3": (78.0, 19.0, 0.0),
    "RFB1": (82.0, 34.0, 270.0),
    "RFB2": (85.0, 34.0, 90.0),
    "RO1": (65.3, 21.0, 90.0),
    "RO2": (66.5, 6.5, 0.0),
    "RP1": (21.0, 34.0, 0.0),
    "J2": (80.0, 42.0, 0.0),
}

# Footprint-local (x, y, total angle) for reference labels whose default
# spot lands on a neighbour's silk or pads in this dense layout.
REFERENCE_AT: dict[str, tuple[float, float, float]] = {
    "RO1": (3.5, 0.0, 0.0),     # placed (65.3, 17.5), off the T1 body edge
    "CO1": (7.0, 0.0, 0.0),     # placed (71.5, 15.0), off RO1's pads
    "CB2": (-4.3, -1.5, 0.0),   # placed (32.0, 31.3), off D3's pad
    "CV1": (0.0, 1.8, 0.0),     # placed (21.0, 38.2), off RC1's body
    "RFB1": (-5.4, 0.0, 0.0),   # placed (82.0, 28.6), off RFB2/J2 labels
    "RFB2": (3.6, 0.0, 0.0),    # placed (85.0, 30.4), a row below RFB1's
    "J2": (-7.0, -2.0, 0.0),    # placed (73.0, 40.0), off RFB1's pads
}



def flyback_silk_graphics(origin: float) -> tuple[str, ...]:
    graphics: list[str] = []
    # Dashed isolation boundary, drawn only where the straddle parts
    # (U2, T1, CY1) and the ISOLATION label leave silkscreen room.
    for y1, y2 in ((2.0, 3.5), (9.9, 11.0), (36.2, 38.1), (40.9, 41.9)):
        graphics.append(
            silk_line((BARRIER_X, y1), (BARRIER_X, y2), origin, width=0.4)
        )
    graphics.append(silk_text("HV", (10.0, 25.0), origin, size=1.6))
    graphics.append(silk_text("ISOLATION", (63.0, 39.5), origin, size=1.0))
    graphics.append(silk_text("3V3", (89.0, 20.0), origin, size=1.6))
    graphics.append(silk_text("DANGER", (7.5, 18.0), origin, size=1.4))
    graphics.append(silk_text("120 VAC", (7.5, 21.0), origin, size=1.4))
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
    d1_k, d1_a = pad("D1", "1"), pad("D1", "2")
    d2_k, d2_a = pad("D2", "1"), pad("D2", "2")
    d3_k, d3_a = pad("D3", "1"), pad("D3", "2")
    d4_k, d4_a = pad("D4", "1"), pad("D4", "2")

    # ACL: post-fuse live to the MOV, D1 anode, D3 cathode.
    router.path(
        "/ACL",
        (rf1_acl, (42.0, 4.5), (45.5, 6.0), rv1_acl),
        layer="F.Cu", width=HV_W,
    )
    router.path("/ACL", (rf1_acl, (29.0, 8.0), d1_a), layer="F.Cu", width=HV_W)
    router.path(
        "/ACL",
        (d1_a, (28.0, 14.0), (28.0, 21.0), (d3_k[0], 21.0), d3_k),
        layer="B.Cu", width=HV_W,
    )

    # N: neutral to the MOV, D2 anode, D4 cathode.
    router.path(
        "/N",
        (j1_n, (j1_n[0], 11.0), (13.5, 13.5), (13.5, 28.0), d4_k),
        layer="F.Cu", width=HV_W,
    )
    router.path("/N", (rv1_n, (20.0, 6.0), j1_n), layer="B.Cu", width=HV_W)
    router.path(
        "/N",
        (d2_a, (24.0, 16.0), (24.0, 11.0), (13.0, 8.5), j1_n),
        layer="B.Cu", width=HV_W,
    )

    # HVP: bridge cathodes -> bulk + (outer pads) -> transformer -> HVIN;
    # the clamp leg runs down the free west lane on the back.
    cb1_p = pad_for("CB1", "/HVP")
    cb1_m = pad_for("CB1", "/HVM")
    cb2_p = pad_for("CB2", "/HVP")
    cb2_m = pad_for("CB2", "/HVM")
    d5_k = pad_for("D5", "/HVP")
    d5_a = pad_for("D5", "/HVM")
    t1_hvp = pad("T1", "1")
    nets.expect("T1", "1", "/HVP")
    u1_hvin = pad("U1", "5")
    u1_drain = pad("U1", "8")
    rc1_hvp = pad_for("RC1", "/HVP")
    router.path("/HVP", (d1_k, d2_k), layer="F.Cu", width=HV_W)
    router.path(
        "/HVP",
        (d1_k, (21.0, 14.5), (27.0, 14.5), cb1_p),
        layer="F.Cu", width=HV_W,
    )
    router.path("/HVP", (cb1_p, (38.0, 13.0), t1_hvp), layer="F.Cu", width=HV_W)
    router.path(
        "/HVP",
        (t1_hvp, (40.0, 19.5), (35.0, 24.0), cb2_p),
        layer="F.Cu", width=HV_W,
    )
    router.path("/HVP", (cb2_p, (33.0, 30.0), d5_k), layer="F.Cu", width=HV_W)
    router.via("/HVP", 48.5, 23.0)
    router.path("/HVP", (t1_hvp, (48.5, 23.0)), layer="F.Cu", width=HV_W)
    router.via("/HVP", 33.0, 40.6)
    router.path(
        "/HVP",
        ((48.5, 23.0), (48.5, 35.0), (35.0, 40.6), (33.0, 40.6)),
        layer="B.Cu", width=HV_W,
    )
    router.path(
        "/HVP", ((33.0, 40.6), (u1_hvin[0] + 1.5, u1_hvin[1]), u1_hvin),
        layer="F.Cu", width=HV_W,
    )
    router.path(
        "/HVP",
        (d2_k, (9.0, 24.0), (9.0, 41.0), rc1_hvp),
        layer="B.Cu", width=HV_W,
    )

    # HVM: bridge anodes, bulk inner pads, TVS anode, controller ground,
    # Y-capacitor.
    u1_gnd1, u1_gnd2 = pad("U1", "1"), pad("U1", "2")
    cy1_hvm = pad_for("CY1", "/HVM")
    router.path("/HVM", (d3_a, d4_a), layer="F.Cu", width=HV_W)
    router.path("/HVM", (cb1_m, cb2_m), layer="B.Cu", width=HV_W)
    router.path("/HVM", (d3_a, (28.0, 23.5), cb2_m), layer="F.Cu", width=HV_W)
    router.path(
        "/HVM",
        (d5_a, (38.0, 34.3), (27.0, 34.3), (26.16, 34.0)),
        layer="F.Cu", width=SIG_W,
    )
    router.path("/HVM", (d4_a, (26.16, 34.0), (24.9, 35.3), u1_gnd1),
                layer="F.Cu", width=SIG_W)
    router.path("/HVM", (u1_gnd1, u1_gnd2), layer="F.Cu", width=SIG_W)
    # Stitch the controller-ground island to the CV1/Y-cap return, which
    # otherwise only meet through the back-layer run.
    router.via("/HVM", 25.5, 32.5)
    router.path("/HVM", ((25.5, 32.5), (26.16, 34.0)), layer="F.Cu", width=SIG_W)
    router.path("/HVM", ((25.5, 32.5), (18.6, 41.2)), layer="B.Cu", width=SIG_W)

    # Clamp: HVP -> RC1 || CC1 -> CLAMP -> D6 -> SW.
    rc1_cl = pad_for("RC1", "/CLAMP")
    cc1_hvp = pad_for("CC1", "/HVP")
    cc1_cl = pad_for("CC1", "/CLAMP")
    d6_cl = pad_for("D6", "/CLAMP")
    d6_sw = pad_for("D6", "/SW")
    router.path(
        "/HVP",
        (rc1_hvp, (rc1_hvp[0], 47.7), (cc1_hvp[0], 47.7), cc1_hvp),
        layer="F.Cu", width=HV_W,
    )
    router.path(
        "/CLAMP",
        (rc1_cl, (25.0, 42.0), (38.0, 42.0), (41.0, 42.5), cc1_cl),
        layer="F.Cu", width=SIG_W,
    )
    router.path("/CLAMP", ((41.0, 42.5), (45.0, 42.3), d6_cl),
                layer="F.Cu", width=SIG_W)

    # SW: transformer primary return, drain, clamp diode. The drain leg
    # hugs the pin-8 row height so the TVS return lane stays clear.
    t1_sw = pad("T1", "4")
    router.path(
        "/SW",
        (t1_sw, (42.0, 34.5), (40.5, 36.1), (u1_drain[0] + 2.0, u1_drain[1]),
         u1_drain),
        layer="F.Cu", width=HV_W,
    )
    router.path("/SW", (t1_sw, (46.0, 33.5), d6_sw), layer="F.Cu", width=SIG_W)

    # VDD and FB: controller housekeeping to the optocoupler (U2 sits
    # high so these arrivals stay >6.4mm from the secondary stubs).
    u1_vdd = pad("U1", "4")
    u1_fb = pad("U1", "3")
    cv1_vdd = pad_for("CV1", "/VDD")
    cv1_hvm = pad_for("CV1", "/HVM")
    u2_vdd = pad("U2", "4")
    u2_fb = pad("U2", "3")
    rp1_fb = pad_for("RP1", "/FB")
    rp1_hvm = pad_for("RP1", "/HVM")
    router.path("/VDD", (u1_vdd, (23.0, 40.0), cv1_vdd), layer="F.Cu", width=SIG_W)
    router.via("/VDD", 20.2, 42.5)
    router.path("/VDD", (cv1_vdd, (20.2, 42.5)), layer="F.Cu", width=SIG_W)
    router.path(
        "/VDD",
        ((20.2, 42.5), (35.0, 30.5), (38.5, 28.5), (42.0, 21.0), (42.0, 13.0),
         (48.0, 10.0), (52.0, 9.5), u2_vdd),
        layer="B.Cu", width=SIG_W,
    )
    router.via("/HVM", 18.6, 41.2)
    router.path("/HVM", (cv1_hvm, (18.6, 41.2)), layer="F.Cu", width=SIG_W)
    router.path(
        "/HVM",
        ((18.6, 41.2), (18.6, 47.3), (44.0, 47.0), (50.0, 47.0), cy1_hvm),
        layer="B.Cu", width=SIG_W,
    )
    router.path("/HVM", (rp1_hvm, (26.16, 34.0)), layer="F.Cu", width=SIG_W)
    router.path(
        "/FB",
        (rp1_fb, (20.21, 37.5), (23.5, u1_fb[1]), u1_fb),
        layer="F.Cu", width=SIG_W,
    )
    router.via("/FB", 24.0, 28.5)
    router.path("/FB", (rp1_fb, (24.0, 28.5)), layer="F.Cu", width=SIG_W)
    router.path(
        "/FB",
        ((24.0, 28.5), (28.5, 25.0), (31.0, 15.0), (36.5, 13.0), (43.0, 8.5),
         (47.0, 5.5), (50.0, 5.0), u2_fb),
        layer="B.Cu", width=SIG_W,
    )

    # ---- Secondary side ----
    t1_sec = pad("T1", "5")
    t1_gnds = pad("T1", "8")
    d7_sec = pad_for("D7", "/SEC")
    d7_3v3 = pad_for("D7", "/3V3")
    router.path("/SEC", (t1_sec, d7_sec), layer="F.Cu", width=HV_W)

    # 3V3 bus along y=31, GNDS bus along y=16.
    router.path("/3V3", (d7_3v3, (82.0, 31.0)), layer="F.Cu", width=HV_W)
    router.path("/GNDS", (t1_gnds, (86.5, 16.0)), layer="F.Cu", width=HV_W)

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
        (rfb1_fbs, (82.0, 36.0), (85.0, 36.0), rfb2_fbs),
        layer="F.Cu", width=SIG_W,
    )
    router.path("/GNDS", (rfb2_gnds, (86.5, 33.0)), layer="F.Cu", width=SIG_W)

    u3_k = pad("U3", "1")
    u3_ref = pad("U3", "2")
    u3_a = pad("U3", "3")
    router.via("/FBS", 80.2, 21.5)
    router.path("/FBS", (u3_ref, (80.2, 21.5)), layer="F.Cu", width=SIG_W)
    router.via("/FBS", 81.3, 37.3)
    router.path("/FBS", ((80.2, 21.5), (81.3, 37.3)), layer="B.Cu", width=SIG_W)
    router.path("/FBS", ((81.3, 37.3), (82.0, 36.0)), layer="F.Cu", width=SIG_W)
    router.path("/GNDS", (u3_a, (79.5, 17.0), (79.5, 16.0)),
                layer="F.Cu", width=SIG_W)
    u2_opk = pad("U2", "2")
    u2_leda = pad("U2", "1")
    router.via("/OPK", 73.3, 17.4)
    router.path("/OPK", (u3_k, (73.3, 17.4)), layer="F.Cu", width=SIG_W)
    router.path("/OPK", ((73.3, 17.4), u2_opk), layer="B.Cu", width=SIG_W)

    # Opto drive: RO1 series resistor, RO2 across the LED.
    ro1_3v3 = pad_for("RO1", "/3V3")
    ro1_leda = pad_for("RO1", "/LEDA")
    ro2_leda = pad_for("RO2", "/LEDA")
    ro2_opk = pad_for("RO2", "/OPK")
    router.path(
        "/3V3", (ro1_3v3, (65.3, 26.0), (67.5, 29.0), (71.0, 31.0)),
        layer="F.Cu", width=SIG_W,
    )
    router.via("/LEDA", 65.9, 19.0)
    router.path("/LEDA", (ro1_leda, (65.9, 19.0)), layer="F.Cu", width=SIG_W)
    router.path("/LEDA", ((65.9, 19.0), u2_leda), layer="B.Cu", width=SIG_W)
    router.path("/LEDA", (ro2_leda, (64.0, 7.5), u2_leda),
                layer="F.Cu", width=SIG_W)
    router.path("/OPK", (ro2_opk, (67.5, 5.0), (64.0, 4.8), u2_opk),
                layer="F.Cu", width=SIG_W)

    # Y-capacitor secondary leg and the output terminal.
    cy1_gnds = pad_for("CY1", "/GNDS")
    j2_3v3 = pad_for("J2", "/3V3")
    j2_gnds = pad_for("J2", "/GNDS")
    router.path(
        "/GNDS",
        (cy1_gnds, (82.0, 45.0), j2_gnds),
        layer="F.Cu", width=SIG_W,
    )
    router.path("/3V3", (j2_3v3, (j2_3v3[0], 31.0)), layer="F.Cu", width=HV_W)
    router.path("/GNDS", (j2_gnds, (86.5, 40.0), (86.5, 16.0)),
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
