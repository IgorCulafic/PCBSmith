"""Run the crash-contained KiCad island observer and classify one W3 fill."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from pcbsmith.kicad.final_fill_adapter import KiCadFinalFillSnapshot
from pcbsmith.kicad.final_fill_connectivity import (
    KiCadFinalFillConnectivityObservation,
    classify_final_fill_reachability,
)
from pcbsmith.kicad.final_fill_thermal import audit_kicad_thermal_spokes


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("board", type=Path)
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--drc-report", type=Path, required=True)
    parser.add_argument("--source-pad", action="append", required=True)
    parser.add_argument(
        "--kicad-python",
        type=Path,
        default=Path("C:/Program Files/KiCad/10.0/bin/python.exe"),
    )
    parser.add_argument(
        "--bridge",
        type=Path,
        default=Path("tools/kicad_final_fill_connectivity_bridge.py"),
    )
    args = parser.parse_args()
    board = args.board.resolve()
    before = _sha(board)
    args.output.mkdir(parents=True, exist_ok=True)
    observation_path = args.output / "connectivity-observation.json"
    process = subprocess.run(
        (str(args.kicad_python), str(args.bridge.resolve()), str(board), str(observation_path)),
        capture_output=True,
        check=False,
        timeout=120,
    )
    (args.output / "bridge.stdout.log").write_bytes(process.stdout)
    (args.output / "bridge.stderr.log").write_bytes(process.stderr)
    if process.returncode != 0 or not observation_path.exists():
        raise RuntimeError(f"KiCad final-fill connectivity bridge failed: {process.returncode}")
    snapshot = KiCadFinalFillSnapshot.model_validate_json(args.snapshot.read_text("utf-8"))
    observation = KiCadFinalFillConnectivityObservation.model_validate_json(
        observation_path.read_text("utf-8")
    )
    classified = classify_final_fill_reachability(
        snapshot,
        observation,
        declared_source_pad_ids=tuple(args.source_pad),
    )
    thermal = audit_kicad_thermal_spokes(
        observation,
        args.drc_report,
        drc_report_board_sha256=before,
    )
    if _sha(board) != before:
        raise RuntimeError("source board changed during read-only W3 island observation")
    (args.output / "classified-final-fill-snapshot.json").write_text(
        json.dumps(classified.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output / "thermal-spoke-audit.json").write_text(
        json.dumps(thermal.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {
        "schema": "pcbsmith-w3-final-fill-connectivity-real-test-v1",
        "board": str(board),
        "board_sha256": before,
        "source_pad_ids": sorted(args.source_pad),
        "region_count": len(classified.regions),
        "source_reachable_region_count": sum(
            item.reachability.value == "source_reachable" for item in classified.regions
        ),
        "floating_region_count": sum(
            item.reachability.value == "floating" for item in classified.regions
        ),
        "unverified_region_count": len(classified.unverified_region_ids),
        "thermal_spoke_evaluated_pad_count": thermal.evaluated_object_count,
        "thermal_spoke_disposition": thermal.disposition.value,
        "source_mutated": False,
        "qualification_boundary": (
            "Exact KiCad IsIsland state, per-filled-outline integer-geometry contact graph, "
            "and exact-revision KiCad starved-thermal DRC applicability evaluation."
        ),
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
