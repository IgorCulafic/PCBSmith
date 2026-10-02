"""Audit the revision and evidence bindings for Phase 17 visual inspection."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fingerprint(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def audit(index_path: Path, results_path: Path, output_path: Path) -> dict[str, object]:
    index = _read(index_path)
    recorded_index_fingerprint = str(index.pop("index_fingerprint"))
    if _fingerprint(index) != recorded_index_fingerprint:
        raise ValueError("inspection index fingerprint mismatch")
    results = _read(results_path)
    if results.get("source_index_fingerprint") != recorded_index_fingerprint:
        raise ValueError("inspection result is not bound to this index")
    if results.get("human_user_approval") is not False:
        raise ValueError("visual inspection must not infer user approval")

    review_root = Path(str(index["review_root"]))
    sources = index.get("sources")
    sheets = index.get("contact_sheets")
    if not isinstance(sources, list) or len(sources) != 40:
        raise ValueError("expected 40 indexed sources")
    if not isinstance(sheets, list) or len(sheets) != 12:
        raise ValueError("expected 12 indexed contact sheets")

    bottom_equivalent_cases: list[str] = []
    board_hash_to_case: dict[str, str] = {}
    for source in sources:
        if not isinstance(source, dict):
            raise TypeError("malformed source record")
        case_id = str(source["case_id"])
        board_sha = str(source["board_sha256"])
        board_hash_to_case[board_sha] = case_id
        manifest_path = review_root / str(source["manifest"])
        if _sha256(manifest_path) != source["manifest_sha256"]:
            raise ValueError(f"manifest hash mismatch: {case_id}")
        artifacts = source.get("artifacts")
        if not isinstance(artifacts, dict) or len(artifacts) != 6:
            raise ValueError(f"artifact role mismatch: {case_id}")
        for artifact in artifacts.values():
            if not isinstance(artifact, dict):
                raise TypeError(f"malformed artifact record: {case_id}")
            path = review_root / str(artifact["path"])
            if _sha256(path) != artifact["sha256"]:
                raise ValueError(f"artifact hash mismatch: {path}")
        bottom_all = artifacts["2d_bottom_all"]
        bottom_copper = artifacts["2d_bottom_copper"]
        if bottom_all["sha256"] == bottom_copper["sha256"]:
            bottom_equivalent_cases.append(case_id)

    for sheet in sheets:
        if not isinstance(sheet, dict):
            raise TypeError("malformed contact sheet record")
        path = index_path.parent / str(sheet["path"])
        if _sha256(path) != sheet["sha256"]:
            raise ValueError(f"contact-sheet hash mismatch: {path}")

    qualification_root = review_root.parent.parent / "failure-placement-gate-v1" / "cases"
    evidence_by_board: dict[str, set[tuple[int, int]]] = defaultdict(set)
    for path in qualification_root.rglob("routing-candidate-qualification.json"):
        item = _read(path)
        candidate_board_sha = str(item.get("routed_source_board_sha256", ""))
        if candidate_board_sha not in board_hash_to_case:
            continue
        burden = item.get("manual_repair_burden")
        if not isinstance(burden, dict):
            raise TypeError(f"missing manual repair burden: {path}")
        evidence_by_board[candidate_board_sha].add(
            (
                int(burden["open_finding_count"]),
                int(burden["violation_finding_count"]),
            )
        )

    actual_attention: dict[str, dict[str, int]] = {}
    actual_clean: list[str] = []
    for board_sha, case_id in sorted(board_hash_to_case.items(), key=lambda item: item[1]):
        observations = evidence_by_board.get(board_sha)
        if not observations or len(observations) != 1:
            raise ValueError(f"ambiguous or missing candidate evidence: {case_id}")
        unconnected, violations = next(iter(observations))
        if unconnected or violations:
            actual_attention[case_id] = {
                "unconnected": unconnected,
                "violations": violations,
            }
        else:
            actual_clean.append(case_id)

    summary = results.get("revision_bound_kicad_summary")
    if not isinstance(summary, dict):
        raise TypeError("missing revision-bound KiCad summary")
    if summary.get("connectivity_and_drc_clean_cases") != actual_clean:
        raise ValueError("clean case list does not match revision-bound evidence")
    if summary.get("attention_cases") != actual_attention:
        raise ValueError("attention case map does not match revision-bound evidence")
    total_unconnected = sum(item["unconnected"] for item in actual_attention.values())
    total_violations = sum(item["violations"] for item in actual_attention.values())
    if summary.get("total_unconnected") != total_unconnected:
        raise ValueError("unconnected total mismatch")
    if summary.get("total_violations") != total_violations:
        raise ValueError("violation total mismatch")
    if len(bottom_equivalent_cases) != 40:
        raise ValueError("bottom-layer equivalence claim is not true for all cases")

    audit_record: dict[str, object] = {
        "schema_id": "pcbsmith-phase17-visual-inspection-audit",
        "schema_version": 1,
        "status": "pass_with_recorded_attention",
        "index_fingerprint": recorded_index_fingerprint,
        "index_sha256": _sha256(index_path),
        "results_sha256": _sha256(results_path),
        "canonical_cases": len(sources),
        "source_images": sum(len(source["artifacts"]) for source in sources),
        "contact_sheets": len(sheets),
        "bottom_view_equivalent_cases": len(bottom_equivalent_cases),
        "connectivity_and_drc_clean_cases": len(actual_clean),
        "attention_cases": len(actual_attention),
        "total_unconnected": total_unconnected,
        "total_violations": total_violations,
        "human_user_approval": False,
    }
    audit_record["audit_fingerprint"] = _fingerprint(audit_record)
    output_path.write_text(
        json.dumps(audit_record, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return audit_record


def main() -> None:
    parser = argparse.ArgumentParser()
    base = Path(
        "experiments/phase17-routing-corpus-40/review/"
        "human-inspection-2026-08-15"
    )
    parser.add_argument("--index", type=Path, default=base / "inspection-index.json")
    parser.add_argument("--results", type=Path, default=base / "inspection-results.json")
    parser.add_argument("--output", type=Path, default=base / "audit-summary.json")
    args = parser.parse_args()
    result = audit(args.index.resolve(), args.results.resolve(), args.output.resolve())
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
