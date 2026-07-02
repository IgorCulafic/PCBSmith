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
SIGNAL_TRACK_WIDTH_MM = 0.3
POWER_TRACK_WIDTH_MM = 0.8
SIGNAL_VIA_SIZE_MM = 0.6
SIGNAL_VIA_DRILL_MM = 0.3
POWER_VIA_SIZE_MM = 0.8
POWER_VIA_DRILL_MM = 0.4
MIN_PARTS_ROW_Y_MM = 4.5
PARTS_ROW_TOP_MARGIN_MM = 3.0
LANE_START_OFFSET_MM = 9.5
LANE_PITCH_MM = 1.6
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
class SilkLine:
    """A polarity/orientation mark line on F.SilkS, footprint-local mm."""

    x1: float
    y1: float
    x2: float
    y2: float


@dataclass(frozen=True)
class SilkText:
    """A small mark text (for example "+" / "-") on F.SilkS, local mm."""

    text: str
    x: float
    y: float


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
    # Polarity marks per docs/pcb-design-rules.md section 8; glyph geometry
    # follows the official KiCad footprint library (cathode bar, "+" cross).
    silk_marks: tuple[SilkLine | SilkText, ...] = ()

    def pads_named(self, name: str) -> tuple[PadSpec, ...]:
        matches = tuple(pad for pad in self.pads if pad.name == name)
        if not matches:
            raise KeyError(name)
        return matches


def rotate_offset(dx: float, dy: float, rotation: float) -> tuple[float, float]:
    """Rotate a footprint-local offset by the KiCad footprint rotation.

    KiCad rotations are counter-clockwise on screen; board coordinates have
    y pointing down, so +90 maps (right, down) to (up, right). Verified live
    against KiCad DRC parity (a wrong transform strands every rotated pad).
    """
    normalized = rotation % 360
    if normalized == 0:
        return (dx, dy)
    if normalized == 90:
        return (dy, -dx)
    if normalized == 180:
        return (-dx, -dy)
    if normalized == 270:
        return (-dy, dx)
    raise BoardGenerationError(
        f"Only right-angle footprint rotations are supported, not {rotation}."
    )


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

# LED variant of the 0603 body: same pads, plus the standard cathode bar
# (KiCad's LED_0603_1608Metric draws this bar at its cathode pad; our LED
# symbol/footprint pair puts the cathode on pad 2, so the bar sits there).
_LED_0603 = FootprintSpec(
    pads=_SMD_0603.pads,
    fab_rect=_SMD_0603.fab_rect,
    silk_rect=_SMD_0603.silk_rect,
    x_min=-1.75,
    x_max=2.15,
    y_min=-1.0,
    y_max=1.0,
    attr="smd",
    silk_marks=(SilkLine(x1=1.9, y1=-0.9, x2=1.9, y2=0.9),),
)

# Power connector: "+" / "-" beside the pins so off-board wiring polarity is
# obvious. PCBSmith topologies always put the positive rail on pin 1.
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
    y_min=-2.9,
    y_max=1.4,
    attr="through_hole",
    is_connector=True,
    silk_marks=(
        SilkText(text="+", x=0.0, y=-2.2),
        SilkText(text="-", x=2.54, y=-2.2),
    ),
)

# LM2596S: pins 1-5 left to right at 1.7 mm pitch, tab carries pin 3 (GND).
_TO_263_5_TABPIN3 = FootprintSpec(
    pads=(
        PadSpec(name="1", x_mm=-3.4, y_mm=6.3, kind="smd", width_mm=1.0, height_mm=2.2),
        PadSpec(name="2", x_mm=-1.7, y_mm=6.3, kind="smd", width_mm=1.0, height_mm=2.2),
        PadSpec(name="3", x_mm=0.0, y_mm=6.3, kind="smd", width_mm=1.0, height_mm=2.2),
        PadSpec(name="4", x_mm=1.7, y_mm=6.3, kind="smd", width_mm=1.0, height_mm=2.2),
        PadSpec(name="5", x_mm=3.4, y_mm=6.3, kind="smd", width_mm=1.0, height_mm=2.2),
        PadSpec(name="3", x_mm=0.0, y_mm=-1.6, kind="smd", width_mm=10.8, height_mm=10.6),
    ),
    fab_rect=(-5.2, -7.0, 5.2, 5.0),
    silk_rect=None,
    x_min=-5.6,
    x_max=5.6,
    y_min=-7.2,
    y_max=7.6,
    attr="smd",
)

