from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pcbsmith.iterative_fixing_ir import (
    ChangeImpactBudget,
    FindingFamily,
    FindingObservation,
    generate_dry_run_impact_report,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "experiments" / "phase17-if1-dry-run-proof-2026-08-20"
W10_ROOT = ROOT / "experiments" / "phase17-w10-proof-boards-v1-2026-08-20"
W9_ROOT = ROOT / "experiments" / "phase17-w9-hard-set-audit-2026-08-20"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _budget(**updates: int | float) -> ChangeImpactBudget:
    values: dict[str, int | float] = {
        "maximum_mutable_object_count": 8,
        "maximum_affected_net_count": 2,
        "maximum_region_count": 1,
        "maximum_existing_copper_object_count": 6,
        "maximum_component_count": 2,
        "maximum_graph_hops": 2,
        "maximum_component_displacement_mm": 3.0,
        "maximum_component_rotation_degrees": 90.0,
        "maximum_ripped_segment_count": 4,
        "maximum_ripped_via_count": 2,
        "maximum_added_segment_count": 6,
        "maximum_added_via_count": 2,
        "maximum_candidate_count": 4,
        "maximum_elapsed_seconds": 60.0,
    }
    values.update(updates)
    return ChangeImpactBudget(**values)


def _observation(
    *,
    board: Path,
    finding_id: str,
    evidence_fingerprint: str,
    family: FindingFamily,
    subjects: tuple[str, ...] = (),
    mutable: tuple[str, ...] = (),
    nets: tuple[str, ...] = (),
    refs: tuple[str, ...] = (),
    region: tuple[float, float, float, float] | None = None,
    detail_complete: bool = True,
) -> FindingObservation:
    return FindingObservation(
        finding_id=finding_id,
        evidence_fingerprint=evidence_fingerprint,
        source_board_sha256=_sha(board),
        family=family,
        subject_object_ids=subjects,
        mutable_object_ids=mutable,
        affected_net_names=nets,
        component_refs=refs,
        target_region_mm=region,
        detail_authority_complete=detail_complete,
    )


def _run_case(
    case_id: str,
    *,
    board: Path,
    observation: FindingObservation,
    budget: ChangeImpactBudget,
    evidence_class: str,
    require_schematic_authority: bool = False,
) -> dict[str, Any]:
    before = _sha(board)
    first = generate_dry_run_impact_report(
        board_file=board,
        observation=observation,
        budget=budget,
        require_schematic_authority=require_schematic_authority,
    )
    second = generate_dry_run_impact_report(
        board_file=board,
        observation=observation,
        budget=budget,
        require_schematic_authority=require_schematic_authority,
    )
    after = _sha(board)
    if first.report_fingerprint != second.report_fingerprint:
        raise RuntimeError(f"{case_id}: dry-run replay is nondeterministic")
    if before != after or first.source_mutated:
        raise RuntimeError(f"{case_id}: source board changed during dry run")
    case_dir = OUTPUT / case_id
    _write_json(case_dir / "finding-observation.json", observation.model_dump(mode="json"))
    _write_json(case_dir / "impact-budget.json", budget.model_dump(mode="json"))
    _write_json(case_dir / "dry-run-impact-report.json", first.model_dump(mode="json"))
    return {
        "case_id": case_id,
        "evidence_class": evidence_class,
        "source_board": str(board.relative_to(ROOT)),
        "source_board_sha256": before,
        "source_hash_unchanged": before == after,
        "replay_deterministic": first.report_fingerprint == second.report_fingerprint,
        "finding_family": observation.family,
        "owner_stage": first.diagnosis.owner_stage,
        "scope": first.diagnosis.scope,
        "disposition": first.envelope.disposition,
        "mutable_object_ids": list(first.envelope.mutable_object_ids),
        "mutable_net_names": list(first.envelope.mutable_net_names),
        "protected_object_count": len(first.envelope.protected_inventory.objects),
        "blocker_ids": list(first.envelope.blocker_ids),
        "required_post_change_gates": list(first.envelope.required_post_change_gates),
        "graph_fingerprint": first.graph.graph_fingerprint,
        "diagnosis_fingerprint": first.diagnosis.diagnosis_fingerprint,
        "envelope_fingerprint": first.envelope.envelope_fingerprint,
        "report_fingerprint": first.report_fingerprint,
    }


def _fault_fixture_board() -> Path:
    board = OUTPUT / "fault-fixtures" / "if1-local-faults.kicad_pcb"
    board.parent.mkdir(parents=True, exist_ok=True)
    board.write_text(
        """(kicad_pcb
  (version 20240108)
  (generator pcbsmith-if1-proof)
  (net 0 "")
  (net 1 "SIG")
  (net 2 "GND")
  (footprint "Connector_Test"
    (layer "F.Cu")
    (uuid "fixture-fp-j1")
    (at 10 10)
    (property "Reference" "J1" (at 0 -2 0) (layer "F.SilkS"))
    (pad "1" thru_hole circle (at 0 0) (size 2 2) (drill 1) (layers "*.Cu" "*.Mask")
      (net 1 "SIG") (uuid "fixture-pad-j1-1"))
    (pad "2" thru_hole circle (at 2.54 0) (size 2 2) (drill 1) (layers "*.Cu" "*.Mask")
      (net 2 "GND") (uuid "fixture-pad-j1-2")))
  (footprint "Resistor_Test"
    (layer "F.Cu")
    (uuid "fixture-fp-r1")
    (at 20 10)
    (property "Reference" "R1" (at 0 -1.5 0) (layer "F.SilkS"))
    (pad "1" smd rect (at -1 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask")
      (net 1 "SIG") (uuid "fixture-pad-r1-1"))
    (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask")
      (net 2 "GND") (uuid "fixture-pad-r1-2")))
  (segment (start 10 10) (end 14 10) (width 0.25) (layer "F.Cu")
    (net 1) (uuid "fixture-seg-a"))
  (segment (start 15 10) (end 19 10) (width 0.25) (layer "F.Cu")
    (net 1) (uuid "fixture-seg-b"))
  (zone (net 2) (net_name "GND") (layer "B.Cu") (uuid "fixture-zone-z")
    (hatch edge 0.5)
    (polygon (pts (xy 5 5) (xy 25 5) (xy 25 15) (xy 5 15))))
  (gr_rect (start 0 0) (end 30 20) (stroke (width 0.05) (type default))
    (fill none) (layer "Edge.Cuts") (uuid "fixture-edge-a")))
""",
        encoding="utf-8",
    )
    return board


def _w10_case(case: str, design: str) -> tuple[Path, FindingObservation, ChangeImpactBudget]:
    root = W10_ROOT / "qualification" / case
    board = root / "final-revision" / f"{design}.kicad_pcb"
    drc = root / "drc-report.json"
    payload = json.loads(drc.read_text(encoding="utf-8"))
    parity_count = len(payload.get("schematic_parity", []))
    if parity_count <= 0:
        raise RuntimeError(f"{case}: retained DRC no longer contains parity findings")
    observation = _observation(
        board=board,
        finding_id=f"schematic-parity-count:{parity_count}",
        evidence_fingerprint=_sha(drc),
        family=FindingFamily.SCHEMATIC_PARITY,
        subjects=("artifact:board",),
        detail_complete=False,
    )
    return (
        board,
        observation,
        _budget(
            maximum_mutable_object_count=0,
            maximum_affected_net_count=0,
            maximum_region_count=0,
            maximum_existing_copper_object_count=0,
            maximum_component_count=0,
        ),
    )


def _rt37_case() -> tuple[Path, FindingObservation, ChangeImpactBudget]:
    root = W9_ROOT / "RT37-tqfp48-sparse-controller"
    inventory = json.loads((root / "inventory.json").read_text(encoding="utf-8"))
    plan = json.loads((root / "marking-repair-plan.json").read_text(encoding="utf-8"))
    request = plan["repair_requests"][0]
    board = Path(inventory["board_file"])
    references = tuple(request["movable_component_references"])
    if len(references) != 1:
        raise RuntimeError("RT37 proof expects one localized marking reference")
    marking_id = f"marking:reference:{references[0]}"
    observation = _observation(
        board=board,
        finding_id=request["target_finding_ids"][0],
        evidence_fingerprint=plan["marking_audit_fingerprint"],
        family=FindingFamily.MARKING,
        subjects=(marking_id,),
        mutable=(marking_id,),
        refs=references,
        region=tuple(request["target_region_mm"]),
    )
    return (
        board,
        observation,
        _budget(
            maximum_mutable_object_count=1,
            maximum_affected_net_count=0,
            maximum_region_count=1,
            maximum_existing_copper_object_count=0,
            maximum_component_count=1,
            maximum_ripped_segment_count=0,
            maximum_ripped_via_count=0,
            maximum_added_segment_count=0,
            maximum_added_via_count=0,
        ),
    )


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    cases: list[dict[str, Any]] = []
    for case, design in (
        ("W10A-ne555-status-pulser", "W10A_NE555_Status_Pulser"),
        ("W10B-12v-to-5v-buck", "W10B_12V_to_5V_Buck"),
    ):
        board, observation, budget = _w10_case(case, design)
        cases.append(
            _run_case(
                f"{case}-parity",
                board=board,
                observation=observation,
                budget=budget,
                evidence_class="retained_real_board_and_kicad_drc",
                require_schematic_authority=True,
            )
        )

    board, observation, budget = _rt37_case()
    cases.append(
        _run_case(
            "RT37-marking",
            board=board,
            observation=observation,
            budget=budget,
            evidence_class="retained_real_board_and_w9_marking_audit",
        )
    )

    fixture = _fault_fixture_board()
    fixture_sha = _sha(fixture)
    fixture_specs = (
        (
            "fixture-open",
            _observation(
                board=fixture,
                finding_id="fixture:open:SIG",
                evidence_fingerprint=hashlib.sha256(b"if1-open-fixture-v1").hexdigest(),
                family=FindingFamily.OPEN,
                subjects=("pad:J1:fixture-pad-j1-1", "segment:fixture-seg-a"),
                nets=("SIG",),
                region=(9.0, 9.0, 20.0, 11.0),
            ),
            _budget(),
        ),
        (
            "fixture-clearance",
            _observation(
                board=fixture,
                finding_id="fixture:clearance:segment-pair",
                evidence_fingerprint=hashlib.sha256(b"if1-clearance-fixture-v1").hexdigest(),
                family=FindingFamily.CLEARANCE,
                subjects=("segment:fixture-seg-a", "segment:fixture-seg-b"),
                mutable=("segment:fixture-seg-a",),
                nets=("SIG",),
                region=(9.0, 9.0, 20.0, 11.0),
            ),
            _budget(maximum_mutable_object_count=1, maximum_existing_copper_object_count=1),
        ),
        (
            "fixture-isolated-zone",
            _observation(
                board=fixture,
                finding_id="fixture:isolated-zone:GND",
                evidence_fingerprint=hashlib.sha256(b"if1-isolated-zone-fixture-v1").hexdigest(),
                family=FindingFamily.ISOLATED_ZONE,
                subjects=("zone:fixture-zone-z",),
                mutable=("zone:fixture-zone-z",),
                nets=("GND",),
                region=(5.0, 5.0, 25.0, 15.0),
            ),
            _budget(maximum_mutable_object_count=1, maximum_existing_copper_object_count=1),
        ),
    )
    for case_id, observation, budget in fixture_specs:
        cases.append(
            _run_case(
                case_id,
                board=fixture,
                observation=observation,
                budget=budget,
                evidence_class="explicit_injected_fault_fixture",
            )
        )
    if _sha(fixture) != fixture_sha:
        raise RuntimeError("shared fault fixture changed during dry-run proof")

    summary = {
        "schema_id": "pcbsmith-phase17-if1-dry-run-proof-v1",
        "case_count": len(cases),
        "real_retained_case_count": sum(
            item["evidence_class"].startswith("retained_real") for item in cases
        ),
        "injected_fault_fixture_count": sum(
            item["evidence_class"] == "explicit_injected_fault_fixture" for item in cases
        ),
        "all_source_hashes_unchanged": all(item["source_hash_unchanged"] for item in cases),
        "all_replays_deterministic": all(item["replay_deterministic"] for item in cases),
        "candidate_files_created": 0,
        "acceptance_claims": 0,
        "cases": cases,
    }
    _write_json(OUTPUT / "summary.json", summary)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
