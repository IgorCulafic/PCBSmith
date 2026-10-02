from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from pcbsmith.kicad import library
from pcbsmith.kicad.concept_review import ConceptItem, examine_concept
from pcbsmith.kicad.floorplan import (
    FILES,
    FloorplanCorridor,
    floorplan_layout,
    geometry_identity,
    require_floorplan,
    require_native_floorplan,
    review_floorplan,
    write_floorplan,
)
from pcbsmith.production_readiness import ReadinessEvidenceFile


@pytest.fixture
def concept(tmp_path, monkeypatch):
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "Test__LED.kicad_mod").write_text(
        """
(footprint "LED" (layer "F.Cu")
 (fp_rect (start -1 -1) (end 3.5 1)
  (stroke (width 0.1) (type default)) (fill none) (layer "F.CrtYd"))
 (pad "1" thru_hole rect (at 0 0) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask"))
 (pad "2" thru_hole circle (at 2.54 0) (size 1.6 1.6) (drill 0.8) (layers "*.Cu" "*.Mask")))
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(library, "VENDORED_DIR", assets)
    library.load_footprint.cache_clear()
    result = examine_concept(
        "four-corners",
        ((0.0, 0.0), (60.0, 0.0), (60.0, 45.0), (0.0, 45.0)),
        tuple(
            ConceptItem(
                item_id=f"D{i}",
                label=f"D{i}",
                side="front",
                kind="footprint",
                footprint_id="Test:LED",
                anchor_mm=(x, y),
                rotation_deg=angle,
                containment="courtyard",
                requirement_resolution="derived",
            )
            for i, (x, y, angle) in enumerate(
                ((5, 5, 0), (55, 5, 90), (55, 40, 180), (5, 40, 270)), 1
            )
        ),
    )
    yield result
    library.load_footprint.cache_clear()


def package(concept, root):
    write_floorplan(
        concept,
        root,
        {r.item.item_id: "corner LED" for r in concept.items},
        (
            FloorplanCorridor(
                name="clockwise intent", references=("D1", "D2"), purpose="signal", width_mm=1
            ),
        ),
    )
    assertion = {
        "floorplan_sha256": hashlib.sha256((root / FILES[0]).read_bytes()).hexdigest(),
        "inspected": True,
        "presented": True,
        "reviewer_id": "synthetic-test",
        "rationale": "Synthetic assertion, not a real-board review",
        "presentation_reference": "unit fixture only",
        "corridor_rationale": "fixture corridor",
    }
    (root / FILES[3]).write_text(json.dumps(assertion), encoding="utf-8")
    return SimpleNamespace(
        approval=SimpleNamespace(concept_review=concept),
        evidence_files={
            "floorplan." + name: ReadinessEvidenceFile(
                relative_path=name, sha256=hashlib.sha256((root / name).read_bytes()).hexdigest()
            )
            for name in FILES
        },
    )


def native(concept):
    poses = floorplan_layout(concept)["placements"]
    fps = "\n".join(
        f'(footprint "Test:LED" (layer "F.Cu") (at {x + 20:g} {y + 20:g} {a:g}) '
        f'(property "Reference" "{ref}" (at 0 0) (layer "F.SilkS")))'
        for ref, (x, y, a) in poses.items()
    )
    return "(kicad_pcb " + fps + '(gr_rect (start 20 20) (end 80 65) (layer "Edge.Cuts")))'


def test_four_corner_floorplan_replays_and_matches_saved_native(concept, tmp_path):
    root = tmp_path / "floorplan"
    bundle = package(concept, root)
    layout = require_floorplan(bundle, root)
    board = tmp_path / "board.kicad_pcb"
    board.write_text(native(concept))
    require_native_floorplan(board, layout, origin_mm=20)
    svg = (root / "floorplan.svg").read_text()
    assert "60 x 45 mm" in svg and "VECTOR FLOORPLAN" in svg
    assert (root / "floorplan.png").read_bytes().startswith(b"\x89PNG")


@pytest.mark.parametrize("name", FILES)
def test_missing_or_stale_floorplan_evidence_rejected(concept, tmp_path, name):
    root = tmp_path / "plan"
    bundle = package(concept, root)
    (root / name).write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        require_floorplan(bundle, root)


@pytest.mark.parametrize("field", ["inspected", "presented", "presentation_reference"])
def test_svg_existence_does_not_substitute_for_review(concept, tmp_path, field):
    root = tmp_path / "plan"
    package(concept, root)
    assertion = json.loads((root / FILES[3]).read_text())
    assertion[field] = False if field != "presentation_reference" else ""
    with pytest.raises(ValueError):
        review_floorplan(root, concept, assertion)


def test_moving_component_invalidates_geometry_but_text_does_not(concept, tmp_path):
    root = tmp_path / "plan"
    package(concept, root)
    first = concept.items[0]
    renamed = concept.model_copy(
        update={
            "items": (
                first.model_copy(
                    update={"item": first.item.model_copy(update={"label": "new note"})}
                ),
                *concept.items[1:],
            )
        }
    )
    assert geometry_identity(renamed) == geometry_identity(concept)
    moved = concept.model_copy(
        update={
            "items": (
                first.model_copy(
                    update={"item": first.item.model_copy(update={"anchor_mm": (6, 5)})}
                ),
                *concept.items[1:],
            )
        }
    )
    assertion = json.loads((root / FILES[3]).read_text())
    with pytest.raises(ValueError, match="geometry differs"):
        review_floorplan(root, moved, assertion)


@pytest.mark.parametrize(
    "before,after",
    [
        ("(at 25 25 0)", "(at 26 25 0)"),
        ("(at 75 25 90)", "(at 75 25 0)"),
        ('(layer "F.Cu")', '(layer "B.Cu")'),
        ("(end 80 65)", "(end 81 65)"),
    ],
)
def test_native_drift_rejected(concept, tmp_path, before, after):
    board = tmp_path / "board.kicad_pcb"
    payload = native(concept)
    assert before in payload
    board.write_text(payload.replace(before, after, 1))
    with pytest.raises(ValueError, match="differs"):
        require_native_floorplan(board, floorplan_layout(concept), origin_mm=20)


def test_native_text_edit_reuses_geometry(concept, tmp_path):
    board = tmp_path / "board.kicad_pcb"
    board.write_text(native(concept).replace("(at 0 0)", "(at 1 2)"))
    require_native_floorplan(board, floorplan_layout(concept), origin_mm=20)


def test_generation_rejects_missing_vector_before_builder(tmp_path, monkeypatch):
    from tests.unit.test_production_readiness import fixture_rebuild_decision, readiness_fixture

    from pcbsmith.production_generators import generate_registered_board_candidate

    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    source, evidence, request = readiness_fixture(tmp_path)

    def forbidden(**kwargs):
        pytest.fail("builder must not run without reviewed floorplan")

    monkeypatch.setattr("pcbsmith.kicad.board.generate_board", forbidden)
    with pytest.raises(ValueError, match="reviewed vector"):
        generate_registered_board_candidate(
            generator_id="pcbsmith.kicad.board:generate_board",
            schematic_file=source.with_suffix(".kicad_sch"),
            output_directory=tmp_path / "new",
            artifact_root=evidence,
            predesign=request.predesign,
            rebuild_decision=fixture_rebuild_decision(source),
        )
    assert not (tmp_path / "new").exists()


def test_concept_replay_uses_retained_source_before_shared_lookup(concept, tmp_path, monkeypatch):
    from pcbsmith.kicad import library
    from pcbsmith.predesign_contract import _require_concept_replay

    monkeypatch.setattr(library, "VENDORED_DIR", tmp_path / "absent-shared")
    monkeypatch.setattr(library, "INSTALLED_SHARE_DIRS", ())
    _require_concept_replay(concept, 0.5)
