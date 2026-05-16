from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pcbsmith.core.geom import Point, nm_to_mm
from pcbsmith.core.schematic import Schematic, SymbolInstance
from pcbsmith.services.board_conventions import board_annotation_rules_summary
from pcbsmith.services.board_feature_intent import board_feature_tool_contract
from pcbsmith.services.board_intelligence import board_routing_rules_summary
from pcbsmith.services.circuit_rules import circuit_rules_tool_contract
from pcbsmith.services.component_selection import component_selection_tool_contract
from pcbsmith.services.project_io import load_project, load_schematic

AI_CONTEXT_SCHEMA = "pcbsmith-ai-context-v1"


def build_ai_context(
    project_dir: Path,
    *,
    kicad_project_dir: Path | None = None,
) -> dict[str, Any]:
    project = load_project(project_dir)
    schematics = tuple(
        (path, load_schematic(project_dir, path)) for path in project.schematics
    )
    context: dict[str, Any] = {
        "schema": AI_CONTEXT_SCHEMA,
        "project": {
            "name": project.name,
            "version": project.version,
            "schematics": list(project.schematics),
            "boards": list(project.boards),
        },
        "ai_tools": {
            "component_selection": component_selection_tool_contract(),
            "circuit_rules": circuit_rules_tool_contract(),
            "board_feature_intent": board_feature_tool_contract(),
        },
        "schematics": [
            _schematic_summary(path, schematic) for path, schematic in schematics
        ],
    }
    if kicad_project_dir is not None:
        context["kicad"] = _kicad_context(kicad_project_dir)
    return context


def write_ai_context(
    project_dir: Path,
    output_path: Path,
    *,
    kicad_project_dir: Path | None = None,
) -> None:
    context = build_ai_context(project_dir, kicad_project_dir=kicad_project_dir)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(context, indent=2) + "\n", encoding="utf-8")


def _schematic_summary(path: str, schematic: Schematic) -> dict[str, Any]:
    return {
        "path": path,
        "id": schematic.id,
        "symbol_count": len(schematic.symbols),
        "wire_count": len(schematic.wires),
        "label_count": len(schematic.labels),
        "no_connect_count": len(schematic.no_connects),
        "symbols": [_symbol_summary(symbol) for symbol in schematic.symbols],
    }


def _symbol_summary(symbol: SymbolInstance) -> dict[str, Any]:
    return {
        "reference": symbol.reference,
        "symbol_id": symbol.symbol_id,
        "value": symbol.value,
        "position_mm": _point_mm(symbol.position),
        "rotation_deg": symbol.rotation_deg,
        "footprint_id": symbol.footprint_id,
    }


def _point_mm(point: Point) -> dict[str, float]:
    return {"x": nm_to_mm(point.x), "y": nm_to_mm(point.y)}


def _kicad_context(kicad_project_dir: Path) -> dict[str, Any]:
    return {
        "project_dir": str(kicad_project_dir),
        "board_rules": _board_rules(),
        "annotation_rules": _annotation_rules(),
        "board_layers": _board_layers(),
        "reports": _kicad_reports(kicad_project_dir),
        "visuals": _kicad_visuals(kicad_project_dir),
    }


def _board_rules() -> dict[str, object]:
    return board_routing_rules_summary()


def _annotation_rules() -> dict[str, object]:
    return board_annotation_rules_summary()


def _board_layers() -> list[dict[str, object]]:
    return [
        {"id": "F.Cu", "role": "front_copper", "routing": True},
        {"id": "B.Cu", "role": "back_copper", "routing": False},
        {"id": "F.SilkS", "role": "front_silkscreen", "routing": False},
        {"id": "B.SilkS", "role": "back_silkscreen", "routing": False},
        {"id": "Edge.Cuts", "role": "board_outline", "routing": False},
    ]


def _kicad_reports(kicad_project_dir: Path) -> list[dict[str, Any]]:
    report_dir = kicad_project_dir / ".pcbsmith" / "kicad-reports"
    reports = []
    for name in ("erc", "drc"):
        path = report_dir / f"{name}.json"
        if path.exists():
            reports.append(_report_summary(name, path))
    board_report = kicad_project_dir / ".pcbsmith" / "board-reports" / "manufacturability.json"
    if board_report.exists():
        reports.append(_manufacturability_report_summary(board_report))
    return reports


def _report_summary(name: str, path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if name == "erc":
        violations = sum(
            len(sheet.get("violations", [])) for sheet in data.get("sheets", [])
        )
        unconnected_items = 0
    else:
        violations = len(data.get("violations", []))
        unconnected_items = len(data.get("unconnected_items", []))
    return {
        "name": name,
        "path": str(path),
        "violations": violations,
        "unconnected_items": unconnected_items,
    }


def _manufacturability_report_summary(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    summary = data.get("summary", {})
    return {
        "name": "manufacturability",
        "path": str(path),
        "violations": 0,
        "unconnected_items": 0,
        "findings": summary.get("finding_count", 0),
        "errors": summary.get("error_count", 0),
        "warnings": summary.get("warning_count", 0),
    }


def _kicad_visuals(kicad_project_dir: Path) -> list[str]:
    visual_dir = kicad_project_dir / ".pcbsmith" / "visual"
    if not visual_dir.exists():
        return []
    return [
        str(path)
        for path in sorted(
            (
                *visual_dir.glob("*.png"),
                *visual_dir.glob("*.svg"),
            )
        )
    ]


__all__ = [
    "AI_CONTEXT_SCHEMA",
    "build_ai_context",
    "write_ai_context",
]
