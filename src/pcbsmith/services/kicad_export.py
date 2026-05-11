from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from pcbsmith.core.board import Board, BoardText, Trace
from pcbsmith.core.geom import Point, Vec, mm_to_nm, nm_to_mm
from pcbsmith.core.project import Project
from pcbsmith.core.schematic import NetLabel, NoConnect, Schematic, SymbolInstance, Wire
from pcbsmith.services.kicad_project import (
    KiCadProjectSkeleton,
    create_kicad_project_skeleton,
    render_kicad_board_file,
    render_kicad_schematic_file,
)
from pcbsmith.services.project_io import load_board, load_project, load_schematic

HANDOFF_FILE_NAME = "pcbsmith_handoff.json"
HANDOFF_SCHEMA = "pcbsmith-kicad-handoff-v1"
PCBSMITH_SYMBOL_LIBRARY_FILE_NAME = "PCBSmith.kicad_sym"
PCBSMITH_SYMBOL_TABLE_FILE_NAME = "sym-lib-table"
PCBSMITH_LIBRARY_NAME = "PCBSmith"
KICAD_ZERO_OFFSET = Vec(0, 0)
KICAD_SCHEMATIC_ITEM_OFFSET = Vec(25_400_000, 25_400_000)
KICAD_SCHEMATIC_SHEET_CENTER = Point(mm_to_nm(147.32), mm_to_nm(104.14))
KICAD_BOARD_DISPLAY_OFFSET_X_MM = 123.5
KICAD_BOARD_DISPLAY_OFFSET_Y_MM = 87.5
KICAD_BOARD_OUTLINE_START_MM = "123.5 87.5"
KICAD_BOARD_OUTLINE_END_MM = "183.5 127.5"
KICAD_LAYER_FRONT_COPPER = "F.Cu"
KICAD_LAYER_BACK_COPPER = "B.Cu"
KICAD_LAYER_FRONT_SILK = "F.SilkS"
KICAD_LAYER_BACK_SILK = "B.SilkS"
KICAD_LAYER_EDGE_CUTS = "Edge.Cuts"
BOARD_PAD_ESCAPE_MM = 3.0


@dataclass(frozen=True)
class NativeSymbolSpec:
    source_symbol_id: str
    library_symbol_name: str
    reference_prefix: str
    value: str
    description: str
    pin_offsets: tuple[Vec, ...]
    power: bool = False
    datasheet: str = "~"


@dataclass(frozen=True)
class NativeSymbolInstance:
    source: SymbolInstance
    spec: NativeSymbolSpec
    reference: str
    uuid: UUID
    pin_uuids: tuple[UUID, ...]

    @property
    def lib_id(self) -> str:
        return f"{PCBSMITH_LIBRARY_NAME}:{self.spec.library_symbol_name}"

    @property
    def pin_points(self) -> tuple[Point, ...]:
        return tuple(self.source.position + offset for offset in self.spec.pin_offsets)


@dataclass(frozen=True)
class NativeBoardNet:
    name: str
    number: int
    wire: Wire


@dataclass(frozen=True)
class NativeBoardFootprint:
    symbol: NativeSymbolInstance
    footprint_name: str
    center_x_mm: str
    center_y_mm: str
    pad_nets: tuple[NativeBoardNet | None, NativeBoardNet | None]


@dataclass(frozen=True)
class NativeBoardPad:
    x_mm: str
    y_mm: str
    net: NativeBoardNet
    escape_direction: int = 0


@dataclass(frozen=True)
class NativePowerPadPosition:
    x_mm: str
    y_mm: str


class KiCadExportResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    skeleton: KiCadProjectSkeleton
    handoff_file: Path


NATIVE_SYMBOL_SPECS: dict[str, NativeSymbolSpec] = {
    "stdlib:R": NativeSymbolSpec(
        source_symbol_id="stdlib:R",
        library_symbol_name="R",
        reference_prefix="R",
        value="R",
        description="Generic resistor",
        pin_offsets=(Vec(-5_080_000, 0), Vec(5_080_000, 0)),
    ),
    "stdlib:C": NativeSymbolSpec(
        source_symbol_id="stdlib:C",
        library_symbol_name="C",
        reference_prefix="C",
        value="C",
        description="Generic capacitor",
        pin_offsets=(Vec(-5_080_000, 0), Vec(5_080_000, 0)),
    ),
    "stdlib:D": NativeSymbolSpec(
        source_symbol_id="stdlib:D",
        library_symbol_name="D",
        reference_prefix="D",
        value="D",
        description="Generic diode",
        pin_offsets=(Vec(-5_080_000, 0), Vec(5_080_000, 0)),
    ),
    "stdlib:LED": NativeSymbolSpec(
        source_symbol_id="stdlib:LED",
        library_symbol_name="LED",
        reference_prefix="LED",
        value="LED",
        description="Generic LED",
        pin_offsets=(Vec(-5_080_000, 0), Vec(5_080_000, 0)),
    ),
    "stdlib:VCC": NativeSymbolSpec(
        source_symbol_id="stdlib:VCC",
        library_symbol_name="VCC",
        reference_prefix="#PWR",
        value="VCC",
        description="Power symbol creates a global label with name VCC",
        pin_offsets=(Vec(0, 0),),
        power=True,
        datasheet="",
    ),
    "stdlib:GND": NativeSymbolSpec(
        source_symbol_id="stdlib:GND",
        library_symbol_name="GND",
        reference_prefix="#PWR",
        value="GND",
        description="Power symbol creates a global label with name GND",
        pin_offsets=(Vec(0, 0),),
        power=True,
        datasheet="",
    ),
    "stdlib:NE555": NativeSymbolSpec(
        source_symbol_id="stdlib:NE555",
        library_symbol_name="NE555",
        reference_prefix="U",
        value="NE555",
        description="Generic 555 timer IC",
        pin_offsets=(
            Vec(mm_to_nm(-7.62), mm_to_nm(-5.08)),
            Vec(mm_to_nm(-7.62), mm_to_nm(-2.54)),
            Vec(mm_to_nm(7.62), mm_to_nm(5.08)),
            Vec(mm_to_nm(-7.62), 0),
            Vec(mm_to_nm(-7.62), mm_to_nm(2.54)),
            Vec(mm_to_nm(7.62), 0),
            Vec(mm_to_nm(7.62), mm_to_nm(-2.54)),
            Vec(mm_to_nm(7.62), mm_to_nm(-5.08)),
        ),
    ),
}

BOARD_FOOTPRINT_NAMES = {
    "stdlib:R": "PCBSmith_R_0603",
    "stdlib:C": "PCBSmith_C_0603",
    "stdlib:D": "PCBSmith_D_0603",
    "stdlib:LED": "PCBSmith_LED_0603",
    "stdlib:NE555": "PCBSmith_SOIC8_NE555",
}


