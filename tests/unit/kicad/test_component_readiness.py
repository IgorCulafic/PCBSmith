"""Pre-placement inventory and evidence binding controls; no physical qualification."""

from __future__ import annotations

import hashlib
import json
import os

import pytest
from tests.unit.test_native_input_closure import native  # noqa: F401

from pcbsmith.kicad.component_readiness import (
    inspect_component_readiness,
    require_component_readiness_snapshot,
)
from pcbsmith.kicad.library import load_footprint
from pcbsmith.kicad.project_dependencies import project_footprint_scope, retain_project_libraries


@pytest.fixture
def inventory(request):
    spec, root, _, _ = request.getfixturevalue("native")
    library = root / "vendor/nested/parts.pretty"
    library.mkdir(parents=True)
    fp = library / "DIP.kicad_mod"
    fp.write_text(
        '(footprint "DIP" (layer "F.Cu") (attr through_hole) '
        '(fp_rect (start -1 -1) (end 7 1) (stroke (width 0.1) (type default)) (layer "F.Fab")) '
        + "".join(
            f'(pad "{i}" thru_hole circle (at {x} 0) (size 2 2) '
            '(drill 0.8) (layers "*.Cu" "*.Mask"))'
            for i, x in [(1, 0), (2, 2.54), (3, 5.08)]
        )
        + '(model "${KIPRJMOD}/models/missing.step"))',
        encoding="utf-8",
    )
    (root / "fp-lib-table").write_text(
        '(fp_lib_table (lib (name "Test") (type "KiCad") '
        '(uri "${KIPRJMOD}/vendor/nested/parts.pretty")))',
        encoding="utf-8",
    )
    return spec, root, fp


def _save_report(spec, root):
    report = inspect_component_readiness(spec, root)
    output = root / "prepared"
    output.mkdir(exist_ok=True)
    path = output / "component-readiness.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return output, hashlib.sha256(path.read_bytes()).hexdigest()


def _pin_evidence(root):
    source = root / "datasheet.txt"
    source.write_text("Synthetic evidence fixture; not a manufacturer datasheet", encoding="utf-8")
    evidence = {
        "manufacturer": "Fixture",
        "part_number": "PART-A",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_local_path": "datasheet.txt",
        "extraction_status": "human_reviewed",
        "package": {
            "package_name": "DIP3",
            "exact_variant": "PART-A",
            "pin_count": 3,
            "locator": {"page": 1},
        },
        "pins": [
            {"number": str(n), "name": f"P{n}", "electrical_role": "signal", "locator": {"page": 1}}
            for n in [1, 2, 3]
        ],
    }
    (root / "component-pin-evidence.json").write_text(
        json.dumps({"U1": evidence}), encoding="utf-8"
    )
    return evidence


def test_nested_footprint_inventory_is_explicit_about_unknowns(inventory):
    spec, root, fp = inventory
    result = inspect_component_readiness(spec, root)
    item = result["components"][0]
    assert result["status"] == "review_required" and not result["production_accepted"]
    assert item["footprint_sha256"] == hashlib.sha256(fp.read_bytes()).hexdigest()
    assert item["mounting"] == "tht"
    assert item["cad_pads"][1]["x_mm"] == 2.54
    assert item["cad_pads"][1]["hole"]["width_mm"] == 0.8
    assert item["pin_evidence"] == "not_supplied"
    assert item["package_qualification"] == "unverified"
    assert item["footprint_default_models"][0]["resolution"] == "unresolved"


def test_matching_pin_sources_do_not_become_approval(inventory):
    spec, root, _ = inventory
    _pin_evidence(root)
    result = inspect_component_readiness(spec, root)
    assert result["components"][0]["pin_evidence"] == "source_and_number_coverage_checked"
    assert result["components"][0]["package_qualification"] == "unverified"
    output, digest = _save_report(spec, root)
    require_component_readiness_snapshot(output, root, digest)


