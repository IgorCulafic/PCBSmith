"""Reusable authority fixture for a quantity-two narrow-stem corridor."""

from __future__ import annotations

from dataclasses import dataclass

from pcbsmith.kicad.board import BoardComponent, BoardLayout, BoardNet, BoardNetlist
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.library import FootprintSpec, PadSpec

FOOTPRINT = "Test:ReducedCapacityTwoStemTerminal"
SCHEMATIC_PROJECT_NAME = "reduced-capacity-two-stem"
SCHEMATIC_SYMBOL_ID = "Connector_Generic:Conn_01x01"
NET_NAMES = ("/STEM_A", "/STEM_B")
TRACK_WIDTH_MM = 0.6
CLEARANCE_MM = 0.2
CAPACITY_QUANTUM_MM = 0.1
COARSE_GRID_MM = 2.0
DETAILED_GRID_MM = 1.0
DEMAND_SPAN_UNITS = 8
PORTAL_SPAN_UNITS = 20
QUANTITY_CAPACITY = 2
PORTAL_RESIDUAL_UNITS = 4
NAMED_PORTAL_RESOURCE_ID = (
    "channel:73c6e6be545e48d788d41f98e34b61edbb4da2e99dae51df30fd44597f499357"
)

# Both chambers are 14 x 6 mm.  The 6 mm-wide stem leaves exactly one
# conservative 2 x 2 mm coarse cell after copper-to-edge inset is applied.
OUTLINE = (
    (0.0, 0.0),
    (14.0, 0.0),
    (14.0, 6.0),
    (10.0, 6.0),
    (10.0, 12.0),
    (14.0, 12.0),
    (14.0, 18.0),
    (0.0, 18.0),
    (0.0, 12.0),
    (4.0, 12.0),
    (4.0, 6.0),
    (0.0, 6.0),
)

TERMINAL_FOOTPRINT_SPEC = FootprintSpec(
    pads=(
        PadSpec(
            name="1",
            x_mm=0.0,
            y_mm=0.0,
            kind="smd",
            width_mm=0.8,
            height_mm=0.8,
            shape="circle",
            layers=("F.Cu", "F.Mask"),
        ),
    ),
    fab_rect=(-0.4, -0.4, 0.4, 0.4),
    silk_rect=None,
    x_min=-0.4,
    x_max=0.4,
    y_min=-0.4,
    y_max=0.4,
    attr="smd",
)


@dataclass(frozen=True)
class ReducedCapacityTwoStemBoard:
    """Exact fixture inputs plus the terminal anchors used by replay checks."""

    layout: BoardLayout
    netlist: BoardNetlist
    terminal_points: tuple[tuple[str, tuple[float, float], tuple[float, float]], ...]


def make_reduced_capacity_two_stem_board() -> ReducedCapacityTwoStemBoard:
    """Build the exact two-net board."""
    terminal_rows = [
        (NET_NAMES[0], "J1", "J2", (3.0, 3.0), (3.0, 15.0)),
        (NET_NAMES[1], "J3", "J4", (11.0, 3.0), (11.0, 15.0)),
    ]

    components: list[BoardComponent] = []
    placements: list[tuple[BoardComponent, float]] = []
    part_y_mm: list[tuple[str, float]] = []
    nets: list[BoardNet] = []
    terminal_points = []
    for net_name, lower_ref, upper_ref, lower, upper in terminal_rows:
        lower_component = BoardComponent(
            lower_ref,
            "TERMINAL",
            FOOTPRINT,
            stable_kicad_uuid(
                "schematic-symbol",
                SCHEMATIC_PROJECT_NAME,
                lower_ref,
                SCHEMATIC_SYMBOL_ID,
            ),
            fields=(
                ("Footprint", FOOTPRINT),
                ("Datasheet", ""),
                ("Description", ""),
            ),
        )
        upper_component = BoardComponent(
            upper_ref,
            "TERMINAL",
            FOOTPRINT,
            stable_kicad_uuid(
                "schematic-symbol",
                SCHEMATIC_PROJECT_NAME,
                upper_ref,
                SCHEMATIC_SYMBOL_ID,
            ),
            fields=(
                ("Footprint", FOOTPRINT),
                ("Datasheet", ""),
                ("Description", ""),
            ),
        )
        components.extend((lower_component, upper_component))
        placements.extend(((lower_component, lower[0]), (upper_component, upper[0])))
        part_y_mm.extend(((lower_ref, lower[1]), (upper_ref, upper[1])))
        nets.append(BoardNet(net_name, ((lower_ref, "1"), (upper_ref, "1"))))
        terminal_points.append((net_name, lower, upper))

    return ReducedCapacityTwoStemBoard(
        layout=BoardLayout(
            placements=tuple(placements),
            segments=(),
            vias=(),
            width_mm=14.0,
            height_mm=18.0,
            outline=OUTLINE,
            part_y_mm=tuple(part_y_mm),
        ),
        netlist=BoardNetlist(components=tuple(components), nets=tuple(nets)),
        terminal_points=tuple(terminal_points),
    )