def export_pcbs_project_to_kicad(
    source_project_dir: Path,
    output_project_dir: Path,
    *,
    project_name: str | None = None,
    uuid_factory: Callable[[], UUID] = uuid4,
) -> KiCadExportResult:
    project = load_project(source_project_dir)
    schematic_path = _first_schematic_path(project)
    board_path = _first_board_path(project)
    schematic = load_schematic(source_project_dir, schematic_path)
    board = load_board(source_project_dir, board_path)
    skeleton = create_kicad_project_skeleton(
        output_project_dir,
        project_name or project.name,
        uuid_factory=uuid_factory,
    )
    native_symbols = _native_symbol_instances(schematic, uuid_factory=uuid_factory)
    if native_symbols:
        (skeleton.project_dir / PCBSMITH_SYMBOL_LIBRARY_FILE_NAME).write_text(
            render_pcbs_kicad_symbol_library(),
            encoding="utf-8",
        )
        (skeleton.project_dir / PCBSMITH_SYMBOL_TABLE_FILE_NAME).write_text(
            render_pcbs_kicad_symbol_table(),
            encoding="utf-8",
        )
    skeleton.schematic_file.write_text(
        render_kicad_schematic_file(
            uuid_factory(),
            render_kicad_schematic_items(
                schematic,
                native_symbols=native_symbols,
                project_name=skeleton.project_name,
                uuid_factory=uuid_factory,
            ),
            lib_symbol_items=render_pcbs_kicad_embedded_symbols()
            if native_symbols
            else (),
        ),
        encoding="utf-8",
    )
    skeleton.board_file.write_text(
        render_kicad_board_file(
            uuid_factory(),
            render_kicad_board_items(
                schematic,
                board=board,
                native_symbols=native_symbols,
                uuid_factory=uuid_factory,
            ),
            outline_start_mm=KICAD_BOARD_OUTLINE_START_MM,
            outline_end_mm=KICAD_BOARD_OUTLINE_END_MM,
        ),
        encoding="utf-8",
    )
    handoff_file = skeleton.project_dir / HANDOFF_FILE_NAME
    handoff_file.write_text(
        render_handoff_manifest(
            project=project,
            schematic_path=schematic_path,
            schematic=schematic,
            skeleton=skeleton,
        ),
        encoding="utf-8",
    )
    return KiCadExportResult(skeleton=skeleton, handoff_file=handoff_file)


def render_handoff_manifest(
    *,
    project: Project,
    schematic_path: str,
    schematic: Schematic,
    skeleton: KiCadProjectSkeleton,
) -> str:
    manifest = {
        "schema": HANDOFF_SCHEMA,
        "source_project": {
            "name": project.name,
            "schematic": schematic_path,
        },
        "kicad_project": {
            "name": skeleton.project_name,
            "project_file": skeleton.project_file.name,
            "schematic_file": skeleton.schematic_file.name,
            "board_file": skeleton.board_file.name,
        },
        "commands": schematic_handoff_commands(schematic),
    }
    return _json_dump(manifest)


def schematic_handoff_commands(schematic: Schematic) -> list[dict[str, object]]:
    commands: list[dict[str, object]] = []
    commands.extend(_symbol_command(symbol) for symbol in schematic.symbols)
    commands.extend(_wire_command(wire) for wire in schematic.wires)
    commands.extend(_label_command(label) for label in schematic.labels)
    commands.extend(_no_connect_command(no_connect) for no_connect in schematic.no_connects)
    return commands


def render_kicad_schematic_items(
    schematic: Schematic,
    *,
    native_symbols: tuple[NativeSymbolInstance, ...] | None = None,
    project_name: str = "",
    uuid_factory: Callable[[], UUID] = uuid4,
) -> tuple[str, ...]:
    native_symbols = _native_symbol_instances(
        schematic, uuid_factory=uuid_factory
    ) if native_symbols is None else native_symbols
    pin_points = {
        (point.x, point.y)
        for symbol in native_symbols
        for point in symbol.pin_points
    }
    power_points = {
        (point.x, point.y): symbol.spec.library_symbol_name
        for symbol in native_symbols
        if symbol.spec.power
        for point in symbol.pin_points
    }
    native_wires = _native_wires(schematic.wires)
    connected_points = {
        (point.x, point.y) for wire in native_wires for point in wire.points
    } | pin_points
    display_offset = _schematic_display_offset(
        schematic,
        native_symbols=native_symbols,
    )

    items: list[str] = []
    items.extend(
        _render_kicad_symbol(
            symbol,
            project_name=project_name,
            offset=display_offset,
        )
        for symbol in native_symbols
    )
    items.extend(
        _render_kicad_wire(wire, uuid_factory(), offset=display_offset)
        for wire in native_wires
    )
    for label in schematic.labels:
        if not _should_render_native_label(
            label,
            connected_points,
            native_wires,
            power_points,
        ):
            continue
        items.append(
            _render_kicad_label(
                label,
                uuid_factory(),
                offset=display_offset,
                hidden=_is_wire_interior_label(
                    label,
                    connected_points,
                    native_wires,
                ),
            )
        )
    items.extend(
        _render_kicad_label(
            label,
            uuid_factory(),
            offset=display_offset,
            hidden=True,
        )
        for label in _power_wire_endpoint_labels(native_wires, power_points)
    )
    items.extend(
        _render_kicad_no_connect(
            no_connect,
            uuid_factory(),
            offset=display_offset,
        )
        for no_connect in schematic.no_connects
    )
    return tuple(items)


def render_kicad_board_items(
    schematic: Schematic,
    *,
    board: Board | None = None,
    native_symbols: tuple[NativeSymbolInstance, ...] | None = None,
    uuid_factory: Callable[[], UUID] = uuid4,
) -> tuple[str, ...]:
    native_symbols = _native_symbol_instances(
        schematic, uuid_factory=uuid_factory
    ) if native_symbols is None else native_symbols
    power_points = {
        (point.x, point.y): symbol.spec.library_symbol_name
        for symbol in native_symbols
        if symbol.spec.power
        for point in symbol.pin_points
    }
    native_wires = _native_wires(schematic.wires)
    board_nets = _native_board_nets(
        schematic.labels,
        native_wires,
        power_points,
    )
    unique_board_nets = _unique_board_nets(board_nets)
    point_nets = _point_board_nets(board_nets)
    footprints = _native_board_footprints(native_symbols, point_nets)
    board_pads = _native_board_pads(footprints, unique_board_nets)

    if not footprints and board is None:
        return ()

    net_numbers = _board_trace_net_numbers(board.traces if board else (), board_nets)
    items: list[str] = []
    items.extend(_render_board_net(net) for net in unique_board_nets)
    items.extend(
        _render_board_net_name(net_name, net_number)
        for net_name, net_number in net_numbers.items()
        if net_name not in {net.name for net in board_nets}
    )
    items.extend(
        _render_board_power_footprint(net, uuid_factory=uuid_factory)
        for net in unique_board_nets
        if net.name in {"VCC", "GND"}
    )
    items.extend(
        _render_board_footprint(footprint, uuid_factory=uuid_factory)
        for footprint in footprints
    )
    items.extend(_render_board_segments(board_pads, uuid_factory=uuid_factory))
    if board is not None:
        for trace in board.traces:
            items.extend(
                _render_command_board_trace(
                    trace,
                    net_number=net_numbers[trace.net_name],
                    uuid_factory=uuid_factory,
                )
            )
        items.extend(
            _render_command_board_text(text, uuid=uuid_factory())
            for text in board.texts
        )
    if footprints and (board is None or not board.texts):
        items.append(
            _render_board_silkscreen_text(
                "PCBSmith Demo",
                x_mm=_board_x_mm(25),
                y_mm=_board_y_mm(5),
                uuid=uuid_factory(),
            )
        )
    return tuple(items)


