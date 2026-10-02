"""Laser artwork geometry tests; these do not approve any real board."""

import xml.etree.ElementTree as ET

import pytest

from pcbsmith.laser_artwork import removal_svg


def svg(content):
    return (
        '<svg viewBox="0.0000 0.0000 297 210">'
        '<g style="fill:none;stroke:#000000;stroke-width:1;'
        'stroke-linecap:round;stroke-linejoin:round">' + content + "</g></svg>"
    ).encode()


def test_explicit_removal_area_scale_and_no_background_rect():
    source = svg(
        '<path style="fill:#000000;fill-rule:evenodd;stroke:none" d="M 20,20 30,20 30,30 20,30 Z"/>'
    )
    result, report = removal_svg(source, (20, 20, 40, 30))
    assert report["removed_area_mm2"] == pytest.approx(100)
    assert report["retained_area_mm2"] == pytest.approx(100)
    root = ET.fromstring(result)
    assert root.get("width") == "20mm" and root.get("height") == "10mm"
    assert b"<rect" not in result and b"#FFFFFF" not in result


def test_hole_in_copper_is_removed_and_trace_stroke_is_retained():
    source = svg(
        '<path style="fill:#000000;fill-rule:evenodd;stroke:none"'
        ' d="M 0,0 10,0 10,10 0,10 Z M 4,4 6,4 6,6 4,6 Z"/>'
    )
    _, report = removal_svg(source, (0, 0, 10, 10))
    assert report["removed_area_mm2"] == pytest.approx(4)
    _, report = removal_svg(svg('<path d="M 2,5 L 8,5"/>'), (0, 0, 10, 10))
    assert report["retained_area_mm2"] == pytest.approx(6 + 3.141593 / 4, abs=0.001)


@pytest.mark.parametrize(
    "content",
    [
        '<rect x="0" y="0" width="10" height="10"/>',
        '<path d="M 0,0 C 1,1 2,2 3,3"/>',
        '<g transform="scale(2)"><path d="M 0,0 L 1,1"/></g>',
        '<path style="stroke:#FFFFFF" d="M 0,0 L 1,1"/>',
    ],
)
def test_unsupported_or_hidden_geometry_rejected(content):
    with pytest.raises(ValueError):
        removal_svg(svg(content), (0, 0, 10, 10))


def test_real_native_fixture_export(tmp_path, monkeypatch):
    from pathlib import Path

    from pcbsmith.laser_artwork import export_laser_artwork

    source = Path(
        "outputs/single-sided-platform-2026-09-11/test-run-2/test_plane_is_filled_before_va1/transaction/routing-candidates/with-plane/candidate/design/fixture.kicad_pcb"
    )
    if not source.is_file():
        pytest.skip("retained native integration fixture not available")
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    report = export_laser_artwork(source, tmp_path / "laser")
    assert report["width_mm"] == 30 and report["height_mm"] == 12
    assert 0 < report["removed_fraction"] < 0.3
    assert report["status"] == "inspection_artwork_not_manufacturing_approval"


def test_isolation_only_retains_floating_pocket_without_bridging():
    from shapely.geometry import Polygon

    from pcbsmith.laser_artwork import _paths

    source = svg(
        '<path style="fill:#000000;fill-rule:evenodd;stroke:none" '
        'd="M 0,0 10,0 10,10 0,10 Z M 2,2 8,2 8,8 2,8 Z"/>'
    )
    result, report = removal_svg(source, (0, 0, 10, 10), floating_clearance_mm=0.3)
    assert report["cam_floating_isolation_verified"]
    assert 28 < report["cam_floating_copper_area_mm2"] < 30
    assert 6 < report["removed_area_mm2"] < 8
    assert report["cad_copper_area_mm2"] == pytest.approx(64)
    root = ET.fromstring(result)
    assert root.get("width") == "10mm"
    assert b"<rect" not in result
    rings = _paths(next(iter(root.iter("{http://www.w3.org/2000/svg}path"))).get("d"))
    shape = Polygon()
    for points, closed in rings:
        assert closed
        shape = shape.symmetric_difference(Polygon(points))
    assert shape.area == pytest.approx(report["removed_area_mm2"], abs=0.0001)
    with pytest.raises(ValueError, match="0.3mm"):
        removal_svg(source, (0, 0, 10, 10), floating_clearance_mm=0.2)


def test_retained_background_respects_edge_clearance():
    from shapely.geometry import Polygon, box

    from pcbsmith.laser_artwork import _paths

    source = svg('<path d="M 4,5 L 6,5"/>')
    result, report = removal_svg(
        source, (0, 0, 10, 10), floating_clearance_mm=0.8, retained_edge_clearance_mm=2
    )
    root = ET.fromstring(result)
    removed = Polygon()
    for points, _closed in _paths(next(root.iter("{http://www.w3.org/2000/svg}path")).get("d")):
        removed = removed.symmetric_difference(Polygon(points))
    retained = box(0, 0, 10, 10).difference(removed)
    assert retained.distance(box(0, 0, 10, 10).boundary) >= 2 - 1e-6
    assert report["cam_retained_edge_isolation_verified"]
    assert report["cam_floating_isolation_verified"]
