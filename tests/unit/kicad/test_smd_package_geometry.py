"""Synthetic SMD geometry controls; no manufacturer or assembly acceptance."""

from __future__ import annotations

import copy
import json
from dataclasses import replace

import pytest
from tests.unit.kicad.test_component_readiness import geometry_inventory, inventory  # noqa: F401
from tests.unit.test_native_input_closure import native  # noqa: F401

from pcbsmith.kicad.component_readiness import (
    SmdPackageGeometryEvidence,
    _check_package_geometry,
    inspect_component_readiness,
    parse_package_geometry,
    require_component_readiness_snapshot,
)
from pcbsmith.kicad.library import _measure, parse_sexpr


def smd_evidence(tht):
    result = {
        k: v
        for k, v in tht.items()
        if k not in {"pins", "maximum_position_error_mm", "minimum_diametral_clearance_mm"}
    }
    result.update(
        mounting="smd",
        land_pattern_basis="Synthetic source-reviewed minimum lands and guaranteed contact regions",
        pins=[
            dict(
                number=p["number"],
                required_land_bounds_mm=[p["x_mm"] - 0.6, -0.6, p["x_mm"] + 0.6, 0.6],
                terminal_contact_bounds_mm=[p["x_mm"] - 0.3, -0.3, p["x_mm"] + 0.3, 0.3],
                minimum_contact_size_mm=[0.5, 0.5],
            )
            for p in tht["pins"]
        ],
    )
    return result


@pytest.fixture
def smd_inventory(request):
    spec, root, evidence_path, tht = request.getfixturevalue("geometry_inventory")
    fp = root / "vendor/nested/parts.pretty/DIP.kicad_mod"
    text = fp.read_text(encoding="utf-8").replace("thru_hole circle", "smd roundrect")
    text = text.replace(
        '(drill 0.8) (layers "*.Cu" "*.Mask")',
        '(roundrect_rratio 0.25) (layers "F.Cu" "F.Mask" "F.Paste")',
    )
    fp.write_text(text, encoding="utf-8")
    evidence = smd_evidence(tht)
    evidence_path.write_text(json.dumps({"U1": evidence}), encoding="utf-8")
    return spec, root, fp, evidence_path, evidence


def test_readiness_accepts_smd_and_rejects_stale_bound_source(smd_inventory):
    import hashlib

    spec, root, _, _, _ = smd_inventory
    result = inspect_component_readiness(spec, root)
    assert result["components"][0]["package_geometry"] == "supplied_smd_geometry_matches_cad"
    assert result["components"][0]["package_qualification"] == "unverified"
    output = root / "prepared"
    output.mkdir()
    path = output / "component-readiness.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    require_component_readiness_snapshot(output, root, digest)
    (root / "package-source.txt").write_text("changed source", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        require_component_readiness_snapshot(output, root, digest)


@pytest.mark.parametrize(
    "change,expected",
    [
        ("coverage", "pin coverage"),
        ("duplicate", "duplicate package"),
        ("contact", "contact is insufficient"),
        ("land", "exceeds actual pad copper"),
        ("corners", "exceeds actual pad copper"),
        ("body", "exceeds footprint courtyard"),
        ("mpn", "another MPN"),
        ("tag", "mounting"),
        ("nan", "finite"),
        ("infinity", "finite"),
        ("zero_contact", "positive"),
        ("inverted", "positive dimensions"),
        ("blank_basis", "review bases"),
        ("swapped", "exceeds actual pad copper"),
    ],
)
def test_smd_rejects_bad_source_geometry(smd_inventory, change, expected):
    spec, root, _, path, original = smd_inventory
    evidence = copy.deepcopy(original)
    pin = evidence["pins"][0]
    if change == "coverage":
        evidence["pins"].pop()
    elif change == "duplicate":
        evidence["pins"].append(copy.deepcopy(pin))
    elif change == "contact":
        pin["terminal_contact_bounds_mm"] = [3, 3, 4, 4]
    elif change == "land":
        pin["required_land_bounds_mm"] = [-1.1, -0.6, 0.6, 0.6]
    elif change == "corners":
        pin["required_land_bounds_mm"] = [-1, -1, 1, 1]
    elif change == "body":
        evidence["body_bounds_mm"] = [-10, -10, 10, 10]
    elif change == "mpn":
        evidence["part_number"] = "WRONG"
    elif change == "tag":
        evidence["mounting"] = "tht"
    elif change in {"nan", "infinity"}:
        pin["required_land_bounds_mm"][0] = float("nan" if change == "nan" else "inf")
    elif change == "zero_contact":
        pin["minimum_contact_size_mm"] = [0, 0.5]
    elif change == "inverted":
        pin["terminal_contact_bounds_mm"] = [1, 1, -1, -1]
    elif change == "blank_basis":
        evidence["land_pattern_basis"] = " "
    elif change == "swapped":
        evidence["pins"][0]["number"], evidence["pins"][1]["number"] = "2", "1"
    path.write_text(json.dumps({"U1": evidence}), encoding="utf-8")
    with pytest.raises(ValueError, match=expected):
        inspect_component_readiness(spec, root)


@pytest.mark.parametrize(
    "change",
    [
        dict(kind="tht"),
        dict(drill_mm=0.5),
        dict(shape="custom"),
        dict(shape="oval"),
        dict(chamfer_positions=("top_left",)),
        dict(layers=("B.Cu",)),
        dict(layers=("*.Cu",)),
        dict(layers=()),
        dict(roundrect_rratio=None),
        dict(roundrect_rratio=0.6),
        dict(roundrect_rratio=float("nan")),
        dict(width_mm=float("inf")),
        dict(width_mm=0),
        dict(name=""),
        dict(name="2"),
    ],
)
def test_smd_fails_closed_for_unsupported_pad_geometry(smd_inventory, change):
    _, _, fp, _, evidence = smd_inventory
    footprint = _measure(parse_sexpr(fp.read_text(encoding="utf-8")), "Test:DIP")
    pads = (replace(footprint.pads[0], **change), *footprint.pads[1:])
    with pytest.raises(ValueError):
        _check_package_geometry(replace(footprint, pads=pads), parse_package_geometry(evidence))


@pytest.mark.parametrize("angle", [0, 90, 37])
@pytest.mark.parametrize("shape", ["rect", "roundrect"])
def test_local_pad_rotation_and_shape_are_used(smd_inventory, angle, shape):
    _, _, fp, _, evidence = smd_inventory
    footprint = _measure(parse_sexpr(fp.read_text(encoding="utf-8")), "Test:DIP")
    pad = replace(footprint.pads[0], width_mm=3, height_mm=1, shape=shape, angle_deg=angle)
    footprint = replace(footprint, pads=(pad, *footprint.pads[1:]))
    evidence["pins"][0].update(
        required_land_bounds_mm=[-1, -0.2, 1, 0.2],
        terminal_contact_bounds_mm=[-0.5, -0.2, 0.5, 0.2],
        minimum_contact_size_mm=[0.5, 0.3],
    )
    if angle == 0:
        _check_package_geometry(footprint, parse_package_geometry(evidence))
    else:
        with pytest.raises(ValueError, match="exceeds actual pad copper"):
            _check_package_geometry(footprint, parse_package_geometry(evidence))


def test_smd_tag_roundtrips_without_losing_contact_evidence(smd_inventory):
    *_, evidence = smd_inventory
    parsed = parse_package_geometry(evidence)
    assert isinstance(parsed, SmdPackageGeometryEvidence)
    assert parse_package_geometry(parsed.model_dump(mode="json")) == parsed
