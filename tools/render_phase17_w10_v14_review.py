"""Generate the standard high-resolution review package for W10 v14."""

from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.kicad.model_preflight import ModelRequirement, preflight_board_models
from pcbsmith.review.visual_package import ReviewFeatures, generate_visual_review_package

ROOT = Path(__file__).resolve().parents[1]
W10 = ROOT / "experiments" / "phase17-w10-upstream-repair-v14-2026-08-20"
OUTPUT = ROOT / "experiments" / "phase17-w10-visual-review-v14-2026-08-20"


def _board(case_dir: Path) -> Path:
    candidates = tuple(
        path
        for path in case_dir.glob("*.kicad_pcb")
        if not path.name.endswith("-placement.kicad_pcb")
        and not path.name.endswith("-reference-routed.kicad_pcb")
    )
    if len(candidates) != 1:
        raise ValueError(f"{case_dir}: expected one authoritative board")
    return candidates[0]


def main() -> int:
    rows: list[dict[str, object]] = []
    for case_dir in sorted((W10 / "boards").iterdir()):
        contract = json.loads((case_dir / "case-contract.json").read_text("utf-8"))
        board = _board(case_dir)
        model_refs = tuple(
            dict.fromkeys(
                (
                    "U1",
                    *contract["required_polarity_refs"],
                    *contract["required_connector_mating_refs"],
                )
            )
        )
        preflight = preflight_board_models(
            board,
            requirements=tuple(
                ModelRequirement(
                    reference=reference,
                    accepted_classifications=(
                        "exact_package",
                        "complete_module",
                        "connector_only",
                        "proxy",
                    ),
                )
                for reference in model_refs
            ),
        )
        case_output = OUTPUT / case_dir.name
        manifest = generate_visual_review_package(
            board_file=board,
            output_dir=case_output,
            stage="final",
            features=ReviewFeatures(
                declared_classes=(
                    ("power_ground", "high_current")
                    if contract["expected_current_paths"]
                    else ("power_ground",)
                )
            ),
            model_preflight=preflight,
            source_revision=str(contract["reference_routed_board_sha256"]),
        )
        rows.append(
            {
                "case_id": contract["case_id"],
                "board": str(board.resolve()),
                "manifest": str((case_output / "review" / "manifest.json").resolve()),
                "package_status": manifest.package_status,
                "model_preflight_status": manifest.model_preflight_status,
                "generated_artifact_count": sum(
                    artifact.state == "generated" for artifact in manifest.artifacts
                ),
                "missing_artifact_count": sum(
                    artifact.state == "missing" for artifact in manifest.artifacts
                ),
            }
        )
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "summary.json").write_text(
        json.dumps(
            {
                "schema": "pcbsmith-phase17-w10-v14-visual-review-v1",
                "case_count": len(rows),
                "cases": rows,
                "boundary": (
                    "Standard 4K/layer-separated 2D and bare-board views are generated. "
                    "Populated 3D remains withheld by declared model-applicability failures."
                ),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
