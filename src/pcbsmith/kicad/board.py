from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import permutations
from pathlib import Path
from uuid import uuid4

from pcbsmith.kicad.cli import (
    KiCadInstall,
    KiCadProcessResult,
    find_kicad_cli,
    run_kicad_process,
)

KICAD_BOARD_VERSION = 20241229
TRACK_WIDTH_MM = 0.3
VIA_SIZE_MM = 0.6
VIA_DRILL_MM = 0.3
PARTS_ROW_Y_MM = 4.5
LANE_START_OFFSET_MM = 8.0
LANE_PITCH_MM = 1.2
PART_GAP_MM = 2.5
BOARD_MARGIN_MM = 3.0
CONNECTOR_EDGE_PAD_OFFSET_MM = 2.0
BOARD_SHEET_ORIGIN_MM = 20.0
EDGE_STROKE_MM = 0.1
MAX_EXHAUSTIVE_ORDER_PARTS = 8


class BoardGenerationError(RuntimeError):
    pass


@dataclass(frozen=True)
class PadSpec:
    name: str
    x_mm: float
    y_mm: float
    kind: str
    width_mm: float
    height_mm: float
    drill_mm: float = 0.0


@dataclass(frozen=True)
class FootprintSpec:
    pads: tuple[PadSpec, ...]
    fab_rect: tuple[float, float, float, float]
    silk_rect: tuple[float, float, float, float] | None
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    attr: str
    is_connector: bool = False

    def pad(self, name: str) -> PadSpec:
        for pad in self.pads:
            if pad.name == name:
                return pad
        raise KeyError(name)


_SMD_0603 = FootprintSpec(
    pads=(
        PadSpec(name="1", x_mm=-0.75, y_mm=0.0, kind="smd", width_mm=0.75, height_mm=0.95),
        PadSpec(name="2", x_mm=0.75, y_mm=0.0, kind="smd", width_mm=0.75, height_mm=0.95),
    ),
    fab_rect=(-0.8, -0.4, 0.8, 0.4),
    silk_rect=(-1.65, -0.9, 1.65, 0.9),
    x_min=-1.75,
    x_max=1.75,
    y_min=-1.0,
    y_max=1.0,
    attr="smd",
)

_PIN_HEADER_1X02 = FootprintSpec(
    pads=(
        PadSpec(
            name="1", x_mm=0.0, y_mm=0.0, kind="tht", width_mm=1.7, height_mm=1.7, drill_mm=1.0
        ),
        PadSpec(
            name="2", x_mm=2.54, y_mm=0.0, kind="tht", width_mm=1.7, height_mm=1.7, drill_mm=1.0
        ),
    ),
    fab_rect=(-1.27, -1.27, 3.81, 1.27),
    silk_rect=None,
    x_min=-1.4,
    x_max=3.94,
    y_min=-1.4,
    y_max=1.4,
    attr="through_hole",
    is_connector=True,
)

FOOTPRINT_LIBRARY: dict[str, FootprintSpec] = {
    "Resistor_SMD:R_0603_1608Metric": _SMD_0603,
    "Capacitor_SMD:C_0603_1608Metric": _SMD_0603,
    "LED_SMD:LED_0603_1608Metric": _SMD_0603,
    "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical": _PIN_HEADER_1X02,
}


@dataclass(frozen=True)
class BoardComponent:
    reference: str
    value: str
    footprint: str
    uuid_path: str
    fields: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class BoardNet:
    name: str
    nodes: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class BoardNetlist:
    components: tuple[BoardComponent, ...]
    nets: tuple[BoardNet, ...]