def _symbol_command(symbol: SymbolInstance) -> dict[str, object]:
    return {
        "type": "place_symbol",
        "reference": symbol.reference,
        "symbol_id": symbol.symbol_id,
        "value": symbol.value,
        "position_nm": _point(symbol.position),
        "rotation_deg": symbol.rotation_deg,
        "footprint_id": symbol.footprint_id,
        "mirrored_x": symbol.mirrored_x,
    }


def _wire_command(wire: Wire) -> dict[str, object]:
    return {
        "type": "add_wire",
        "points_nm": [_point(point) for point in wire.points],
    }


def _label_command(label: NetLabel) -> dict[str, object]:
    return {
        "type": "add_label",
        "name": label.name,
        "position_nm": _point(label.position),
    }


def _no_connect_command(no_connect: NoConnect) -> dict[str, object]:
    return {
        "type": "add_no_connect",
        "position_nm": _point(no_connect.position),
    }


def _point(point: Point) -> dict[str, int]:
    return {"x": point.x, "y": point.y}


def _native_symbol_instances(
    schematic: Schematic,
    *,
    uuid_factory: Callable[[], UUID],
) -> tuple[NativeSymbolInstance, ...]:
    power_index = 1
    native_symbols: list[NativeSymbolInstance] = []
    for symbol in schematic.symbols:
        spec = NATIVE_SYMBOL_SPECS.get(symbol.symbol_id)
        if spec is None:
            continue
        reference = symbol.reference
        if spec.power:
            reference = f"{spec.reference_prefix}{power_index:02d}"
            power_index += 1
        native_symbols.append(
            NativeSymbolInstance(
                source=symbol,
                spec=spec,
                reference=reference,
                uuid=uuid_factory(),
                pin_uuids=tuple(uuid_factory() for _ in spec.pin_offsets),
            )
        )
    return tuple(native_symbols)


def _wire_connects_native_points(
    wire: Wire,
    pin_points: set[tuple[int, int]],
) -> bool:
    if len({(point.x, point.y) for point in wire.points}) <= 1:
        return False
    return (
        (wire.points[0].x, wire.points[0].y) in pin_points
        and (wire.points[-1].x, wire.points[-1].y) in pin_points
    )


def _native_wires(wires: tuple[Wire, ...]) -> list[Wire]:
    return [
        wire
        for wire in wires
        if len({(point.x, point.y) for point in wire.points}) > 1
    ]


def _schematic_display_offset(
    schematic: Schematic,
    *,
    native_symbols: tuple[NativeSymbolInstance, ...],
) -> Vec:
    points = _schematic_display_points(schematic, native_symbols=native_symbols)
    if not points:
        return KICAD_SCHEMATIC_ITEM_OFFSET
    left = min(point.x for point in points)
    right = max(point.x for point in points)
    top = min(point.y for point in points)
    bottom = max(point.y for point in points)
    center_x = (left + right) // 2
    center_y = (top + bottom) // 2
    return Vec(
        KICAD_SCHEMATIC_SHEET_CENTER.x - center_x,
        KICAD_SCHEMATIC_SHEET_CENTER.y - center_y,
    )


def _schematic_display_points(
    schematic: Schematic,
    *,
    native_symbols: tuple[NativeSymbolInstance, ...],
) -> tuple[Point, ...]:
    points: list[Point] = []
    for symbol in native_symbols:
        points.append(symbol.source.position)
        points.extend(symbol.pin_points)
    for wire in schematic.wires:
        points.extend(wire.points)
    points.extend(label.position for label in schematic.labels)
    points.extend(no_connect.position for no_connect in schematic.no_connects)
    return tuple(points)


def _should_render_native_label(
    label: NetLabel,
    connected_points: set[tuple[int, int]],
    native_wires: list[Wire],
    power_points: dict[tuple[int, int], str],
) -> bool:
    if _duplicates_power_symbol_label(label, power_points):
        return False
    return (label.position.x, label.position.y) in connected_points or any(
        _point_on_wire(label.position, wire) for wire in native_wires
    )


def _is_wire_interior_label(
    label: NetLabel,
    connected_points: set[tuple[int, int]],
    native_wires: list[Wire],
) -> bool:
    return (label.position.x, label.position.y) not in connected_points and any(
        _point_on_wire(label.position, wire) for wire in native_wires
    )


def _duplicates_power_symbol_label(
    label: NetLabel,
    power_points: dict[tuple[int, int], str],
) -> bool:
    return power_points.get((label.position.x, label.position.y)) == label.name


def _point_on_wire(point: Point, wire: Wire) -> bool:
    return any(
        _point_on_segment(point, start, end)
        for start, end in zip(wire.points, wire.points[1:], strict=False)
    )


def _point_on_segment(point: Point, start: Point, end: Point) -> bool:
    cross = (point.x - start.x) * (end.y - start.y) - (
        point.y - start.y
    ) * (end.x - start.x)
    if cross != 0:
        return False
    return (
        min(start.x, end.x) <= point.x <= max(start.x, end.x)
        and min(start.y, end.y) <= point.y <= max(start.y, end.y)
    )


def _power_wire_endpoint_labels(
    wires: list[Wire],
    power_points: dict[tuple[int, int], str],
) -> tuple[NetLabel, ...]:
    labels: list[NetLabel] = []
    for wire in wires:
        first = wire.points[0]
        last = wire.points[-1]
        first_key = (first.x, first.y)
        last_key = (last.x, last.y)
        if first_key in power_points:
            labels.append(NetLabel(name=power_points[first_key], position=last))
        if last_key in power_points:
            labels.append(NetLabel(name=power_points[last_key], position=first))
    return tuple(labels)


