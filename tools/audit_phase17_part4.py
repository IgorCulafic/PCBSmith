"""Independent audit of retained Phase 17 Part 4 evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pcbsmith.kicad.escape_technology import EscapeTechnologyDecision
from pcbsmith.kicad.reference_continuity import parse_reference_continuity


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _matching_case_dir(root: Path, case_id: str) -> Path:
    matches = tuple((root / "boards").glob(f"{case_id}-*"))
    if len(matches) != 1:
        raise ValueError(f"expected one source case for {case_id}, found {len(matches)}")
    return matches[0]


def _source_hash_exists(case_dir: Path, expected_sha256: str) -> bool:
    return any(_sha256(path) == expected_sha256 for path in case_dir.rglob("*.kicad_pcb"))


def audit(root: Path, output: Path) -> dict[str, object]:
    summary_path = output / "summary.json"
    summary = _read(summary_path)
    binding = summary.get("source_binding")
    if not isinstance(binding, dict):
        raise TypeError("Part 4 summary lacks source binding")
    expected_bindings = {
        "runner_sha256": _sha256(Path(__file__).with_name("run_phase17_part4.py")),
        "bridge_sha256": _sha256(Path(__file__).with_name("kicad_board_part4_bridge.py")),
        "base_bridge_sha256": _sha256(
            Path(__file__).with_name("kicad_board_feasibility_bridge.py")
        ),
        "policy_sha256": _sha256(root / "part4-policy.json"),
    }
    if binding != expected_bindings:
        raise ValueError("Part 4 source binding is stale")
    continuity = summary.get("continuity")
    escape = summary.get("escape_technology")
    if not isinstance(continuity, dict) or not isinstance(escape, dict):
        raise TypeError("Part 4 summary sections are malformed")
    continuity_results = continuity.get("results")
    escape_results = escape.get("results")
    if not isinstance(continuity_results, list) or not isinstance(escape_results, list):
        raise TypeError("Part 4 summary result lists are malformed")
    audited_continuity = 0
    audited_escape = 0
    source_hashes_verified = 0
    log_files_verified_empty = 0
    for raw in continuity_results:
        if not isinstance(raw, dict):
            raise TypeError("continuity result must be an object")
        case_id = str(raw["case_id"])
        source_sha = str(raw["source_board_sha256"])
        case_dir = _matching_case_dir(root, case_id)
        if not _source_hash_exists(case_dir, source_sha):
            raise ValueError(f"continuity source revision is missing for {case_id}")
        source_hashes_verified += 1
        evidence_dir = next(
            iter((output / "continuity" / case_dir.name).glob(f"revision-{source_sha[:12]}")),
            None,
        )
        if evidence_dir is None:
            raise FileNotFoundError(f"continuity evidence directory is missing for {case_id}")
        observation_path = evidence_dir / "physical-observation.json"
        if _sha256(observation_path) != raw["observation_sha256"]:
            raise ValueError(f"continuity observation hash mismatch for {case_id}")
        evidence = parse_reference_continuity(_read(observation_path))
        if evidence.evidence_fingerprint != raw["evidence_fingerprint"]:
            raise ValueError(f"continuity fingerprint mismatch for {case_id}")
        result = _read(evidence_dir / "result.json")
        if result != raw:
            raise ValueError(f"continuity compact result mismatch for {case_id}")
        for log in evidence_dir.glob("*.log"):
            if log.stat().st_size:
                raise ValueError(f"unexpected bridge diagnostics: {log}")
            log_files_verified_empty += 1
        audited_continuity += 1
    for raw in escape_results:
        if not isinstance(raw, dict):
            raise TypeError("escape result must be an object")
        case_id = str(raw["case_id"])
        source_sha = str(raw["source_board_sha256"])
        case_dir = _matching_case_dir(root, case_id)
        if not _source_hash_exists(case_dir, source_sha):
            raise ValueError(f"escape source revision is missing for {case_id}")
        source_hashes_verified += 1
        evidence_dir = next(
            iter((output / "escape" / case_dir.name).glob(f"revision-{source_sha[:12]}")),
            None,
        )
        if evidence_dir is None:
            raise FileNotFoundError(f"escape evidence directory is missing for {case_id}")
        decision = EscapeTechnologyDecision.model_validate(
            _read(evidence_dir / "escape-technology-decision.json")
        )
        if decision.decision_fingerprint != raw["decision_fingerprint"]:
            raise ValueError(f"escape decision fingerprint mismatch for {case_id}")
        result = _read(evidence_dir / "result.json")
        if result != raw:
            raise ValueError(f"escape compact result mismatch for {case_id}")
        for trial in decision.candidates:
            if trial.geometry_trial is None:
                continue
            trial_path = evidence_dir / f"trial-{trial.candidate_id}.json"
            if _sha256(trial_path) != trial.geometry_trial.observation_sha256:
                raise ValueError(f"escape geometry observation hash mismatch for {case_id}")
        for log in evidence_dir.glob("*.log"):
            if log.stat().st_size:
                raise ValueError(f"unexpected bridge diagnostics: {log}")
            log_files_verified_empty += 1
        audited_escape += 1
    files = tuple(
        path
        for path in output.rglob("*")
        if path.is_file() and path.name not in {"audit-summary.json", "REPORT.md"}
    )
    result: dict[str, object] = {
        "schema": "pcbsmith-phase17-part4-audit-v1",
        "summary_sha256": _sha256(summary_path),
        "source_binding_verified": True,
        "continuity_evidence_validated": audited_continuity,
        "escape_decisions_validated": audited_escape,
        "source_hashes_verified": source_hashes_verified,
        "empty_bridge_log_files_verified": log_files_verified_empty,
        "audited_file_count": len(files),
        "audited_bytes": sum(path.stat().st_size for path in files),
    }
    result["audit_fingerprint"] = _fingerprint(result)
    (output / "audit-summary.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("experiments/phase17-routing-corpus-40"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output = (args.output or root / "part4-v1").resolve()
    print(json.dumps(audit(root, output), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
