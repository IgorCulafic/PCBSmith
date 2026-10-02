"""Run one retained real-board KiCad refill and exact final-fill readback."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pcbsmith.kicad.final_fill_adapter import refill_and_read_kicad_board


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_board", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    source_before = hashlib.sha256(args.source_board.read_bytes()).hexdigest()
    candidate, snapshot = refill_and_read_kicad_board(args.source_board, args.output_dir)
    source_after = hashlib.sha256(args.source_board.read_bytes()).hexdigest()
    if source_after != source_before:
        raise RuntimeError("source board changed during isolated W3 refill transaction")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "final-fill-snapshot.json").write_text(
        json.dumps(snapshot.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {
        "schema": "pcbsmith-w3-final-fill-real-test-v1",
        "source_board": str(args.source_board.resolve()),
        "source_board_sha256": source_before,
        "candidate_board": str(candidate.resolve()),
        "candidate_board_sha256": snapshot.filled_board_sha256,
        "kicad_version": snapshot.kicad_version,
        "zone_count": len(snapshot.zones),
        "filled_region_count": len(snapshot.regions),
        "zone_intent_unchanged": snapshot.zone_intent_unchanged,
        "stale_fill": snapshot.stale_fill,
        "unverified_region_count": len(snapshot.unverified_region_ids),
        "qualification_boundary": (
            "Exact saved-fill inventory only. Region-to-pad/track/via reachability, "
            "thermal adequacy, and whole-board acceptance remain unverified."
        ),
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
