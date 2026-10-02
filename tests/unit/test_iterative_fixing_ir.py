from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pcbsmith.cli import main
from pcbsmith.iterative_fixing_ir import (
    BoardDependencyGraph,
    ChangeImpactBudget,
    DependencyEdge,
    DependencyObject,
    DependencyObjectKind,
    DependencyRelation,
    DryRunDisposition,
    FindingFamily,
    FindingObservation,
    RepairOwnerStage,
    build_change_impact_envelope,
    build_saved_board_dependency_graph,
    diagnose_finding,
    generate_dry_run_impact_report,
    protected_inventory_matches,
)


def _board(tmp_path: Path) -> Path:
    board = tmp_path / "fixture.kicad_pcb"
    board.write_text(
        """(kicad_pcb
  (version 20240108)
  (generator pcbsmith-test)
  (net 0 "")
  (net 1 "SIG")
  (net 2 "GND")
  (footprint "Connector_Test"
    (layer "F.Cu")
    (uuid "fp-j1")
    (at 10 10)
    (property "Reference" "J1" (at 0 -2 0) (layer "F.SilkS"))
    (pad "1" thru_hole circle (at 0 0) (size 2 2) (drill 1) (layers "*.Cu" "*.Mask")
      (net 1 "SIG") (uuid "pad-j1-1"))
    (pad "2" thru_hole circle (at 2.54 0) (size 2 2) (drill 1) (layers "*.Cu" "*.Mask")
      (net 2 "GND") (uuid "pad-j1-2")))
  (footprint "Resistor_Test"
    (layer "F.Cu")
    (uuid "fp-r1")
    (at 20 10)
    (property "Reference" "R1" (at 0 -1.5 0) (layer "F.SilkS"))
    (pad "1" smd rect (at -1 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask")
      (net 1 "SIG") (uuid "pad-r1-1"))
    (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu" "F.Paste" "F.Mask")
      (net 2 "GND") (uuid "pad-r1-2")))
  (segment (start 10 10) (end 14 10) (width 0.25) (layer "F.Cu")
    (net 1) (uuid "seg-a"))
  (segment (start 15 10) (end 19 10) (width 0.25) (layer "F.Cu")
    (net 1) (uuid "seg-b"))
  (zone (net 2) (net_name "GND") (layer "B.Cu") (uuid "zone-z")
    (hatch edge 0.5)
    (polygon (pts (xy 5 5) (xy 25 5) (xy 25 15) (xy 5 15))))
  (gr_rect (start 0 0) (end 30 20) (stroke (width 0.05) (type default))
    (fill none) (layer "Edge.Cuts") (uuid "edge-a")))
""",
        encoding="utf-8",
    )
    return board


def _budget(**changes: int | float) -> ChangeImpactBudget:
    values: dict[str, int | float] = {
        "maximum_mutable_object_count": 8,
        "maximum_affected_net_count": 2,
        "maximum_region_count": 1,
        "maximum_existing_copper_object_count": 6,
        "maximum_component_count": 2,
        "maximum_added_segment_count": 4,
        "maximum_added_via_count": 2,
    }
    values.update(changes)
    return ChangeImpactBudget(**values)


def _observation(
    board: Path,
    family: FindingFamily,
    *,
    subject: tuple[str, ...] = (),
    mutable: tuple[str, ...] = (),
    nets: tuple[str, ...] = (),
    refs: tuple[str, ...] = (),
    detail_complete: bool = True,
) -> FindingObservation:
    board_sha = hashlib.sha256(board.read_bytes()).hexdigest()
    return FindingObservation(
        finding_id=f"fixture:{family}",
        evidence_fingerprint=hashlib.sha256(f"evidence:{family}".encode()).hexdigest(),
        source_board_sha256=board_sha,
        family=family,
        subject_object_ids=subject,
        mutable_object_ids=mutable,
        affected_net_names=nets,
        component_refs=refs,
        target_region_mm=(8.0, 8.0, 21.0, 12.0),
        detail_authority_complete=detail_complete,
    )


