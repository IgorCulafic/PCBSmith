"""Generate and authority-check the Retro-Pad proof-of-concept project."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pcbsmith.generation.retro_pad import compose_retro_pad
from pcbsmith.kicad.board import render_board_previews
from pcbsmith.kicad.design_checks import run_design_checks
from pcbsmith.kicad.export_retro_pad import export_retro_pad_to_kicad
from pcbsmith.kicad.model_preflight import (
    ModelRegistryEntry,
    ModelRequirement,
    preflight_board_models,
)
from pcbsmith.kicad.retro_pad_board import (
    RETRO_PAD_RULE_PROFILE,
    generate_retro_pad_board,
    generate_retro_pad_placement_board,
    retro_pad_checks_spec,
)
from pcbsmith.kicad.retro_pad_models import generate_retro_pad_proxy_models
from pcbsmith.kicad.validate import export_schematic_svg, run_kicad_drc, run_kicad_erc
from pcbsmith.predesign_gate import require_concept_approval
from pcbsmith.review.visual_package import (
    DetailRegion,
    ReviewFeatures,
    generate_visual_review_package,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs" / "retro-pad-r002"
DEFAULT_SOURCE = DEFAULT_OUTPUT
DEFAULT_ASSETS = ROOT / "outputs" / "retro-pad-r001"
PROJECT_NAME = "retro-pad"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require_placement_inspection(output: Path, placement_board: Path) -> None:
    inspection_file = output / "evidence" / "placement-inspection.json"
    manifest_file = output / "review" / "manifest.json"
    if not inspection_file.exists() or not manifest_file.exists():
        raise RuntimeError("final routing requires a retained placement inspection")
    inspection = json.loads(inspection_file.read_text(encoding="utf-8"))
    if inspection.get("status") != "passed":
        raise RuntimeError("placement inspection has not passed")
    expected = {
        "board_sha256": _sha256(placement_board),
        "review_manifest_sha256": _sha256(manifest_file),
    }
    for field, live_hash in expected.items():
        if inspection.get(field) != live_hash:
            raise RuntimeError(f"placement inspection is stale: {field}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    parser.add_argument("--stage", choices=("placement", "final"), default="final")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    output = args.output.resolve()
    source = args.source.resolve()
    assets = args.assets.resolve()
    require_concept_approval(
        project_id="retro-pad",
        normalized_brief_file=source / "predesign" / "normalized-brief.json",
        concept_review_file=source / "predesign" / "concept-review.json",
        approval_file=source / "predesign" / "concept-approval.json",
    )
    output.mkdir(parents=True, exist_ok=True)
    generate_retro_pad_proxy_models(output)
    circuit = compose_retro_pad()
    (output / "circuit.json").write_text(circuit.model_dump_json(indent=2), encoding="utf-8")
    artifacts = export_retro_pad_to_kicad(
        circuit,
        output,
        project_name=PROJECT_NAME,
        profile=RETRO_PAD_RULE_PROFILE,
    )
    schematic = Path(artifacts["schematic_file"])
    erc = run_kicad_erc(schematic)
    schematic_svg, schematic_findings = export_schematic_svg(schematic)

    placement_board = output / f"{PROJECT_NAME}-placement.kicad_pcb"
    _, placement_layout = generate_retro_pad_placement_board(
        schematic_file=schematic,
        board_file=placement_board,
        outline_file=assets / "input" / "board_outline.png",
        silkscreen_file=assets / "input" / "silkscreen_art.png",
    )
    evidence = output / "evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    if args.stage == "placement":
        placement_preflight = preflight_board_models(placement_board)
        placement_visual = generate_visual_review_package(
            board_file=placement_board,
            output_dir=output,
            stage="placement",
            features=ReviewFeatures(
                has_bottom_components=True,
                has_zones=True,
                has_cutouts=True,
                has_vias=False,
                declared_classes=(),
                detail_regions=(),
            ),
            model_preflight=placement_preflight,
        )
        placement_summary = {
            "schema": "pcbsmith-retro-pad-placement-summary-v1",
            "board_file": str(placement_board),
            "placements": len(placement_layout.placements),
            "visual_review": placement_visual.model_dump(mode="json", by_alias=True),
        }
        (evidence / "placement-summary.json").write_text(
            json.dumps(placement_summary, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(
            json.dumps(
                {
                    "stage": "placement",
                    "board": str(placement_board),
                    "visual_review": placement_visual.package_status,
                },
                indent=2,
            )
        )
        return 0
    _require_placement_inspection(output, placement_board)

    board = output / f"{PROJECT_NAME}.kicad_pcb"
    board_netlist, layout = generate_retro_pad_board(
        schematic_file=schematic,
        board_file=board,
        outline_file=assets / "input" / "board_outline.png",
        silkscreen_file=assets / "input" / "silkscreen_art.png",
    )
    design_review = run_design_checks(
        layout,
        board_netlist,
        retro_pad_checks_spec(),
        RETRO_PAD_RULE_PROFILE,
    )
    drc = run_kicad_drc(board)
    previews, preview_findings = render_board_previews(board)

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
                None if is_proxy else "https://gitlab.com/kicad/libraries/kicad-packages3D"
            ),
            redistributable=is_proxy,
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
            for reference in (
                "J1",
                "U1",
                "U2",
                "SW1",
                "SW2",
                "SW3",
                "SW4",
                "SW5",
                "D5",
                "D6",
                "D7",
                "D8",
            )
        ),
    )
    (evidence / "model-preflight.json").write_text(
        preflight.model_dump_json(indent=2, by_alias=True), encoding="utf-8"
    )
    visual = generate_visual_review_package(
        board_file=board,
        output_dir=output,
        stage="final",
        features=ReviewFeatures(
            has_bottom_components=True,
            has_zones=True,
            has_cutouts=True,
            has_vias=bool(layout.vias),
            # The package already emits isolated front, back, and combined
            # copper plus focused USB/matrix/encoder crops.  Do not declare
            # semantic net-class renders until the review renderer can
            # actually produce them; declared artifacts are mandatory.
            declared_classes=(),
            detail_regions=(
                DetailRegion(
                    region_id="usb-mcu",
                    bounds_mm=(39.0, 6.0, 68.0, 37.0),
                    reason="USB-C, ESD, clock, and MCU routing",
                    side="back",
                ),
                DetailRegion(
                    region_id="key-matrix",
                    bounds_mm=(6.0, 3.0, 47.0, 36.0),
                    reason="four switches, matrix diodes, and reverse LEDs",
                    side="back",
                ),
                DetailRegion(
                    region_id="encoder",
                    bounds_mm=(67.0, 6.0, 95.0, 34.0),
                    reason="encoder body, push switch, and debounce network",
                    side="back",
                ),
            ),
        ),
        model_preflight=preflight,
    )
    summary = {
        "schema": "pcbsmith-retro-pad-generation-summary-v1",
        "erc": erc.model_dump(mode="json"),
        "drc": drc.model_dump(mode="json"),
        "design_review": design_review.model_dump(mode="json"),
        "model_preflight": preflight.model_dump(mode="json", by_alias=True),
        "visual_review": visual.model_dump(mode="json", by_alias=True),
        "schematic_svg": schematic_svg,
        "schematic_findings": schematic_findings,
        "previews": previews,
        "preview_findings": preview_findings,
        "routing": {
            "segments": len(layout.segments),
            "vias": len(layout.vias),
            "nets": len(board_netlist.nets),
        },
    }
    (evidence / "generation-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "erc": erc.status,
                "drc": drc.status,
                "design_review": design_review.status,
                "model_preflight": preflight.status,
                "visual_review": visual.package_status,
                "segments": len(layout.segments),
                "vias": len(layout.vias),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
