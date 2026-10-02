"""Generate and freeze two materially different Phase 17 W10 proof boards."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from pcbsmith.generators.circuit_examples import (
    Timer555AstableCircuit,
    export_timer_555_astable_kicad_project,
)
from pcbsmith.kicad.library import QuotedString, SExpr, parse_sexpr, serialize_sexpr
from pcbsmith.operations.design_operations import (
    BuckConverterDesignRequest,
    generate_buck_converter_design,
)


@dataclass(frozen=True)
class ProofCase:
    case_id: str
    slug: str
    title: str
    tier: str
    purpose: str
    net_widths_mm: dict[str, float]
    expected_current_paths: tuple[dict[str, object], ...]
    required_refdes_refs: tuple[str, ...]
    required_polarity_refs: tuple[str, ...]
    required_connector_mating_refs: tuple[str, ...]
    generator: Callable[[Path], None]


def _generate_signal_case(case_dir: Path) -> None:
    source_model = case_dir.parent / f".{case_dir.name}-source-model"
    export_timer_555_astable_kicad_project(
        source_model,
        case_dir,
        Timer555AstableCircuit(
            name="W10A NE555 Status Pulser",
            supply_voltage="5V",
            timing_resistor_a="10k",
            timing_resistor_b="100k",
            timing_capacitor="10uF",
            decoupling_capacitor="100nF",
            control_capacitor="10nF",
            led_resistor="680",
            led_value="Red LED",
        ),
    )
    shutil.move(source_model, case_dir / "source-model")


def _generate_power_case(case_dir: Path) -> None:
    generate_buck_converter_design(
        BuckConverterDesignRequest(
            name="W10B 12V to 5V Buck",
            input_voltage_min_v=9.0,
            input_voltage_nominal_v=12.0,
            input_voltage_max_v=16.0,
            output_voltage_v=5.0,
            load_current_a=1.0,
        ),
        case_dir,
        execute_kicad=False,
    )


CASES = (
    ProofCase(
        case_id="W10A",
        slug="ne555-status-pulser",
        title="NE555 status pulser",
        tier="beginner",
        purpose=(
            "Signal/timing proof with an eight-pin IC, decoupling, polarized LED and "
            "timing capacitor, mixed front/back routing, and no ampacity claim."
        ),
        net_widths_mm={
            "VCC": 0.50,
            "GND": 0.50,
            "DISCH": 0.30,
            "TIMING": 0.30,
            "CTRL": 0.30,
            "OUT": 0.30,
            "LED_A": 0.30,
        },
        expected_current_paths=(),
        required_refdes_refs=("J1", "U1", "R1", "R2", "C1", "C2", "C3", "R3", "LED1"),
        required_polarity_refs=("LED1",),
        required_connector_mating_refs=(),
        generator=_generate_signal_case,
    ),
    ProofCase(
        case_id="W10B",
        slug="12v-to-5v-buck",
        title="12 V to 5 V, 1 A buck converter",
        tier="medium",
        purpose=(
            "Power proof with 1 A source-to-sink paths, a switching node, feedback, "
            "polarized diode/capacitor obligations, and connector accessibility."
        ),
        net_widths_mm={
            "VIN": 1.00,
            "GND": 1.00,
            "SW": 1.00,
            "VOUT": 1.00,
            "FB": 0.30,
        },
        required_refdes_refs=("J1", "J2", "U1", "L1", "D1", "CIN", "COUT", "RFB1", "RFB2"),
        expected_current_paths=(
            {
                "path_id": "input-power",
                "source": "J1.1",
                "sink": "U1.1",
                "return_source": "U1.3",
                "return_sink": "J1.2",
                "current_a": 0.75,
                "requires_ampacity_claim": True,
            },
            {
                "path_id": "output-power",
                "source": "L1.2",
                "sink": "J2.1",
                "return_source": "J2.2",
                "return_sink": "U1.3",
                "current_a": 1.0,
                "requires_ampacity_claim": True,
            },
        ),
        required_polarity_refs=("CIN", "COUT", "D1"),
        required_connector_mating_refs=("J1", "J2"),
        generator=_generate_power_case,
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    destination = args.output.resolve()
    if destination.exists():
        raise FileExistsError(f"proof output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="w10-proof-", dir=destination.parent) as raw:
        root = Path(raw)
        (root / "boards").mkdir(parents=True)
        records = []
        for case in CASES:
            case_dir = root / "boards" / f"{case.case_id}-{case.slug}"
            case.generator(case_dir)
            project = _single(case_dir, "*.kicad_pro")
            schematic = _single(case_dir, "*.kicad_sch")
            routed_reference = _single(case_dir, "*.kicad_pcb")
            reference_copy = case_dir / f"{case.case_id}-{case.slug}-reference-routed.kicad_pcb"
            shutil.copy2(routed_reference, reference_copy)
            placement = case_dir / f"{case.case_id}-{case.slug}-placement.kicad_pcb"
            placement.write_text(
                _placement_only_text(routed_reference.read_text(encoding="utf-8")),
                encoding="utf-8",
            )
            contract = {
                "schema": "pcbsmith-w10-proof-case-v1",
                "case_id": case.case_id,
                "title": case.title,
                "tier": case.tier,
                "layers": 2,
                "purpose": case.purpose,
                "placement_board": placement.name,
                "placement_board_sha256": _sha256(placement),
                "reference_routed_board": reference_copy.name,
                "reference_routed_board_sha256": _sha256(reference_copy),
                "project_file": project.name,
                "project_file_sha256": _sha256(project),
                "schematic_file": schematic.name,
                "schematic_file_sha256": _sha256(schematic),
                "nets": [
                    {"name": name, "width_mm": width}
                    for name, width in sorted(case.net_widths_mm.items())
                ],
                "expected_current_paths": list(case.expected_current_paths),
                "required_refdes_refs": list(case.required_refdes_refs),
                "required_polarity_refs": list(case.required_polarity_refs),
                "required_connector_mating_refs": list(case.required_connector_mating_refs),
                "required_review_artifact_ids": [
                    "2d:front-design:png",
                    "2d:back-design:png",
                    "2d:front-copper:png",
                    "2d:back-copper:png",
                    "2d:combined-copper:png",
                ],
                "qualification_boundary": (
                    "A generated proof candidate is not release-qualified until every W7-W10 "
                    "gate is bound to the exact final saved-board revision."
                ),
            }
            _write_json(case_dir / "case-contract.json", contract)
            records.append(contract)
        protocol = {
            "schema": "pcbsmith-phase17-w10-proof-protocol-v1",
            "case_count": len(records),
            "layers": 2,
            "case_ids": [item["case_id"] for item in records],
            "material_difference": (
                "W10A is a low-current timing/control board; W10B is a switching-power board "
                "with declared 1 A paths and wider copper."
            ),
            "failure_policy": (
                "Retain every result; do not resize, weaken rules, add layers, or regenerate "
                "the whole board in response to a local failure."
            ),
            "unseen_policy": (
                "Neither exact board revision existed during W3/W7-W9 implementation. No "
                "proof-specific gate exception is allowed after contract freeze."
            ),
            "gate_order": [
                "geometry",
                "topology",
                "placement",
                "local_fanout",
                "routing",
                "final_fill",
                "exact_checks",
                "repair",
                "review",
            ],
            "cases": records,
        }
        _write_json(root / "protocol.json", protocol)
        _write_manifest(root)
        os.replace(root, destination)
    print(json.dumps({"output": str(destination), "case_count": len(CASES)}))
    return 0


def _single(root: Path, pattern: str) -> Path:
    matches = tuple(root.glob(pattern))
    if len(matches) != 1:
        raise ValueError(f"expected one {pattern} in {root}, found {len(matches)}")
    return matches[0]


def _placement_only_text(board_text: str) -> str:
    root = parse_sexpr(board_text)
    if not isinstance(root, list):
        raise ValueError("KiCad board root must be a list")
    retained: list[SExpr] = []
    for item in root:
        if isinstance(item, list) and item:
            head = _atom(item[0])
            if head in {"segment", "via", "zone"}:
                continue
        retained.append(item)
    return serialize_sexpr(retained) + "\n"


def _atom(value: SExpr) -> str:
    return value.value if isinstance(value, QuotedString) else str(value)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_manifest(root: Path) -> None:
    files = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name == "artifact-manifest.json":
            continue
        files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": _sha256(path),
                "bytes": path.stat().st_size,
            }
        )
    _write_json(root / "artifact-manifest.json", {"files": files})


if __name__ == "__main__":
    raise SystemExit(main())