# Schottky diode: cathode bar on silk (our diode symbol/footprint pair puts
# the cathode on pad 2).
_D_SMA = FootprintSpec(
    pads=(
        PadSpec(name="1", x_mm=-2.15, y_mm=0.0, kind="smd", width_mm=2.4, height_mm=1.7),
        PadSpec(name="2", x_mm=2.15, y_mm=0.0, kind="smd", width_mm=2.4, height_mm=1.7),
    ),
    fab_rect=(-2.3, -1.45, 2.3, 1.45),
    silk_rect=(-2.45, -1.6, 2.45, 1.6),
    x_min=-3.6,
    x_max=3.9,
    y_min=-1.8,
    y_max=1.8,
    attr="smd",
    silk_marks=(SilkLine(x1=3.7, y1=-1.6, x2=3.7, y2=1.6),),
)

# Polarized electrolytic: "+" cross beside the positive pad (KiCad's
# CP_Elec_8x10 draws the same cross; our capacitor pair puts + on pad 2).
_CP_ELEC_8X10 = FootprintSpec(
    pads=(
        PadSpec(name="1", x_mm=-3.05, y_mm=0.0, kind="smd", width_mm=3.2, height_mm=1.6),
        PadSpec(name="2", x_mm=3.05, y_mm=0.0, kind="smd", width_mm=3.2, height_mm=1.6),
    ),
    fab_rect=(-4.15, -4.15, 4.15, 4.15),
    silk_rect=None,
    x_min=-4.9,
    x_max=4.9,
    y_min=-5.4,
    y_max=4.3,
    attr="smd",
    silk_marks=(
        SilkLine(x1=2.55, y1=-4.75, x2=3.55, y2=-4.75),
        SilkLine(x1=3.05, y1=-5.25, x2=3.05, y2=-4.25),
    ),
)

_L_12X12 = FootprintSpec(
    pads=(
        PadSpec(name="1", x_mm=-4.35, y_mm=0.0, kind="smd", width_mm=4.4, height_mm=5.0),
        PadSpec(name="2", x_mm=4.35, y_mm=0.0, kind="smd", width_mm=4.4, height_mm=5.0),
    ),
    fab_rect=(-6.25, -6.25, 6.25, 6.25),
    silk_rect=None,
    x_min=-6.8,
    x_max=6.8,
    y_min=-6.4,
    y_max=6.4,
    attr="smd",
)

