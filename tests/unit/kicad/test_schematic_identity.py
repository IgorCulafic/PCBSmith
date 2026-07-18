from __future__ import annotations

import ast
import re
from pathlib import Path
from uuid import UUID

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.generation.divider_highpass_led import compose_divider_highpass_led
from pcbsmith.kicad.export_divider_highpass_led import (
    _render_schematic,
    _wire,
)
from pcbsmith.kicad.reader_schematic import (
    ReaderInstance,
    ReaderSpec,
    render_reader_schematic,
)

KICAD_SOURCE = Path(__file__).resolve().parents[3] / "src" / "pcbsmith" / "kicad"
UUID_PATTERN = re.compile(
    r'\(uuid\s+"?([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-'
    r'[0-9a-f]{4}-[0-9a-f]{12})"?\)'
)


def _circuit():
    intent = classify_circuit_intent("voltage divider high-pass LED indicator")
    return compose_divider_highpass_led(intent, select_topology(intent))


def _uuids(rendered: str) -> list[str]:
    return UUID_PATTERN.findall(rendered)


def _assert_unique_v5_uuids(rendered: str) -> None:
    values = _uuids(rendered)
    assert values
    assert len(values) == len(set(values))
    assert all(UUID(value).version == 5 for value in values)


def _uuid4_sites(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported_functions: set[str] = set()
    imported_modules: set[str] = set()
    sites: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "uuid":
            for alias in node.names:
                if alias.name == "uuid4":
                    imported_functions.add(alias.asname or alias.name)
                    sites.append(f"{path.name}:{node.lineno}: import uuid4")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "uuid":
                    imported_modules.add(alias.asname or alias.name)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if (
            isinstance(node.func, ast.Name)
            and node.func.id in imported_functions
        ):
            sites.append(f"{path.name}:{node.lineno}: call {node.func.id}")
        elif (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "uuid4"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in imported_modules
        ):
            sites.append(
                f"{path.name}:{node.lineno}: call {node.func.value.id}.uuid4"
            )
    return sites


def test_production_kicad_generators_do_not_import_or_call_uuid4() -> None:
    sites = [
        site
        for path in sorted(KICAD_SOURCE.rglob("*.py"))
        for site in _uuid4_sites(path)
    ]
    assert sites == []


def test_machine_schematic_is_byte_repeatable_with_unique_v5_uuids() -> None:
    circuit = _circuit()
    first = _render_schematic(circuit, "StableMachine")
    second = _render_schematic(circuit, "StableMachine")

    assert first == second
    _assert_unique_v5_uuids(first)


def test_reader_schematic_is_byte_repeatable_with_unique_v5_uuids() -> None:
    circuit = _circuit()
    spec = ReaderSpec(
        instances=(
            ReaderInstance("R1", "Device:R", (50.8, 50.8)),
            ReaderInstance("R2", "Device:R", (50.8, 76.2)),
        ),
        wires=(
            ((50.8, 46.99), (50.8, 40.64)),
            ((50.8, 54.61), (50.8, 72.39)),
            ((50.8, 80.01), (50.8, 88.9)),
        ),
        labels=(
            ("VCC", (50.8, 40.64)),
            ("MID", (50.8, 63.5)),
            ("GND", (50.8, 88.9)),
        ),
    )
    pin_nets = {
        "R1": {"1": "VCC", "2": "MID"},
        "R2": {"1": "MID", "2": "GND"},
    }
    first = render_reader_schematic(
        circuit, spec, project_name="StableReader", pin_nets=pin_nets
    )
    second = render_reader_schematic(
        circuit, spec, project_name="StableReader", pin_nets=pin_nets
    )

    assert first == second
    _assert_unique_v5_uuids(first)


def test_wire_identity_is_direction_independent_and_occurrence_explicit() -> None:
    forward = _uuids(_wire((1.0, 2.0), (3.0, 4.0)))[0]
    reverse = _uuids(_wire((3.0, 4.0), (1.0, 2.0)))[0]
    second_occurrence = _uuids(
        _wire((1.0, 2.0), (3.0, 4.0), occurrence=1)
    )[0]

    assert forward == reverse
    assert second_occurrence != forward