def _native_board_nets(
    labels: tuple[NetLabel, ...],
    wires: list[Wire],
    power_points: dict[tuple[int, int], str],
) -> tuple[NativeBoardNet, ...]:
    component_names = _wire_component_net_names(labels, wires, power_points)
    names: list[str] = []
    nets: list[NativeBoardNet] = []
    for index, wire in enumerate(wires):
        name = component_names[index]
        if name not in names:
            names.append(name)
        nets.append(NativeBoardNet(name=name, number=names.index(name) + 1, wire=wire))
    return tuple(nets)


def _wire_component_net_names(
    labels: tuple[NetLabel, ...],
    wires: list[Wire],
    power_points: dict[tuple[int, int], str],
) -> dict[int, str]:
    parent = list(range(len(wires)))

    def find(index: int) -> int:
        root = parent[index]
        if root != index:
            parent[index] = find(root)
        return parent[index]

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for left_index, left_wire in enumerate(wires):
        for right_index, right_wire in enumerate(wires[left_index + 1 :], start=left_index + 1):
            if _wires_touch(left_wire, right_wire):
                union(left_index, right_index)

    component_names: dict[int, str] = {}
    next_fallback = 1
    for component in sorted({find(index) for index in range(len(wires))}):
        component_wires = [
            wire for index, wire in enumerate(wires) if find(index) == component
        ]
        name = _wire_group_net_name(labels, component_wires, power_points)
        if name is None:
            name = f"N${next_fallback}"
            next_fallback += 1
        component_names[component] = name

    return {index: component_names[find(index)] for index in range(len(wires))}


def _wire_group_net_name(
    labels: tuple[NetLabel, ...],
    wires: list[Wire],
    power_points: dict[tuple[int, int], str],
) -> str | None:
    power_names: list[str] = []
    label_names: list[str] = []
    for wire in wires:
        for point in wire.points:
            power_name = power_points.get((point.x, point.y))
            if power_name is not None and power_name not in power_names:
                power_names.append(power_name)
        for label in labels:
            if _point_on_wire(label.position, wire) and label.name not in label_names:
                label_names.append(label.name)

    if power_names:
        return sorted(power_names)[0]
    if label_names:
        return sorted(label_names)[0]
    return None


def _wires_touch(left: Wire, right: Wire) -> bool:
    return any(_point_on_wire(point, right) for point in left.points) or any(
        _point_on_wire(point, left) for point in right.points
    )


def _unique_board_nets(
    board_nets: tuple[NativeBoardNet, ...],
) -> tuple[NativeBoardNet, ...]:
    unique: dict[tuple[int, str], NativeBoardNet] = {}
    for net in board_nets:
        unique.setdefault((net.number, net.name), net)
    return tuple(sorted(unique.values(), key=lambda net: net.number))


def _point_board_nets(
    board_nets: tuple[NativeBoardNet, ...],
) -> dict[tuple[int, int], NativeBoardNet]:
    point_nets: dict[tuple[int, int], NativeBoardNet] = {}
    for net in board_nets:
        for point in (net.wire.points[0], net.wire.points[-1]):
            point_nets[(point.x, point.y)] = net
    return point_nets


def _native_board_footprints(
    native_symbols: tuple[NativeSymbolInstance, ...],
    point_nets: dict[tuple[int, int], NativeBoardNet],
) -> tuple[NativeBoardFootprint, ...]:
    footprints: list[NativeBoardFootprint] = []
    for board_index, symbol in enumerate(
        (symbol for symbol in native_symbols if not symbol.spec.power),
    ):
        footprint_name = BOARD_FOOTPRINT_NAMES.get(symbol.spec.source_symbol_id)
        if footprint_name is None or len(symbol.pin_points) != 2:
            continue
        center_x_mm = _board_x_mm(10 + board_index * 17)
        footprints.append(
            NativeBoardFootprint(
                symbol=symbol,
                footprint_name=footprint_name,
                center_x_mm=center_x_mm,
                center_y_mm=_board_y_mm(20 + nm_to_mm(symbol.source.position.y)),
                pad_nets=(
                    point_nets.get(
                        (symbol.pin_points[0].x, symbol.pin_points[0].y)
                    ),
                    point_nets.get(
                        (symbol.pin_points[1].x, symbol.pin_points[1].y)
                    ),
                ),
            )
        )
    return tuple(footprints)


def _native_board_pads(
    footprints: tuple[NativeBoardFootprint, ...],
    board_nets: tuple[NativeBoardNet, ...],
) -> tuple[NativeBoardPad, ...]:
    pads: list[NativeBoardPad] = []
    for net in board_nets:
        power_position = _board_power_pad_position(net.name)
        if power_position is not None:
            pads.append(
                NativeBoardPad(
                    x_mm=power_position.x_mm,
                    y_mm=power_position.y_mm,
                    net=net,
                    escape_direction=1,
                )
            )

    for footprint in footprints:
        for x_offset, net, escape_direction in zip(
            ("-4", "4"), footprint.pad_nets, (-1, 1), strict=True
        ):
            if net is None:
                continue
            pads.append(
                NativeBoardPad(
                    x_mm=_offset_mm(footprint.center_x_mm, x_offset),
                    y_mm=footprint.center_y_mm,
                    net=net,
                    escape_direction=escape_direction,
                )
            )
    return tuple(pads)


def _render_kicad_symbol(
    symbol: NativeSymbolInstance,
    *,
    project_name: str,
    offset: Vec = KICAD_ZERO_OFFSET,
) -> str:
    source = symbol.source
    position = source.position + offset
    reference = symbol.reference
    value = source.value or symbol.spec.value
    reference_property = _render_symbol_property(
        "Reference",
        reference,
        position.x,
        position.y - 2_540_000,
        hidden=symbol.spec.power,
    )
    value_y = position.y + (
        2_540_000 if not symbol.spec.power else -2_540_000
    )
    value_property = _render_symbol_property("Value", value, position.x, value_y)
    footprint_property = _render_symbol_property(
        "Footprint", "", position.x, position.y, hidden=True
    )
    datasheet_property = _render_symbol_property(
        "Datasheet",
        symbol.spec.datasheet,
        position.x,
        position.y,
        hidden=True,
    )
    description_property = _render_symbol_property(
        "Description",
        symbol.spec.description,
        position.x,
        position.y,
        hidden=True,
    )
    return f"""  (symbol
    (lib_id "{symbol.lib_id}")
    (at {_format_mm(position.x)} {_format_mm(position.y)} {source.rotation_deg})
    (unit 1)
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
    (dnp no)
    (uuid "{symbol.uuid}")
    {reference_property}
    {value_property}
    {footprint_property}
    {datasheet_property}
    {description_property}
{_render_symbol_pins(symbol)}
    (instances
      (project "{_escape_kicad_string(project_name)}"
        (path "/"
          (reference "{_escape_kicad_string(reference)}")
          (unit 1)
        )
      )
    )
  )"""


def _render_symbol_pins(symbol: NativeSymbolInstance) -> str:
    return "\n".join(
        f"""    (pin "{index}"
      (uuid "{pin_uuid}")
    )"""
        for index, pin_uuid in enumerate(symbol.pin_uuids, start=1)
    )


