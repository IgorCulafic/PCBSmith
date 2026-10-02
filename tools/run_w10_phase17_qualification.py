"""Freeze and rerun the Phase 17 corpus without upgrading historical claims."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from pcbsmith.kicad.validate import run_kicad_drc

GATE_ORDER = (
    "geometry",
    "topology",
    "placement",
    "local_fanout",
    "routing",
    "final_fill",
    "exact_checks",
    "repair",
    "review",
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} must contain a JSON object")
    return value


def _live_drc(board: Path) -> dict[str, Any]:
    before = _sha(board)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="pcbsmith-w10-") as raw:
        root = Path(raw)
        candidate = root / board.name
        shutil.copy2(board, candidate)
        report = run_kicad_drc(candidate, schematic_parity=False)
        report_path = candidate.parent / ".pcbsmith" / "kicad" / "drc.json"
        payload = _read(report_path) if report_path.exists() else {}
        sections: dict[str, int] = {}
        for name in ("violations", "unconnected_items", "schematic_parity"):
            entries = payload.get(name, [])
            sections[name] = len(entries) if isinstance(entries, list) else -1
        after = _sha(candidate)
    if _sha(board) != before:
        raise RuntimeError(f"source board changed during isolated DRC: {board}")
    return {
        "status": report.status,
        "source_board_sha256": before,
        "refilled_candidate_sha256": after,
        "source_mutated": False,
        "seconds": round(time.perf_counter() - started, 6),
        **sections,
        "finding_count": len(report.findings),
        "findings": list(report.findings),
        "schematic_parity_scope": "not_run_in_board_only_corpus",
    }


def _case_records(corpus: Path, *, live_drc: bool) -> list[dict[str, Any]]:
    prior = _read(corpus / "results.json")
    raw_cases = prior.get("cases")
    if not isinstance(raw_cases, list):
        raise TypeError("corpus results cases must be a list")
    records: list[dict[str, Any]] = []
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise TypeError("corpus case must be an object")
        case_id = str(raw["case_id"])
        board = corpus / str(raw["routed_board"])
        exists = board.is_file()
        current_sha = _sha(board) if exists else None
        recorded_sha = str(raw.get("routed_board_sha256", ""))
        record: dict[str, Any] = {
            "case_id": case_id,
            "tier": str(raw["tier"]),
            "board": str(board.resolve()),
            "board_exists": exists,
            "recorded_board_sha256": recorded_sha,
            "current_board_sha256": current_sha,
            "historical_hash_matches": exists and current_sha == recorded_sha,
            "historical_success": bool(raw.get("success", False)),
            "historical_unconnected_count": int(raw.get("unconnected", 0)),
            "historical_drc_violation_count": int(raw.get("drc_violations", 0)),
            "historical_label_reused_as_w10_pass": False,
        }
        record["live_drc"] = _live_drc(board) if live_drc and exists else None
        records.append(record)
    return sorted(records, key=lambda item: item["case_id"])


def _hard_set_inventory(hard_set: Path) -> list[dict[str, Any]]:
    generation = _read(hard_set / "generation-summary.json")
    preflight = _read(hard_set / "placement-preflight-summary.json")
    preflight_by_case = {
        str(item["case_id"]): item for item in preflight.get("cases", []) if isinstance(item, dict)
    }
    records = []
    for item in generation.get("cases", []):
        if not isinstance(item, dict):
            continue
        case_id = str(item["case_id"])
        board = hard_set / str(item["placement_board"])
        routed = tuple(
            sorted(
                board.parent.glob("external/freerouting-v2.3.0/attempt-*/*-freerouting.kicad_pcb")
            )
        )
        placement = preflight_by_case.get(case_id, {})
        records.append(
            {
                "case_id": case_id,
                "placement_board_exists": board.is_file(),
                "placement_board_sha256": _sha(board) if board.is_file() else None,
                "placement_geometry_clean": placement.get("placement_geometry_clean"),
                "silkscreen_clean": placement.get("silkscreen_clean"),
                "retained_freerouting_2_3_candidate_count": len(routed),
                "retained_freerouting_2_3_candidates": [str(path.resolve()) for path in routed],
            }
        )
    return sorted(records, key=lambda item: item["case_id"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--corpus",
        type=Path,
        default=Path("experiments/phase17-real-test-40-2026-08-16"),
    )
    parser.add_argument(
        "--hard-set",
        type=Path,
        default=Path("experiments/phase17-two-layer-placement-repair-8-v11-2026-08-16"),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--skip-live-drc", action="store_true")
    args = parser.parse_args()
    corpus = args.corpus.resolve()
    hard_set = args.hard_set.resolve()
    cases = _case_records(corpus, live_drc=not args.skip_live_drc)
    tier_counts: dict[str, int] = {}
    for item in cases:
        tier = str(item["tier"])
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    live = [item["live_drc"] for item in cases if item["live_drc"] is not None]
    blockers = [
        "W3 fragmented-region contact mapping and thermal-spoke qualification remain unverified",
        "schematic parity is absent from the legacy board-only corpus",
        "condition-matched current/environment evidence is absent for the legacy corpus",
        "W8 local-repair execution is not integrated across the frozen corpus",
        "W9 exact production-marking audit is not integrated across the frozen corpus",
        "two materially different post-freeze proof boards have not been run",
    ]
    protocol = {
        "schema": "pcbsmith-phase17-w10-frozen-qualification-v1",
        "gate_order": list(GATE_ORDER),
        "corpus_identity": {
            "path": str(corpus),
            "protocol_sha256": _sha(corpus / "protocol.json"),
            "results_sha256": _sha(corpus / "results.json"),
            "case_count": len(cases),
            "tier_counts": dict(sorted(tier_counts.items())),
        },
        "hard_set_identity": {
            "path": str(hard_set),
            "protocol_sha256": _sha(hard_set / "protocol.json"),
            "generation_summary_sha256": _sha(hard_set / "generation-summary.json"),
            "placement_summary_sha256": _sha(hard_set / "placement-preflight-summary.json"),
        },
        "comparability": {
            "historical_result_labels_are_w10_passes": False,
            "reason": (
                "The retained boards predate the W0 identity, W1 profile, W2 topology, W3 fill, "
                "W5 escape, W6 registry, W7 aggregate, W8 repair, and W9 review contracts."
            ),
        },
        "live_drc": {
            "performed": not args.skip_live_drc,
            "board_count": len(live),
            "zero_all_violation_and_unconnected_count": sum(
                item["violations"] == 0 and item["unconnected_items"] == 0 for item in live
            ),
            "source_mutation_count": sum(bool(item["source_mutated"]) for item in live),
            "total_seconds": round(sum(float(item["seconds"]) for item in live), 6),
            "qualification_boundary": (
                "Live KiCad board DRC on isolated copies; schematic parity and W2-W9 semantic "
                "qualification are not inferred."
            ),
        },
        "cases": cases,
        "hard_set": _hard_set_inventory(hard_set),
        "release_qualified_case_count": 0,
        "phase17_complete": False,
        "blockers": blockers,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(protocol, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {key: protocol[key] for key in ("live_drc", "phase17_complete", "blockers")}, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
