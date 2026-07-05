"""Art-grid board layout for the LED text-matrix topology.

Placement follows the glyph geometry: every LED sits on a dot-grid cell, its
string resistor sits in a feed row above the glyph field, the input connector
hugs the left edge, and two horizontal power rails frame the field (VIN on
top, GND on the bottom). Routing is collision-free by construction:

- every series link stays inside its own 5 mm column (vertical drops with one
  short jog above the destination pad), and columns never share a string;
- rail drops run above/below all series copper, at pad x positions that are
  unique per column.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from pcbsmith.generation.led_art import LedArtPlan
from pcbsmith.kicad.board import (
    FOOTPRINT_LIBRARY,
    POWER_TRACK_WIDTH_MM,
    SIGNAL_TRACK_WIDTH_MM,
    BoardComponent,
    BoardGenerationError,
    BoardLayout,
    BoardNetlist,
    TrackSegment,
    export_kicad_netlist_xml,
    mounting_hole_placements,
    net_name_in,
    parse_board_netlist,
    render_board_from_layout,
    rotate_offset,
)
from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult, find_kicad_cli

ART_PITCH_MM = 5.0
ART_X0_MM = 12.0
ART_Y0_MM = 20.0
RESISTOR_ROW_Y_MM = 13.0
TOP_RAIL_Y_MM = 8.5
BOTTOM_RAIL_Y_MM = 44.0
BOTTOM_BAND_MM = 8.0
CONNECTOR_ANCHOR_X_MM = 2.0
CONNECTOR_ANCHOR_Y_MM = 25.0
# Edge-parallel connector: the official 1x02 vertical header already stacks
# its pads in y (pin 1 / "+" on top), matching the user's hand-edited
# reference without any rotation.
CONNECTOR_ROTATION_DEG = 0.0
JOG_CLEARANCE_MM = 1.5
BOARD_MARGIN_MM = 3.0


def compute_led_art_board_layout(
    netlist: BoardNetlist,
    plan: LedArtPlan,
    power_net_names: frozenset[str] = frozenset(),
) -> BoardLayout:
    positions: dict[str, tuple[float, float]] = {}
    for string in plan.strings:
        x = ART_X0_MM + string.column * ART_PITCH_MM
        positions[string.resistor_ref] = (x, RESISTOR_ROW_Y_MM)
        for led_ref, row in zip(string.led_refs, string.rows, strict=True):
            positions[led_ref] = (x, ART_Y0_MM + row * ART_PITCH_MM)

    rotations: dict[str, float] = {}
    components_by_reference: dict[str, BoardComponent] = {}
    for component in netlist.components:
        components_by_reference[component.reference] = component
        spec = FOOTPRINT_LIBRARY.get(component.footprint)
        if spec is None:
            raise BoardGenerationError(
                f"No board footprint geometry is defined for {component.footprint}."
            )
        if spec.is_connector:
            positions[component.reference] = (
                CONNECTOR_ANCHOR_X_MM,
                CONNECTOR_ANCHOR_Y_MM,
            )
            rotations[component.reference] = CONNECTOR_ROTATION_DEG
        if component.reference not in positions:
            raise BoardGenerationError(
                f"The art plan has no grid position for {component.reference}."
            )
    missing = sorted(set(positions) - set(components_by_reference))
    if missing:
        raise BoardGenerationError(
            "The netlist is missing planned components: " + ", ".join(missing)
        )
    placements: list[tuple[BoardComponent, float]] = []
    part_y: list[tuple[str, float]] = []
    for reference in sorted(positions, key=lambda ref: positions[ref]):
        x, y = positions[reference]
        placements.append((components_by_reference[reference], x))
        part_y.append((reference, y))

    def pad_position(reference: str, pin: str) -> tuple[float, float]:
        component = components_by_reference[reference]
        spec = FOOTPRINT_LIBRARY[component.footprint]
        pad = spec.pads_named(pin)[0]
        x, y = positions[reference]
        dx, dy = rotate_offset(pad.x_mm, pad.y_mm, rotations.get(reference, 0.0))
        return (x + dx, y + dy)

    segments: list[TrackSegment] = []
    for net in netlist.nets:
        power = net_name_in(net.name, power_net_names)
        width = POWER_TRACK_WIDTH_MM if power else SIGNAL_TRACK_WIDTH_MM
        pads = [pad_position(reference, pin) for reference, pin in net.nodes]
        if net_name_in(net.name, frozenset({"VIN"})):
            segments.extend(_rail(net.name, pads, TOP_RAIL_Y_MM, width))
        elif net_name_in(net.name, frozenset({"GND"})):
            segments.extend(_rail(net.name, pads, BOTTOM_RAIL_Y_MM, width))
        elif len(pads) == 2:
            segments.extend(_series_link(net.name, pads, width))
        else:
            raise BoardGenerationError(
                f"Net {net.name} has {len(pads)} pads; the art router only "
                "handles the two power rails and two-pad series links."
            )

    xs = [segment.x1 for segment in segments] + [segment.x2 for segment in segments]
    xs.extend(x for x, _ in positions.values())
    width_mm = max(xs) + BOARD_MARGIN_MM
    height_mm = BOTTOM_RAIL_Y_MM + BOTTOM_BAND_MM
    for component, x, y in mounting_hole_placements(width_mm, height_mm):
        placements.append((component, x))
        part_y.append((component.reference, y))
    return BoardLayout(
        placements=tuple(placements),
        segments=tuple(segments),
        vias=(),
        width_mm=width_mm,
        height_mm=height_mm,
        parts_row_y_mm=RESISTOR_ROW_Y_MM,
        part_y_mm=tuple(part_y),
        part_rotation=tuple(sorted(rotations.items())),
    )


def _rail(
    net_name: str,
    pads: Sequence[tuple[float, float]],
    rail_y: float,
    width: float,
) -> tuple[TrackSegment, ...]:
    segments = [
        TrackSegment(
            x1=x, y1=y, x2=x, y2=rail_y, layer="F.Cu", net_name=net_name,
            width_mm=width,
        )
        for x, y in pads
    ]
    xs = sorted(x for x, _ in pads)
    segments.append(
        TrackSegment(
            x1=xs[0], y1=rail_y, x2=xs[-1], y2=rail_y, layer="F.Cu",
            net_name=net_name, width_mm=width,
        )
    )
    return tuple(segments)


def _series_link(
    net_name: str,
    pads: Sequence[tuple[float, float]],
    width: float,
) -> tuple[TrackSegment, ...]:
    (xa, ya), (xb, yb) = sorted(pads, key=lambda pad: pad[1])
    if abs(xb - xa) > ART_PITCH_MM:
        raise BoardGenerationError(
            f"Series net {net_name} spans {abs(xb - xa):.1f}mm horizontally; "
            "series links must stay inside one glyph column."
        )
    jog_y = yb - JOG_CLEARANCE_MM
    if jog_y <= ya:
        raise BoardGenerationError(
            f"Series net {net_name} pads are too close vertically for a jog."
        )
    segments = [
        TrackSegment(
            x1=xa, y1=ya, x2=xa, y2=jog_y, layer="F.Cu", net_name=net_name,
            width_mm=width,
        )
    ]
    if xa != xb:
        segments.append(
            TrackSegment(
                x1=xa, y1=jog_y, x2=xb, y2=jog_y, layer="F.Cu", net_name=net_name,
                width_mm=width,
            )
        )
    segments.append(
        TrackSegment(
            x1=xb, y1=jog_y, x2=xb, y2=yb, layer="F.Cu", net_name=net_name,
            width_mm=width,
        )
    )
    return tuple(segments)


def generate_led_art_board(
    *,
    schematic_file: Path,
    board_file: Path,
    plan: LedArtPlan,
    power_net_names: frozenset[str] = frozenset(),
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> tuple[BoardNetlist, BoardLayout]:
    netlist_file = export_kicad_netlist_xml(schematic_file, finder=finder, runner=runner)
    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    layout = compute_led_art_board_layout(netlist, plan, power_net_names)
    board_file.write_text(render_board_from_layout(netlist, layout), encoding="utf-8")
    return netlist, layout