def _render_symbol_property(
    name: str,
    value: str,
    x_nm: int,
    y_nm: int,
    *,
    hidden: bool = False,
) -> str:
    hide = "\n        (hide yes)" if hidden else ""
    return f"""(property "{_escape_kicad_string(name)}" "{_escape_kicad_string(value)}"
      (at {_format_mm(x_nm)} {_format_mm(y_nm)} 0)
      (effects
        (font
          (size 1.27 1.27)
        ){hide}
      )
    )"""


def _render_kicad_label(
    label: NetLabel,
    item_uuid: UUID,
    *,
    offset: Vec = KICAD_ZERO_OFFSET,
    hidden: bool = False,
) -> str:
    position = label.position + offset
    font_size = "0.01 0.01" if hidden else "1.27 1.27"
    hide_line = "\n      (hide yes)" if hidden else ""
    return f"""  (label "{_escape_kicad_string(label.name)}"
    (at {_format_mm(position.x)} {_format_mm(position.y)} 0)
    (effects
      (font
        (size {font_size})
      ){hide_line}
    )
    (uuid "{item_uuid}")
  )"""


def _render_kicad_wire(
    wire: Wire,
    item_uuid: UUID,
    *,
    offset: Vec = KICAD_ZERO_OFFSET,
) -> str:
    points = " ".join(
        f"(xy {_format_mm(point.x + offset.dx)} {_format_mm(point.y + offset.dy)})"
        for point in wire.points
    )
    return f"""  (wire
    (pts
      {points}
    )
    (stroke
      (width 0)
      (type solid)
    )
    (uuid "{item_uuid}")
  )"""


def _render_kicad_no_connect(
    no_connect: NoConnect,
    item_uuid: UUID,
    *,
    offset: Vec = KICAD_ZERO_OFFSET,
) -> str:
    position = no_connect.position + offset
    return f"""  (no_connect
    (at {_format_mm(position.x)} {_format_mm(position.y)})
    (uuid "{item_uuid}")
  )"""


def _render_board_net(net: NativeBoardNet) -> str:
    return f'  (net {net.number} "{_escape_kicad_string(net.name)}")'


def _render_board_net_name(net_name: str, net_number: int) -> str:
    return f'  (net {net_number} "{_escape_kicad_string(net_name)}")'


def _render_board_footprint(
    footprint: NativeBoardFootprint,
    *,
    uuid_factory: Callable[[], UUID],
) -> str:
    reference = footprint.symbol.reference
    value = footprint.symbol.source.value or footprint.symbol.spec.value
    return f"""  (footprint "{footprint.footprint_name}"
    (layer "F.Cu")
    (uuid {uuid_factory()})
    (at {footprint.center_x_mm} {footprint.center_y_mm})
    (property "Reference" "{_escape_kicad_string(reference)}"
      (at 0 -1.6 0)
      (layer "{KICAD_LAYER_FRONT_SILK}")
      (uuid {uuid_factory()})
      (effects
        (font
          (size 1 1)
          (thickness 0.15)
        )
      )
    )
    (property "Value" "{_escape_kicad_string(value)}"
      (at 0 1.6 0)
      (layer "F.Fab")
      (uuid {uuid_factory()})
      (effects
        (font
          (size 1 1)
          (thickness 0.15)
        )
      )
    )
    (attr smd)
    (fp_rect
      (start -2.5 -0.8)
      (end 2.5 0.8)
      (stroke
        (width 0.12)
        (type solid)
      )
      (fill none)
      (layer "F.SilkS")
      (uuid {uuid_factory()})
    )
{_render_board_pad("1", "-4", footprint.pad_nets[0], uuid_factory())}
{_render_board_pad("2", "4", footprint.pad_nets[1], uuid_factory())}
  )"""


def _render_board_pad(
    number: str,
    x_mm: str,
    net: NativeBoardNet | None,
    uuid: UUID,
) -> str:
    net_text = (
        '(net 0 "")'
        if net is None
        else f'(net {net.number} "{_escape_kicad_string(net.name)}")'
    )
    return f"""    (pad "{number}" smd roundrect
      (at {x_mm} 0)
      (size 1.4 1.4)
      (layers "F.Cu" "F.Paste" "F.Mask")
      (roundrect_rratio 0.25)
      {net_text}
      (pinfunction "{number}")
      (pintype "passive")
      (uuid {uuid})
    )"""


def _render_board_power_footprint(
    net: NativeBoardNet,
    *,
    uuid_factory: Callable[[], UUID],
) -> str:
    position = _board_power_pad_position(net.name)
    x_mm = _board_x_mm(4) if position is None else position.x_mm
    y_mm = _board_y_mm(20) if position is None else position.y_mm
    return f"""  (footprint "PCBSmith_POWER_PAD"
    (layer "F.Cu")
    (uuid {uuid_factory()})
    (at {x_mm} {y_mm})
    (property "Reference" "{_escape_kicad_string(net.name)}"
      (at 0 -2 0)
      (layer "{KICAD_LAYER_FRONT_SILK}")
      (uuid {uuid_factory()})
      (effects
        (font
          (size 1 1)
          (thickness 0.15)
        )
      )
    )
    (property "Value" "Power Pad"
      (at 0 2 0)
      (layer "F.Fab")
      (uuid {uuid_factory()})
      (effects
        (font
          (size 1 1)
          (thickness 0.15)
        )
      )
    )
    (attr smd)
    (pad "1" smd roundrect
      (at 0 0)
      (size 1.8 1.8)
      (layers "F.Cu" "F.Paste" "F.Mask")
      (roundrect_rratio 0.25)
      (net {net.number} "{_escape_kicad_string(net.name)}")
      (pinfunction "1")
      (pintype "passive")
      (uuid {uuid_factory()})
    )
  )"""


def _render_board_segment(
    *,
    start_x_mm: str,
    start_y_mm: str,
    end_x_mm: str,
    end_y_mm: str,
    net: NativeBoardNet,
    uuid: UUID,
) -> str:
    return _render_board_segment_values(
        start_x_mm=start_x_mm,
        start_y_mm=start_y_mm,
        end_x_mm=end_x_mm,
        end_y_mm=end_y_mm,
        width_mm="0.25",
        layer=KICAD_LAYER_FRONT_COPPER,
        net_number=net.number,
        uuid=uuid,
    )


def _render_board_silkscreen_text(
    text: str,
    *,
    x_mm: str,
    y_mm: str,
    uuid: UUID,
) -> str:
    return _render_board_text(
        text,
        x_mm=x_mm,
        y_mm=y_mm,
        rotation_deg=0,
        layer=KICAD_LAYER_FRONT_SILK,
        size_mm="1.5",
        thickness_mm="0.15",
        uuid=uuid,
    )


