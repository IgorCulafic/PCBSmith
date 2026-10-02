"""Run exact W9 marking/review/repair integration on the eight hard cases."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from pcbsmith.automatic_review_gate import (
    CANONICAL_FINAL_ARTIFACT_IDS,
    qualify_automatic_review,
)
from pcbsmith.bounded_local_repair import LocalRepairBudget
from pcbsmith.kicad.routing_evidence import inspect_kicad_drc_report, inspect_saved_board_routing
from pcbsmith.marking_repair_integration import build_marking_repair_plan
from pcbsmith.production_marking_adapter import (
    ProductionMarkingRequirements,
    audit_kicad_production_markings,
    inspect_saved_board_markings,
)
from pcbsmith.review.visual_package import RenderProfile, ReviewArtifact, VisualReviewManifest
from pcbsmith.routed_copper_graph_ir import fingerprint
from pcbsmith.whole_board_qualification_adapter import qualify_production_board


def _missing_manifest(board: Path, board_sha256: str) -> VisualReviewManifest:
    return VisualReviewManifest(
        schema="pcbsmith-visual-review-manifest-v1",
        render_profile=RenderProfile(),
        stage="final",
        board_file=str(board.resolve()),
        board_sha256=board_sha256,
        copper_sha256=board_sha256,
        kicad_version="10.0.3",
        renderer_version="unavailable:not-generated",
        model_preflight_status="unavailable:not-run",
        package_status="generation_failed",
        artifacts=tuple(
            ReviewArtifact(
                artifact_id=artifact_id,
                category="canonical-final",
                relative_path=f"missing/{artifact_id.replace(':', '-')}.png",
                media_type="image/png",
                required=True,
                state="missing",
            )
            for artifact_id in CANONICAL_FINAL_ARTIFACT_IDS
        ),
        findings=("canonical final review artifacts were not generated",),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("hard_set", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for case_dir in sorted((args.hard_set / "boards").iterdir()):
        if not case_dir.is_dir():
            continue
        revisions = sorted((case_dir / "placement-check").glob("revision-*"))
        if not revisions:
            continue
        revision = revisions[-1]
        board = revision / "source-placement.kicad_pcb"
        drc = revision / "drc.json"
        contract = case_dir / "case-contract.json"
        contract_data = json.loads(contract.read_text("utf-8"))
        requested = tuple(
            sorted(
                str(item["reference"])
                for item in contract_data.get("placements", [])
                if isinstance(item, dict) and item.get("reference")
            )
        )
        inventory = inspect_saved_board_markings(board)
        requirements = ProductionMarkingRequirements.build(
            board_sha256=inventory.board_sha256,
            source_authority_sha256=hashlib.sha256(contract.read_bytes()).hexdigest(),
            declaration_complete=False,
            required_refdes_refs=requested,
        )
        audit = audit_kicad_production_markings(
            inventory=inventory,
            requirements=requirements,
            drc_report=drc,
            drc_report_board_sha256=inventory.board_sha256,
        )
        manifest = _missing_manifest(board, inventory.board_sha256)
        manifest_fingerprint = fingerprint(manifest.model_dump(mode="json"))
        preliminary_review = qualify_automatic_review(
            manifest=manifest,
            manifest_fingerprint=manifest_fingerprint,
            marking_audit=audit,
        )
        preliminary_qualification = qualify_production_board(
            case_id=str(contract_data.get("case_id", case_dir.name)),
            refilled_board_sha256=inventory.board_sha256,
            drc_evidence=inspect_kicad_drc_report(drc),
            drc_board_sha256=inventory.board_sha256,
            routing_evidence=inspect_saved_board_routing(board),
            fill_snapshot=None,
            fill_connectivity=None,
            thermal_audit=None,
            topology=None,
            reference_continuity=None,
            automatic_review=preliminary_review,
            craft=None,
        )
        repair_plan = build_marking_repair_plan(
            audit=audit,
            drc_report=drc,
            source_qualification_fingerprint=(
                preliminary_qualification.qualification_fingerprint
            ),
            budget=LocalRepairBudget(
                maximum_displacement_mm=3.0,
                maximum_ripped_segment_count=0,
                maximum_ripped_via_count=0,
                maximum_added_segment_count=0,
                maximum_added_via_count=0,
                maximum_attempt_count=4,
                maximum_elapsed_seconds=60.0,
            ),
        )
        review = qualify_automatic_review(
            manifest=manifest,
            manifest_fingerprint=manifest_fingerprint,
            marking_audit=audit,
            proposed_repair_request_fingerprints=tuple(
                item.request_fingerprint for item in repair_plan.repair_requests
            ),
        )
        case_output = output / case_dir.name
        case_output.mkdir(parents=True, exist_ok=True)
        payloads = {
            "inventory.json": inventory.model_dump_json(indent=2),
            "requirements.json": requirements.model_dump_json(indent=2),
            "marking-audit.json": audit.model_dump_json(indent=2),
            "visual-manifest.json": manifest.model_dump_json(indent=2, by_alias=True),
            "automatic-review.json": review.model_dump_json(indent=2),
            "preliminary-qualification.json": preliminary_qualification.model_dump_json(indent=2),
            "marking-repair-plan.json": repair_plan.model_dump_json(indent=2),
        }
        for name, payload in payloads.items():
            (case_output / name).write_text(payload + "\n", encoding="utf-8")
        rows.append(
            {
                "case_id": str(contract_data.get("case_id", case_dir.name)),
                "case_directory": case_dir.name,
                "board_sha256": inventory.board_sha256,
                "inspected_mark_count": audit.inspected_mark_count,
                "finding_count": len(audit.finding_ids),
                "silk_over_copper_count": len(audit.silk_over_copper_finding_ids),
                "silk_over_silk_count": len(audit.silk_over_silk_finding_ids),
                "silk_edge_count": len(audit.silk_edge_finding_ids),
                "missing_refdes_count": len(audit.missing_refdes_finding_ids),
                "unverified_check_ids": list(audit.unverified_check_ids),
                "localized_repair_request_count": len(repair_plan.repair_requests),
                "unlocalized_finding_count": len(repair_plan.unlocalized_finding_ids),
                "visual_package_complete": review.visual_package_complete,
                "w7_release_qualified": preliminary_qualification.release_qualified,
                "exact_gate_passed": (
                    audit.inspected_mark_count > 0
                    and not audit.finding_ids
                    and not audit.unverified_check_ids
                ),
            }
        )
    summary = {
        "schema": "pcbsmith-w9-hard-set-integration-v1",
        "case_count": len(rows),
        "exact_pass_count": sum(bool(item["exact_gate_passed"]) for item in rows),
        "total_finding_count": sum(int(item["finding_count"]) for item in rows),
        "localized_repair_request_count": sum(
            int(item["localized_repair_request_count"]) for item in rows
        ),
        "cases": rows,
        "qualification_boundary": (
            "Exact saved-board refdes/silkscreen inventory plus revision-bound KiCad DRC, "
            "missing canonical review manifests, W7 fail-closed qualification, and localized "
            "W8 requests. No repair candidate is accepted or source board mutated in this audit. "
            "Legacy case contracts omit polarity/connector-mating declarations."
        ),
    }
    (output / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["exact_pass_count"] == summary["case_count"] else 2


if __name__ == "__main__":
    raise SystemExit(main())