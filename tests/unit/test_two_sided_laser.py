"""Synthetic CAM controls and read-only native replay; no board acceptance."""

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from shapely import get_parts, union_all
from shapely.affinity import scale
from shapely.geometry import LineString, Point, Polygon, box

from pcbsmith.laser_artwork import (
    _paths,
    export_laser_artwork,
    export_laser_variants,
    removal_svg,
    verify_actual_copper_isolation,
)


def native_svg(shapes):
    commands = []
    for shape in get_parts(union_all(shapes)):
        for ring in [shape.exterior, *shape.interiors]:
            commands.append("M " + " L ".join(f"{x:.9f},{y:.9f}" for x, y in ring.coords) + " Z")
    return (
        '<svg viewBox="0.0000 0.0000 10 10"><path '
        'style="fill:#000000;fill-rule:evenodd;stroke:none" d="' + " ".join(commands) + '"/></svg>'
    ).encode()


def geometry(svg):
    root = ET.fromstring(svg)
    result = Polygon()
    for points, closed in _paths(next(root.iter("{http://www.w3.org/2000/svg}path")).get("d")):
        assert closed
        result = result.symmetric_difference(Polygon(points))
    return result


def fixture(tmp_path, layer="B.Cu", mirror=True):
    board = tmp_path / "synthetic.kicad_pcb"
    board.write_text(
        '(kicad_pcb (layers (0 "F.Cu" signal) (2 "B.Cu" signal))'
        ' (gr_rect (start 0 0) (end 10 10) (layer "Edge.Cuts"))'
        ' (footprint "smd" (layer "F.Cu") (at 3 7)'
        ' (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu")))'
        ' (footprint "pth" (layer "F.Cu") (at 7 5)'
        ' (pad "1" thru_hole circle (at 0 0) (size 2 2)'
        ' (drill 1) (layers "*.Cu") (remove_unused_layers no)))'
        ' (segment (start 3 7) (end 4 3) (width 0.5) (layer "F.Cu"))'
        ' (segment (start 4 3) (end 7 5) (width 0.5) (layer "B.Cu"))'
        ' (via (at 4 3) (size 1.8) (drill 0.8) (layers "F.Cu" "B.Cu")))'
    )
    shapes = [Point(7, 5).buffer(1, quad_segs=64), Point(4, 3).buffer(0.9, quad_segs=64)]
    if layer == "F.Cu":
        shapes += [box(2.5, 6.5, 3.5, 7.5), LineString([(3, 7), (4, 3)]).buffer(0.25, quad_segs=64)]
    else:
        shapes += [LineString([(4, 3), (7, 5)]).buffer(0.25, quad_segs=64)]
    source = native_svg([union_all(shapes)])
    removal, _ = removal_svg(source, (0, 0, 10, 10), floating_clearance_mm=0.51, mirror_x=mirror)
    return board, source, removal


@pytest.mark.parametrize("layer,mirror", [("F.Cu", False), ("B.Cu", False), ("B.Cu", True)])
def test_each_face_contains_native_lands_and_tracks(tmp_path, layer, mirror):
    board, _, removal = fixture(tmp_path, layer, mirror)
    result = verify_actual_copper_isolation(
        board,
        removal,
        minimum_clearance_mm=0.5,
        minimum_edge_clearance_mm=0,
        two_sided=True,
        copper_layer=layer,
        mirror_x=mirror,
    )
    assert result["actual_clearance_lower_bound_mm"] >= 0.5
    assert result["copper_layer"] == layer
    assert result["mirror_x"] == mirror


def test_wrong_face_or_wrong_flip_is_rejected(tmp_path):
    board, _, removal = fixture(tmp_path)
    for layer, mirrored in [("F.Cu", False), ("B.Cu", False)]:
        with pytest.raises(ValueError, match="omits native|joins native"):
            verify_actual_copper_isolation(
                board,
                removal,
                minimum_clearance_mm=0.5,
                minimum_edge_clearance_mm=0,
                two_sided=True,
                copper_layer=layer,
                mirror_x=mirrored,
            )


@pytest.mark.parametrize(
    "old,new",
    [
        ("(drill 0.8)", "(drill 2)"),
        ("(drill 1)", "(drill oval 1 1.2)"),
        ("(remove_unused_layers no)", "(remove_unused_layers yes)"),
        ('(layers "F.Cu" "B.Cu")', '(layers "F.Cu" "In1.Cu")'),
        ("(via (at", "(via blind (at"),
        ("(drill 1)", "(drill 1 (offset 0.1 0))"),
        ("(size 2 2)", "(size 2 2) (padstack (mode custom))"),
        ('(layers (0 "F.Cu" signal)', '(layers (1 "In1.Cu" signal) (0 "F.Cu" signal)'),
    ],
)
def test_unsupported_drills_or_layer_geometry_fail_closed(tmp_path, old, new):
    board, _, removal = fixture(tmp_path)
    board.write_text(board.read_text().replace(old, new))
    with pytest.raises((ValueError, TypeError)):
        verify_actual_copper_isolation(
            board,
            removal,
            minimum_clearance_mm=0.5,
            minimum_edge_clearance_mm=0,
            two_sided=True,
            copper_layer="B.Cu",
            mirror_x=True,
        )


def test_legacy_does_not_silently_accept_two_faces(tmp_path):
    board, _, removal = fixture(tmp_path)
    with pytest.raises(ValueError):
        verify_actual_copper_isolation(
            board,
            removal,
            minimum_clearance_mm=0.5,
            minimum_edge_clearance_mm=0,
        )


