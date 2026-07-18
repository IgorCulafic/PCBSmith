from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import permutations
from pathlib import Path

from pcbsmith.kicad.board_mask import (
    mask_aperture_render_identity,
    render_board_mask_aperture,
)
from pcbsmith.kicad.board_region import BoardCutoutPolygon, validate_cutouts
from pcbsmith.kicad.cli import (
    KiCadInstall,
    KiCadProcessResult,
    find_kicad_cli,
    run_kicad_process,
)
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.library import (
    FootprintLibraryError,
    FootprintSpec,
    PadSpec,
    QuotedString,
    SilkLine,
    SilkText,
    SList,
    build_footprint_library,
    load_footprint,
    parse_sexpr,
    render_embedded_footprint,
    rotate_offset,
    serialize_sexpr,
)
from pcbsmith.mask_geometry import (
    MaskAperture,
    ViaMaskIntent,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile

__all__ = [
    "PadSpec",
    "FootprintSpec",
    "canonical_kicad_netlist_xml_text",
    "SilkLine",
    "SilkText",
    "rotate_offset",
    "FOOTPRINT_LIBRARY",
    "BoardGenerationError",
    "BoardComponent",
    "BoardNet",
    "BoardNetlist",
    "TrackSegment",
    "ViaSpec",
    "BoardLayout",
    "BoardCutoutPolygon",
    "placement_y",
    "placement_rotation",
    "rotated_bounds",
    "net_name_in",
    "is_power_net",
    "export_kicad_netlist_xml",
    "parse_board_netlist",
    "generate_board",
    "render_board",
    "render_board_from_layout",
    "render_board_previews",
    "compute_board_layout",
]

KICAD_BOARD_VERSION = 20241229
SIGNAL_TRACK_WIDTH_MM = DEFAULT_PCB_RULE_PROFILE.geometry.default_signal_trace_width_mm
POWER_TRACK_WIDTH_MM = DEFAULT_PCB_RULE_PROFILE.geometry.default_power_trace_width_mm
SIGNAL_VIA_SIZE_MM = DEFAULT_PCB_RULE_PROFILE.geometry.routing_via_diameter_mm
SIGNAL_VIA_DRILL_MM = DEFAULT_PCB_RULE_PROFILE.geometry.routing_via_drill_mm
POWER_VIA_SIZE_MM = DEFAULT_PCB_RULE_PROFILE.geometry.power_via_diameter_mm
POWER_VIA_DRILL_MM = DEFAULT_PCB_RULE_PROFILE.geometry.power_via_drill_mm
MIN_PARTS_ROW_Y_MM = 4.5
PARTS_ROW_TOP_MARGIN_MM = 3.0
LANE_START_OFFSET_MM = 9.5
LANE_PITCH_MM = 1.6
PART_GAP_MM = 2.5
BOARD_MARGIN_MM = 3.0
CONNECTOR_EDGE_PAD_OFFSET_MM = 2.0
CONNECTOR_ESCAPE_PITCH_MM = 1.9
SIDE_ESCAPE_PITCH_MM = 0.7
FANOUT_SPREAD_PITCH_MM = 1.0
FANOUT_JOG_CLEAR_MM = 0.45
FANOUT_JOG_PITCH_MM = 0.55
SIDE_ESCAPE_START_MM = 0.7
TOP_LANE_GAP_MM = 2.0
TOP_CHANNEL_FLOOR_MM = 8.3  # below the mounting-hole band
PAD_SIDE_EPSILON_MM = 0.01
BOARD_SHEET_ORIGIN_MM = 20.0
EDGE_STROKE_MM = 0.1
MAX_EXHAUSTIVE_ORDER_PARTS = 8


class BoardGenerationError(RuntimeError):
    pass


FOOTPRINT_LIBRARY: dict[str, FootprintSpec] = build_footprint_library()

# Official KiCad footprints are drawn in their datasheet orientation; the row
# layout needs pins spread along x facing the routing channel below, so some
# packages take a default rotation (KiCad degrees, CCW on screen).
MOUNTING_HOLE_FOOTPRINT = "MountingHole:MountingHole_3.2mm_M3"
MOUNTING_HOLE_INSET_MM = 4.0
# With corner holes the parts row moves below the top hole band and the
# board gains a bottom band below the routing lanes (rule 5.1).
MOUNTING_HOLE_ROW_MIN_Y_MM = 10.0
MOUNTING_HOLE_BAND_MM = 8.0
MOUNTING_HOLE_WIDTH_EXTRA_MM = 3.0


def mounting_hole_placements(
    board_width: float, board_height: float
) -> tuple[tuple[BoardComponent, float, float], ...]:
    corners = (
        (MOUNTING_HOLE_INSET_MM, MOUNTING_HOLE_INSET_MM),
        (board_width - MOUNTING_HOLE_INSET_MM, MOUNTING_HOLE_INSET_MM),
        (MOUNTING_HOLE_INSET_MM, board_height - MOUNTING_HOLE_INSET_MM),
        (board_width - MOUNTING_HOLE_INSET_MM, board_height - MOUNTING_HOLE_INSET_MM),
    )
    return tuple(
        (
            BoardComponent(
                reference=f"H{index}",
                value="M3",
                footprint=MOUNTING_HOLE_FOOTPRINT,
                uuid_path=stable_kicad_uuid(
                    "board-component-path",
                    "mounting-hole",
                    f"H{index}",
                ),
            ),
            x,
            y,
        )
        for index, (x, y) in enumerate(corners, start=1)
    )


ROW_DEFAULT_ROTATIONS: dict[str, float] = {
    # TO-263-5 is drawn pins-left; rotation 90 turns pins 1-5 to face down
    # (left to right) into the routing channel, with the tab above the row.
    "Package_TO_SOT_SMD:TO-263-5_TabPin3": 90.0,
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
    # Inherit serializes as KiCad "none" so the editor, downstream readers,
    # and semantic identity all see the same process-default intent.
    front_mask: ViaMaskIntent = ViaMaskIntent.INHERIT
    back_mask: ViaMaskIntent = ViaMaskIntent.INHERIT


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
    # Copper zones (net_name, layer, rect in board mm) appended by layouts
    # that pour planes; rendered as filled zones.
    zones: tuple[tuple[str, str, tuple[float, float, float, float]], ...] = ()
    # Custom board outline polygon (board mm); None keeps the rectangle.
    outline: tuple[tuple[float, float], ...] | None = None
    # Raw board-level graphic items (silkscreen art, text), pre-rendered.
    graphics: tuple[str, ...] = ()
    # References of footprints mounted on the BACK of the board.
    part_flip: tuple[str, ...] = ()
    # References whose silkscreen reference text is hidden (art faces).
    hide_references: tuple[str, ...] = ()
    # Per-reference label repositioning: footprint-local (x, y, total
    # angle) for the Reference property, for dense layouts where the
    # default spot lands on a neighbour.
    part_reference_at: tuple[tuple[str, tuple[float, float, float]], ...] = ()
    # Typed board-level solder-mask apertures. Raw graphics remain supported
    # as opaque KiCad strings and are deliberately not interpreted.
    mask_apertures: tuple[MaskAperture, ...] = ()
    # Exact internal board voids rendered as closed Edge.Cuts polygons.
    cutouts: tuple[BoardCutoutPolygon, ...] = ()

    def __post_init__(self) -> None:
        if not self.cutouts:
            return
        outer = self.outline or (
            (0.0, 0.0),
            (self.width_mm, 0.0),
            (self.width_mm, self.height_mm),
            (0.0, self.height_mm),
        )
        object.__setattr__(self, "cutouts", validate_cutouts(outer, self.cutouts))


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


def rotated_bounds(spec: FootprintSpec, rotation: float) -> tuple[float, float, float, float]:
    """Footprint bounds (x_min, x_max, y_min, y_max) after rotation."""
    corners = (
        rotate_offset(spec.x_min, spec.y_min, rotation),
        rotate_offset(spec.x_min, spec.y_max, rotation),
        rotate_offset(spec.x_max, spec.y_min, rotation),
        rotate_offset(spec.x_max, spec.y_max, rotation),
    )
    xs = [x for x, _ in corners]
    ys = [y for _, y in corners]
    return (min(xs), max(xs), min(ys), max(ys))


def export_kicad_netlist_xml(
    schematic_file: Path,
    *,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> Path:
    netlist_file = schematic_file.parent / ".pcbsmith" / "kicad" / f"{schematic_file.stem}.net.xml"
    install = finder()
    if install is None:
        raise BoardGenerationError("KiCad CLI was not found; the board netlist export was not run.")
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


def canonical_kicad_netlist_xml_text(xml_text: str) -> str:
    """Canonicalize KiCad netlist XML without host paths or wall-clock time.

    The root project and hierarchical sheet identities remain as file names;
    only their machine-specific directory prefixes are removed.
    """

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as error:
        raise BoardGenerationError(f"KiCad netlist XML could not be parsed: {error}") from error

    design = root.find("design")
    if design is not None:
        source = design.find("source")
        if source is not None and source.text:
            source.text = Path(source.text.replace("\\", "/")).name
        date = design.find("date")
        if date is not None:
            design.remove(date)
    for prop in root.iter("property"):
        if prop.get("name") == "Sheetfile" and prop.get("value"):
            prop.set("value", Path(prop.get("value", "").replace("\\", "/")).name)
    for element in root.iter():
        if element.text is not None and not element.text.strip():
            element.text = None
        if element.tail is not None and not element.tail.strip():
            element.tail = None
    ET.indent(root, space="  ")
    body = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body + "\n"


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
                uuid_path=_element_text(comp, "tstamps")
                or stable_kicad_uuid(
                    "board-component-path",
                    "netlist-fallback",
                    reference,
                ),
                fields=tuple(fields),
            )
        )
    if not components:
        raise BoardGenerationError("KiCad netlist contained no board components with footprints.")

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
    ground_pour: bool = False,
    thermal_pour_references: tuple[str, ...] = (),
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: Callable[[Sequence[str]], KiCadProcessResult] | None = None,
) -> BoardNetlist:
    netlist_file = export_kicad_netlist_xml(schematic_file, finder=finder, runner=runner)
    netlist = parse_board_netlist(netlist_file.read_text(encoding="utf-8"))
    layout = compute_board_layout(
        netlist,
        power_net_names,
        sensitive_net_names,
        ground_pour=ground_pour,
        thermal_pour_references=thermal_pour_references,
        profile=profile,
    )
    board_file.write_text(
        render_board_from_layout(netlist, layout, profile=profile), encoding="utf-8"
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


ZONE_EDGE_INSET_MM = 0.75
THERMAL_POUR_MARGIN_MM = 2.5


def compute_board_layout(
    netlist: BoardNetlist,
    power_net_names: frozenset[str] = frozenset(),
    sensitive_net_names: frozenset[str] = frozenset(),
    *,
    ground_pour: bool = False,
    thermal_pour_references: tuple[str, ...] = (),
    mounting_holes: bool = True,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
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

    rotations = {
        component.reference: _row_rotation(component)
        for component in netlist.components
        if _row_rotation(component)
    }
    placements = _place_components(netlist.components, netlist.nets, power_net_names)
    top_extent = max(-_bounds_for(component, rotations)[2] for component, _ in placements)
    parts_row_y = max(
        MOUNTING_HOLE_ROW_MIN_Y_MM if mounting_holes else MIN_PARTS_ROW_Y_MM,
        PARTS_ROW_TOP_MARGIN_MM + top_extent,
    )
    north_nets = _north_net_count(netlist, placements, rotations)
    if north_nets:
        # Multi-side packages route their north pads into a mirrored channel
        # above the parts row; the row moves down to make space for it.
        floor = TOP_CHANNEL_FLOOR_MM if mounting_holes else 1.5
        parts_row_y = max(
            parts_row_y,
            floor + 0.8 + TOP_LANE_GAP_MM + (north_nets - 1) * LANE_PITCH_MM + top_extent,
        )
    segments, vias, lane_bottom_y = _route_channel(
        netlist,
        placements,
        rotations,
        parts_row_y=parts_row_y,
        power_net_names=power_net_names,
        sensitive_net_names=sensitive_net_names,
        profile=profile,
    )
    last_component, last_anchor = placements[-1]
    last_spec = FOOTPRINT_LIBRARY[last_component.footprint]
    last_bounds = _bounds_for(last_component, rotations)
    if last_spec.is_connector and len(placements) > 1:
        # A trailing connector hugs the right board edge, mirroring the lead.
        last_rotation = rotations.get(last_component.reference, 0.0)
        pad_xs = [rotate_offset(pad.x_mm, pad.y_mm, last_rotation)[0] for pad in last_spec.pads]
        board_width = last_anchor + max(pad_xs) + CONNECTOR_EDGE_PAD_OFFSET_MM
        if mounting_holes:
            # Push the right edge out so the corner holes clear the last
            # interior part's courtyard (live DRC caught H2 vs COUT).
            board_width += MOUNTING_HOLE_WIDTH_EXTRA_MM
    else:
        board_width = last_anchor + last_bounds[1] + BOARD_MARGIN_MM
        if mounting_holes:
            board_width += MOUNTING_HOLE_WIDTH_EXTRA_MM
    board_width = max(
        board_width,
        max(
            anchor_x
            + _bounds_for(component, rotations)[1]
            + _escape_reserve(
                FOOTPRINT_LIBRARY[component.footprint],
                rotations.get(component.reference, 0.0),
            )[1]
            for component, anchor_x in placements
        ),
    )
    board_height = lane_bottom_y + (MOUNTING_HOLE_BAND_MM if mounting_holes else BOARD_MARGIN_MM)
    part_y: list[tuple[str, float]] = []
    if mounting_holes:
        holes = mounting_hole_placements(board_width, board_height)
        placements = (*placements, *((component, x) for component, x, _ in holes))
        part_y.extend((component.reference, y) for component, _, y in holes)
    zones = _pour_zones(
        netlist,
        placements,
        rotations,
        parts_row_y=parts_row_y,
        board_width=board_width,
        board_height=board_height,
        ground_pour=ground_pour,
        thermal_pour_references=thermal_pour_references,
    )
    return BoardLayout(
        placements=placements,
        segments=segments,
        vias=vias,
        width_mm=board_width,
        height_mm=board_height,
        parts_row_y_mm=parts_row_y,
        part_y_mm=tuple(part_y),
        part_rotation=tuple(sorted(rotations.items())),
        zones=zones,
    )


def _pour_zones(
    netlist: BoardNetlist,
    placements: tuple[tuple[BoardComponent, float], ...],
    rotations: dict[str, float],
    *,
    parts_row_y: float,
    board_width: float,
    board_height: float,
    ground_pour: bool,
    thermal_pour_references: tuple[str, ...],
) -> tuple[tuple[str, str, tuple[float, float, float, float]], ...]:
    if not ground_pour and not thermal_pour_references:
        return ()
    ground_nets = [net.name for net in netlist.nets if net_name_in(net.name, frozenset({"GND"}))]
    if not ground_nets:
        raise BoardGenerationError("A ground pour was requested but the netlist has no GND net.")
    ground = ground_nets[0]
    zones: list[tuple[str, str, tuple[float, float, float, float]]] = []
    if ground_pour:
        # Full-board ground plane on the back copper (rule 3.2).
        zones.append(
            (
                ground,
                "B.Cu",
                (
                    ZONE_EDGE_INSET_MM,
                    ZONE_EDGE_INSET_MM,
                    board_width - ZONE_EDGE_INSET_MM,
                    board_height - ZONE_EDGE_INSET_MM,
                ),
            )
        )
    anchors = {component.reference: anchor for component, anchor in placements}
    specs = {component.reference: component.footprint for component, _ in placements}
    for reference in thermal_pour_references:
        if reference not in anchors:
            raise BoardGenerationError(
                f"Thermal pour requested for {reference}, which is not placed."
            )
        bounds = rotated_bounds(FOOTPRINT_LIBRARY[specs[reference]], rotations.get(reference, 0.0))
        anchor_x = anchors[reference]
        # Dissipation copper around the power tab (rule 3.5).
        zones.append(
            (
                ground,
                "F.Cu",
                (
                    max(
                        ZONE_EDGE_INSET_MM,
                        anchor_x + bounds[0] - THERMAL_POUR_MARGIN_MM,
                    ),
                    max(
                        ZONE_EDGE_INSET_MM,
                        parts_row_y + bounds[2] - THERMAL_POUR_MARGIN_MM,
                    ),
                    min(
                        board_width - ZONE_EDGE_INSET_MM,
                        anchor_x + bounds[1] + THERMAL_POUR_MARGIN_MM,
                    ),
                    min(
                        board_height - ZONE_EDGE_INSET_MM,
                        parts_row_y + bounds[3] + THERMAL_POUR_MARGIN_MM,
                    ),
                ),
            )
        )
    return tuple(zones)


def _row_rotation(component: BoardComponent) -> float:
    return ROW_DEFAULT_ROTATIONS.get(component.footprint, 0.0)


def _bounds_for(
    component: BoardComponent,
    rotations: dict[str, float],
) -> tuple[float, float, float, float]:
    spec = FOOTPRINT_LIBRARY[component.footprint]
    return rotated_bounds(spec, rotations.get(component.reference, 0.0))


def net_name_in(net_name: str, names: frozenset[str]) -> bool:
    return net_name.lstrip("/").upper() in {name.upper() for name in names}


def is_power_net(net_name: str, power_net_names: frozenset[str]) -> bool:
    return net_name_in(net_name, power_net_names)


def render_board(
    netlist: BoardNetlist,
    power_net_names: frozenset[str] = frozenset(),
    sensitive_net_names: frozenset[str] = frozenset(),
    *,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
) -> str:
    layout = compute_board_layout(netlist, power_net_names, sensitive_net_names, profile=profile)
    return render_board_from_layout(netlist, layout, profile=profile)


def render_board_from_layout(
    netlist: BoardNetlist,
    layout: BoardLayout,
    *,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
) -> str:
    net_numbers = {net.name: index for index, net in enumerate(netlist.nets, start=1)}
    pad_nets = {(reference, pin): net.name for net in netlist.nets for reference, pin in net.nodes}
    board_width = layout.width_mm
    board_height = layout.height_mm

    sections: list[str] = [_render_header(profile)]
    footprint_occurrences: dict[tuple[str, str], int] = {}
    for component, anchor_x in layout.placements:
        spec = FOOTPRINT_LIBRARY[component.footprint]
        rotation = placement_rotation(layout, component.reference)
        bindings: dict[str, tuple[int, str]] = {}
        for pad in spec.pads:
            net_name = pad_nets.get((component.reference, pad.name))
            if net_name is not None:
                bindings[pad.name] = (net_numbers[net_name], net_name)
        # Text angles in board files are TOTAL angles, so 0 keeps the
        # marks upright regardless of the footprint rotation.
        marks = tuple(
            (mark.text, mark.x, mark.y, 0.0)
            for mark in spec.silk_marks
            if isinstance(mark, SilkText)
        )
        _bind_unnamed_pads(spec, bindings)
        footprint_identity = (component.uuid_path.strip("/"), component.reference)
        footprint_occurrence = footprint_occurrences.get(footprint_identity, 0)
        footprint_occurrences[footprint_identity] = footprint_occurrence + 1
        try:
            sections.append(
                render_embedded_footprint(
                    load_footprint(component.footprint),
                    reference=component.reference,
                    value=component.value,
                    x_mm=anchor_x + BOARD_SHEET_ORIGIN_MM,
                    y_mm=placement_y(layout, component.reference) + BOARD_SHEET_ORIGIN_MM,
                    rotation=rotation,
                    uuid_path=component.uuid_path,
                    pad_nets=bindings,
                    extra_fields=component.fields,
                    extra_silk_texts=marks,
                    force_board_only=spec.board_only,
                    flip=component.reference in layout.part_flip,
                    hide_reference=component.reference in layout.hide_references,
                    reference_at=dict(layout.part_reference_at).get(component.reference),
                    identity_occurrence=footprint_occurrence,
                )
            )
        except FootprintLibraryError as exc:
            raise BoardGenerationError(str(exc)) from exc
    segment_occurrences: dict[tuple[str, ...], int] = {}
    for segment in layout.segments:
        identity = _segment_identity(segment)
        occurrence = _take_occurrence(identity, segment_occurrences)
        sections.append(_segment(segment, net_numbers, occurrence))
    via_occurrences: dict[tuple[str, ...], int] = {}
    for via in layout.vias:
        identity = _via_identity(via)
        occurrence = _take_occurrence(identity, via_occurrences)
        sections.append(_via(via, net_numbers, occurrence))
    zone_occurrences: dict[tuple[str, ...], int] = {}
    for zone_index, (zone_net, zone_layer, zone_rect) in enumerate(layout.zones):
        identity = _zone_identity(zone_net, zone_layer, zone_rect)
        occurrence = _take_occurrence(identity, zone_occurrences)
        sections.append(
            _zone(
                zone_net,
                zone_layer,
                zone_rect,
                net_numbers,
                zone_index,
                occurrence,
            )
        )
    origin = BOARD_SHEET_ORIGIN_MM
    mask_occurrences: dict[tuple[str, ...], int] = {}
    graphic_occurrences: dict[tuple[str, str], int] = {}
    for aperture in layout.mask_apertures:
        identity = mask_aperture_render_identity(aperture)
        occurrence = _take_occurrence(identity, mask_occurrences)
        # Typed apertures cross the same final serialization boundary as the
        # legacy raw graphic they replace.  Besides preserving byte parity,
        # sharing this normalizer and occurrence ledger prevents a typed
        # aperture and an equivalent raw graphic from receiving the same
        # rendered-object identity.
        sections.append(
            _render_raw_board_graphic(
                render_board_mask_aperture(aperture, origin, occurrence=occurrence),
                graphic_occurrences,
            )
        )
    for graphic in layout.graphics:
        sections.append(_render_raw_board_graphic(graphic, graphic_occurrences))
    for cutout in layout.cutouts:
        points = "\n          ".join(
            f"(xy {_mm(x + origin)} {_mm(y + origin)})" for x, y in cutout.points
        )
        sections.append(
            f"""  (gr_poly
    (pts
          {points}
    )
    (stroke (width {_mm(EDGE_STROKE_MM)}) (type default))
    (fill none)
    (layer "Edge.Cuts")
    (uuid {stable_kicad_uuid("board-cutout", cutout.semantic_fingerprint())})
  )"""
        )
    if layout.outline is not None:
        points = "\n          ".join(
            f"(xy {_mm(x + origin)} {_mm(y + origin)})" for x, y in layout.outline
        )
        sections.append(
            f"""  (gr_poly
    (pts
          {points}
    )
    (stroke (width {_mm(EDGE_STROKE_MM)}) (type default))
    (fill none)
    (layer "Edge.Cuts")
    (uuid {stable_kicad_uuid("board-outline", "polygon")})
  )"""
        )
    else:
        sections.append(
            f"""  (gr_rect
    (start {_mm(origin)} {_mm(origin)})
    (end {_mm(origin + board_width)} {_mm(origin + board_height)})
    (stroke (width {_mm(EDGE_STROKE_MM)}) (type default))
    (fill none)
    (layer "Edge.Cuts")
    (uuid {stable_kicad_uuid("board-outline", "rectangle")})
  )"""
        )
    return "\n".join(("\n".join(sections), ")", ""))


def _bind_unnamed_pads(
    spec: FootprintSpec,
    bindings: dict[str, tuple[int, str]],
) -> None:
    """Give unnamed pads (thermal-tab paste splits) the net of the named pad
    they overlap, so DRC does not flag mask bridges to a no-net pad."""
    unnamed = [pad for pad in spec.pads if not pad.name]
    if not unnamed or "" in bindings:
        return
    for pad in unnamed:
        for named in spec.pads:
            if not named.name or named.name not in bindings:
                continue
            if (
                abs(pad.x_mm - named.x_mm) * 2 < pad.width_mm + named.width_mm
                and abs(pad.y_mm - named.y_mm) * 2 < pad.height_mm + named.height_mm
            ):
                bindings[""] = bindings[named.name]
                return


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
        rotation = _row_rotation(component)
        x_min, x_max, _, _ = rotated_bounds(spec, rotation)
        left_reserve, right_reserve = _escape_reserve(spec, rotation)
        if spec.is_connector:
            stacked = max(len(column) for column in _connector_pad_columns(spec, rotation).values())
            connector_reserve = (
                CONNECTOR_ESCAPE_PITCH_MM * (stacked - 1) + 0.6 if stacked > 1 else 0.0
            )
            if index == 0:
                right_reserve = max(right_reserve, connector_reserve)
            else:
                left_reserve = max(left_reserve, connector_reserve)
        if index == 0 and spec.is_connector:
            # The leading connector hugs the board corner so off-board wiring
            # lands at the edge, matching hand-layout convention.
            first_pad = rotate_offset(spec.pads[0].x_mm, spec.pads[0].y_mm, rotation)
            anchor_x = CONNECTOR_EDGE_PAD_OFFSET_MM - first_pad[0]
        else:
            anchor_x = max(cursor, BOARD_MARGIN_MM) - x_min + left_reserve
        placements.append((component, anchor_x))
        cursor = anchor_x + x_max + right_reserve + PART_GAP_MM
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
        component for component in components if FOOTPRINT_LIBRARY[component.footprint].is_connector
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
    positions = {component.reference: anchor_x for component, anchor_x in _anchor_row(ordered)}
    total = 0.0
    for net in nets:
        xs = [positions[reference] for reference, _ in net.nodes if reference in positions]
        if len(xs) > 1:
            weight = POWER_NET_SPAN_WEIGHT if is_power_net(net.name, power_net_names) else 1.0
            total += (max(xs) - min(xs)) * weight
    return total


def _pad_side(dx: float, dy: float) -> str:
    """Which footprint side a pad sits on, in rotated offsets (y down)."""
    if abs(dy) >= abs(dx) and dy < -PAD_SIDE_EPSILON_MM:
        return "north"
    if abs(dx) > abs(dy) and dx < -PAD_SIDE_EPSILON_MM:
        return "west"
    if abs(dx) > abs(dy) and dx > PAD_SIDE_EPSILON_MM:
        return "east"
    return "south"


def _side_escapes(spec: FootprintSpec, rotation: float) -> dict[str, tuple[str, float, int]]:
    """East/west pads of a multi-side package (QFN) share an x column, so
    each detours outward into its own drop column: pad name -> (side, offset
    from the anchor). Connectors keep their dedicated escape scheme."""
    if spec.is_connector:
        return {}
    all_sides: set[str] = set()
    sides: dict[str, list[tuple[str, float]]] = {"west": [], "east": []}
    for pad in spec.pads:
        if not pad.name:
            continue
        dx, dy = rotate_offset(pad.x_mm, pad.y_mm, rotation)
        side = _pad_side(dx, dy)
        all_sides.add(side)
        if side in sides:
            sides[side].append((pad.name, dy))
    if len(all_sides) < 3:
        # Two-pin parts and tabbed packages are not multi-side fanouts.
        return {}
    escapes: dict[str, tuple[str, float, int]] = {}
    bounds = rotated_bounds(spec, rotation)
    for side, pads in sides.items():
        # Bottom-most pad first: it takes the closest escape column, so the
        # longer stubs of pads above it cross only columns whose verticals
        # start below their own y (no F.Cu crossings by construction).
        pads.sort(key=lambda item: item[1], reverse=True)
        for rank, (name, _) in enumerate(pads):
            offset = SIDE_ESCAPE_START_MM + rank * SIDE_ESCAPE_PITCH_MM
            if side == "west":
                escapes[name] = (side, bounds[0] - offset, 0)
            else:
                escapes[name] = (side, bounds[1] + offset, 0)
    # North/south pads of a fine-pitch package spread onto a wider column
    # grid (45-degree jogs at the pad exit) so lane vias clear neighbouring
    # drops; without this a 0.6 mm via sits 0.5 mm from the next pin's track.
    for vertical_side in ("north", "south"):
        group = [
            (pad.name, rotate_offset(pad.x_mm, pad.y_mm, rotation)[0])
            for pad in spec.pads
            if pad.name and _pad_side(*rotate_offset(pad.x_mm, pad.y_mm, rotation)) == vertical_side
        ]
        if len(group) < 2:
            continue
        group.sort(key=lambda item: item[1])
        center = sum(dx for _, dx in group) / len(group)
        half = (len(group) - 1) / 2
        for index, (name, _dx) in enumerate(group):
            spread_x = center + (index - half) * FANOUT_SPREAD_PITCH_MM
            # Nested elbows: the outermost pad of each half takes the
            # shallowest jog; ranks increase towards the centre.
            jog_rank = round(half - abs(index - half))
            escapes[name] = (vertical_side, spread_x, jog_rank)
    return escapes


def _escape_reserve(spec: FootprintSpec, rotation: float) -> tuple[float, float]:
    """Extra row width a part needs for its side-escape drop columns."""
    escapes = _side_escapes(spec, rotation)
    bounds = rotated_bounds(spec, rotation)
    left = 0.0
    right = 0.0
    for side, escape_x, _rank in escapes.values():
        if side == "west":
            left = max(left, bounds[0] - escape_x + 0.4)
        elif side == "east":
            right = max(right, escape_x - bounds[1] + 0.4)
        else:
            left = max(left, bounds[0] - escape_x + 0.4)
            right = max(right, escape_x - bounds[1] + 0.4)
    return (left, right)


def _north_net_count(
    netlist: BoardNetlist,
    placements: tuple[tuple[BoardComponent, float], ...],
    rotations: dict[str, float],
) -> int:
    """How many nets need a top-channel lane (any pad on a north side)."""
    spec_by_reference = {
        component.reference: FOOTPRINT_LIBRARY[component.footprint] for component, _ in placements
    }
    count = 0
    for net in netlist.nets:
        for reference, pin in net.nodes:
            spec = spec_by_reference[reference]
            rotation = rotations.get(reference, 0.0)
            if not _side_escapes(spec, rotation):
                continue
            try:
                pads = spec.pads_named(pin)
            except KeyError:
                continue
            if any(
                _pad_side(*rotate_offset(pad.x_mm, pad.y_mm, rotation)) == "north" for pad in pads
            ):
                count += 1
                break
    return count


def _route_channel(
    netlist: BoardNetlist,
    placements: tuple[tuple[BoardComponent, float], ...],
    rotations: dict[str, float],
    *,
    parts_row_y: float = MIN_PARTS_ROW_Y_MM,
    power_net_names: frozenset[str] = frozenset(),
    sensitive_net_names: frozenset[str] = frozenset(),
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
) -> tuple[tuple[TrackSegment, ...], tuple[ViaSpec, ...], float]:
    anchor_by_reference = {
        component.reference: (anchor_x, FOOTPRINT_LIBRARY[component.footprint])
        for component, anchor_x in placements
    }
    escape_x = _connector_escapes(placements, rotations)
    side_escape_by_reference = {
        component.reference: _side_escapes(
            FOOTPRINT_LIBRARY[component.footprint],
            rotations.get(component.reference, 0.0),
        )
        for component, _ in placements
    }
    top_extent = max(
        -rotated_bounds(
            FOOTPRINT_LIBRARY[component.footprint],
            rotations.get(component.reference, 0.0),
        )[2]
        for component, _ in placements
    )
    top_lane_base = parts_row_y - top_extent - TOP_LANE_GAP_MM
    # The lane zone starts below the DEEPEST pad on the board; a tall
    # stacked connector (1x08 header) reaches far below the anchor row and
    # lanes must never fall inside its pad column (live DRC: via on pad 6).
    bottom_extent = max(
        rotated_bounds(
            FOOTPRINT_LIBRARY[component.footprint],
            rotations.get(component.reference, 0.0),
        )[3]
        for component, _ in placements
    )
    lane_start = max(LANE_START_OFFSET_MM, bottom_extent + TOP_LANE_GAP_MM)
    segments: list[TrackSegment] = []
    vias: list[ViaSpec] = []
    lane_index = 0
    top_lane_index = 0
    lane_bottom_y = parts_row_y + lane_start
    # Sensitive (high impedance) nets take the deepest lanes, maximising the
    # clearance between them and component bodies such as inductors.
    routed_nets = (
        *(net for net in netlist.nets if not net_name_in(net.name, sensitive_net_names)),
        *(net for net in netlist.nets if net_name_in(net.name, sensitive_net_names)),
    )
    for net in routed_nets:
        power = is_power_net(net.name, power_net_names)
        track_width = (
            profile.geometry.default_power_trace_width_mm
            if power
            else profile.geometry.default_signal_trace_width_mm
        )
        via_size = (
            profile.geometry.power_via_diameter_mm
            if power
            else profile.geometry.routing_via_diameter_mm
        )
        via_drill = (
            profile.geometry.power_via_drill_mm if power else profile.geometry.routing_via_drill_mm
        )

        # One drop per distinct pad column; when several same-net pads share a
        # column (for example a TO-263 tab over its GND pin), the drop from the
        # topmost pad passes through the others and connects them. North-side
        # pads of multi-side packages drop UP into the mirrored top channel.
        down_columns: dict[float, float] = {}
        up_columns: dict[float, float] = {}
        # Per-column drop width: columns fed through a fine-pitch fanout keep
        # the clamped width all the way to the lane (a 0.8 mm power drop's
        # round end cap grazed the neighbouring jog, live DRC).
        column_widths: dict[float, float] = {}
        for reference, pin in net.nodes:
            anchor_x, spec = anchor_by_reference[reference]
            rotation = rotations.get(reference, 0.0)
            try:
                matching_pads = spec.pads_named(pin)
            except KeyError as exc:
                raise BoardGenerationError(
                    f"Footprint for {reference} has no pad named {pin!r}."
                ) from exc
            side_escapes = side_escape_by_reference[reference]
            for pad in matching_pads:
                dx, dy = rotate_offset(pad.x_mm, pad.y_mm, rotation)
                pad_x = round(anchor_x + dx, 6)
                pad_y = parts_row_y + dy
                pad_track_width = min(track_width, min(pad.width_mm, pad.height_mm))
                stub_x = escape_x.get((reference, pin))
                side_escape = side_escapes.get(pin)
                if side_escape is not None and side_escape[0] in ("north", "south"):
                    # Fine-pitch fanout, nested elbows: straight out of the
                    # pad, a ranked horizontal jog, then the spread column.
                    spread_x = round(anchor_x + side_escape[1], 6)
                    pad_half = (
                        max(pad.width_mm, pad.height_mm) / 2
                        if abs(dy) >= abs(dx)
                        else min(pad.width_mm, pad.height_mm) / 2
                    )
                    reach = pad_half + FANOUT_JOG_CLEAR_MM + side_escape[2] * FANOUT_JOG_PITCH_MM
                    jog_y = pad_y - reach if side_escape[0] == "north" else pad_y + reach
                    segments.append(
                        TrackSegment(
                            x1=pad_x,
                            y1=pad_y,
                            x2=pad_x,
                            y2=jog_y,
                            layer="F.Cu",
                            net_name=net.name,
                            width_mm=pad_track_width,
                        )
                    )
                    if abs(spread_x - pad_x) > PAD_SIDE_EPSILON_MM:
                        segments.append(
                            TrackSegment(
                                x1=pad_x,
                                y1=jog_y,
                                x2=spread_x,
                                y2=jog_y,
                                layer="F.Cu",
                                net_name=net.name,
                                width_mm=pad_track_width,
                            )
                        )
                    column_widths[spread_x] = min(
                        column_widths.get(spread_x, track_width), pad_track_width
                    )
                    if side_escape[0] == "north":
                        if spread_x not in up_columns or jog_y > up_columns[spread_x]:
                            up_columns[spread_x] = jog_y
                    elif spread_x not in down_columns or jog_y < down_columns[spread_x]:
                        down_columns[spread_x] = jog_y
                    continue
                if stub_x is None and side_escape is not None:
                    stub_x = anchor_x + side_escape[1]
                if stub_x is not None:
                    # Escape stub: the pad leaves its shared column
                    # horizontally before dropping, so the drop does not
                    # pass through a neighbouring pad.
                    segments.append(
                        TrackSegment(
                            x1=pad_x,
                            y1=pad_y,
                            x2=stub_x,
                            y2=pad_y,
                            layer="F.Cu",
                            net_name=net.name,
                            width_mm=pad_track_width,
                        )
                    )
                    pad_x = round(stub_x, 6)
                    column_widths[pad_x] = min(
                        column_widths.get(pad_x, track_width), pad_track_width
                    )
                    if pad_x not in down_columns or pad_y < down_columns[pad_x]:
                        down_columns[pad_x] = pad_y
                    continue
                if side_escapes and side_escape is None and _pad_side(dx, dy) == "north":
                    if pad_x not in up_columns or pad_y > up_columns[pad_x]:
                        up_columns[pad_x] = pad_y
                elif pad_x not in down_columns or pad_y < down_columns[pad_x]:
                    down_columns[pad_x] = pad_y
        if len(down_columns) + len(up_columns) < 2:
            continue

        # A single bottom pad on a net that also has a top lane needs no
        # bottom lane of its own: the cross-channel join carries it (a lone
        # via on an unused lane reports as dangling).
        if down_columns and (len(down_columns) >= 2 or not up_columns):
            lane_y = parts_row_y + lane_start + lane_index * LANE_PITCH_MM
            lane_bottom_y = max(lane_bottom_y, lane_y)
            lane_index += 1
            for pad_x, pad_y in sorted(down_columns.items()):
                segments.append(
                    TrackSegment(
                        x1=pad_x,
                        y1=pad_y,
                        x2=pad_x,
                        y2=lane_y,
                        layer="F.Cu",
                        net_name=net.name,
                        width_mm=column_widths.get(pad_x, track_width),
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
            xs = sorted(down_columns)
            if len(xs) > 1:
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

        if up_columns:
            top_lane_y = top_lane_base - top_lane_index * LANE_PITCH_MM
            top_lane_index += 1
            top_xs = list(up_columns)
            for pad_x, pad_y in sorted(up_columns.items()):
                segments.append(
                    TrackSegment(
                        x1=pad_x,
                        y1=pad_y,
                        x2=pad_x,
                        y2=top_lane_y,
                        layer="F.Cu",
                        net_name=net.name,
                        width_mm=column_widths.get(
                            pad_x,
                            min(
                                track_width,
                                profile.geometry.default_signal_trace_width_mm,
                            ),
                        ),
                    )
                )
                vias.append(
                    ViaSpec(
                        x=pad_x,
                        y=top_lane_y,
                        net_name=net.name,
                        size_mm=via_size,
                        drill_mm=via_drill,
                    )
                )
            if down_columns:
                # Cross-channel join: extend one bottom drop upward through
                # its own pad to the top lane. Pick the column whose drop
                # starts HIGHEST (a row-level pad): joining from a deep pad,
                # such as a stacked connector pin, would cross every pad and
                # stub above it (live DRC caught SDA slicing through P1).
                join_x = min(down_columns, key=lambda x: (down_columns[x], x))
                segments.append(
                    TrackSegment(
                        x1=join_x,
                        y1=down_columns[join_x],
                        x2=join_x,
                        y2=top_lane_y,
                        layer="F.Cu",
                        net_name=net.name,
                        width_mm=track_width,
                    )
                )
                vias.append(
                    ViaSpec(
                        x=join_x,
                        y=top_lane_y,
                        net_name=net.name,
                        size_mm=via_size,
                        drill_mm=via_drill,
                    )
                )
                top_xs.append(join_x)
            top_xs.sort()
            if len(top_xs) > 1:
                segments.append(
                    TrackSegment(
                        x1=top_xs[0],
                        y1=top_lane_y,
                        x2=top_xs[-1],
                        y2=top_lane_y,
                        layer="B.Cu",
                        net_name=net.name,
                        width_mm=track_width,
                    )
                )
    return tuple(segments), tuple(vias), lane_bottom_y


def _connector_pad_columns(
    spec: FootprintSpec, rotation: float
) -> dict[float, list[tuple[PadSpec, float]]]:
    columns: dict[float, list[tuple[PadSpec, float]]] = {}
    for pad in spec.pads:
        dx, dy = rotate_offset(pad.x_mm, pad.y_mm, rotation)
        columns.setdefault(round(dx, 6), []).append((pad, dy))
    return columns


def _connector_escapes(
    placements: tuple[tuple[BoardComponent, float], ...],
    rotations: dict[str, float],
) -> dict[tuple[str, str], float]:
    """Escape drop columns for connector pads stacked along a board edge.

    The official vertical pin header stacks its pads in y, so all pads share
    one x column. The lowest pad (closest to the routing channel) drops
    straight; each pad above it detours horizontally into its own column —
    towards the board interior — before dropping past its neighbours.
    """
    escapes: dict[tuple[str, str], float] = {}
    if not placements:
        return escapes
    last_reference = placements[-1][0].reference
    for index, (component, anchor_x) in enumerate(placements):
        spec = FOOTPRINT_LIBRARY[component.footprint]
        if not spec.is_connector:
            continue
        rotation = rotations.get(component.reference, 0.0)
        columns = {
            round(anchor_x + column_x, 6): pads
            for column_x, pads in _connector_pad_columns(spec, rotation).items()
        }
        # Trailing (right-edge) connectors escape leftwards into the board.
        direction = -1.0 if (component.reference == last_reference and index > 0) else 1.0
        for column_x, pads in columns.items():
            if len(pads) < 2:
                continue
            pads.sort(key=lambda item: item[1], reverse=True)  # lowest first
            for rank, (pad, _) in enumerate(pads[1:], start=1):
                escapes[(component.reference, pad.name)] = (
                    column_x + direction * CONNECTOR_ESCAPE_PITCH_MM * rank
                )
    return escapes


def _take_occurrence(
    identity: tuple[str, ...],
    occurrences: dict[tuple[str, ...], int],
) -> int:
    occurrence = occurrences.get(identity, 0)
    occurrences[identity] = occurrence + 1
    return occurrence


def _raw_graphic_head(node: SList) -> str:
    if not node:
        raise BoardGenerationError("A raw board graphic cannot be empty.")
    head = node[0]
    if isinstance(head, QuotedString):
        return head.value
    if isinstance(head, str):
        return head
    raise BoardGenerationError("A raw board graphic has no object head.")


def _render_raw_board_graphic(
    graphic: str,
    occurrences: dict[tuple[str, str], int],
) -> str:
    """Normalize one opaque board object with a semantic, stable UUID."""
    try:
        node = parse_sexpr(graphic)
    except FootprintLibraryError as exc:
        raise BoardGenerationError(f"Malformed raw board graphic: {exc}") from exc
    head = _raw_graphic_head(node)
    node[:] = [
        child
        for child in node
        if not (
            isinstance(child, list)
            and child
            and _raw_graphic_head(child) in {"uuid", "tstamp"}
        )
    ]
    semantic = serialize_sexpr(node)
    identity = (head, semantic)
    occurrence = occurrences.get(identity, 0)
    occurrences[identity] = occurrence + 1
    node.append(
        [
            "uuid",
            QuotedString(
                stable_kicad_uuid(
                    "board-raw-graphic-v1",
                    head,
                    semantic,
                    str(occurrence),
                )
            ),
        ]
    )
    return "  " + serialize_sexpr(node, indent=1)


def _canonical_segment_endpoints(
    segment: TrackSegment,
) -> tuple[tuple[str, str], tuple[str, str]]:
    first = (_mm(segment.x1), _mm(segment.y1))
    second = (_mm(segment.x2), _mm(segment.y2))
    return (first, second) if first <= second else (second, first)


def _segment_identity(segment: TrackSegment) -> tuple[str, ...]:
    start, end = _canonical_segment_endpoints(segment)
    return (
        "segment",
        segment.net_name,
        segment.layer,
        _mm(segment.width_mm),
        *start,
        *end,
    )


def _via_identity(via: ViaSpec) -> tuple[str, ...]:
    return (
        "via",
        via.net_name,
        _mm(via.x),
        _mm(via.y),
        _mm(via.size_mm),
        _mm(via.drill_mm),
        via.front_mask.value,
        via.back_mask.value,
    )


def _zone_identity(
    net_name: str,
    layer: str,
    rect: tuple[float, float, float, float],
) -> tuple[str, ...]:
    x1, y1, x2, y2 = rect
    return (
        "zone",
        net_name,
        layer,
        _mm(min(x1, x2)),
        _mm(min(y1, y2)),
        _mm(max(x1, x2)),
        _mm(max(y1, y2)),
    )


def _segment(
    segment: TrackSegment,
    _net_numbers: dict[str, int],
    occurrence: int,
) -> str:
    origin = BOARD_SHEET_ORIGIN_MM
    item_uuid = stable_kicad_uuid(
        "board-copper",
        *_segment_identity(segment),
        str(occurrence),
    )
    return (
        f"  (segment (start {_mm(segment.x1 + origin)} {_mm(segment.y1 + origin)}) "
        f"(end {_mm(segment.x2 + origin)} {_mm(segment.y2 + origin)}) "
        f'(width {_mm(segment.width_mm)}) (layer "{segment.layer}") '
        f"(net {_q(segment.net_name)}) (uuid {item_uuid}))"
    )


def _via_mask_token(intent: ViaMaskIntent) -> str:
    return {
        ViaMaskIntent.INHERIT: "none",
        ViaMaskIntent.OPEN: "no",
        ViaMaskIntent.TENTED: "yes",
    }[intent]


def _via(
    via: ViaSpec,
    _net_numbers: dict[str, int],
    occurrence: int,
) -> str:
    origin = BOARD_SHEET_ORIGIN_MM
    front_mask = _via_mask_token(via.front_mask)
    back_mask = _via_mask_token(via.back_mask)
    item_uuid = stable_kicad_uuid(
        "board-copper",
        *_via_identity(via),
        str(occurrence),
    )
    return (
        f"  (via (at {_mm(via.x + origin)} {_mm(via.y + origin)}) (size {_mm(via.size_mm)}) "
        f'(drill {_mm(via.drill_mm)}) (layers "F.Cu" "B.Cu") '
        f"(tenting (front {front_mask}) (back {back_mask})) "
        f"(net {_q(via.net_name)}) (uuid {item_uuid}))"
    )


def _zone(
    net_name: str,
    layer: str,
    rect: tuple[float, float, float, float],
    net_numbers: dict[str, int],
    priority: int = 0,
    occurrence: int = 0,
) -> str:
    origin = BOARD_SHEET_ORIGIN_MM
    x1, y1, x2, y2 = rect
    item_uuid = stable_kicad_uuid(
        "board-copper",
        *_zone_identity(net_name, layer, rect),
        str(occurrence),
    )
    points = "\n          ".join(
        f"(xy {_mm(x + origin)} {_mm(y + origin)})"
        for x, y in ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
    )
    priority_clause = "" if priority == 0 else f"\n    (priority {priority})"
    return f"""  (zone
    (net {_q(net_name)})
    (layer "{layer}")
    (uuid {item_uuid}){priority_clause}
    (hatch edge 0.5)
    (connect_pads yes
      (clearance 0.5))
    (min_thickness 0.25)
    (filled_areas_thickness no)
    (fill yes
      (thermal_gap 0.5)
      (thermal_bridge_width 0.5)
    )
    (polygon
      (pts
          {points}
      )
    )
  )"""


def _render_header(profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE) -> str:
    expansion = profile.geometry.default_pad_solder_mask_expansion_mm
    mask_setup = (
        ""
        if expansion is None
        else f"""\n\n  (setup
    (pad_to_mask_clearance {_mm(expansion)})
  )"""
    )
    return f"""(kicad_pcb
  (version {KICAD_BOARD_VERSION})
  (generator "PCBSmith")

  (general
    (thickness {profile.geometry.board_thickness_mm:g})
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
  ){mask_setup}"""


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