FOOTPRINT_LIBRARY: dict[str, FootprintSpec] = {
    "Resistor_SMD:R_0603_1608Metric": _SMD_0603,
    "Capacitor_SMD:C_0603_1608Metric": _SMD_0603,
    "LED_SMD:LED_0603_1608Metric": _LED_0603,
    "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical": _PIN_HEADER_1X02,
    "Package_TO_SOT_SMD:TO-263-5_TabPin3": _TO_263_5_TABPIN3,
    "Diode_SMD:D_SMA": _D_SMA,
    "Capacitor_SMD:CP_Elec_8x10": _CP_ELEC_8X10,
    "Inductor_SMD:L_12x12mm_H8mm": _L_12X12,
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


@dataclass(frozen=True)
class TrackSegment:
    x1: float
    y1: float
    x2: float
    y2: float
    layer: str
    net_name: str
    width_mm: float = SIGNAL_TRACK_WIDTH_MM


@dataclass(frozen=True)
class ViaSpec:
    x: float
    y: float
    net_name: str
    size_mm: float = SIGNAL_VIA_SIZE_MM
    drill_mm: float = SIGNAL_VIA_DRILL_MM


@dataclass(frozen=True)
class BoardLayout:
    placements: tuple[tuple[BoardComponent, float], ...]
    segments: tuple[TrackSegment, ...]
    vias: tuple[ViaSpec, ...]
    width_mm: float
    height_mm: float
    parts_row_y_mm: float = MIN_PARTS_ROW_Y_MM
    # Per-reference y anchors for layouts that are not a single row (for
    # example art grids); references absent here sit on the parts row.
    part_y_mm: tuple[tuple[str, float], ...] = ()
    # Per-reference right-angle rotations (KiCad degrees, CCW); absent = 0.
    part_rotation: tuple[tuple[str, float], ...] = ()


def placement_y(layout: BoardLayout, reference: str) -> float:
    for candidate, y_mm in layout.part_y_mm:
        if candidate == reference:
            return y_mm
    return layout.parts_row_y_mm


def placement_rotation(layout: BoardLayout, reference: str) -> float:
    for candidate, rotation in layout.part_rotation:
        if candidate == reference:
            return rotation
    return 0.0


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
    power_net_names: frozenset[str] = frozenset(),
    sensitive_net_names: frozenset[str] = frozenset(),
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> BoardNetlist:
    netlist_file = export_kicad_netlist_xml(schematic_file, finder=finder, runner=runner)
    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    board_file.write_text(
        render_board(netlist, power_net_names, sensitive_net_names),
        encoding="utf-8",
    )
    return netlist


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


def compute_board_layout(
    netlist: BoardNetlist,
    power_net_names: frozenset[str] = frozenset(),
    sensitive_net_names: frozenset[str] = frozenset(),
) -> BoardLayout:
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

    placements = _place_components(netlist.components, netlist.nets, power_net_names)
    parts_row_y = max(
        MIN_PARTS_ROW_Y_MM,
        PARTS_ROW_TOP_MARGIN_MM
        + max(
            -FOOTPRINT_LIBRARY[component.footprint].y_min
            for component, _ in placements
        ),
    )
    segments, vias, lane_bottom_y = _route_channel(
        netlist,
        placements,
        parts_row_y=parts_row_y,
        power_net_names=power_net_names,
        sensitive_net_names=sensitive_net_names,
    )
    last_component, last_anchor = placements[-1]
    last_spec = FOOTPRINT_LIBRARY[last_component.footprint]
    if last_spec.is_connector and len(placements) > 1:
        # A trailing connector hugs the right board edge, mirroring the lead.
        board_width = (
            last_anchor
            + max(pad.x_mm for pad in last_spec.pads)
            + CONNECTOR_EDGE_PAD_OFFSET_MM
        )
    else:
        board_width = last_anchor + last_spec.x_max + BOARD_MARGIN_MM
    board_width = max(
        board_width,
        max(
            anchor_x + FOOTPRINT_LIBRARY[component.footprint].x_max
            for component, anchor_x in placements
        ),
    )
    board_height = lane_bottom_y + BOARD_MARGIN_MM
    return BoardLayout(
        placements=placements,
        segments=segments,
        vias=vias,
        width_mm=board_width,
        height_mm=board_height,
        parts_row_y_mm=parts_row_y,
    )


def net_name_in(net_name: str, names: frozenset[str]) -> bool:
    return net_name.lstrip("/").upper() in {name.upper() for name in names}


def is_power_net(net_name: str, power_net_names: frozenset[str]) -> bool:
    return net_name_in(net_name, power_net_names)


def render_board(
    netlist: BoardNetlist,
    power_net_names: frozenset[str] = frozenset(),
    sensitive_net_names: frozenset[str] = frozenset(),
) -> str:
    layout = compute_board_layout(netlist, power_net_names, sensitive_net_names)
    return render_board_from_layout(netlist, layout)


def render_board_from_layout(netlist: BoardNetlist, layout: BoardLayout) -> str:
    net_numbers = {net.name: index for index, net in enumerate(netlist.nets, start=1)}
    pad_nets = {
        (reference, pin): net.name
        for net in netlist.nets
        for reference, pin in net.nodes
    }
    board_width = layout.width_mm
    board_height = layout.height_mm

    sections: list[str] = [_render_header()]
    sections.append('  (net 0 "")')
    for net in netlist.nets:
        sections.append(f'  (net {net_numbers[net.name]} {_q(net.name)})')
    for component, anchor_x in layout.placements:
        sections.append(
            _render_footprint(
                component,
                anchor_x,
                pad_nets,
                net_numbers,
                anchor_y=placement_y(layout, component.reference),
                rotation=placement_rotation(layout, component.reference),
            )
        )
    for segment in layout.segments:
        sections.append(_segment(segment, net_numbers))
    for via in layout.vias:
        sections.append(_via(via, net_numbers))
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


POWER_NET_SPAN_WEIGHT = 3.0


def _place_components(
    components: tuple[BoardComponent, ...],
    nets: tuple[BoardNet, ...] = (),
    power_net_names: frozenset[str] = frozenset(),
) -> tuple[tuple[BoardComponent, float], ...]:
    ordered = _order_components(components, nets, power_net_names)
    return _anchor_row(ordered)


def _anchor_row(
    ordered: tuple[BoardComponent, ...],
) -> tuple[tuple[BoardComponent, float], ...]:
    placements: list[tuple[BoardComponent, float]] = []
    cursor = 0.0
    for index, component in enumerate(ordered):
        spec = FOOTPRINT_LIBRARY[component.footprint]
        if index == 0 and spec.is_connector:
            # The leading connector hugs the board corner so off-board wiring
            # lands at the edge, matching hand-layout convention.
            anchor_x = CONNECTOR_EDGE_PAD_OFFSET_MM - spec.pads[0].x_mm
        else:
            anchor_x = max(cursor, BOARD_MARGIN_MM) - spec.x_min
        placements.append((component, anchor_x))
        cursor = anchor_x + spec.x_max + PART_GAP_MM
    return tuple(placements)


def _order_components(
    components: tuple[BoardComponent, ...],
    nets: tuple[BoardNet, ...],
    power_net_names: frozenset[str] = frozenset(),
) -> tuple[BoardComponent, ...]:
    # Connectors carry off-board wiring, so they sit at the board edges: the
    # first leads the row (left edge) and any further connectors close it
    # (right edge) so power enters one side and leaves the other. Interior
    # parts take the order that minimises the net span, weighted towards
    # power nets so the switching path stays physically tight.
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
    lead = connectors[:1]
    tail = connectors[1:]
    if not nets or not others:
        return (*lead, *others, *tail)

    def cost(middle: tuple[BoardComponent, ...]) -> float:
        return _row_net_span((*lead, *middle, *tail), nets, power_net_names)

    if len(others) > MAX_EXHAUSTIVE_ORDER_PARTS:
        best_order = _order_by_local_search(others, cost)
    else:
        best_order = others
        best_cost = cost(others)
        for candidate in permutations(others):
            candidate_cost = cost(candidate)
            if candidate_cost < best_cost:
                best_cost = candidate_cost
                best_order = candidate
    return (*lead, *best_order, *tail)


def _order_by_local_search(
    others: tuple[BoardComponent, ...],
    cost: Callable[[tuple[BoardComponent, ...]], float],
) -> tuple[BoardComponent, ...]:
    """Deterministic pairwise-swap hill climb for rows too long to enumerate."""
    order = list(others)
    best_cost = cost(tuple(order))
    improved = True
    while improved:
        improved = False
        for i in range(len(order)):
            for j in range(i + 1, len(order)):
                order[i], order[j] = order[j], order[i]
                swapped_cost = cost(tuple(order))
                if swapped_cost < best_cost:
                    best_cost = swapped_cost
                    improved = True
                else:
                    order[i], order[j] = order[j], order[i]
    return tuple(order)


def _row_net_span(
    ordered: tuple[BoardComponent, ...],
    nets: tuple[BoardNet, ...],
    power_net_names: frozenset[str] = frozenset(),
) -> float:
    positions = {
        component.reference: anchor_x
        for component, anchor_x in _anchor_row(ordered)
    }
    total = 0.0
    for net in nets:
        xs = [positions[reference] for reference, _ in net.nodes if reference in positions]
        if len(xs) > 1:
            weight = (
                POWER_NET_SPAN_WEIGHT
                if is_power_net(net.name, power_net_names)
                else 1.0
            )
            total += (max(xs) - min(xs)) * weight
    return total


def _route_channel(
    netlist: BoardNetlist,
    placements: tuple[tuple[BoardComponent, float], ...],
    *,
    parts_row_y: float = MIN_PARTS_ROW_Y_MM,
    power_net_names: frozenset[str] = frozenset(),
    sensitive_net_names: frozenset[str] = frozenset(),
) -> tuple[tuple[TrackSegment, ...], tuple[ViaSpec, ...], float]:
    anchor_by_reference = {
        component.reference: (anchor_x, FOOTPRINT_LIBRARY[component.footprint])
        for component, anchor_x in placements
    }
    segments: list[TrackSegment] = []
    vias: list[ViaSpec] = []
    lane_index = 0
    lane_bottom_y = parts_row_y + LANE_START_OFFSET_MM
    # Sensitive (high impedance) nets take the deepest lanes, maximising the
    # clearance between them and component bodies such as inductors.
    routed_nets = (
        *(net for net in netlist.nets if not net_name_in(net.name, sensitive_net_names)),
        *(net for net in netlist.nets if net_name_in(net.name, sensitive_net_names)),
    )
    for net in routed_nets:
        power = is_power_net(net.name, power_net_names)
        track_width = POWER_TRACK_WIDTH_MM if power else SIGNAL_TRACK_WIDTH_MM
        via_size = POWER_VIA_SIZE_MM if power else SIGNAL_VIA_SIZE_MM
        via_drill = POWER_VIA_DRILL_MM if power else SIGNAL_VIA_DRILL_MM

        # One drop per distinct pad column; when several same-net pads share a
        # column (for example a TO-263 tab over its GND pin), the drop from the
        # topmost pad passes through the others and connects them.
        pads_by_column: dict[float, float] = {}
        for reference, pin in net.nodes:
            anchor_x, spec = anchor_by_reference[reference]
            try:
                matching_pads = spec.pads_named(pin)
            except KeyError as exc:
                raise BoardGenerationError(
                    f"Footprint for {reference} has no pad named {pin!r}."
                ) from exc
            for pad in matching_pads:
                pad_x = round(anchor_x + pad.x_mm, 6)
                pad_y = parts_row_y + pad.y_mm
                if pad_x not in pads_by_column or pad_y < pads_by_column[pad_x]:
                    pads_by_column[pad_x] = pad_y
        if len(pads_by_column) < 2:
            continue
        lane_y = parts_row_y + LANE_START_OFFSET_MM + lane_index * LANE_PITCH_MM
        lane_bottom_y = max(lane_bottom_y, lane_y)
        lane_index += 1
        for pad_x, pad_y in sorted(pads_by_column.items()):
            segments.append(
                TrackSegment(
                    x1=pad_x,
                    y1=pad_y,
                    x2=pad_x,
                    y2=lane_y,
                    layer="F.Cu",
                    net_name=net.name,
                    width_mm=track_width,
                )
            )
            vias.append(
                ViaSpec(
                    x=pad_x,
                    y=lane_y,
                    net_name=net.name,
                    size_mm=via_size,
                    drill_mm=via_drill,
                )
            )
        xs = sorted(pads_by_column)
        segments.append(
            TrackSegment(
                x1=xs[0],
                y1=lane_y,
                x2=xs[-1],
                y2=lane_y,
                layer="B.Cu",
                net_name=net.name,
                width_mm=track_width,
            )
        )
    return tuple(segments), tuple(vias), lane_bottom_y


def _segment(segment: TrackSegment, net_numbers: dict[str, int]) -> str:
    origin = BOARD_SHEET_ORIGIN_MM
    return (
        f"  (segment (start {_mm(segment.x1 + origin)} {_mm(segment.y1 + origin)}) "
        f"(end {_mm(segment.x2 + origin)} {_mm(segment.y2 + origin)}) "
        f'(width {_mm(segment.width_mm)}) (layer "{segment.layer}") '
        f"(net {net_numbers[segment.net_name]}) (uuid {uuid4()}))"
    )


def _via(via: ViaSpec, net_numbers: dict[str, int]) -> str:
    origin = BOARD_SHEET_ORIGIN_MM
    return (
        f"  (via (at {_mm(via.x + origin)} {_mm(via.y + origin)}) (size {_mm(via.size_mm)}) "
        f'(drill {_mm(via.drill_mm)}) (layers "F.Cu" "B.Cu") '
        f"(net {net_numbers[via.net_name]}) (uuid {uuid4()}))"
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
    *,
    anchor_y: float = MIN_PARTS_ROW_Y_MM,
    rotation: float = 0.0,
) -> str:
    spec = FOOTPRINT_LIBRARY[component.footprint]
    center_x = (spec.x_min + spec.x_max) / 2
    rotation_clause = f" {_mm(rotation)}" if rotation else ""
    at_clause = (
        f"{_mm(anchor_x + BOARD_SHEET_ORIGIN_MM)} "
        f"{_mm(anchor_y + BOARD_SHEET_ORIGIN_MM)}{rotation_clause}"
    )
    parts: list[str] = [
        f"""  (footprint {_q(component.footprint)}
    (layer "F.Cu")
    (uuid {uuid4()})
    (at {at_clause})
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
    for mark in spec.silk_marks:
        if isinstance(mark, SilkLine):
            parts.append(
                f"""    (fp_line
      (start {_mm(mark.x1)} {_mm(mark.y1)})
      (end {_mm(mark.x2)} {_mm(mark.y2)})
      (stroke (width 0.15) (type solid))
      (layer "F.SilkS")
      (uuid {uuid4()})
    )"""
            )
        else:
            # Counter-rotate mark text so "+" / "-" stay upright on rotated
            # footprints (KiCad adds the footprint angle to text angles).
            parts.append(
                f"""    (fp_text user {_q(mark.text)}
      (at {_mm(mark.x)} {_mm(mark.y)} {_mm((360 - rotation) % 360)})
      (layer "F.SilkS")
      (uuid {uuid4()})
      (effects
        (font
          (size 1 1)
          (thickness 0.15)
        )
      )
    )"""
            )
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