def test_regional_clearance_changes_background_only_and_mirrors_once():
    copper = LineString([(2, 2), (2, 7), (7, 7)]).buffer(0.3, quad_segs=64)
    source = native_svg([copper])
    isolated, _ = removal_svg(source, (0, 0, 10, 10), floating_clearance_mm=0.8)
    cleared, report = removal_svg(
        source,
        (0, 0, 10, 10),
        floating_clearance_mm=0.8,
        full_clear_regions_mm=((0, 4, 5, 10),),
    )
    left = geometry(cleared)
    assert left.difference(geometry(isolated)).area > 1
    assert left.intersection(copper).area < 1e-5
    assert box(0, 4, 5, 10).difference(left.union(copper)).area < 1e-5
    mirrored, _ = removal_svg(
        source,
        (0, 0, 10, 10),
        floating_clearance_mm=0.8,
        full_clear_regions_mm=((0, 4, 5, 10),),
        mirror_x=True,
    )
    assert geometry(mirrored).symmetric_difference(scale(left, xfact=-1, origin=(5, 0))).area < 1e-5
    assert report["full_clear_regions_mm"] == [[0, 4, 5, 10]]


@pytest.mark.parametrize(
    "region", [(-1, 0, 3, 3), (0, 0, 11, 3), (4, 4, 2, 7), (0, 0, float("nan"), 3)]
)
def test_full_clear_region_must_be_inside_board(region):
    with pytest.raises(ValueError, match="region"):
        removal_svg(native_svg([box(4, 4, 6, 6)]), (0, 0, 10, 10), full_clear_regions_mm=(region,))


def test_batch_rejects_path_traversal_and_unbounded_count(tmp_path, monkeypatch):
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    for variants in [{"../escape": {}}, {f"v{i}": {} for i in range(9)}, {"front": {"unknown": 1}}]:
        with pytest.raises(ValueError):
            export_laser_variants(tmp_path / "unused", tmp_path / "out", variants)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("layer,mirror", [("F.Cu", False), ("B.Cu", True)])
def test_real_native_two_sided_source_read_only(tmp_path, monkeypatch, layer, mirror):
    source = Path("outputs/duofilter-two-sided-2026-09-21/delivery/KiCad/duofilter.kicad_pcb")
    if not source.is_file():
        pytest.skip("Retained native source not available")
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    report = export_laser_artwork(
        source,
        tmp_path / "cam",
        two_sided=True,
        copper_layer=layer,
        mirror_x=mirror,
        floating_clearance_mm=0.51,
        retained_edge_clearance_mm=0.51,
    )
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    assert report["copper_layer"] == layer
    assert report["native_geometry_check"]["board_sha256"] == digest
    assert json.loads((tmp_path / "cam/artwork.json").read_bytes()) == report


@pytest.mark.parametrize("fault", [None, "layer", "mirror", "clear_region", "source", "inspection"])
def test_real_native_handover_cam_replay_binds_each_variant(tmp_path, monkeypatch, fault):
    from pcbsmith.board_handover import _require_isolation
    from pcbsmith.manufacturing_lineage import file_sha256

    source = Path("outputs/duofilter-two-sided-2026-09-21/delivery/KiCad/duofilter.kicad_pcb")
    if not source.is_file():
        pytest.skip("Retained native source not available")
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    export_laser_artwork(
        source,
        tmp_path / "cam",
        two_sided=True,
        copper_layer="B.Cu",
        mirror_x=True,
        floating_clearance_mm=0.51,
        full_clear_regions_mm=((0, 0, 10, 10),),
    )
    svg = tmp_path / "cam/copper-removal.svg"
    manifest = tmp_path / "cam/artwork.json"
    report = json.loads(manifest.read_bytes())
    if fault == "layer":
        report["copper_layer"] = "F.Cu"
    elif fault == "mirror":
        report["mirror_x"] = False
    elif fault == "clear_region":
        report["full_clear_regions_mm"] = [[0, 0, 20, 20]]
    elif fault == "source":
        report["source_inputs"] = {}
    manifest.write_text(json.dumps(report))
    request = {
        "isolation_manifest": "cam/artwork.json",
        "isolation_inspection": {
            "svg_sha256": file_sha256(svg),
            "manifest_sha256": file_sha256(manifest),
            "inspection": "pending" if fault == "inspection" else "accepted",
            "reviewer": "synthetic test",
            "mechanism": "synthetic test, not a real inspection",
            "view_reference": "synthetic",
            "findings": ["Synthetic acceptance-control fixture only"],
        },
    }
    delivered = {"path": str(svg), "sha256": file_sha256(svg)}
    if fault:
        with pytest.raises(ValueError):
            _require_isolation(request, tmp_path, source, delivered)
    else:
        assert _require_isolation(request, tmp_path, source, delivered)["copper_layer"] == "B.Cu"


def test_batch_uses_one_source_and_keeps_each_variant_explicit(tmp_path, monkeypatch):
    source = Path("outputs/duofilter-two-sided-2026-09-21/delivery/KiCad/duofilter.kicad_pcb")
    if not source.is_file():
        pytest.skip("Retained native source not available")
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    result = export_laser_variants(
        source,
        tmp_path / "batch",
        {
            "front": {"two_sided": True, "copper_layer": "F.Cu", "floating_clearance_mm": 0.51},
            "back": {
                "two_sided": True,
                "copper_layer": "B.Cu",
                "mirror_x": True,
                "floating_clearance_mm": 0.81,
                "full_clear_regions_mm": [[0, 0, 10, 10]],
            },
        },
    )
    assert set(result["variants"]) == {"front", "back"}
    assert result["source_inputs"] == result["variants"]["front"]["source_inputs"]
    assert result["source_inputs"] == result["variants"]["back"]["source_inputs"]
    assert result["variants"]["front"]["mirror_x"] is False
    assert result["variants"]["back"]["mirror_x"] is True
