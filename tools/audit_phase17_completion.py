"""Validate the Phase 17 completion-gap audit against retained evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"expected mapping: {label}")
    return value


def _integer(mapping: dict[str, object], key: str) -> int:
    value = mapping[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"expected integer: {key}")
    return value


def audit(root: Path, summary_path: Path, output_path: Path) -> dict[str, object]:
    summary = _read(summary_path)
    document_path = root / str(summary["audit_document"])
    document = document_path.read_text(encoding="utf-8")
    if summary.get("phase_status") != "active_not_complete":
        raise ValueError("Phase 17 audit must remain active_not_complete")
    if summary.get("completion_certificate_issued") is not False:
        raise ValueError("completion certificate must not be issued")
    if summary.get("fresh_repository_wide_test_claimed") is not False:
        raise ValueError("audit must not claim the deferred combined test")

    expected_ids = (
        *(f"B{value}" for value in range(1, 6)),
        *(f"A{value}" for value in range(1, 14)),
        *(f"G{value}" for value in range(1, 18)),
    )
    table_ids = re.findall(r"^\| ([BAG]\d+) \|", document, flags=re.MULTILINE)
    if tuple(table_ids) != expected_ids:
        raise ValueError("checklist mapping is missing, duplicated, or reordered")

    blockers = summary.get("blocking_items")
    if not isinstance(blockers, list):
        raise TypeError("blocking_items must be a list")
    blocker_ids = tuple(str(_mapping(item, "blocking item")["id"]) for item in blockers)
    if blocker_ids != ("G4", "G8", "G11", "G13", "G16"):
        raise ValueError("completion blocker ledger mismatch")

    qualification = _read(
        root / "experiments/phase17-routing-corpus-40/failure-placement-gate-v1/"
        "qualification-summary.json"
    )
    routed = _mapping(qualification["routed"], "qualification routed")
    part4 = _read(root / "experiments/phase17-routing-corpus-40/part4-v1/summary.json")
    continuity = _mapping(part4["continuity"], "Part 4 continuity")
    escape = _mapping(part4["escape_technology"], "Part 4 escape")
    visual = _read(
        root / "experiments/phase17-routing-corpus-40/review/"
        "human-inspection-2026-08-15/audit-summary.json"
    )
    published = _mapping(summary["corpus_evidence"], "published corpus evidence")

    derived = {
        "routed_revisions": _integer(routed, "cases"),
        "protected_identity_parity_clean": _integer(routed, "protected_parity_clean"),
        "connectivity_and_drc_clean": _integer(routed, "kicad_connectivity_and_drc_clean"),
        "unconnected_findings": _integer(routed, "open_findings"),
        "violations": _integer(routed, "violation_findings"),
        "width_neckdown_segments": _integer(routed, "width_neckdown_segments"),
        "unsupported_reference_signal_segments": _integer(continuity, "exact_unsupported_segments"),
        "unstitched_signal_transitions": _integer(continuity, "unstitched_signal_transitions"),
        "fine_pitch_cases_evaluated": _integer(escape, "cases"),
        "diagnostic_escape_geometry_successes": _integer(escape, "geometry_option_cases"),
        "fabrication_current_qualified_escape_candidates": _integer(escape, "qualified_candidates"),
        "release_qualified_candidates": _integer(routed, "release_qualified"),
    }
    if published != derived:
        raise ValueError("published corpus values do not match retained evidence")

    visual_summary = _mapping(summary["visual_inspection"], "visual inspection")
    visual_fields = {
        "canonical_cases": _integer(visual, "canonical_cases"),
        "source_images": _integer(visual, "source_images"),
        "contact_sheets": _integer(visual, "contact_sheets"),
        "human_user_approval": visual["human_user_approval"],
        "audit_fingerprint": visual["audit_fingerprint"],
    }
    for key, value in visual_fields.items():
        if visual_summary.get(key) != value:
            raise ValueError(f"visual inspection field mismatch: {key}")

    critical_paths = (
        "src/pcbsmith/prompt_examiner.py",
        "src/pcbsmith/workflow_feasibility.py",
        "src/pcbsmith/production_workflow.py",
        "src/pcbsmith/applicability_execution.py",
        "src/pcbsmith/component_review_execution.py",
        "src/pcbsmith/kicad/routing_candidate_transaction.py",
        "src/pcbsmith/kicad/routing_external_adapters.py",
        "tests/unit/test_production_workflow.py",
        "tests/unit/kicad/test_routing_candidate_transaction.py",
        "tests/unit/kicad/test_routing_external_adapters.py",
        ".pcbsmith/verification/phase17/r2-measured-corpus.json",
        ".pcbsmith/verification/phase17/r4-persisted-handoff.json",
        ".pcbsmith/verification/phase17/r5-measured-corpus.json",
    )
    missing = [path for path in critical_paths if not (root / path).exists()]
    if missing:
        raise ValueError(f"critical audit paths are missing: {missing}")

    stewardship_requirements = {
        "docs/routing-placement-plan.md": (
            "ACTIVE; COMPLETION AUDIT PUBLISHED; FIVE ACCEPTANCE",
            "- [ ] Inspect the canonical review packages for both complete cross-board",
            "- [x] Publish a Phase 17 completion audit mapping every migrated implementation",
        ),
        "docs/roadmap-progress-review-2026-08-10.md": (
            "updated 2026-08-15",
            "**Closed 2026-08-15:** publish the Phase 17 completion audit",
        ),
        "docs/current-state.md": (
            "The 2026-08-15 Phase 17 completion audit now maps all 35 checklist items",
            "`docs/phase17-completion-audit-2026-08-15.md`",
        ),
    }
    stewardship_hashes: dict[str, str] = {}
    for relative_path, required_text in stewardship_requirements.items():
        path = root / relative_path
        text = path.read_text(encoding="utf-8")
        for value in required_text:
            if value not in text:
                raise ValueError(f"stewardship text missing from {relative_path}: {value}")
        stewardship_hashes[relative_path] = _sha256(path)

    result: dict[str, object] = {
        "schema_id": "pcbsmith-phase17-completion-audit-validation",
        "schema_version": 1,
        "status": "valid_active_not_complete",
        "mapped_checklist_items": len(expected_ids),
        "blocking_items": len(blockers),
        "blocker_ids": list(blocker_ids),
        "critical_paths_checked": len(critical_paths),
        "stewardship_documents_checked": len(stewardship_requirements),
        "stewardship_sha256": stewardship_hashes,
        "summary_sha256": _sha256(summary_path),
        "document_sha256": _sha256(document_path),
        "qualification_sha256": _sha256(
            root / "experiments/phase17-routing-corpus-40/failure-placement-gate-v1/"
            "qualification-summary.json"
        ),
        "part4_summary_sha256": _sha256(
            root / "experiments/phase17-routing-corpus-40/part4-v1/summary.json"
        ),
        "visual_audit_sha256": _sha256(
            root / "experiments/phase17-routing-corpus-40/review/"
            "human-inspection-2026-08-15/audit-summary.json"
        ),
        "fresh_repository_wide_test_claimed": False,
    }
    result["audit_fingerprint"] = _fingerprint(result)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument(
        "--summary",
        type=Path,
        default=Path(
            "experiments/phase17-routing-corpus-40/phase17-completion-audit-2026-08-15.json"
        ),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(
            "experiments/phase17-routing-corpus-40/"
            "phase17-completion-audit-validation-2026-08-15.json"
        ),
    )
    args = parser.parse_args()
    root = args.root.resolve()
    result = audit(root, (root / args.summary).resolve(), (root / args.output).resolve())
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