def test_saved_board_graph_has_stable_board_objects_and_exact_revision(tmp_path: Path) -> None:
    board = _board(tmp_path)
    first = build_saved_board_dependency_graph(board)
    second = build_saved_board_dependency_graph(board)
    ids = {item.object_id for item in first.objects}
    assert first == second
    assert first.graph_fingerprint == second.graph_fingerprint
    assert {"artifact:board", "component:J1", "footprint:J1", "pad:J1:pad-j1-1"} <= ids
    assert {"segment:seg-a", "segment:seg-b", "zone:zone-z", "marking:reference:R1"} <= ids
    assert first.source_board_sha256 == hashlib.sha256(board.read_bytes()).hexdigest()


def test_graph_and_report_fingerprints_do_not_depend_on_local_path(tmp_path: Path) -> None:
    board = _board(tmp_path)
    copy = tmp_path / "copy" / board.name
    copy.parent.mkdir()
    copy.write_bytes(board.read_bytes())
    first = build_saved_board_dependency_graph(board)
    second = build_saved_board_dependency_graph(copy)
    observation = _observation(board, FindingFamily.OPEN, nets=("SIG",))
    first_report = generate_dry_run_impact_report(
        board_file=board, observation=observation, budget=_budget()
    )
    second_report = generate_dry_run_impact_report(
        board_file=copy, observation=observation, budget=_budget()
    )
    assert first.graph_fingerprint == second.graph_fingerprint
    assert first_report.report_fingerprint == second_report.report_fingerprint


def test_graph_build_canonicalizes_input_order_and_rejects_unknown_edges(tmp_path: Path) -> None:
    graph = build_saved_board_dependency_graph(_board(tmp_path))
    rebuilt = BoardDependencyGraph.build(
        source_board_file=graph.source_board_file,
        source_board_sha256=graph.source_board_sha256,
        objects=tuple(reversed(graph.objects)),
        edges=tuple(reversed(graph.edges)),
        observed_authority_complete=True,
        unresolved_authority_ids=(),
    )
    assert rebuilt.graph_fingerprint == graph.graph_fingerprint
    bad_edge = DependencyEdge(
        source_object_id="artifact:board",
        target_object_id="missing:object",
        relation=DependencyRelation.CONTAINS,
    )
    with pytest.raises(ValidationError, match="unknown object"):
        BoardDependencyGraph.build(
            source_board_file=graph.source_board_file,
            source_board_sha256=graph.source_board_sha256,
            objects=graph.objects,
            edges=(*graph.edges, bad_edge),
            observed_authority_complete=True,
            unresolved_authority_ids=(),
        )


def test_graph_rejects_duplicate_object_identity(tmp_path: Path) -> None:
    graph = build_saved_board_dependency_graph(_board(tmp_path))
    with pytest.raises(ValidationError, match="identities must be unique"):
        BoardDependencyGraph.build(
            source_board_file=graph.source_board_file,
            source_board_sha256=graph.source_board_sha256,
            objects=(*graph.objects, graph.objects[0]),
            edges=graph.edges,
            observed_authority_complete=True,
            unresolved_authority_ids=(),
        )


def test_stale_finding_revision_is_rejected(tmp_path: Path) -> None:
    board = _board(tmp_path)
    graph = build_saved_board_dependency_graph(board)
    observation = _observation(board, FindingFamily.OPEN, nets=("SIG",)).model_copy(
        update={"source_board_sha256": "0" * 64}
    )
    with pytest.raises(ValueError, match="another board revision"):
        diagnose_finding(graph, observation)


def test_open_report_selects_only_existing_copper_on_affected_net(tmp_path: Path) -> None:
    board = _board(tmp_path)
    graph = build_saved_board_dependency_graph(board)
    diagnosis = diagnose_finding(
        graph,
        _observation(
            board,
            FindingFamily.OPEN,
            subject=("pad:J1:pad-j1-1", "segment:seg-a"),
            nets=("SIG",),
        ),
    )
    envelope = build_change_impact_envelope(graph, diagnosis, _budget())
    assert envelope.disposition is DryRunDisposition.READY_FOR_CANDIDATE_TRANSACTION
    assert envelope.mutable_object_ids == ("segment:seg-a", "segment:seg-b")
    assert "pad:J1:pad-j1-1" not in envelope.mutable_object_ids
    assert envelope.mutable_net_names == ("SIG",)


