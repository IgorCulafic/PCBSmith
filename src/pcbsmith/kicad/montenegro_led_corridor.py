"""Local perimeter-routing repairs for the Montenegro LED chain."""

from __future__ import annotations

from shapely.geometry import LineString

from pcbsmith.kicad.board import BoardLayout, BoardNetlist, ViaSpec
from pcbsmith.kicad.montenegro_geometry import MontenegroGeometry
from pcbsmith.kicad.shaped_board import NetLookup, Router, placed_pad


def apply_led_chain_10_corridor(
    layout: BoardLayout,
    netlist: BoardNetlist,
    geometry: MontenegroGeometry,
) -> BoardLayout:
    """Bridge the one large LED-site gap around the southern peninsula.

    Curvature filtering deliberately omits several possible LED sites in this
    narrow region. A straight D10-to-D11 chord therefore leaves the board. The
    bridge follows the legal interior on B.Cu and uses via-in-pad transitions
    at the two front-mounted LEDs.
    """

    net = "/LED_CHAIN_10"
    lookup = NetLookup(netlist)
    lookup.expect("D10", "2", net)
    lookup.expect("D11", "4", net)
    by_ref = {component.reference: component for component in netlist.components}
    anchors = {component.reference: x for component, x in layout.placements}
    anchors_y = dict(layout.part_y_mm)
    rotations = dict(layout.part_rotation)

    def pad(reference: str, pin: str) -> tuple[float, float]:
        return placed_pad(
            by_ref[reference].footprint,
            pin,
            anchor=(anchors[reference], anchors_y[reference]),
            rotation=rotations.get(reference, 0.0),
        )

    start = pad("D10", "2")
    end = pad("D11", "4")
    points = (
        start,
        (68.0, 163.0),
        (68.5, 158.0),
        (68.0, 152.0),
        (62.0, 146.0),
        (54.0, 142.0),
        (47.0, 138.0),
        (44.0, 135.0),
        (48.0, 131.0),
        (56.0, 129.0),
        end,
    )
    if not geometry.polygon.buffer(-0.15).covers(LineString(points)):
        raise ValueError("LED_CHAIN_10 corridor leaves the Montenegro outline")

    router = Router()
    router.path(net, points, layer="B.Cu", width=0.25)
    for x, y in (start, end):
        router.vias.append(
            ViaSpec(
                x=x,
                y=y,
                net_name=net,
                size_mm=0.55,
                drill_mm=0.30,
            )
        )
    return BoardLayout(
        **{
            **layout.__dict__,
            "segments": (*layout.segments, *router.segments),
            "vias": (*layout.vias, *router.vias),
        }
    )