def _render_board_text(
    text: str,
    *,
    x_mm: str,
    y_mm: str,
    rotation_deg: int,
    layer: str,
    size_mm: str,
    thickness_mm: str,
    uuid: UUID,
) -> str:
    return f"""  (gr_text "{_escape_kicad_string(text)}"
    (at {x_mm} {y_mm} {rotation_deg})
    (layer "{layer}")
    (uuid {uuid})
    (effects
      (font
        (size {size_mm} {size_mm})
        (thickness {thickness_mm})
      )
      (justify left)
    )
  )"""


def _render_command_board_trace(
    trace: Trace,
    *,
    net_number: int,
    uuid_factory: Callable[[], UUID],
) -> tuple[str, ...]:
    return tuple(
        _render_board_segment_values(
            start_x_mm=_board_point_x_mm(start),
            start_y_mm=_board_point_y_mm(start),
            end_x_mm=_board_point_x_mm(end),
            end_y_mm=_board_point_y_mm(end),
            width_mm=_format_mm(trace.width),
            layer=trace.layer,
            net_number=net_number,
            uuid=uuid_factory(),
        )
        for start, end in zip(trace.points, trace.points[1:], strict=False)
    )


def _render_command_board_text(text: BoardText, *, uuid: UUID) -> str:
    return _render_board_text(
        text.text,
        x_mm=_board_point_x_mm(text.position),
        y_mm=_board_point_y_mm(text.position),
        rotation_deg=text.rotation_deg,
        layer=text.layer,
        size_mm=_format_mm(text.size),
        thickness_mm=_format_mm(text.thickness),
        uuid=uuid,
    )


def _render_board_segment_values(
    *,
    start_x_mm: str,
    start_y_mm: str,
    end_x_mm: str,
    end_y_mm: str,
    width_mm: str,
    layer: str,
    net_number: int,
    uuid: UUID,
) -> str:
    return (
        f"  (segment (start {start_x_mm} {start_y_mm}) "
        f"(end {end_x_mm} {end_y_mm}) (width {width_mm}) "
        f'(layer "{layer}") (net {net_number}) (uuid {uuid}))'
    )


def _render_board_segments(
    pads: tuple[NativeBoardPad, ...],
    *,
    uuid_factory: Callable[[], UUID],
) -> tuple[str, ...]:
    segments: list[str] = []
    rendered_keys: set[tuple[int, str, str, str, str]] = set()
    net_numbers = sorted({pad.net.number for pad in pads})
    for net_number in net_numbers:
        net_pads = sorted(
            (pad for pad in pads if pad.net.number == net_number),
            key=lambda pad: (float(pad.y_mm), float(pad.x_mm)),
        )
        route_segments = (
            _ground_return_lane_segments(net_pads)
            if net_pads and net_pads[0].net.name == "GND" and len(net_pads) >= 3
            else tuple(
                segment
                for start, end in zip(net_pads, net_pads[1:], strict=False)
                for segment in _routed_board_pad_segments(start, end)
            )
        )
        for route_start, route_end in route_segments:
            segment_key = _board_segment_key(net_number, route_start, route_end)
            if segment_key in rendered_keys:
                continue
            rendered_keys.add(segment_key)
            segments.append(
                _render_board_segment(
                    start_x_mm=route_start[0],
                    start_y_mm=route_start[1],
                    end_x_mm=route_end[0],
                    end_y_mm=route_end[1],
                    net=net_pads[0].net,
                    uuid=uuid_factory(),
                )
            )
    return tuple(segments)


def _board_segment_key(
    net_number: int,
    route_start: tuple[str, str],
    route_end: tuple[str, str],
) -> tuple[int, str, str, str, str]:
    left, right = sorted((route_start, route_end))
    return (net_number, left[0], left[1], right[0], right[1])


def _ground_return_lane_segments(
    pads: list[NativeBoardPad],
) -> tuple[tuple[tuple[str, str], tuple[str, str]], ...]:
    connector_position = _board_power_pad_position("GND")
    if connector_position is None:
        return ()
    connector = next(
        (
            pad
            for pad in pads
            if pad.x_mm == connector_position.x_mm and pad.y_mm == connector_position.y_mm
        ),
        None,
    )
    if connector is None:
        return ()

    routed_pads = [pad for pad in pads if pad is not connector]
    if not routed_pads:
        return ()

    lane_x = max(
        _board_pad_escape_point(pad)[0]
        if pad.escape_direction > 0
        else float(pad.x_mm)
        for pad in routed_pads
    )
    lane_y = float(_board_y_mm(36))
    lowest_escape_y = min(_board_pad_escape_point(pad)[1] for pad in routed_pads)
    connector_escape = _board_pad_escape_point(connector)
    segments: list[tuple[tuple[str, str], tuple[str, str]]] = []
    segments.extend(
        _route_segments_from_points(
            (
                (float(connector.x_mm), float(connector.y_mm)),
                connector_escape,
                (connector_escape[0], lane_y),
                (lane_x, lane_y),
                (lane_x, lowest_escape_y),
            )
        )
    )
    for pad in routed_pads:
        escape = _board_pad_escape_point(pad)
        segments.extend(
            _route_segments_from_points(
                (
                    (lane_x, escape[1]),
                    escape,
                    (float(pad.x_mm), float(pad.y_mm)),
                )
            )
        )
    return tuple(segments)


def _routed_board_pad_segments(
    start: NativeBoardPad,
    end: NativeBoardPad,
) -> tuple[tuple[tuple[str, str], tuple[str, str]], ...]:
    start_x = float(start.x_mm)
    start_y = float(start.y_mm)
    end_x = float(end.x_mm)
    end_y = float(end.y_mm)
    start_escape = _board_pad_escape_point(start)
    end_escape = _board_pad_escape_point(end)
    if (
        start_y == end_y
        and start.escape_direction != 0
        and end.escape_direction != 0
        and abs(end_x - start_x) <= 2 * BOARD_PAD_ESCAPE_MM
    ):
        start_escape = (start_x, start_y)
        end_escape = (end_x, end_y)
    route_points = _routed_board_pad_points(
        start_escape[0],
        start_escape[1],
        end_escape[0],
        end_escape[1],
    )
    route_points = _dedupe_route_points(
        (
            (start_x, start_y),
            start_escape,
            *route_points,
            end_escape,
            (end_x, end_y),
        )
    )
    return _route_segments_from_points(route_points)


def _route_segments_from_points(
    route_points: tuple[tuple[float, float], ...],
) -> tuple[tuple[tuple[str, str], tuple[str, str]], ...]:
    return tuple(
        (
            (_format_plain_mm(start_x), _format_plain_mm(start_y)),
            (_format_plain_mm(end_x), _format_plain_mm(end_y)),
        )
        for (start_x, start_y), (end_x, end_y) in zip(
            route_points, route_points[1:], strict=False
        )
        if start_x != end_x or start_y != end_y
    )


