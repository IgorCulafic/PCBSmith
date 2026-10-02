"""Run the W7 production adapter over retained revision-bound evidence."""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from pcbsmith.kicad.final_fill_adapter import KiCadFinalFillSnapshot
from pcbsmith.kicad.final_fill_connectivity import KiCadFinalFillConnectivityObservation
from pcbsmith.kicad.final_fill_thermal import KiCadThermalSpokeAudit
from pcbsmith.kicad.routing_evidence import inspect_kicad_drc_report, inspect_saved_board_routing
from pcbsmith.whole_board_qualification_adapter import qualify_production_board


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--board", type=Path, required=True)
    parser.add_argument("--drc", type=Path, required=True)
    parser.add_argument("--fill-snapshot", type=Path, required=True)
    parser.add_argument("--fill-connectivity", type=Path, required=True)
    parser.add_argument("--thermal-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    board = args.board.resolve()
    board_sha = hashlib.sha256(board.read_bytes()).hexdigest()
    result = qualify_production_board(
        case_id=args.case_id,
        refilled_board_sha256=board_sha,
        drc_evidence=inspect_kicad_drc_report(args.drc),
        drc_board_sha256=board_sha,
        routing_evidence=inspect_saved_board_routing(board),
        fill_snapshot=KiCadFinalFillSnapshot.model_validate_json(
            args.fill_snapshot.read_text("utf-8")
        ),
        fill_connectivity=KiCadFinalFillConnectivityObservation.model_validate_json(
            args.fill_connectivity.read_text("utf-8")
        ),
        thermal_audit=KiCadThermalSpokeAudit.model_validate_json(
            args.thermal_audit.read_text("utf-8")
        ),
        topology=None,
        reference_continuity=None,
        automatic_review=None,
        craft=None,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(result.model_dump_json(indent=2))
    return 0 if result.release_qualified else 2


if __name__ == "__main__":
    raise SystemExit(main())
