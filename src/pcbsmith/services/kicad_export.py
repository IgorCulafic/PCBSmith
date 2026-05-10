from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict

from pcbsmith.core.geom import Point
from pcbsmith.core.project import Project
from pcbsmith.core.schematic import NetLabel, NoConnect, Schematic, SymbolInstance, Wire
from pcbsmith.services.kicad_project import KiCadProjectSkeleton, create_kicad_project_skeleton
from pcbsmith.services.project_io import load_project, load_schematic

HANDOFF_FILE_NAME = "pcbsmith_handoff.json"
HANDOFF_SCHEMA = "pcbsmith-kicad-handoff-v1"


class KiCadExportResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    skeleton: KiCadProjectSkeleton
    handoff_file: Path


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
    "render_handoff_manifest",
    "schematic_handoff_commands",
]