def test_clearance_requires_explicit_mutation_side(tmp_path: Path) -> None:
    board = _board(tmp_path)
    graph = build_saved_board_dependency_graph(board)
    ambiguous = diagnose_finding(
        graph,
        _observation(
            board,
            FindingFamily.CLEARANCE,
            subject=("segment:seg-a", "segment:seg-b"),
            nets=("SIG",),
        ),
    )
    assert (
        build_change_impact_envelope(graph, ambiguous, _budget()).disposition
        is DryRunDisposition.BLOCKED_UNRESOLVED_AUTHORITY
    )
    resolved = diagnose_finding(
        graph,
        _observation(
            board,
            FindingFamily.CLEARANCE,
            subject=("segment:seg-a", "segment:seg-b"),
            mutable=("segment:seg-a",),
            nets=("SIG",),
        ),
    )
    envelope = build_change_impact_envelope(graph, resolved, _budget())
    assert envelope.disposition is DryRunDisposition.READY_FOR_CANDIDATE_TRANSACTION
    assert envelope.mutable_object_ids == ("segment:seg-a",)
    assert any(item.object_id == "segment:seg-b" for item in envelope.protected_inventory.objects)


def test_isolated_zone_scope_mutates_only_zone_intent(tmp_path: Path) -> None:
    board = _board(tmp_path)
    graph = build_saved_board_dependency_graph(board)
    diagnosis = diagnose_finding(
        graph,
        _observation(
            board,
            FindingFamily.ISOLATED_ZONE,
            subject=("zone:zone-z",),
            mutable=("zone:zone-z",),
            nets=("GND",),
        ),
    )
    envelope = build_change_impact_envelope(graph, diagnosis, _budget())
    assert envelope.mutable_object_ids == ("zone:zone-z",)
    assert envelope.disposition is DryRunDisposition.READY_FOR_CANDIDATE_TRANSACTION
    assert "final_fill" in envelope.required_post_change_gates


def test_marking_scope_does_not_move_component(tmp_path: Path) -> None:
    board = _board(tmp_path)
    graph = build_saved_board_dependency_graph(board)
    diagnosis = diagnose_finding(
        graph,
        _observation(
            board,
            FindingFamily.MARKING,
            subject=("marking:reference:R1",),
            mutable=("marking:reference:R1",),
            refs=("R1",),
        ),
    )
    envelope = build_change_impact_envelope(graph, diagnosis, _budget())
    assert envelope.mutable_object_ids == ("marking:reference:R1",)
    assert "footprint:R1" not in envelope.mutable_object_ids
    assert any(item.object_id == "footprint:R1" for item in envelope.protected_inventory.objects)


def test_parity_count_without_details_fails_closed(tmp_path: Path) -> None:
    board = _board(tmp_path)
    graph = build_saved_board_dependency_graph(board, require_schematic_authority=True)
    diagnosis = diagnose_finding(
        graph,
        _observation(
            board,
            FindingFamily.SCHEMATIC_PARITY,
            subject=("artifact:board",),
            detail_complete=False,
        ),
    )
    envelope = build_change_impact_envelope(graph, diagnosis, _budget())
    assert envelope.disposition is DryRunDisposition.BLOCKED_UNRESOLVED_AUTHORITY
    assert "schematic_parity_detail_required" in envelope.blocker_ids
    assert not envelope.mutable_object_ids