def _board_pad_escape_point(pad: NativeBoardPad) -> tuple[float, float]:
    x_mm = float(pad.x_mm)
    y_mm = float(pad.y_mm)
    if pad.escape_direction == 0:
        return (x_mm, y_mm)
    return (x_mm + pad.escape_direction * BOARD_PAD_ESCAPE_MM, y_mm)


def _routed_board_pad_points(
    start_x: float,
    start_y: float,
    end_x: float,
    end_y: float,
) -> tuple[tuple[float, float], ...]:
    if start_x == end_x or start_y == end_y:
        return ((start_x, start_y), (end_x, end_y))

    dx = end_x - start_x
    dy = end_y - start_y
    x_direction = 1 if dx > 0 else -1
    y_direction = 1 if dy > 0 else -1
    chamfer = min(abs(dx) / 4, abs(dy) / 4, 1.5)
    mid_x = start_x + dx / 2

    return _dedupe_route_points(
        (
            (start_x, start_y),
            (mid_x - x_direction * chamfer, start_y),
            (mid_x, start_y + y_direction * chamfer),
            (mid_x, end_y - y_direction * chamfer),
            (mid_x + x_direction * chamfer, end_y),
            (end_x, end_y),
        )
    )


def _dedupe_route_points(
    points: tuple[tuple[float, float], ...],
) -> tuple[tuple[float, float], ...]:
    deduped: list[tuple[float, float]] = []
    for point in points:
        rounded = (round(point[0], 6), round(point[1], 6))
        if not deduped or deduped[-1] != rounded:
            deduped.append(rounded)
    return tuple(deduped)


def _board_power_pad_position(net_name: str) -> NativePowerPadPosition | None:
    if net_name == "VCC":
        return NativePowerPadPosition(x_mm=_board_x_mm(4), y_mm=_board_y_mm(20))
    if net_name == "GND":
        return NativePowerPadPosition(x_mm=_board_x_mm(4), y_mm=_board_y_mm(24))
    return None


def _offset_mm(base_mm: str, offset_mm: str) -> str:
    return _format_plain_mm(float(base_mm) + float(offset_mm))


def _board_x_mm(value_mm: float) -> str:
    return _format_plain_mm(KICAD_BOARD_DISPLAY_OFFSET_X_MM + value_mm)


def _board_y_mm(value_mm: float) -> str:
    return _format_plain_mm(KICAD_BOARD_DISPLAY_OFFSET_Y_MM + value_mm)


def _board_point_x_mm(point: Point) -> str:
    return _board_x_mm(nm_to_mm(point.x))


def _board_point_y_mm(point: Point) -> str:
    return _board_y_mm(nm_to_mm(point.y))


def _board_trace_net_numbers(
    traces: tuple[Trace, ...],
    board_nets: tuple[NativeBoardNet, ...],
) -> dict[str, int]:
    net_numbers = {net.name: net.number for net in board_nets}
    next_number = max(net_numbers.values(), default=0) + 1
    for trace in traces:
        if trace.net_name not in net_numbers:
            net_numbers[trace.net_name] = next_number
            next_number += 1
    return net_numbers


