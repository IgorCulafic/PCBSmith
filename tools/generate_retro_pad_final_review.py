"""Generate the standardized final routed review for a Retro-Pad candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pcbsmith.kicad.model_preflight import (
    ModelRegistryEntry,
    ModelRequirement,
    preflight_board_models,
)
from pcbsmith.review.visual_package import (
    DetailRegion,
    ReviewFeatures,
    generate_visual_review_package,
)

ROOT = Path(__file__).resolve().parents[1]


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("project", choices=("retro-pad-3x3-r001", "retro-pad-r003"))
    return parser.parse_args()


def _registry(board: Path) -> tuple[ModelRegistryEntry, ...]:
    inventory = preflight_board_models(board)
    entries: dict[str, ModelRegistryEntry] = {}
    for item in inventory.models:
        if item.status != "resolved" or item.resolved_path is None:
            continue
        is_proxy = item.raw_path.startswith("${KIPRJMOD}/models/retro-pad-")
        entries[item.raw_path] = ModelRegistryEntry(
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
    return tuple(entries.values())


def _configuration(
    project: str,
) -> tuple[Path, tuple[str, ...], tuple[DetailRegion, ...]]:
    output = ROOT / "outputs" / project
    if project == "retro-pad-3x3-r001":
        board = output / f"{project}-routing-candidate.kicad_pcb"
        required = (
            "J1",
            "J2",
            "U1",
            "U2",
            "SW10",
            *(f"SW{index}" for index in range(1, 10)),
            *(f"D{index}" for index in range(10, 19)),
        )
        details = (
            DetailRegion(
                region_id="matrix-front",
                bounds_mm=(27.0, 17.0, 91.0, 82.0),
                reason="3x3 switch, LED, aperture, label, and copper alignment",
                side="front",
            ),
            DetailRegion(
                region_id="encoder-usb-front",
                bounds_mm=(48.0, 0.0, 118.0, 38.0),
                reason="USB edge, encoder clearance, and routed USB entry",
                side="front",
            ),
            DetailRegion(
                region_id="support-back",
                bounds_mm=(5.0, 0.0, 110.0, 98.0),
                reason="controller support placement and routed back copper",
                side="back",
            ),
        )
        return board, required, details

    board = output / f"{project}-routing-candidate.kicad_pcb"
    required = (
        "J1",
        "J2",
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
    details = (
        DetailRegion(
            region_id="left-controls",
            bounds_mm=(0.0, 0.0, 43.0, 55.0),
            reason="left controls, apertures, diodes, and routed copper",
            side="front",
        ),
        DetailRegion(
            region_id="center-front",
            bounds_mm=(43.0, 11.0, 102.0, 44.0),
            reason="USB-C, encoder, heart, and front routing",
            side="front",
        ),
        DetailRegion(
            region_id="center-back",
            bounds_mm=(43.0, 11.0, 108.0, 44.0),
            reason="MCU support cluster, ISP header, and back routing",
            side="back",
        ),
        DetailRegion(
            region_id="right-controls",
            bounds_mm=(102.0, 0.0, 145.0, 55.0),
            reason="right controls, apertures, diodes, and routed copper",
            side="front",
        ),
    )
    return board, required, details


def main() -> int:
    args = _arguments()
    board, required, details = _configuration(args.project)
    if not board.is_file():
        raise FileNotFoundError(board)
    registry = _registry(board)
    preflight = preflight_board_models(
        board,
        registry=registry,
        requirements=tuple(
            ModelRequirement(
                reference=reference,
                accepted_classifications=(
                    ("proxy", "exact_package")
                    if reference.startswith("SW")
                    else ("exact_package", "complete_module")
                ),
            )
            for reference in required
        ),
    )
    manifest = generate_visual_review_package(
        board_file=board,
        output_dir=board.parent / "review-final",
        stage="final",
        features=ReviewFeatures(
            has_bottom_components=True,
            has_zones=True,
            has_cutouts=True,
            has_vias=True,
            declared_classes=(),
            detail_regions=details,
        ),
        model_preflight=preflight,
    )
    print(
        json.dumps(
            {
                "board": str(board),
                "model_preflight": preflight.status,
                "review": manifest.package_status,
                "routing_state": (
                    None
                    if manifest.routing_evidence is None
                    else manifest.routing_evidence.state.value
                ),
                "artifact_count": len(manifest.artifacts),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
