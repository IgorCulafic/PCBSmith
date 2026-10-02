"""Rejection tests: these never create an accepted inspection record."""

import hashlib

import pytest
from tests.unit.review.test_visual_package import (
    FakeRunner,
    _board,
    _model_report,
    _rasterize,
)

from pcbsmith.kicad.cli import KiCadInstall
from pcbsmith.kicad.library import parse_sexpr
from pcbsmith.review.visual_package import (
    ReviewFeatures,
    _augment_features_from_board,
    generate_visual_review_package,
    record_visual_inspection,
)


@pytest.mark.parametrize(
    "failure",
    [
        "blank_findings",
        "blank_reviewer",
        "blank_mechanism",
        "changed_image",
        "missing_image",
        "unknown_id",
        "bad_state",
    ],
)
def test_invalid_inspection_batch_never_changes_manifest(tmp_path, failure):
    board = _board(tmp_path)
    manifest = generate_visual_review_package(
        board_file=board,
        output_dir=tmp_path / "out",
        stage="placement",
        features=ReviewFeatures(),
        model_preflight=_model_report(board),
        finder=lambda: KiCadInstall(path=board, source="fixture"),
        runner=FakeRunner(),
        rasterizer=_rasterize,
    )
    path = tmp_path / "out/review/manifest.json"
    artifact = next(a for a in manifest.artifacts if a.required)
    decisions = {artifact.artifact_id: ("attention_required", ("Software rejection control.",))}
    reviewer, mechanism = "fixture", "test-only"
    if failure == "blank_findings":
        decisions[artifact.artifact_id] = ("accepted", ())
    elif failure == "blank_reviewer":
        reviewer = " "
    elif failure == "blank_mechanism":
        mechanism = " "
    elif failure == "changed_image":
        (path.parent / artifact.relative_path).write_bytes(b"changed")
    elif failure == "missing_image":
        (path.parent / artifact.relative_path).unlink()
    elif failure == "unknown_id":
        decisions["absent"] = ("attention_required", ("No such artifact.",))
    else:
        decisions[artifact.artifact_id] = ("typo", ("Invalid state.",))
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        record_visual_inspection(path, reviewer=reviewer, mechanism=mechanism, decisions=decisions)
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_cutout_in_native_outline_triggers_views_without_caller_flag():
    outer = '(gr_rect (start 0 0) (end 20 20) (layer "Edge.Cuts"))'
    inner = '(gr_circle (center 10 10) (end 11 10) (layer "Edge.Cuts"))'
    assert not _augment_features_from_board(
        ReviewFeatures(), parse_sexpr(f"(kicad_pcb {outer})")
    ).has_cutouts
    assert _augment_features_from_board(
        ReviewFeatures(), parse_sexpr(f"(kicad_pcb {outer} {inner})")
    ).has_cutouts