def _format_plain_mm(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")


def render_pcbs_kicad_symbol_table() -> str:
    return f"""(sym_lib_table
  (version 7)
  (lib
    (name "{PCBSMITH_LIBRARY_NAME}")
    (type "KiCad")
    (uri "${{KIPRJMOD}}/{PCBSMITH_SYMBOL_LIBRARY_FILE_NAME}")
    (options "")
    (descr "PCBSmith generated symbols")
  )
)
"""


def render_pcbs_kicad_symbol_library() -> str:
    symbols = "\n\n".join(
        _render_library_symbol(spec, embedded=False)
        for spec in NATIVE_SYMBOL_SPECS.values()
    )
    return f"""(kicad_symbol_lib
  (version 20251024)
  (generator "PCBSmith")
  (generator_version "0.1")
{symbols}
)
"""


def render_pcbs_kicad_embedded_symbols() -> tuple[str, ...]:
    return tuple(
        _render_library_symbol(spec, embedded=True)
        for spec in NATIVE_SYMBOL_SPECS.values()
    )


def _render_library_symbol(spec: NativeSymbolSpec, *, embedded: bool) -> str:
    name = (
        f"{PCBSMITH_LIBRARY_NAME}:{spec.library_symbol_name}"
        if embedded
        else spec.library_symbol_name
    )
    if spec.library_symbol_name == "NE555":
        return _render_ne555_library_symbol(name, spec.description)
    if spec.library_symbol_name == "R":
        return _render_two_pin_box_library_symbol(
            name,
            reference="R",
            value="R",
            description="Generic resistor",
            drawing=_resistor_symbol_drawing(),
            pin_length_mm="2.54",
        )
    if spec.library_symbol_name == "C":
        return _render_two_pin_box_library_symbol(
            name,
            reference="C",
            value="C",
            description="Generic capacitor",
            drawing=_capacitor_symbol_drawing(),
            pin_length_mm="4.318",
        )
    if spec.library_symbol_name == "D":
        return _render_two_pin_box_library_symbol(
            name,
            reference="D",
            value="D",
            description="Generic diode",
            drawing=_diode_symbol_drawing("D_0_1"),
            pin_length_mm="3.81",
        )
    if spec.library_symbol_name == "LED":
        return _render_two_pin_box_library_symbol(
            name,
            reference="LED",
            value="LED",
            description="Generic LED",
            drawing=_led_symbol_drawing(),
            pin_length_mm="3.81",
        )
    if spec.library_symbol_name == "VCC":
        return _render_power_library_symbol(
            name,
            value="VCC",
            description=spec.description,
            pin_direction=90,
            drawing=_vcc_symbol_drawing(),
            value_y_nm=2_540_000,
        )
    if spec.library_symbol_name == "GND":
        return _render_power_library_symbol(
            name,
            value="GND",
            description=spec.description,
            pin_direction=270,
            drawing=_gnd_symbol_drawing(),
            value_y_nm=-2_540_000,
        )
    raise ValueError(f"Unsupported native KiCad symbol: {spec.source_symbol_id}")


def _render_two_pin_box_library_symbol(
    name: str,
    *,
    reference: str,
    value: str,
    description: str,
    drawing: str,
    pin_length_mm: str,
) -> str:
    return f"""  (symbol "{name}"
    (pin_numbers
      (hide yes)
    )
    (pin_names
      (offset 0)
    )
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
    {_render_symbol_property("Reference", reference, 0, -2_540_000)}
    {_render_symbol_property("Value", value, 0, 2_540_000)}
    {_render_symbol_property("Footprint", "", 0, 0, hidden=True)}
    {_render_symbol_property("Datasheet", "~", 0, 0, hidden=True)}
    {_render_symbol_property("Description", description, 0, 0, hidden=True)}
{drawing}
    (symbol "{value}_1_1"
      (pin passive line
        (at -5.08 0 0)
        (length {pin_length_mm})
        (name "1"
          (effects
            (font
              (size 1.27 1.27)
            )
          )
        )
        (number "1"
          (effects
            (font
              (size 1.27 1.27)
            )
          )
        )
      )
      (pin passive line
        (at 5.08 0 180)
        (length {pin_length_mm})
        (name "2"
          (effects
            (font
              (size 1.27 1.27)
            )
          )
        )
        (number "2"
          (effects
            (font
              (size 1.27 1.27)
            )
          )
        )
      )
    )
  )"""


def _render_power_library_symbol(
    name: str,
    *,
    value: str,
    description: str,
    pin_direction: int,
    drawing: str,
    value_y_nm: int,
) -> str:
    return f"""  (symbol "{name}"
    (power)
    (pin_numbers
      (hide yes)
    )
    (pin_names
      (offset 0)
      (hide yes)
    )
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
    {_render_symbol_property("Reference", "#PWR", 0, -3_810_000, hidden=True)}
    {_render_symbol_property("Value", value, 0, value_y_nm)}
    {_render_symbol_property("Footprint", "", 0, 0, hidden=True)}
    {_render_symbol_property("Datasheet", "", 0, 0, hidden=True)}
    {_render_symbol_property("Description", description, 0, 0, hidden=True)}
{drawing}
    (symbol "{value}_1_1"
      (pin power_out line
        (at 0 0 {pin_direction})
        (length 0)
        (name "{value}"
          (effects
            (font
              (size 1.27 1.27)
            )
          )
        )
        (number "1"
          (effects
            (font
              (size 1.27 1.27)
            )
          )
        )
      )
    )
  )"""


def _render_ne555_library_symbol(name: str, description: str) -> str:
    return f"""  (symbol "{name}"
    (pin_numbers
      (hide no)
    )
    (pin_names
      (offset 0.762)
    )
    (exclude_from_sim no)
    (in_bom yes)
    (on_board yes)
    {_render_symbol_property("Reference", "U", 0, -10_160_000)}
    {_render_symbol_property("Value", "NE555", 0, 10_160_000)}
    {_render_symbol_property("Footprint", "", 0, 0, hidden=True)}
    {_render_symbol_property("Datasheet", "~", 0, 0, hidden=True)}
    {_render_symbol_property("Description", description, 0, 0, hidden=True)}
    (symbol "NE555_0_1"
      (rectangle
        (start -5.08 7.62)
        (end 5.08 -7.62)
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type none)
        )
      )
    )
    (symbol "NE555_1_1"
{_ne555_pin("1", "GND", -7.62, 5.08, 0)}
{_ne555_pin("2", "TRIG", -7.62, 2.54, 0)}
{_ne555_pin("3", "OUT", 7.62, -5.08, 180)}
{_ne555_pin("4", "RESET", -7.62, 0, 0)}
{_ne555_pin("5", "CTRL", -7.62, -2.54, 0)}
{_ne555_pin("6", "THRESH", 7.62, 0, 180)}
{_ne555_pin("7", "DISCH", 7.62, 2.54, 180)}
{_ne555_pin("8", "VCC", 7.62, 5.08, 180)}
    )
  )"""


def _ne555_pin(
    number: str,
    name: str,
    x_mm: float,
    y_mm: float,
    direction: int,
) -> str:
    return f"""      (pin passive line
        (at {x_mm:.2f} {y_mm:.2f} {direction})
        (length 2.54)
        (name "{name}"
          (effects
            (font
              (size 1.27 1.27)
            )
          )
        )
        (number "{number}"
          (effects
            (font
              (size 1.27 1.27)
            )
          )
        )
      )"""


def _resistor_symbol_drawing() -> str:
    return """    (symbol "R_0_1"
      (rectangle
        (start -2.54 -1.27)
        (end 2.54 1.27)
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type none)
        )
      )
    )"""


def _capacitor_symbol_drawing() -> str:
    return """    (symbol "C_0_1"
      (polyline
        (pts
          (xy -0.762 1.905) (xy -0.762 -1.905)
        )
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type none)
        )
      )
      (polyline
        (pts
          (xy 0.762 1.905) (xy 0.762 -1.905)
        )
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type none)
        )
      )
    )"""


def _diode_symbol_drawing(symbol_name: str) -> str:
    return f"""    (symbol "{symbol_name}"
      (polyline
        (pts
          (xy -1.27 1.905) (xy -1.27 -1.905) (xy 1.27 0) (xy -1.27 1.905)
        )
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type none)
        )
      )
      (polyline
        (pts
          (xy 1.27 1.905) (xy 1.27 -1.905)
        )
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type none)
        )
      )
    )"""


def _led_symbol_drawing() -> str:
    return f"""{_diode_symbol_drawing("LED_0_1")}
    (symbol "LED_0_2"
      (polyline
        (pts
          (xy 1.524 1.524) (xy 2.794 2.794)
        )
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type none)
        )
      )
      (polyline
        (pts
          (xy 2.032 0.508) (xy 3.302 1.778)
        )
        (stroke
          (width 0.254)
          (type default)
        )
        (fill
          (type none)
        )
      )
    )"""


def _vcc_symbol_drawing() -> str:
    return """      (symbol "VCC_0_1"
        (polyline
          (pts
            (xy 0 0) (xy 0 1.27)
          )
          (stroke
            (width 0)
            (type default)
          )
          (fill
            (type none)
          )
        )
      )"""


def _gnd_symbol_drawing() -> str:
    return """      (symbol "GND_0_1"
        (polyline
          (pts
            (xy 0 0) (xy 0 -1.27) (xy 1.27 -1.27)
            (xy 0 -2.54) (xy -1.27 -1.27) (xy 0 -1.27)
          )
          (stroke
            (width 0)
            (type default)
          )
          (fill
            (type none)
          )
        )
      )"""


def _format_mm(value_nm: int) -> str:
    value = nm_to_mm(value_nm)
    return f"{value:.6f}".rstrip("0").rstrip(".")


def _escape_kicad_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _first_schematic_path(project: Project) -> str:
    if not project.schematics:
        raise ValueError("Project has no schematics")
    return project.schematics[0]


def _first_board_path(project: Project) -> str:
    if not project.boards:
        raise ValueError("Project has no boards")
    return project.boards[0]


def _json_dump(value: object) -> str:
    import json

    return json.dumps(value, indent=2, sort_keys=True) + "\n"


__all__ = [
    "HANDOFF_FILE_NAME",
    "HANDOFF_SCHEMA",
    "KiCadExportResult",
    "export_pcbs_project_to_kicad",
    "render_kicad_board_items",
    "render_kicad_schematic_items",
    "render_handoff_manifest",
    "schematic_handoff_commands",
]
