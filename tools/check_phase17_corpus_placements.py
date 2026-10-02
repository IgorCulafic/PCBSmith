"""Run immutable placement-only KiCad DRC preflight for the Phase 17 corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

SILKSCREEN_VIOLATION_TYPES = frozenset({"silk_edge_clearance", "silk_over_copper", "silk_overlap"})


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return payload


def check_case(case_dir: Path, kicad_cli: Path) -> dict[str, object]:
    placement = next(case_dir.glob("*-placement.kicad_pcb"))
    source_hash = _sha256(placement)
    check_dir = case_dir / "placement-check" / f"revision-{source_hash[:12]}"
    evidence_path = check_dir / "placement-evidence.json"
    if evidence_path.exists():
        cached = _read_json(evidence_path)
        if cached.get("schema") == "pcbsmith-placement-preflight-v2":
            return cached
    check_dir.mkdir(parents=True, exist_ok=True)
    source = check_dir / "source-placement.kicad_pcb"
    shutil.copy2(placement, source)
    report = check_dir / "drc.json"
    command = (
        str(kicad_cli),
        "pcb",
        "drc",
        "--format",
        "json",
        "--output",
        str(report),
        "--refill-zones",
        "--save-board",
        str(source),
    )
    process = subprocess.run(command, cwd=check_dir, capture_output=True, check=False)
    (check_dir / "drc.stdout.log").write_bytes(process.stdout)
    (check_dir / "drc.stderr.log").write_bytes(process.stderr)
    violations: list[object] = []
    unconnected: list[object] = []
    violation_types: list[str] = []
    if report.exists():
        payload = json.loads(report.read_text(encoding="utf-8"))
        violations = payload.get("violations", [])
        unconnected = payload.get("unconnected_items", [])
        violation_types = sorted(
            str(item.get("type", "unknown")) for item in violations if isinstance(item, dict)
        )
    contract = json.loads((case_dir / "case-contract.json").read_text(encoding="utf-8"))
    blocking_types = tuple(
        item for item in violation_types if item not in SILKSCREEN_VIOLATION_TYPES
    )
    silkscreen_types = tuple(item for item in violation_types if item in SILKSCREEN_VIOLATION_TYPES)
    evidence: dict[str, object] = {
        "schema": "pcbsmith-placement-preflight-v2",
        "case_id": contract["case_id"],
        "tier": contract["tier"],
        "source_board_sha256": source_hash,
        "kicad_exit_code": process.returncode,
        "placement_geometry_clean": process.returncode == 0 and not blocking_types,
        "silkscreen_clean": process.returncode == 0 and not silkscreen_types,
        "mechanical_clean": process.returncode == 0 and not violations,
        "violation_count": len(violations),
        "violation_types": violation_types,
        "blocking_violation_count": len(blocking_types),
        "blocking_violation_types": blocking_types,
        "silkscreen_violation_count": len(silkscreen_types),
        "silkscreen_violation_types": silkscreen_types,
        "expected_unrouted_item_count": len(unconnected),
        "gate_policy": (
            "Placement geometry rejects all non-silkscreen DRC violations. Silkscreen "
            "findings are a separate cleanup gate. Unconnected items are recorded but "
            "not rejected because routing has not run yet."
        ),
    }
    _write_json(evidence_path, evidence)
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("experiments/phase17-routing-corpus-40"))
    parser.add_argument(
        "--kicad-cli", type=Path, default=Path("C:/Program Files/KiCad/10.0/bin/kicad-cli.exe")
    )
    args = parser.parse_args()
    root = args.root.resolve()
    kicad_cli = args.kicad_cli.resolve()
    results = []
    case_dirs = tuple(path for path in sorted((root / "boards").iterdir()) if path.is_dir())
    for index, case_dir in enumerate(case_dirs, start=1):
        print(f"[{index}/{len(case_dirs)}] {case_dir.name}", flush=True)
        results.append(check_case(case_dir, kicad_cli))
    summary = {
        "schema": "pcbsmith-placement-preflight-summary-v2",
        "attempted": len(results),
        "clean": sum(item["mechanical_clean"] is True for item in results),
        "failed": sum(item["mechanical_clean"] is not True for item in results),
        "placement_geometry_clean": sum(
            item["placement_geometry_clean"] is True for item in results
        ),
        "silkscreen_clean": sum(item["silkscreen_clean"] is True for item in results),
        "cases": results,
    }
    _write_json(root / "placement-preflight-summary.json", summary)
    print(json.dumps({key: summary[key] for key in ("attempted", "clean", "failed")}))


if __name__ == "__main__":
    main()
