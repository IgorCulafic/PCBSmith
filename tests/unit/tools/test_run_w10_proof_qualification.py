from __future__ import annotations

import hashlib
from pathlib import Path

from tools.run_w10_proof_qualification import _copy_project_context, _missing_manifest

from pcbsmith.automatic_review_gate import CANONICAL_FINAL_ARTIFACT_IDS


def test_missing_manifest_is_hash_bound_and_fail_closed(tmp_path: Path) -> None:
    board = tmp_path / "proof.kicad_pcb"
    board.write_text("(kicad_pcb)", encoding="utf-8")

    manifest = _missing_manifest(board, "render stopped")

    assert manifest.board_sha256 == hashlib.sha256(board.read_bytes()).hexdigest()
    assert manifest.package_status == "generation_failed"
    assert tuple(item.artifact_id for item in manifest.artifacts) == (
        CANONICAL_FINAL_ARTIFACT_IDS
    )
    assert all(item.state == "missing" for item in manifest.artifacts)


def test_project_context_uses_project_stem_without_mutating_source(tmp_path: Path) -> None:
    case = tmp_path / "case"
    case.mkdir()
    (case / "Demo.kicad_pro").write_text("project", encoding="utf-8")
    (case / "Demo.kicad_sch").write_text("schematic", encoding="utf-8")
    (case / "sym-lib-table").write_text("symbols", encoding="utf-8")
    source = case / "router-output.kicad_pcb"
    source.write_text("board", encoding="utf-8")
    source_before = source.read_bytes()

    board, schematic = _copy_project_context(case, tmp_path / "candidate", source)

    assert board.name == "Demo.kicad_pcb"
    assert schematic.name == "Demo.kicad_sch"
    assert board.read_bytes() == source_before
    assert source.read_bytes() == source_before