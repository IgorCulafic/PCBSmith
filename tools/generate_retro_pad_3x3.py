"""Generate the unrouted rectangular 3x3 Retro-Pad placement package."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from pcbsmith.generation.retro_pad_3x3 import compose_retro_pad_3x3
from pcbsmith.kicad.export_retro_pad import export_retro_pad_to_kicad
from pcbsmith.kicad.model_preflight import (
    ModelRegistryEntry,
    ModelRequirement,
    preflight_board_models,
)
from pcbsmith.kicad.retro_pad_3x3_board import (
    generate_retro_pad_3x3_placement_board,
)
from pcbsmith.kicad.retro_pad_3x3_schematic import (
    NO_CONNECTS_3X3,
    RETRO_PAD_3X3_SCHEMATIC_INSTANCES,
)
from pcbsmith.kicad.retro_pad_board import RETRO_PAD_RULE_PROFILE
from pcbsmith.kicad.retro_pad_models import generate_retro_pad_proxy_models
from pcbsmith.kicad.symbols import load_symbol
from pcbsmith.kicad.validate import export_schematic_svg, run_kicad_erc
from pcbsmith.kicad.virtual_drc import run_virtual_drc
from pcbsmith.review.visual_package import (
    DetailRegion,
    ReviewFeatures,
    generate_visual_review_package,
    rasterize_svg_with_resvg,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs" / "retro-pad-3x3-r001"
PROJECT_NAME = "retro-pad-3x3-r001"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_predesign_record(output: Path) -> None:
    predesign = output / "predesign"
    predesign.mkdir(parents=True, exist_ok=True)
    record = {
        "schema": "pcbsmith-retro-pad-3x3-predesign-v1",
        "project_id": PROJECT_NAME,
        "status": "requirements_interpreted_placement_pending",
        "request_basis": (
            "User requested a similar regular-shape board with a centered 3x3 "
            "button matrix, upper-right encoder, and open lower corners."
        ),
        "target_envelope_mm": [120.0, 100.0],
        "placement_contract": {
            "outline": "standard rectangular PCB",
            "switches": "centered 3x3 array at 19.05 mm pitch",
            "encoder": "upper-right front",
            "usb_c": "centered and flush with top edge",
            "lower_corners": "front-side component-free except mounting holes",
            "routing": "prohibited until user approves the placement package",
        },
    }
    (predesign / "decision.json").write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (predesign / "brief.md").write_text(
        """# Retro-Pad 3x3 placement brief

Status: requirements interpreted; exact KiCad placement awaiting review.

- 120 x 100 mm standard rectangular two-layer board.
- Nine Cherry MX footprints in a centered 3x3 matrix at 19.05 mm pitch.
- One series diode per key; three row and three column nets.
- Nine reverse-mount SK6812MINI-E pixels and aligned 2 mm optical apertures.
- EC11 encoder in the upper-right; USB-C centered on the straight top edge.
- Open lower-left and lower-right front areas, with support electronics concentrated
  on the back and in the lower-center band.