@pytest.mark.parametrize("change", ["mpn", "pin", "source", "reference"])
def test_wrong_or_stale_pin_evidence_stops_before_layout(inventory, change):
    spec, root, _ = inventory
    evidence = _pin_evidence(root)
    ref = "U1"
    if change == "mpn":
        evidence["part_number"] = "OTHER"
        evidence["package"]["exact_variant"] = "OTHER"
    elif change == "pin":
        evidence["pins"][2]["number"] = "9"
    elif change == "source":
        (root / "datasheet.txt").write_text("changed", encoding="utf-8")
    else:
        ref = "U99"
    (root / "component-pin-evidence.json").write_text(json.dumps({ref: evidence}), encoding="utf-8")
    with pytest.raises(ValueError):
        inspect_component_readiness(spec, root)


def test_inventory_ignores_stale_timestamp_cache_and_records_real_smd(inventory):
    spec, root, fp = inventory
    with project_footprint_scope(root):
        old = load_footprint("Test:DIP")
    stat = fp.stat()
    fp.write_text(
        fp.read_text(encoding="utf-8").replace("(at 2.54 0)", "(at 3.54 0)"), encoding="utf-8"
    )
    os.utime(fp, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert old.spec.pads[1].x_mm == 2.54
    assert inspect_component_readiness(spec, root)["components"][0]["cad_pads"][1]["x_mm"] == 3.54
    fp.write_text(
        fp.read_text(encoding="utf-8").replace("thru_hole circle", "smd rect"), encoding="utf-8"
    )
    assert inspect_component_readiness(spec, root)["components"][0]["mounting"] == "smd"


def test_changed_library_rejected_when_sealing_prepared_inventory(inventory):
    spec, root, fp = inventory
    output, digest = _save_report(spec, root)
    fp.write_text(fp.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed since preparation"):
        require_component_readiness_snapshot(output, root, digest)


def test_missing_nested_library_rejected(inventory):
    spec, root, fp = inventory
    fp.rename(fp.with_suffix(".missing"))
    with pytest.raises(RuntimeError, match="missing from pinned project library"):
        inspect_component_readiness(spec, root)


def test_nested_library_retention_reopens_identically(inventory, tmp_path):
    spec, root, fp = inventory
    destination = tmp_path / "retained"
    snapshots = retain_project_libraries(root, destination)
    assert snapshots[fp] == fp.read_bytes()
    (destination / "fp-lib-table").write_bytes((root / "fp-lib-table").read_bytes())
    with project_footprint_scope(destination):
        reopened = load_footprint("Test:DIP", verify_content=True)
    assert reopened.source_file.is_relative_to(destination)
    assert reopened.source_file.read_bytes() == fp.read_bytes()


@pytest.fixture
def geometry_inventory(inventory):
    spec, root, fp = inventory
    text = fp.read_text(encoding="utf-8").replace(
        "(model ",
        "(fp_rect (start -1.5 -1.5) (end 7.5 1.5) (stroke (width 0.05) (type default)) "
        '(layer "F.CrtYd")) (model ',
    )
    fp.write_text(text, encoding="utf-8")
    source = root / "package-source.txt"
    source.write_text(
        "Synthetic package geometry source; not physical qualification", encoding="utf-8"
    )
    evidence = {
        "part_number": "PART-A",
        "source_local_path": "package-source.txt",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_page": 1,
        "coordinate_basis": "Synthetic top view, origin at pin 1, positive x toward pin 3",
        "body_bounds_mm": [-1, -1, 7, 1],
        "maximum_position_error_mm": 0.01,
        "minimum_diametral_clearance_mm": 0.2,
        "pins": [
            {"number": str(n), "x_mm": x, "y_mm": 0, "maximum_lead_diameter_mm": 0.5}
            for n, x in [(1, 0), (2, 2.54), (3, 5.08)]
        ],
    }
    path = root / "component-package-geometry.json"
    path.write_text(json.dumps({"U1": evidence}), encoding="utf-8")
    return spec, root, path, evidence


def test_source_bound_tht_geometry_matches_without_physical_claim(geometry_inventory):
    spec, root, _, _ = geometry_inventory
    result = inspect_component_readiness(spec, root)
    assert result["components"][0]["package_geometry"] == "supplied_tht_geometry_matches_cad"
    assert result["components"][0]["package_qualification"] == "unverified"


@pytest.mark.parametrize(
    "change,expected",
    [
        ("pitch", "position/pitch"),
        ("order", "position/pitch"),
        ("lead", "lead/clearance"),
        ("body", "exceeds footprint courtyard"),
        ("part", "another MPN"),
        ("source", "changed package geometry source"),
    ],
)
def test_incompatible_procurement_geometry_fails_early(geometry_inventory, change, expected):
    spec, root, path, evidence = geometry_inventory
    if change == "pitch":
        evidence["pins"][1]["x_mm"] = 2.0
    elif change == "order":
        evidence["pins"][0]["number"], evidence["pins"][2]["number"] = "3", "1"
    elif change == "lead":
        evidence["pins"][0]["maximum_lead_diameter_mm"] = 0.9
    elif change == "body":
        evidence["body_bounds_mm"] = [-2, -2, 8, 2]
    elif change == "part":
        evidence["part_number"] = "OTHER"
    else:
        (root / "package-source.txt").write_text("changed", encoding="utf-8")
    path.write_text(json.dumps({"U1": evidence}), encoding="utf-8")
    with pytest.raises(ValueError, match=expected):
        inspect_component_readiness(spec, root)


def test_geometry_nonfinite_allowance_rejected(geometry_inventory):
    spec, root, path, evidence = geometry_inventory
    evidence["maximum_position_error_mm"] = float("inf")
    path.write_text(json.dumps({"U1": evidence}), encoding="utf-8")
    with pytest.raises(ValueError):
        inspect_component_readiness(spec, root)


def test_predesign_approval_replays_changed_inventory_before_sealing(inventory, monkeypatch):
    from pcbsmith.predesign_preparation import _approve_prepared_predesign

    spec, root, fp = inventory
    output, digest = _save_report(spec, root)
    prepared = output / "prepared-inputs.json"
    prepared.write_text(
        json.dumps(
            {
                "native_project_path": str(root),
                "component_readiness_sha256": digest,
                "source_spec_sha256": "irrelevant-for-this-control",
            }
        ),
        encoding="utf-8",
    )
    engineering = output / "engineering.json"
    engineering.write_text("{}", encoding="utf-8")
    assertion = output / "assertion.json"
    assertion.write_text(
        json.dumps(
            {
                "prepared_inputs_sha256": hashlib.sha256(prepared.read_bytes()).hexdigest(),
                "engineering_sha256": hashlib.sha256(engineering.read_bytes()).hexdigest(),
                "disposition": "approve_predesign",
                "rationale": "Synthetic boundary test",
            }
        ),
        encoding="utf-8",
    )
    fp.write_text(fp.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    with pytest.raises(ValueError, match="changed since preparation"):
        _approve_prepared_predesign(output, engineering, assertion)
    assert not (output / "predesign.json").exists()


@pytest.mark.parametrize(
    "populated,reference,expected",
    [
        (True, None, "cover populated"),
        (False, "UNKNOWN", "only declared"),
        (False, None, "Selected model preflight failed"),
    ],
)
def test_model_coverage_distinguishes_unpopulated_features(
    inventory, monkeypatch, populated, reference, expected
):
    spec, root, _ = inventory
    first = spec.parts[0].model_copy(update={"populated": populated})
    second = first.model_copy(update={"reference": "U2", "populated": True})
    spec = spec.model_copy(update={"parts": (first, second)})
    (root / "design-spec.json").write_text(spec.model_dump_json(), encoding="utf-8")
    # Isolate coverage; exact native source closure is covered independently.
    monkeypatch.setattr(
        "pcbsmith.kicad.component_readiness.require_native_input_closure", lambda *args: None
    )
    requirements = [{"reference": "U2", "accepted_classifications": ["proxy"]}]
    if reference:
        requirements.append({"reference": reference, "accepted_classifications": ["proxy"]})
    selection = {
        "applicability": "applicable",
        "rationale": "Synthetic coverage control",
        "requirements": requirements,
        "registry": [
            {
                "raw_path": "${KIPRJMOD}/models/missing.step",
                "classification": "proxy",
                "license_status": "synthetic",
                "local_path": "models/missing.step",
                "expected_sha256": "1" * 64,
                "expected_transform": {
                    "offset_xyz": ["0"] * 3,
                    "scale_xyz": ["1"] * 3,
                    "rotate_xyz": ["0"] * 3,
                },
            }
        ],
    }
    (root / "component-model-selection.json").write_text(json.dumps(selection), encoding="utf-8")
    with pytest.raises(ValueError, match=expected):
        inspect_component_readiness(spec, root)
