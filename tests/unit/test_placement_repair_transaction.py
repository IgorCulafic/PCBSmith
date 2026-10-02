from __future__ import annotations

import hashlib
from pathlib import Path

from pcbsmith.placement_repair_transaction import (
    PlacementPose,
    extract_placement_snapshot,
    run_placement_repair_transaction,
)


def _board(path: Path) -> Path:
    path.write_text(
        """(kicad_pcb (version 20240108)
  (net 1 "SIG") (net 2 "GND")
  (footprint "A" (layer "F.Cu") (at 10 10)
    (property "Reference" "U1")
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG")))
  (footprint "B" (layer "F.Cu") (at 30 10)
    (property "Reference" "C1")
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG"))
    (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu") (net 2 "GND")))
  (footprint "C" (layer "F.Cu") (at 50 10)
    (property "Reference" "J1")
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 2 "GND"))))
""",
        encoding="utf-8",
    )
    return path


def test_topology_extraction_weights_signal_relations(tmp_path: Path) -> None:
    snapshot = extract_placement_snapshot(_board(tmp_path / "x.kicad_pcb"))
    relation = next(
        item
        for item in snapshot.relations
        if {item.first_reference, item.second_reference} == {"U1", "C1"}
    )
    assert relation.shared_nets == ("SIG",)
    assert relation.weight == 2.0


def test_transaction_compacts_cluster_and_preserves_unrelated_pose(tmp_path: Path) -> None:
    source = _board(tmp_path / "x.kicad_pcb")
    result = run_placement_repair_transaction(
        source_board=source,
        target_poses=(PlacementPose(reference="C1", x_mm=15, y_mm=10),),
        retained_root=tmp_path / "retained",
        minimum_anchor_spacing_mm=2,
        exact_validator=lambda _path: (),
    )
    assert result.accepted
    assert result.changed_references == ("C1",)
    before = {pose.reference: pose for pose in result.before.poses}
    after = {pose.reference: pose for pose in result.after.poses}
    assert after["J1"] == before["J1"]
    assert result.after.topology_cost < result.before.topology_cost
    assert "(at 30 10)" in source.read_text(encoding="utf-8")


def test_exact_validator_and_spacing_gate_reject_candidate(tmp_path: Path) -> None:
    source = _board(tmp_path / "x.kicad_pcb")
    result = run_placement_repair_transaction(
        source_board=source,
        target_poses=(PlacementPose(reference="C1", x_mm=10.5, y_mm=10),),
        retained_root=tmp_path / "retained",
        minimum_anchor_spacing_mm=2,
        exact_validator=lambda _path: ("routing_capacity_failed",),
    )
    assert not result.accepted
    assert "anchor_spacing:C1:U1" in result.blockers
    assert "routing_capacity_failed" in result.blockers


def test_transaction_retains_project_library_context_and_post_validator_hash(
    tmp_path: Path,
) -> None:
    source = _board(tmp_path / "x.kicad_pcb")
    (tmp_path / "fp-lib-table").write_text("(fp_lib_table)\n", encoding="utf-8")
    library = tmp_path / "PCBSmith.pretty"
    library.mkdir()
    (library / "Part.kicad_mod").write_text("(footprint Part)\n", encoding="utf-8")

    def validator(candidate: Path) -> tuple[str, ...]:
        candidate.write_text(candidate.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        assert (candidate.parent / "fp-lib-table").exists()
        assert (candidate.parent / "PCBSmith.pretty" / "Part.kicad_mod").exists()
        return ()

    result = run_placement_repair_transaction(
        source_board=source,
        target_poses=(PlacementPose(reference="C1", x_mm=15, y_mm=10),),
        retained_root=tmp_path / "retained",
        minimum_anchor_spacing_mm=2,
        exact_validator=validator,
    )

    retained = Path(result.retained_board)
    assert result.accepted
    assert retained.parent.name == f"candidate-{result.after.board_sha256[:12]}"
    assert retained.parent.joinpath("fp-lib-table").exists()
    assert retained.parent.joinpath("PCBSmith.pretty", "Part.kicad_mod").exists()
    assert hashlib.sha256(retained.read_bytes()).hexdigest() == result.after.board_sha256


def test_transaction_rejects_validator_pose_mutation(tmp_path: Path) -> None:
    source = _board(tmp_path / "x.kicad_pcb")

    def validator(candidate: Path) -> tuple[str, ...]:
        text = candidate.read_text(encoding="utf-8")
        candidate.write_text(text.replace("(at 50 10)", "(at 49 10)"), encoding="utf-8")
        return ()

    result = run_placement_repair_transaction(
        source_board=source,
        target_poses=(PlacementPose(reference="C1", x_mm=15, y_mm=10),),
        retained_root=tmp_path / "retained",
        minimum_anchor_spacing_mm=2,
        exact_validator=validator,
    )

    assert not result.accepted
    assert "exact_validator_changed_protected_placement" in result.blockers


def test_transaction_rejects_requested_pose_off_declared_grid(tmp_path: Path) -> None:
    source = _board(tmp_path / "x.kicad_pcb")
    result = run_placement_repair_transaction(
        source_board=source,
        target_poses=(PlacementPose(reference="C1", x_mm=15.1, y_mm=10),),
        retained_root=tmp_path / "retained",
        minimum_anchor_spacing_mm=2,
        exact_validator=lambda _path: (),
        placement_grid_mm=0.25,
    )

    assert not result.accepted
    assert "placement_off_grid:C1" in result.blockers