- Stop before routing and obtain user approval of the engineering placement renders.
""",
        encoding="utf-8",
    )


def _pin_population_audit() -> dict[str, object]:
    components: list[dict[str, object]] = []
    incomplete: list[str] = []
    for reference, lib_id, _x, _y, connected in RETRO_PAD_3X3_SCHEMATIC_INSTANCES:
        symbol_pins = {pin.number for pin in load_symbol(lib_id).pins}
        connected_pins = set(connected)
        no_connect_pins = set(NO_CONNECTS_3X3.get(reference, ()))
        missing = sorted(symbol_pins - connected_pins - no_connect_pins)
        unknown = sorted((connected_pins | no_connect_pins) - symbol_pins)
        status = "complete" if not missing and not unknown else "incomplete"
        if status != "complete":
            incomplete.append(reference)
        components.append(
            {
                "reference": reference,
                "symbol": lib_id,
                "symbol_pin_count": len(symbol_pins),
                "connected_pins": sorted(connected_pins),
                "intentional_no_connect_pins": sorted(no_connect_pins),
                "missing_population": missing,
                "unknown_declared_pins": unknown,
                "status": status,
            }
        )
    audit: dict[str, object] = {
        "schema": "pcbsmith-pin-population-audit-v1",
        "status": "passed" if not incomplete else "failed",
        "component_count": len(components),
        "components": components,
        "footprint_only_mechanical_pads": {"SW10": ["MP"]},
        "incomplete_references": incomplete,
    }
    if incomplete:
        raise RuntimeError(f"pin population audit failed: {incomplete}")
    return audit


def main() -> int:
    args = _parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    _write_predesign_record(output)
    generate_retro_pad_proxy_models(output)

    circuit = compose_retro_pad_3x3()
    (output / "circuit.json").write_text(
        circuit.model_dump_json(indent=2), encoding="utf-8"
    )
    artifacts = export_retro_pad_to_kicad(
        circuit,
        output,
        project_name=PROJECT_NAME,
        profile=RETRO_PAD_RULE_PROFILE,
        instances=RETRO_PAD_3X3_SCHEMATIC_INSTANCES,
        no_connects=NO_CONNECTS_3X3,
    )
    schematic = Path(artifacts["schematic_file"])
    evidence = output / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    pin_audit = _pin_population_audit()
    (evidence / "pin-population-audit.json").write_text(
        json.dumps(pin_audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    erc = run_kicad_erc(schematic)
    schematic_svg, schematic_findings = export_schematic_svg(schematic)
    schematic_review = output / "review" / "schematic" / "schematic.png"
    schematic_review.parent.mkdir(parents=True, exist_ok=True)
    if schematic_svg is not None:
        rasterize_svg_with_resvg(Path(schematic_svg), schematic_review, 3840, 2715, None)

    board = output / f"{PROJECT_NAME}-placement.kicad_pcb"
    netlist, layout = generate_retro_pad_3x3_placement_board(
        schematic_file=schematic,
        board_file=board,
    )
    virtual_findings = run_virtual_drc(layout, netlist, RETRO_PAD_RULE_PROFILE)
    placement_blockers = tuple(
        finding
        for finding in virtual_findings
        if finding.check not in {"pad_connectivity", "silk_over_pad"}
    )
    if placement_blockers:
        raise RuntimeError(
            "placement geometry audit failed: "
            + "; ".join(finding.message for finding in placement_blockers)
        )
    geometry_audit = {
        "schema": "pcbsmith-retro-pad-placement-geometry-audit-v1",
        "status": "passed",
        "blocking_findings": [],
        "expected_unrouted_findings": dict(
            sorted(Counter(finding.check for finding in virtual_findings).items())
        ),
    }
    (evidence / "placement-geometry-audit.json").write_text(
        json.dumps(geometry_audit, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    inventory = preflight_board_models(board)
    registry_by_path: dict[str, ModelRegistryEntry] = {}
    for item in inventory.models:
        if item.status != "resolved" or item.resolved_path is None:
            continue
        is_proxy = item.raw_path.startswith("${KIPRJMOD}/models/retro-pad-")
        registry_by_path[item.raw_path] = ModelRegistryEntry(
            raw_path=item.raw_path,
            local_path=item.resolved_path,
            expected_sha256=item.sha256,
            classification="proxy" if is_proxy else "exact_package",
            license_status=(
                "project_generated_visual_proxy"
                if is_proxy
                else "KiCad_official_library_local_install"
            ),
            source_url=(
                None
                if is_proxy
                else "https://gitlab.com/kicad/libraries/kicad-packages3D"
            ),
            redistributable=is_proxy,
        )
    required_models = (
        "J1", "J2", "U1", "U2", "SW10",
        *(f"SW{index}" for index in range(1, 10)),
        *(f"D{index}" for index in range(10, 19)),
    )
    preflight = preflight_board_models(
        board,
        registry=tuple(registry_by_path.values()),
        requirements=tuple(
            ModelRequirement(
                reference=reference,
                accepted_classifications=(
                    ("proxy", "exact_package")
                    if reference.startswith("SW")
                    else ("exact_package", "complete_module")
                ),
            )
            for reference in required_models
        ),
    )
    visual = generate_visual_review_package(
        board_file=board,
        output_dir=output,
        stage="placement",
        features=ReviewFeatures(
            has_bottom_components=True,
            has_zones=True,
            has_cutouts=True,
            has_vias=False,
            declared_classes=(),
            detail_regions=(
                DetailRegion(
                    region_id="matrix-front",
                    bounds_mm=(27.0, 17.0, 91.0, 82.0),
                    reason="3x3 switch, LED, aperture, and label alignment",
                    side="front",
                ),
                DetailRegion(
                    region_id="encoder-usb-front",
                    bounds_mm=(48.0, 0.0, 118.0, 38.0),
                    reason="USB edge and upper-right encoder clearance",
                    side="front",
                ),
                DetailRegion(
                    region_id="lower-corners-front",
                    bounds_mm=(0.0, 78.0, 120.0, 100.0),
                    reason="requested open lower-left and lower-right areas",
                    side="front",
                ),
                DetailRegion(
                    region_id="support-back",
                    bounds_mm=(5.0, 0.0, 110.0, 98.0),
                    reason="controller, USB, key diode, LED, and encoder support placement",
                    side="back",
                ),
            ),
        ),
        model_preflight=preflight,
    )
    summary = {
        "schema": "pcbsmith-retro-pad-3x3-placement-summary-v1",
        "status": "generated_pending_agent_and_user_inspection",
        "board_file": str(board),
        "board_sha256": _sha256(board),
        "schematic_file": str(schematic),
        "schematic_sha256": _sha256(schematic),
        "component_count": len(netlist.components),
        "placement_count": len(layout.placements),
        "outline_size_mm": [layout.width_mm, layout.height_mm],
        "erc": erc.model_dump(mode="json"),
        "pin_population_audit": pin_audit,
        "placement_geometry_audit": geometry_audit,
        "schematic_export_findings": list(schematic_findings),
        "model_preflight": preflight.model_dump(mode="json"),
        "visual_review": visual.model_dump(mode="json", by_alias=True),
    }
    (evidence / "placement-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "stage": "placement",
                "board": str(board),
                "erc": erc.status,
                "models": preflight.status,
                "visual_review": visual.package_status,
                "outline_mm": [layout.width_mm, layout.height_mm],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