def test_budget_boundary_accepts_equal_and_rejects_one_over(tmp_path: Path) -> None:
    board = _board(tmp_path)
    graph = build_saved_board_dependency_graph(board)
    diagnosis = diagnose_finding(
        graph,
        _observation(board, FindingFamily.OPEN, nets=("SIG",)),
    )
    equal = build_change_impact_envelope(
        graph,
        diagnosis,
        _budget(maximum_mutable_object_count=2, maximum_existing_copper_object_count=2),
    )
    over = build_change_impact_envelope(
        graph,
        diagnosis,
        _budget(maximum_mutable_object_count=1, maximum_existing_copper_object_count=2),
    )
    assert equal.disposition is DryRunDisposition.READY_FOR_CANDIDATE_TRANSACTION
    assert over.disposition is DryRunDisposition.BLOCKED_BUDGET
    assert "budget:mutable_objects:2>1" in over.blocker_ids


def test_graph_hop_budget_is_enforced_without_cycle_loop(tmp_path: Path) -> None:
    board = _board(tmp_path)
    graph = build_saved_board_dependency_graph(board)
    diagnosis = diagnose_finding(
        graph,
        _observation(
            board,
            FindingFamily.OPEN,
            subject=("pad:J1:pad-j1-1",),
            nets=("SIG",),
        ),
    )
    envelope = build_change_impact_envelope(
        graph,
        diagnosis,
        _budget(maximum_graph_hops=0),
    )
    assert envelope.disposition is DryRunDisposition.BLOCKED_BUDGET
    assert "budget:graph_hops:1>0" in envelope.blocker_ids


def test_protected_inventory_detects_tampered_object(tmp_path: Path) -> None:
    board = _board(tmp_path)
    graph = build_saved_board_dependency_graph(board)
    diagnosis = diagnose_finding(
        graph,
        _observation(board, FindingFamily.MARKING, refs=("R1",)),
    )
    inventory = build_change_impact_envelope(graph, diagnosis, _budget()).protected_inventory
    assert protected_inventory_matches(inventory, graph)
    target = next(item for item in graph.objects if item.object_id == "footprint:R1")
    changed = target.model_copy(update={"source_object_fingerprint": "f" * 64})
    altered_graph = graph.model_copy(
        update={
            "objects": tuple(
                changed if item.object_id == target.object_id else item for item in graph.objects
            )
        }
    )
    assert not protected_inventory_matches(inventory, altered_graph)


def test_dry_run_never_changes_source_or_claims_acceptance(tmp_path: Path) -> None:
    board = _board(tmp_path)
    before = board.read_bytes()
    report = generate_dry_run_impact_report(
        board_file=board,
        observation=_observation(board, FindingFamily.OPEN, nets=("SIG",)),
        budget=_budget(),
    )
    assert board.read_bytes() == before
    assert report.source_board_sha256_before == report.source_board_sha256_after
    assert not report.source_mutated
    assert not report.candidate_created
    assert not report.acceptance_claimed


def test_cli_writes_replayable_dry_run_report(tmp_path: Path) -> None:
    board = _board(tmp_path)
    observation_file = tmp_path / "finding.json"
    budget_file = tmp_path / "budget.json"
    output = tmp_path / "report.json"
    observation_file.write_text(
        _observation(board, FindingFamily.OPEN, nets=("SIG",)).model_dump_json(indent=2),
        encoding="utf-8",
    )
    budget_file.write_text(_budget().model_dump_json(indent=2), encoding="utf-8")
    result = main(
        [
            "iterative-fix-dry-run",
            str(board),
            "--finding",
            str(observation_file),
            "--budget",
            str(budget_file),
            "--output",
            str(output),
        ]
    )
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert result == 0
    assert payload["schema_id"] == "pcbsmith-iterative-fix-dry-run-v1"
    assert payload["source_board_sha256_before"] == payload["source_board_sha256_after"]


def test_dependency_object_rejects_cross_revision_fingerprint() -> None:
    with pytest.raises(ValidationError, match="source_board_sha256"):
        DependencyObject(
            object_id="component:U1",
            object_kind=DependencyObjectKind.COMPONENT,
            authority_stage=RepairOwnerStage.SEMANTIC_DESIGN,
            source_board_sha256="bad",
            source_object_fingerprint="0" * 64,
        )
