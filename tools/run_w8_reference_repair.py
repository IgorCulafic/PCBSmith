"""Execute one real reference-field repair through the generic W8 transaction."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from pcbsmith.automatic_review_gate import ProductionMarkingAudit
from pcbsmith.bounded_local_repair import LocalRepairRequest
from pcbsmith.kicad.library import QuotedString, SExpr, parse_sexpr, serialize_sexpr
from pcbsmith.local_repair_execution import (
    RepairCandidateAssessment,
    execute_bounded_local_repair,
)
from pcbsmith.marking_repair_integration import MarkingRepairPlan
from pcbsmith.production_marking_adapter import (
    ProductionMarkingRequirements,
    audit_kicad_production_markings,
    inspect_saved_board_markings,
)
from pcbsmith.routed_copper_graph_ir import fingerprint


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-drc", type=Path, required=True)
    parser.add_argument("--source-audit", type=Path, required=True)
    parser.add_argument("--source-requirements", type=Path, required=True)
    parser.add_argument("--repair-plan", type=Path, required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--displacement-mm", type=float, required=True)
    parser.add_argument("--change-bounds", type=float, nargs=4, required=True)
    parser.add_argument("--transaction-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source_audit = ProductionMarkingAudit.model_validate_json(args.source_audit.read_text("utf-8"))
    source_requirements = ProductionMarkingRequirements.model_validate_json(
        args.source_requirements.read_text("utf-8")
    )
    plan = MarkingRepairPlan.model_validate_json(args.repair_plan.read_text("utf-8"))
    request: LocalRepairRequest = next(
        item for item in plan.repair_requests if item.request_id == args.request_id
    )
    protected = {"copper-and-placement": _protected_fingerprint(args.source)}

    def proposer(_source: Path, attempt_dir: Path, _attempt: int) -> Path:
        destination = attempt_dir / args.candidate.name
        shutil.copy2(args.candidate, destination)
        return destination

    def assessor(candidate: Path) -> RepairCandidateAssessment:
        inventory = inspect_saved_board_markings(candidate)
        requirements = ProductionMarkingRequirements.build(
            board_sha256=inventory.board_sha256,
            source_authority_sha256=source_requirements.source_authority_sha256,
            declaration_complete=source_requirements.declaration_complete,
            required_refdes_refs=inventory.footprint_refs,
            required_polarity_refs=source_requirements.required_polarity_refs,
            required_connector_mating_refs=(source_requirements.required_connector_mating_refs),
        )
        audit = audit_kicad_production_markings(
            inventory=inventory,
            requirements=requirements,
            drc_report=args.candidate_drc,
            drc_report_board_sha256=inventory.board_sha256,
        )
        source_findings = set(source_audit.finding_ids)
        candidate_findings = set(audit.finding_ids)
        return RepairCandidateAssessment.build(
            candidate_board_sha256=inventory.board_sha256,
            changed_object_ids=(args.reference,),
            moved_component_displacements_mm={args.reference: args.displacement_mm},
            removed_segment_ids=(),
            removed_via_ids=(),
            added_segment_ids=(),
            added_via_ids=(),
            change_bounds_mm=tuple(args.change_bounds),
            target_findings_removed=tuple(sorted(source_findings - candidate_findings)),
            new_finding_ids=tuple(sorted(candidate_findings - source_findings)),
            protected_region_fingerprints={
                "copper-and-placement": _protected_fingerprint(candidate)
            },
            unresolved_burden=(len(candidate_findings) + len(audit.unverified_check_ids)),
            craft_cost=0,
        )

    execution = execute_bounded_local_repair(
        source_board=args.source,
        transaction_root=args.transaction_root,
        request=request,
        source_protected_region_fingerprints=protected,
        source_unresolved_burden=(
            len(source_audit.finding_ids) + len(source_audit.unverified_check_ids)
        ),
        source_craft_cost=0,
        proposer=proposer,
        assessor=assessor,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(execution.model_dump_json(indent=2) + "\n", encoding="utf-8")
    print(execution.model_dump_json(indent=2))
    return 0 if execution.result.publish_authorized else 2


def _protected_fingerprint(board_file: Path) -> str:
    root = parse_sexpr(board_file.read_text("utf-8"))
    if not isinstance(root, list):
        raise ValueError("saved board root must be a list")
    retained: list[object] = []
    for item in root:
        if not isinstance(item, list):
            continue
        head = _atom(item[0]) if item else ""
        if head in {"net", "segment", "via", "zone"}:
            retained.append(item)
        elif head in {"gr_line", "gr_rect", "gr_arc", "gr_circle", "gr_poly"}:
            if any(
                isinstance(child, list)
                and child
                and _atom(child[0]) == "layer"
                and len(child) >= 2
                and _atom(child[1]) == "Edge.Cuts"
                for child in item
            ):
                retained.append(item)
        elif head in {"footprint", "module"}:
            retained.append(
                [
                    child
                    for child in item
                    if not isinstance(child, list)
                    or (child and _atom(child[0]) in {"layer", "uuid", "at", "pad"})
                ]
            )
    return fingerprint(serialize_sexpr(retained))


def _atom(value: SExpr) -> str:
    return value.value if isinstance(value, QuotedString) else str(value)


if __name__ == "__main__":
    raise SystemExit(main())
