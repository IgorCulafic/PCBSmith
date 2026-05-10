from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from pcbsmith.core.geom import Point, Vec, nm_to_mm
from pcbsmith.core.project import Project
from pcbsmith.core.schematic import NetLabel, NoConnect, Schematic, SymbolInstance, Wire
from pcbsmith.services.kicad_project import (
    KiCadProjectSkeleton,
    create_kicad_project_skeleton,
    render_kicad_schematic_file,
)
from pcbsmith.services.project_io import load_project, load_schematic

HANDOFF_FILE_NAME = "pcbsmith_handoff.json"
HANDOFF_SCHEMA = "pcbsmith-kicad-handoff-v1"
PCBSMITH_SYMBOL_LIBRARY_FILE_NAME = "PCBSmith.kicad_sym"
PCBSMITH_SYMBOL_TABLE_FILE_NAME = "sym-lib-table"
PCBSMITH_LIBRARY_NAME = "PCBSmith"
KICAD_ZERO_OFFSET = Vec(0, 0)
KICAD_SCHEMATIC_ITEM_OFFSET = Vec(25_400_000, 25_400_000)


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
    schematic = load_schematic(source_project_dir, schematic_path)
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
    native_wires = [
        wire
        for wire in schematic.wires
        if _wire_connects_native_points(wire, pin_points)
    ]
    connected_points = {
        (point.x, point.y) for wire in native_wires for point in wire.points
    } | pin_points

    items: list[str] = []
    items.extend(
        _render_kicad_symbol(
            symbol,
            project_name=project_name,
            offset=KICAD_SCHEMATIC_ITEM_OFFSET,
        )
        for symbol in native_symbols
    )
    items.extend(
        _render_kicad_wire(wire, uuid_factory(), offset=KICAD_SCHEMATIC_ITEM_OFFSET)
        for wire in native_wires
    )
    items.extend(
        _render_kicad_label(
            label,
            uuid_factory(),
            offset=KICAD_SCHEMATIC_ITEM_OFFSET,
        )
        for label in schematic.labels
        if _should_render_native_label(
            label,
            connected_points,
            native_wires,
            power_points,
        )
    )
    items.extend(
        _render_kicad_label(
            label,
            uuid_factory(),
            offset=KICAD_SCHEMATIC_ITEM_OFFSET,
            hidden=True,
        )
        for label in _power_wire_endpoint_labels(native_wires, power_points)
    )
    items.extend(
        _render_kicad_no_connect(
            no_connect,
            uuid_factory(),
            offset=KICAD_SCHEMATIC_ITEM_OFFSET,
        )
        for no_connect in schematic.no_connects
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
    if spec.library_symbol_name == "R":
        return _render_two_pin_box_library_symbol(
            name,
            reference="R",
            value="R",
            description="Generic resistor",
            drawing=_resistor_symbol_drawing(),
        )
    if spec.library_symbol_name == "C":
        return _render_two_pin_box_library_symbol(
            name,
            reference="C",
            value="C",
            description="Generic capacitor",
            drawing=_capacitor_symbol_drawing(),
        )
    if spec.library_symbol_name == "D":
        return _render_two_pin_box_library_symbol(
            name,
            reference="D",
            value="D",
            description="Generic diode",
            drawing=_diode_symbol_drawing("D_0_1"),
        )
    if spec.library_symbol_name == "LED":
        return _render_two_pin_box_library_symbol(
            name,
            reference="LED",
            value="LED",
            description="Generic LED",
            drawing=_led_symbol_drawing(),
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
        (length 0)
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
        (length 0)
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


def _json_dump(value: object) -> str:
    import json

    return json.dumps(value, indent=2, sort_keys=True) + "\n"


__all__ = [
    "HANDOFF_FILE_NAME",
    "HANDOFF_SCHEMA",
    "KiCadExportResult",
    "export_pcbs_project_to_kicad",
    "render_kicad_schematic_items",
    "render_handoff_manifest",
    "schematic_handoff_commands",
]