def export_kicad_netlist_xml(
    schematic_file: Path,
    *,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> Path:
    netlist_file = (
        schematic_file.parent / ".pcbsmith" / "kicad" / f"{schematic_file.stem}.net.xml"
    )
    install = finder()
    if install is None:
        raise BoardGenerationError(
            "KiCad CLI was not found; the board netlist export was not run."
        )
    command = (
        str(install.path),
        "sch",
        "export",
        "netlist",
        "--format",
        "kicadxml",
        "--output",
        str(netlist_file),
        str(schematic_file),
    )
    netlist_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        netlist_file.unlink(missing_ok=True)
        process = run_kicad_process(command) if runner is None else runner(command)
    except OSError as exc:
        raise BoardGenerationError(f"KiCad netlist export could not run: {exc}") from exc
    if process.returncode != 0:
        detail = process.stderr.strip() or process.stdout.strip() or "unknown error"
        raise BoardGenerationError(f"KiCad netlist export failed: {detail}")
    if not netlist_file.exists():
        raise BoardGenerationError("KiCad netlist export did not write an output file.")
    return netlist_file


def parse_board_netlist(xml_text: str) -> BoardNetlist:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        raise BoardGenerationError(f"KiCad netlist XML could not be parsed: {exc}") from exc

    components: list[BoardComponent] = []
    for comp in root.iter("comp"):
        reference = comp.get("ref") or ""
        if not reference or reference.startswith("#"):
            continue
        footprint = _element_text(comp, "footprint")
        if not footprint:
            continue
        fields: list[tuple[str, str]] = []
        for field in comp.iter("field"):
            name = field.get("name") or ""
            if not name or name in {"Reference", "Value"}:
                continue
            fields.append((name, (field.text or "").strip()))
        components.append(
            BoardComponent(
                reference=reference,
                value=_element_text(comp, "value") or reference,
                footprint=footprint,
                uuid_path=_element_text(comp, "tstamps") or str(uuid4()),
                fields=tuple(fields),
            )
        )
    if not components:
        raise BoardGenerationError(
            "KiCad netlist contained no board components with footprints."
        )

    placed = {component.reference for component in components}
    nets: list[BoardNet] = []
    for net in root.iter("net"):
        name = net.get("name") or ""
        nodes = tuple(
            (node.get("ref") or "", node.get("pin") or "")
            for node in net.iter("node")
            if (node.get("ref") or "") in placed
        )
        if name and nodes:
            nets.append(BoardNet(name=name, nodes=nodes))
    return BoardNetlist(
        components=tuple(components),
        nets=tuple(sorted(nets, key=lambda net: net.name)),
    )


def generate_board(
    *,
    schematic_file: Path,
    board_file: Path,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> Path:
    netlist_file = export_kicad_netlist_xml(schematic_file, finder=finder, runner=runner)
    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    board_file.write_text(render_board(netlist), encoding="utf-8")
    return board_file


RENDER_VIEWS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("top", ("--side", "top")),
    ("bottom", ("--side", "bottom")),
    ("perspective", ("--perspective", "--rotate", "-30,0,-20", "--zoom", "0.9")),
)


def render_board_previews(
    board_file: Path,
    *,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """Render PNG previews of a board. Best-effort: failures become findings."""
    install = finder()
    if install is None:
        return {}, ("KiCad CLI was not found; board previews were not rendered.",)

    previews: dict[str, str] = {}
    findings: list[str] = []
    for view, view_args in RENDER_VIEWS:
        output = board_file.parent / f"{board_file.stem}-{view}.png"
        command = (
            str(install.path),
            "pcb",
            "render",
            "--output",
            str(output),
            "--width",
            "1600",
            "--height",
            "1000",
            "--quality",
            "high",
            *view_args,
            str(board_file),
        )
        try:
            process = run_kicad_process(command) if runner is None else runner(command)
        except OSError as exc:
            findings.append(f"Board {view} preview could not be rendered: {exc}")
            continue
        if process.returncode != 0 or not output.exists():
            detail = process.stderr.strip() or process.stdout.strip() or "unknown error"
            findings.append(f"Board {view} preview render failed: {detail}")
            continue
        previews[view] = str(output)
    return previews, tuple(findings)


def render_board(netlist: BoardNetlist) -> str:
    unknown = sorted(
        {
            component.footprint
            for component in netlist.components
            if component.footprint not in FOOTPRINT_LIBRARY
        }
    )
    if unknown:
        raise BoardGenerationError(
            "No board footprint geometry is defined for: " + ", ".join(unknown)
        )

    placements = _place_components(netlist.components, netlist.nets)
    net_numbers = {net.name: index for index, net in enumerate(netlist.nets, start=1)}
    pad_nets = {
        (reference, pin): net.name
        for net in netlist.nets
        for reference, pin in net.nodes
    }

    tracks, lane_bottom_y = _route_channel(netlist, placements, net_numbers)
    board_width = max(
        anchor_x + FOOTPRINT_LIBRARY[component.footprint].x_max
        for component, anchor_x in placements
    ) + BOARD_MARGIN_MM
    board_height = lane_bottom_y + BOARD_MARGIN_MM

    sections: list[str] = [_render_header()]
    sections.append('  (net 0 "")')
    for net in netlist.nets:
        sections.append(f'  (net {net_numbers[net.name]} {_q(net.name)})')
    for component, anchor_x in placements:
        sections.append(_render_footprint(component, anchor_x, pad_nets, net_numbers))
    sections.extend(tracks)
    origin = BOARD_SHEET_ORIGIN_MM
    sections.append(
        f"""  (gr_rect
    (start {_mm(origin)} {_mm(origin)})
    (end {_mm(origin + board_width)} {_mm(origin + board_height)})
    (stroke (width {_mm(EDGE_STROKE_MM)}) (type default))
    (fill none)
    (layer "Edge.Cuts")
    (uuid {uuid4()})
  )"""
    )
    return "\n".join(("\n".join(sections), ")", ""))


def _place_components(
    components: tuple[BoardComponent, ...],
    nets: tuple[BoardNet, ...] = (),
) -> tuple[tuple[BoardComponent, float], ...]:
    ordered = _order_components(components, nets)
    placements: list[tuple[BoardComponent, float]] = []
    cursor = 0.0
    for index, component in enumerate(ordered):
        spec = FOOTPRINT_LIBRARY[component.footprint]
        if index == 0 and spec.is_connector:
            # Connector pads hug the board corner so off-board wiring lands
            # at the edge, matching hand-layout convention.
            anchor_x = CONNECTOR_EDGE_PAD_OFFSET_MM - spec.pads[0].x_mm
        else:
            anchor_x = max(cursor, BOARD_MARGIN_MM) - spec.x_min
        placements.append((component, anchor_x))
        cursor = anchor_x + spec.x_max + PART_GAP_MM
    return tuple(placements)


def _order_components(
    components: tuple[BoardComponent, ...],
    nets: tuple[BoardNet, ...],
) -> tuple[BoardComponent, ...]:
    # Connectors carry off-board wiring, so they lead the row at the board
    # edge. The remaining parts take the row order that minimises the total
    # horizontal span of all nets, which recovers signal-flow ordering.
    connectors = tuple(
        component
        for component in components
        if FOOTPRINT_LIBRARY[component.footprint].is_connector
    )
    others = tuple(
        component
        for component in components
        if not FOOTPRINT_LIBRARY[component.footprint].is_connector
    )
    if not nets or not others or len(others) > MAX_EXHAUSTIVE_ORDER_PARTS:
        return (*connectors, *others)

    best_order = others
    best_cost = _row_net_span(connectors, others, nets)
    for candidate in permutations(others):
        cost = _row_net_span(connectors, candidate, nets)
        if cost < best_cost:
            best_cost = cost
            best_order = candidate
    return (*connectors, *best_order)


def _row_net_span(
    connectors: tuple[BoardComponent, ...],
    others: tuple[BoardComponent, ...],
    nets: tuple[BoardNet, ...],
) -> float:
    positions: dict[str, float] = {}
    cursor = 0.0
    for index, component in enumerate((*connectors, *others)):
        spec = FOOTPRINT_LIBRARY[component.footprint]
        if index == 0 and spec.is_connector:
            anchor_x = CONNECTOR_EDGE_PAD_OFFSET_MM - spec.pads[0].x_mm
        else:
            anchor_x = max(cursor, BOARD_MARGIN_MM) - spec.x_min
        positions[component.reference] = anchor_x
        cursor = anchor_x + spec.x_max + PART_GAP_MM

    total = 0.0
    for net in nets:
        xs = [positions[reference] for reference, _ in net.nodes if reference in positions]
        if len(xs) > 1:
            total += max(xs) - min(xs)
    return total


def _route_channel(
    netlist: BoardNetlist,
    placements: tuple[tuple[BoardComponent, float], ...],
    net_numbers: dict[str, int],
) -> tuple[list[str], float]:
    anchor_by_reference = {
        component.reference: (anchor_x, FOOTPRINT_LIBRARY[component.footprint])
        for component, anchor_x in placements
    }
    tracks: list[str] = []
    lane_index = 0
    lane_bottom_y = PARTS_ROW_Y_MM + LANE_START_OFFSET_MM
    for net in netlist.nets:
        pad_positions: list[tuple[float, float]] = []
        for reference, pin in net.nodes:
            anchor_x, spec = anchor_by_reference[reference]
            try:
                pad = spec.pad(pin)
            except KeyError as exc:
                raise BoardGenerationError(
                    f"Footprint for {reference} has no pad named {pin!r}."
                ) from exc
            pad_positions.append((anchor_x + pad.x_mm, PARTS_ROW_Y_MM + pad.y_mm))
        if len(pad_positions) < 2:
            continue
        lane_y = PARTS_ROW_Y_MM + LANE_START_OFFSET_MM + lane_index * LANE_PITCH_MM
        lane_bottom_y = max(lane_bottom_y, lane_y)
        lane_index += 1
        number = net_numbers[net.name]
        for pad_x, pad_y in pad_positions:
            tracks.append(_segment(pad_x, pad_y, pad_x, lane_y, "F.Cu", number))
            tracks.append(_via(pad_x, lane_y, number))
        xs = sorted(x for x, _ in pad_positions)
        tracks.append(_segment(xs[0], lane_y, xs[-1], lane_y, "B.Cu", number))
    return tracks, lane_bottom_y


def _segment(x1: float, y1: float, x2: float, y2: float, layer: str, net: int) -> str:
    origin = BOARD_SHEET_ORIGIN_MM
    return (
        f"  (segment (start {_mm(x1 + origin)} {_mm(y1 + origin)}) "
        f"(end {_mm(x2 + origin)} {_mm(y2 + origin)}) "
        f'(width {_mm(TRACK_WIDTH_MM)}) (layer "{layer}") (net {net}) (uuid {uuid4()}))'
    )


def _via(x: float, y: float, net: int) -> str:
    origin = BOARD_SHEET_ORIGIN_MM
    return (
        f"  (via (at {_mm(x + origin)} {_mm(y + origin)}) (size {_mm(VIA_SIZE_MM)}) "
        f'(drill {_mm(VIA_DRILL_MM)}) (layers "F.Cu" "B.Cu") (net {net}) (uuid {uuid4()}))'
    )


def _render_header() -> str:
    return f"""(kicad_pcb
  (version {KICAD_BOARD_VERSION})
  (generator "PCBSmith")

  (general
    (thickness 1.6)
  )

  (paper "A4")

  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
    (32 "B.Adhes" user)
    (33 "F.Adhes" user)
    (34 "B.Paste" user)
    (35 "F.Paste" user)
    (36 "B.SilkS" user)
    (37 "F.SilkS" user)
    (38 "B.Mask" user)
    (39 "F.Mask" user)
    (44 "Edge.Cuts" user)
  )"""


def _render_footprint(
    component: BoardComponent,
    anchor_x: float,
    pad_nets: dict[tuple[str, str], str],
    net_numbers: dict[str, int],
) -> str:
    spec = FOOTPRINT_LIBRARY[component.footprint]
    center_x = (spec.x_min + spec.x_max) / 2
    parts: list[str] = [
        f"""  (footprint {_q(component.footprint)}
    (layer "F.Cu")
    (uuid {uuid4()})
    (at {_mm(anchor_x + BOARD_SHEET_ORIGIN_MM)} {_mm(PARTS_ROW_Y_MM + BOARD_SHEET_ORIGIN_MM)})
    (property "Reference" {_q(component.reference)}
      (at {_mm(center_x)} {_mm(spec.y_min - 1.2)} 0)
      (layer "F.SilkS")
      (uuid {uuid4()})
      (effects
        (font
          (size 0.8 0.8)
          (thickness 0.12)
        )
      )
    )
    (property "Value" {_q(component.value)}
      (at {_mm(center_x)} 0 0)
      (layer "F.Fab")
      (uuid {uuid4()})
      (effects
        (font
          (size 0.5 0.5)
          (thickness 0.06)
        )
      )
    )
    (path "/{component.uuid_path.strip('/')}")
    (attr {spec.attr})"""
    ]
    for field_name, field_value in component.fields:
        parts.append(
            f"""    (property {_q(field_name)} {_q(field_value)}
      (at 0 0 0)
      (layer "F.Fab")
      (hide yes)
      (uuid {uuid4()})
      (effects
        (font
          (size 0.5 0.5)
          (thickness 0.06)
        )
      )
    )"""
        )
    parts.append(_fp_rect(spec.fab_rect, "F.Fab", 0.08))
    if spec.silk_rect is not None:
        parts.append(_fp_rect(spec.silk_rect, "F.SilkS", 0.1))
    for pad in spec.pads:
        net_name = pad_nets.get((component.reference, pad.name))
        net_clause = (
            f"      (net {net_numbers[net_name]} {_q(net_name)})\n"
            if net_name is not None
            else ""
        )
        if pad.kind == "smd":
            parts.append(
                f"""    (pad {_q(pad.name)} smd roundrect
      (at {_mm(pad.x_mm)} {_mm(pad.y_mm)})
      (size {_mm(pad.width_mm)} {_mm(pad.height_mm)})
      (layers "F.Cu" "F.Paste" "F.Mask")
      (roundrect_rratio 0.25)
{net_clause}      (pintype "passive")
      (uuid {uuid4()})
    )"""
            )
        else:
            parts.append(
                f"""    (pad {_q(pad.name)} thru_hole circle
      (at {_mm(pad.x_mm)} {_mm(pad.y_mm)})
      (size {_mm(pad.width_mm)} {_mm(pad.height_mm)})
      (drill {_mm(pad.drill_mm)})
      (layers "*.Cu" "*.Mask")
{net_clause}      (pintype "passive")
      (uuid {uuid4()})
    )"""
            )
    parts.append("  )")
    return "\n".join(parts)


def _fp_rect(rect: tuple[float, float, float, float], layer: str, stroke: float) -> str:
    x1, y1, x2, y2 = rect
    return f"""    (fp_rect
      (start {_mm(x1)} {_mm(y1)})
      (end {_mm(x2)} {_mm(y2)})
      (stroke (width {_mm(stroke)}) (type solid))
      (fill none)
      (layer "{layer}")
      (uuid {uuid4()})
    )"""


def _element_text(parent: ET.Element, tag: str) -> str | None:
    element = parent.find(tag)
    if element is None or element.text is None:
        return None
    text = element.text.strip()
    return text or None


def _mm(value: float) -> str:
    formatted = f"{value:.3f}".rstrip("0").rstrip(".")
    return formatted or "0"


def _q(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
