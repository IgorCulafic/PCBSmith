"""Generate and verify the approved AeroSense-2F R001 design."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from pcbsmith.generation.aerosense_2f import compose_aerosense_2f
from pcbsmith.kicad.aerosense_2f_board import (
    AEROSENSE_RULE_PROFILE,
    generate_aerosense_placement_board,
    generate_aerosense_routed_board,
    register_aerosense_assets,
)
from pcbsmith.kicad.export_aerosense_2f import (
    INSTANCES,
    NO_CONNECTS,
    export_aerosense_2f_to_kicad,
)
from pcbsmith.kicad.routing_evidence import (
    RoutingArtifactState,
    inspect_saved_board_routing,
)
from pcbsmith.kicad.symbols import load_symbol
from pcbsmith.kicad.validate import (
    export_schematic_svg,
    run_kicad_drc,
    run_kicad_erc,
)
from pcbsmith.kicad.virtual_drc import run_virtual_drc
from pcbsmith.review.visual_package import rasterize_svg_with_resvg

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs" / "aerosense-2f-r001" / "design"
PROJECT_NAME = "aerosense-2f-r001"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pin_population_audit() -> dict[str, object]:
    components: list[dict[str, object]] = []
    incomplete: list[str] = []
    for reference, lib_id, _x, _y, connected in INSTANCES:
        pins = {pin.number for pin in load_symbol(lib_id).pins}
        populated = set(connected)
        no_connects = set(NO_CONNECTS.get(reference, ()))
        missing = sorted(pins - populated - no_connects)
        unknown = sorted((populated | no_connects) - pins)
        if missing or unknown:
            incomplete.append(reference)
        components.append(
            {
                "reference": reference,
                "symbol": lib_id,
                "missing_population": missing,
                "unknown_declared_pins": unknown,
                "status": "complete" if not missing and not unknown else "incomplete",
            }
        )
    if incomplete:
        raise RuntimeError(f"pin population audit failed: {incomplete}")
    return {
        "schema": "pcbsmith-pin-population-audit-v1",
        "status": "passed",
        "component_count": len(components),
        "components": components,
        "incomplete_references": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--stage", choices=("placement", "routed"), default="routed")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    evidence_dir = output / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    register_aerosense_assets(output)

    circuit = compose_aerosense_2f()
    (output / "circuit.json").write_text(
        circuit.model_dump_json(indent=2), encoding="utf-8"
    )
    artifacts = export_aerosense_2f_to_kicad(
        circuit,
        output,
        project_name=PROJECT_NAME,
        profile=AEROSENSE_RULE_PROFILE,
    )
    schematic = Path(artifacts["schematic_file"])
    pin_audit = _pin_population_audit()
    (evidence_dir / "pin-population-audit.json").write_text(
        json.dumps(pin_audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    erc = run_kicad_erc(schematic)
    if erc.status != "passed":
        raise RuntimeError(f"KiCad ERC failed: {erc.findings}")
    schematic_svg, schematic_findings = export_schematic_svg(schematic)
    schematic_png = output / "review" / "schematic" / "schematic.png"
    schematic_png.parent.mkdir(parents=True, exist_ok=True)
    if schematic_svg is not None:
        rasterize_svg_with_resvg(
            Path(schematic_svg), schematic_png, 3840, 2715, None
        )

    board = output / (
        f"{PROJECT_NAME}.kicad_pcb"
        if args.stage == "routed"
        else f"{PROJECT_NAME}-placement.kicad_pcb"
    )
    generator = (
        generate_aerosense_routed_board
        if args.stage == "routed"
        else generate_aerosense_placement_board
    )
    netlist, layout = generator(schematic_file=schematic, board_file=board)
    virtual = run_virtual_drc(layout, netlist, AEROSENSE_RULE_PROFILE)
    virtual_summary = {
        "schema": "pcbsmith-aerosense-virtual-drc-v1",
        "stage": args.stage,
        "finding_counts": dict(
            sorted(Counter(finding.check for finding in virtual).items())
        ),
        "findings": [
            {
                "check": finding.check,
                "message": finding.message,
            }
            for finding in virtual
        ],
    }
    (evidence_dir / f"virtual-drc-{args.stage}.json").write_text(
        json.dumps(virtual_summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    drc = run_kicad_drc(board) if args.stage == "routed" else None
    routing = (
        inspect_saved_board_routing(board) if args.stage == "routed" else None
    )
    if routing is not None:
        (evidence_dir / "routing-evidence.json").write_text(
            routing.model_dump_json(indent=2), encoding="utf-8"
        )
    gate_failures: list[str] = []
    if args.stage == "placement":
        placement_blockers = tuple(
            finding
            for finding in virtual
            if finding.check != "pad_connectivity"
        )
        if placement_blockers:
            gate_failures.append(
                f"{len(placement_blockers)} placement geometry finding(s)"
            )
    else:
        if virtual:
            gate_failures.append(
                f"{len(virtual)} routed virtual-DRC finding(s)"
            )
        if drc is None or drc.status != "passed":
            gate_failures.append("KiCad DRC did not pass")
        if (
            routing is None
            or routing.state is not RoutingArtifactState.ROUTED_CANDIDATE
            or routing.uncovered_net_names
        ):
            gate_failures.append("saved board is not a fully covered routed candidate")
    summary = {
        "schema": "pcbsmith-aerosense-generation-summary-v1",
        "stage": args.stage,
        "board_file": str(board),
        "board_sha256": _sha256(board),
        "schematic_file": str(schematic),
        "schematic_sha256": _sha256(schematic),
        "component_count": len(netlist.components),
        "net_count": len(netlist.nets),
        "segment_count": len(layout.segments),
        "via_count": len(layout.vias),
        "erc": erc.model_dump(mode="json"),
        "drc": drc.model_dump(mode="json") if drc is not None else None,
        "routing": (
            routing.model_dump(mode="json") if routing is not None else None
        ),
        "schematic_export_findings": list(schematic_findings),
        "virtual_drc_counts": virtual_summary["finding_counts"],
        "hard_gate": {
            "status": "passed" if not gate_failures else "failed",
            "failures": gate_failures,
        },
    }
    (evidence_dir / f"generation-summary-{args.stage}.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    if gate_failures:
        raise RuntimeError(
            "AeroSense generation hard gate failed: " + "; ".join(gate_failures)
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
