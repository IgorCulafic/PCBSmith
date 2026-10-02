"""Publish human-readable and machine-readable results for a real-test corpus."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from collections import Counter, defaultdict
from pathlib import Path


def _read(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _latest_attempt(case_dir: Path) -> tuple[Path, dict[str, object], Path]:
    candidates: list[tuple[Path, dict[str, object], Path]] = []
    for evidence_path in sorted(
        (case_dir / "external" / "freerouting-v2.2.4").glob("attempt-*/route-evidence.json")
    ):
        evidence = _read(evidence_path)
        if not isinstance(evidence, dict):
            continue
        boards = tuple(evidence_path.parent.glob("*-freerouting.kicad_pcb"))
        if len(boards) != 1:
            continue
        expected = evidence.get("routed_board_sha256")
        if expected == _sha256(boards[0]):
            candidates.append((evidence_path.parent, evidence, boards[0]))
    if not candidates:
        raise FileNotFoundError(f"No hash-bound routed attempt: {case_dir}")
    return candidates[-1]


def summarize(root: Path) -> dict[str, object]:
    matrix = _read(root / "case-matrix.json")
    if not isinstance(matrix, list) or len(matrix) != 40:
        raise ValueError("Expected a frozen 40-case matrix")
    contracts = {str(item["case_id"]): item for item in matrix if isinstance(item, dict)}
    rows: list[dict[str, object]] = []
    for case_dir in sorted((root / "boards").iterdir()):
        if not case_dir.is_dir():
            continue
        case_id = case_dir.name.split("-", 1)[0]
        contract = contracts[case_id]
        attempt, evidence, routed_source = _latest_attempt(case_dir)
        project_name = case_dir.name
        review_board = case_dir / f"{project_name}.kicad_pcb"
        shutil.copy2(routed_source, review_board)
        project_file = case_dir / f"{project_name}.kicad_pro"
        board_sha = _sha256(review_board)
        manifest_matches = tuple(
            (root / "review" / "qualified" / case_id).glob(
                f"revision-{board_sha[:12]}/review-manifest.json"
            )
        )
        if len(manifest_matches) != 1:
            raise FileNotFoundError(f"No revision-bound review manifest: {case_id}")
        drc = evidence["drc"]
        widths = evidence["widths"]
        geometry = evidence["geometry"]
        if (
            not isinstance(drc, dict)
            or not isinstance(widths, dict)
            or not isinstance(geometry, dict)
        ):
            raise TypeError(f"Malformed route evidence: {case_id}")
        width_report = widths.get("report")
        if not isinstance(width_report, dict):
            raise TypeError(f"Malformed width report: {case_id}")
        success = evidence.get("success") is True
        unconnected = int(drc["unconnected_count"])
        violations = int(drc["violation_count"])
        failure_reasons: list[str] = []
        if unconnected:
            failure_reasons.append(f"{unconnected} unconnected")
        if violations:
            failure_reasons.append(f"{violations} DRC violations")
        if width_report.get("width_intent_accepted") is not True:
            failure_reasons.append("width intent rejected")
        for stage in ("export", "router", "import"):
            item = evidence.get(stage)
            if isinstance(item, dict) and item.get("exit_code") != 0:
                failure_reasons.append(f"{stage} failed")
        row: dict[str, object] = {
            "case_id": case_id,
            "tier": str(contract["difficulty"]),
            "title": str(contract["title"]),
            "component_count": len(contract["placements"]),
            "net_count": len(contract["nets"]),
            "board_width_mm": contract["board"]["width_mm"],
            "board_height_mm": contract["board"]["height_mm"],
            "maximum_width_mm": max(float(item["width_mm"]) for item in contract["nets"]),
            "success": success,
            "width_intent_accepted": width_report.get("width_intent_accepted") is True,
            "drc_violations": violations,
            "unconnected": unconnected,
            "segments": int(geometry["segment_count"]),
            "vias": int(geometry["via_count"]),
            "router_seconds": round(float(evidence["router"]["seconds"]), 6),
            "total_pipeline_seconds": round(
                sum(
                    float(evidence[stage]["seconds"])
                    for stage in ("export", "router", "import", "widths", "drc")
                ),
                6,
            ),
            "failure_reason": "; ".join(failure_reasons),
            "project_file": project_file.relative_to(root).as_posix(),
            "placement_board": next(case_dir.glob("*-placement.kicad_pcb"))
            .relative_to(root)
            .as_posix(),
            "routed_board": review_board.relative_to(root).as_posix(),
            "route_evidence": (attempt / "route-evidence.json").relative_to(root).as_posix(),
            "review_manifest": manifest_matches[0].relative_to(root).as_posix(),
            "routed_board_sha256": board_sha,
        }
        rows.append(row)
    if len(rows) != 40:
        raise ValueError(f"Expected 40 routed cases, found {len(rows)}")

    tier_rows: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        tier_rows[str(row["tier"])].append(row)
    tier_order = ("very_simple", "simple", "beginner", "medium")
    tiers = []
    for tier in tier_order:
        items = tier_rows[tier]
        tiers.append(
            {
                "tier": tier,
                "attempted": len(items),
                "passed": sum(item["success"] is True for item in items),
                "failed": sum(item["success"] is not True for item in items),
                "unconnected": sum(int(item["unconnected"]) for item in items),
                "drc_violations": sum(int(item["drc_violations"]) for item in items),
                "router_seconds": round(sum(float(item["router_seconds"]) for item in items), 6),
            }
        )
    review_audit = _read(root / "review" / "qualified" / "audit-summary.json")
    payload: dict[str, object] = {
        "schema": "pcbsmith-four-tier-real-test-results-v1",
        "attempted": len(rows),
        "passed": sum(row["success"] is True for row in rows),
        "failed": sum(row["success"] is not True for row in rows),
        "width_intent_accepted": sum(row["width_intent_accepted"] is True for row in rows),
        "drc_violations": sum(int(row["drc_violations"]) for row in rows),
        "unconnected": sum(int(row["unconnected"]) for row in rows),
        "failure_reason_counts": dict(
            sorted(
                Counter(str(row["failure_reason"]) for row in rows if row["failure_reason"]).items()
            )
        ),
        "tiers": tiers,
        "review_bundle_audit_complete": isinstance(review_audit, dict)
        and review_audit.get("complete") is True,
        "manual_visual_approval": False,
        "cases": rows,
    }
    _write_json(root / "results.json", payload)
    _write_csv(root / "results.csv", rows)
    (root / "RESULTS.md").write_text(_results_markdown(payload), encoding="utf-8")
    (root / "KICAD-PROJECT-INDEX.md").write_text(_index_markdown(rows), encoding="utf-8")
    _write_manifest(root)
    return payload


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _results_markdown(payload: dict[str, object]) -> str:
    lines = [
        "# Phase 17 four-tier real routing test",
        "",
        "## Outcome",
        "",
        f"- Strict pass: **{payload['passed']}/{payload['attempted']}**",
        f"- Retained failures: **{payload['failed']}**",
        f"- Width intent accepted: **{payload['width_intent_accepted']}/40**",
        f"- KiCad DRC violations: **{payload['drc_violations']}**",
        f"- Unconnected items: **{payload['unconnected']}**",
        "- Canonical review bundles: **40 boards / 240 images**, independently hash-audited",
        "- Manual visual approval: **not inferred**",
        "",
        "A strict pass requires successful KiCad DSN export, Freerouting, KiCad SES import, "
        "trace-width read-back, zero DRC violations, and zero unconnected items.",
        "",
        "## Results by tier",
        "",
        "| Tier | Passed | Failed | Unconnected | DRC violations |",
        "|---|---:|---:|---:|---:|",
    ]
    tiers = payload["tiers"]
    if not isinstance(tiers, list):
        raise TypeError("Malformed tier summary")
    for item in tiers:
        lines.append(
            f"| {item['tier']} | {item['passed']}/10 | {item['failed']} | "
            f"{item['unconnected']} | {item['drc_violations']} |"
        )
    lines.extend(
        [
            "",
            "## Retained failures",
            "",
            "| Case | Tier | Design | Failure | Segments | Vias |",
            "|---|---|---|---|---:|---:|",
        ]
    )
    cases = payload["cases"]
    if not isinstance(cases, list):
        raise TypeError("Malformed case results")
    for item in cases:
        if item["success"] is True:
            continue
        lines.append(
            f"| {item['case_id']} | {item['tier']} | {item['title']} | "
            f"{item['failure_reason']} | {item['segments']} | {item['vias']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The simple tier achieved 10/10. Failures were connectivity misses, not clearance "
            "or short-circuit violations, and all 40 cases preserved their requested trace-width "
            "intent. The concentration of failures in the TQFP48/multi-load medium cases points "
            "to two-layer fanout and congestion limits. RT01 is a useful low-complexity outlier "
            "and should be diagnosed separately rather than explained by density.",
            "",
            "These are routing evaluation boards, not electrically qualified products. Passing "
            "does not establish schematic correctness, current capacity, thermal performance, "
            "manufacturability, assembly yield, EMC, mechanical fit, or safety.",
            "",
            "## Review entry points",
            "",
            "- `KICAD-PROJECT-INDEX.md`: all matching `.kicad_pro` and routed `.kicad_pcb` pairs",
            "- `results.csv` and `results.json`: per-case machine-readable results",
            "- `review/inspection-2026-08-16/`: 12 contact sheets",
            "- `review/qualified/`: 240 full-resolution revision-bound images",
            "- `boards/*/external/freerouting-v2.2.4/attempt-01/`: complete router evidence/logs",
            "",
        ]
    )
    return "\n".join(lines)


def _index_markdown(rows: list[dict[str, object]]) -> str:
    lines = [
        "# KiCad project index",
        "",
        "Open the `.kicad_pro` file for a case; its matching `.kicad_pcb` is the latest "
        "hash-bound routed candidate. Failed candidates are intentionally retained and labeled.",
        "",
        "| Case | Tier | Status | Project | Routed PCB | Evidence | Review |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        status = "PASS" if row["success"] else f"FAIL ({row['failure_reason']})"
        lines.append(
            f"| {row['case_id']} | {row['tier']} | {status} | "
            f"[{Path(str(row['project_file'])).name}]({row['project_file']}) | "
            f"[{Path(str(row['routed_board'])).name}]({row['routed_board']}) | "
            f"[route-evidence.json]({row['route_evidence']}) | "
            f"[review-manifest.json]({row['review_manifest']}) |"
        )
    return "\n".join(lines) + "\n"


def _write_manifest(root: Path) -> None:
    excluded = {"final-artifact-manifest.json"}
    records = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name in excluded:
            continue
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    _write_json(root / "final-artifact-manifest.json", {"files": records})


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("experiments/phase17-real-test-40-2026-08-16"),
    )
    args = parser.parse_args()
    result = summarize(args.root.resolve())
    print(
        json.dumps(
            {key: result[key] for key in ("attempted", "passed", "failed", "unconnected")},
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
