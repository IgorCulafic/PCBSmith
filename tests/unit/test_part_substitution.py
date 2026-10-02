"""Synthetic source/transaction controls; not purchased-part qualification."""

from __future__ import annotations

import copy
import hashlib
import json
import xml.etree.ElementTree as ET

import pytest
from tests.unit.kicad.test_component_readiness import (
    _pin_evidence,
    inventory,  # noqa: F401
)
from tests.unit.kicad.test_component_readiness import (
    geometry_inventory as base_geometry,  # noqa: F401
)
from tests.unit.test_board_revision import checks as native_checks  # noqa: F401
from tests.unit.test_native_input_closure import native  # noqa: F401

import pcbsmith.board_revision as revision
from pcbsmith.board_revision import BoardRevisionRequest
from pcbsmith.kicad.part_substitution import PartSubstitution, plan_part_substitutions
from pcbsmith.native_project import NativeProjectSpec, inspect_native_input_closure


@pytest.fixture
def checks(request):
    return request.getfixturevalue("native_checks")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(params=["tht", "smd"])
def substitution(request, monkeypatch):
    spec, root, _, old_geometry = request.getfixturevalue("base_geometry")
    old_pin = _pin_evidence(root)
    fp = root / "vendor/nested/parts.pretty/DIP.kicad_mod"
    footprint = (
        fp.read_text(encoding="utf-8")
        .replace(
            '(footprint "DIP"',
            '(footprint "Test:DIP" (uuid "fp") (at 10 10) '
            '(property "Reference" "U1" (at 0 -2)) (property "Value" "PART") '
            '(property "MPN" "PART-A")',
        )
        .replace('(model "${KIPRJMOD}/models/missing.step")', "")
        .replace('(pad "1" thru_hole', '(pad "1" thru_hole')
        .replace("(at 0 0) (size 2 2)", '(at 0 0) (net 1 "V") (size 2 2)')
        .replace("(at 2.54 0) (size 2 2)", '(at 2.54 0) (net 2 "GND") (size 2 2)')
    )
    board = root / "closure.kicad_pcb"
    board.write_text(
        '(kicad_pcb (version 20260206) (generator "synthetic") '
        '(layers (0 "F.Cu" signal) (31 "B.Cu" signal)) (net 1 "V") (net 2 "GND") '
        + footprint
        + " (segment (start 10 10) (end 11 10) (width 0.3) "
        '(layer "F.Cu") (net 1) (uuid "copper")))',
        encoding="utf-8",
    )
    sch = board.with_suffix(".kicad_sch")
    sch.write_text(
        '(kicad_sch (symbol (uuid "symbol") (lib_id "Test:Part") '
        '(property "Reference" "U1") (property "Value" "PART") '
        '(property "Footprint" "Test:DIP") (property "MPN" "PART-A")))',
        encoding="utf-8",
    )
    board.with_suffix(".kicad_pro").write_text("{}", encoding="utf-8")
    xml = root / ".pcbsmith/kicad/closure.net.xml"
    _, report = inspect_native_input_closure(spec, sch, xml)
    (root / "netlist-vs-intent.json").write_text(json.dumps(report), encoding="utf-8")
    (root / "component-model-selection.json").write_text(
        json.dumps(
            {"applicability": "not_applicable", "rationale": "Synthetic 2D transaction control"}
        ),
        encoding="utf-8",
    )
    source = root / "replacement.txt"
    source.write_text(
        "Synthetic replacement pin, geometry and electrical review source", encoding="utf-8"
    )
    pin = copy.deepcopy(old_pin)
    pin.update(part_number="PART-B", source_local_path=source.name, source_sha256=sha(source))
    pin["package"]["exact_variant"] = "PART-B"
    geometry = dict(
        old_geometry, part_number="PART-B", source_local_path=source.name, source_sha256=sha(source)
    )
    if request.param == "smd":
        from tests.unit.kicad.test_smd_package_geometry import smd_evidence

        for path in (board, fp):
            text = path.read_text(encoding="utf-8")
            text = text.replace("thru_hole circle", "smd roundrect")
            text = text.replace(
                '(drill 0.8) (layers "*.Cu" "*.Mask")',
                '(roundrect_rratio 0.25) (layers "F.Cu" "F.Mask" "F.Paste")',
            )
            path.write_text(text, encoding="utf-8")
        old_smd = smd_evidence(old_geometry)
        (root / "component-package-geometry.json").write_text(
            json.dumps({"U1": old_smd}), encoding="utf-8"
        )
        geometry = smd_evidence(geometry)
    replacement = PartSubstitution(
        reference="U1",
        expected_mpn="PART-A",
        replacement_value="PART-B",
        pin_evidence=pin,
        geometry_evidence=geometry,
        electrical_review_path=source.name,
        electrical_review_sha256=sha(source),
        reviewer_id="synthetic-test",
        rationale="Fixture compatibility",
        suitable_for_current_circuit=True,
    )

    # Exercise the real closure refresh with an explicitly synthetic native exporter.
    def export(schematic):
        current = NativeProjectSpec.model_validate_json(
            (schematic.parent / "design-spec.json").read_bytes()
        )
        result = ET.fromstring(xml.read_bytes())
        for comp in result.findall("./components/comp"):
            part = next(p for p in current.parts if p.reference == comp.attrib["ref"])
            comp.find("value").text = part.value
            comp.find("fields/field").text = part.mpn
        target = schematic.parent / ".pcbsmith/kicad/closure.net.xml"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(ET.tostring(result))
        return target

    monkeypatch.setattr("pcbsmith.kicad.board.export_kicad_netlist_xml", export)
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    monkeypatch.setattr("pcbsmith.board_job.bind_revision_job", lambda *a, **k: None)
    return board, replacement


def make_request(board, replacement):
    return BoardRevisionRequest(
        source_inputs=revision.inspect_board_revision(board, substitutions=(replacement,))[
            "source_inputs"
        ],
        rationale="Synthetic same-footprint substitution",
        substitutions=(replacement,),
    )


def test_substitution_replays_and_commits_all_inputs(substitution, checks, tmp_path):
    board, replacement = substitution
    req = make_request(board, replacement)
    originals = {p: (board.parent / p).read_bytes() for p in req.source_inputs}
    directory = tmp_path.with_name(tmp_path.name + "-edit")
    candidate = revision.create_board_revision(board=board, request=req, output=directory)
    assert all((board.parent / p).read_bytes() == value for p, value in originals.items())
    assert revision.replay_board_revision(directory)[0] == candidate
    delta = json.loads((directory / "delta.json").read_bytes())
    assert delta["changed_ids"] == ["fp"] and delta["before"]["copper"] == delta["after"]["copper"]
    assert delta["generator_invocations"] == delta["router_invocations"] == 0
    revision.apply_board_revision(board=board, directory=directory)
    assert len(checks) == 2
    assert '"PART-B"' in board.read_text(encoding="utf-8")
    assert '"PART-B"' in board.with_suffix(".kicad_sch").read_text(encoding="utf-8")
    assert (
        NativeProjectSpec.model_validate_json((board.parent / "design-spec.json").read_bytes())
        .parts[0]
        .mpn
        == "PART-B"
    )
    assert (
        json.loads((board.parent / "component-pin-evidence.json").read_bytes())["U1"]["part_number"]
        == "PART-B"
    )
    assert (
        json.loads((board.parent / "component-package-geometry.json").read_bytes())["U1"][
            "part_number"
        ]
        == "PART-B"
    )
    for p, value in originals.items():
        assert (directory / "before" / p).read_bytes() == value
    assert (
        json.loads((board.parent / revision.LEDGER).read_bytes())["edits"][0]["production_accepted"]
        is False
    )


@pytest.mark.parametrize(
    "change",
    [
        "mpn",
        "pin_function",
        "pin_order",
        "pitch",
        "body",
        "lead",
        "source",
        "review",
        "footprint",
        "net",
        "locked",
        "sheet",
    ],
)
def test_unqualified_or_changed_replacement_is_rejected(substitution, change):
    board, replacement = substitution
    data = replacement.model_dump(mode="json")
    if change == "mpn":
        data["expected_mpn"] = "OTHER"
    elif change == "pin_function":
        data["pin_evidence"]["pins"][0]["name"] = "OTHER"
    elif change == "pin_order":
        data["pin_evidence"]["pins"][0]["number"], data["pin_evidence"]["pins"][1]["number"] = (
            "2",
            "1",
        )
    elif change == "pitch":
        pin = data["geometry_evidence"]["pins"][1]
        if "x_mm" in pin:
            pin["x_mm"] = 3.0
        else:
            pin["required_land_bounds_mm"] = [8, -0.6, 9.2, 0.6]
    elif change == "body":
        data["geometry_evidence"]["body_bounds_mm"] = [-9, -9, 9, 9]
    elif change == "lead":
        pin = data["geometry_evidence"]["pins"][0]
        if "maximum_lead_diameter_mm" in pin:
            pin["maximum_lead_diameter_mm"] = 2
        else:
            pin["minimum_contact_size_mm"] = [2, 2]
    elif change == "source":
        (board.parent / "replacement.txt").write_text("changed", encoding="utf-8")
    elif change == "review":
        data["electrical_review_sha256"] = "0" * 64
    elif change == "sheet":
        sch = board.with_suffix(".kicad_sch")
        sch.write_text(
            sch.read_text(encoding="utf-8").replace("(kicad_sch ", "(kicad_sch (sheet) "),
            encoding="utf-8",
        )
    else:
        text = board.read_text(encoding="utf-8")
        text = (
            text.replace('"Test:DIP"', '"Test:OTHER"')
            if change == "footprint"
            else text.replace('(net 1 "V") (size', '(net 2 "GND") (size')
            if change == "net"
            else text.replace('(footprint "Test:DIP"', '(footprint "Test:DIP" locked')
        )
        board.write_text(text, encoding="utf-8")
    with pytest.raises((ValueError, KeyError)):
        plan_part_substitutions(board, (PartSubstitution.model_validate(data),))


@pytest.mark.parametrize(
    "relative",
    [
        "design-spec.json",
        "component-pin-evidence.json",
        "component-package-geometry.json",
        "replacement.txt",
        "closure.kicad_sch",
        "netlist-vs-intent.json",
        ".pcbsmith/kicad/closure.net.xml",
    ],
)
def test_substitution_tampering_cannot_apply(substitution, checks, tmp_path, relative):
    board, replacement = substitution
    before = board.read_bytes()
    directory = tmp_path.with_name(tmp_path.name + "-edit")
    revision.create_board_revision(
        board=board, request=make_request(board, replacement), output=directory
    )
    path = directory / "design" / relative
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(ValueError):
        revision.apply_board_revision(board=board, directory=directory)
    assert board.read_bytes() == before


def test_substitution_rolls_back_multi_file_apply(substitution, checks, tmp_path, monkeypatch):
    from pcbsmith.operations import file_transaction

    board, replacement = substitution
    req = make_request(board, replacement)
    before = {p: (board.parent / p).read_bytes() for p in req.source_inputs}
    directory = tmp_path.with_name(tmp_path.name + "-edit")
    revision.create_board_revision(board=board, request=req, output=directory)
    original_write = file_transaction.atomic_write
    failed = False

    def interrupt(path, payload):
        nonlocal failed
        if path == board.parent / "component-pin-evidence.json" and not failed:
            failed = True
            raise OSError("synthetic mid-commit failure")
        return original_write(path, payload)

    monkeypatch.setattr(file_transaction, "atomic_write", interrupt)
    with pytest.raises(file_transaction.FileTransactionError, match="rolled back"):
        revision.apply_board_revision(board=board, directory=directory)
    assert failed
    assert all((board.parent / p).read_bytes() == value for p, value in before.items())
    assert not (board.parent / revision.LEDGER).exists()


def test_substitution_resumes_same_source_bound_transaction(
    substitution, checks, tmp_path, monkeypatch
):
    board, replacement = substitution
    req = make_request(board, replacement)
    directory = tmp_path.with_name(tmp_path.name + "-edit")
    original = revision._placement_evidence

    def interrupt(*args):
        raise KeyboardInterrupt("synthetic interruption after atomic candidate edit")

    monkeypatch.setattr(revision, "_placement_evidence", interrupt)
    with pytest.raises(KeyboardInterrupt):
        revision.create_board_revision(board=board, request=req, output=directory)
    assert '"PART-A"' in board.read_text(encoding="utf-8")
    assert not (directory / "failure.json").exists()
    monkeypatch.setattr(revision, "_placement_evidence", original)
    candidate = revision.create_board_revision(
        board=board, request=req, output=directory, resume=True
    )
    assert revision.replay_board_revision(directory)[0] == candidate
    assert len(checks) == 1


def test_missing_qualification_context_blocks_before_candidate(substitution, checks, tmp_path):
    board, replacement = substitution
    req = make_request(board, replacement)
    req.source_inputs.pop("replacement.txt")
    directory = tmp_path.with_name(tmp_path.name + "-edit")
    with pytest.raises(ValueError, match="complete qualification/source context"):
        revision.create_board_revision(board=board, request=req, output=directory)
    assert not directory.exists() and not checks


def test_substitution_requires_live_worker(substitution, tmp_path, monkeypatch):
    board, replacement = substitution
    req = make_request(board, replacement)

    def reject():
        raise RuntimeError("no live worker")

    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", reject)
    with pytest.raises(RuntimeError, match="no live worker"):
        revision.create_board_revision(
            board=board, request=req, output=tmp_path.with_name(tmp_path.name + "-edit")
        )


def test_substitution_does_not_weaken_failed_native_checks(substitution, tmp_path, monkeypatch):
    board, replacement = substitution
    original = board.read_bytes()

    def failed(board, output, **kwargs):
        output.mkdir(parents=True)
        return {"passed": False}

    monkeypatch.setattr(revision, "_native_checks", failed)
    directory = tmp_path.with_name(tmp_path.name + "-edit")
    revision.create_board_revision(
        board=board, request=make_request(board, replacement), output=directory
    )
    with pytest.raises(ValueError, match="digitally checked"):
        revision.apply_board_revision(board=board, directory=directory)
    assert board.read_bytes() == original


def test_substitution_context_rejects_path_escape(substitution):
    board, replacement = substitution
    replacement = replacement.model_copy(update={"electrical_review_path": "../outside.txt"})
    from pcbsmith.operations.file_transaction import FileTransactionError

    with pytest.raises(FileTransactionError, match="relative and confined"):
        make_request(board, replacement)


@pytest.mark.parametrize("substitution", ["smd"], indirect=True)
@pytest.mark.parametrize("angle", [0, 90, 37])
def test_smd_rotated_board_preserves_geometry(substitution, angle):
    from pcbsmith.kicad.component_readiness import SmdPackageGeometryEvidence
    from pcbsmith.kicad.library import parse_sexpr, serialize_sexpr
    from pcbsmith.kicad.native_edits import child, children

    board, replacement = substitution
    assert isinstance(replacement.geometry_evidence, SmdPackageGeometryEvidence)
    # Use an elongated pad/land so an unnormalized 90/37 degree angle
    # actually fails. Square pads could conceal a parent-rotation bug.
    data = replacement.model_dump(mode="json")
    data["geometry_evidence"]["pins"][0].update(
        required_land_bounds_mm=[-1, -0.2, 1, 0.2],
        terminal_contact_bounds_mm=[-0.5, -0.2, 0.5, 0.2],
        minimum_contact_size_mm=[0.5, 0.3],
    )
    replacement = PartSubstitution.model_validate(data)
    path = board.parent / "component-package-geometry.json"
    old = json.loads(path.read_bytes())
    old["U1"]["pins"][0] = data["geometry_evidence"]["pins"][0]
    path.write_text(json.dumps(old), encoding="utf-8")
    tree = parse_sexpr(board.read_text(encoding="utf-8"))
    fp = children(tree, "footprint")[0]
    child(children(fp, "pad")[0], "size")[1:] = ["3", "1"]
    child(fp, "at").append(str(angle))
    for pad in children(fp, "pad"):
        child(pad, "at").append(str(angle))
    board.write_text(serialize_sexpr(tree), encoding="utf-8")
    original = board.read_bytes()
    delta, records = plan_part_substitutions(board, (replacement,))
    assert records[0]["geometry"] == "source_bound_smd_land_screen_passed"
    assert board.read_bytes() == original
    new = parse_sexpr(delta[board.name].decode())
    new_fp = children(new, "footprint")[0]
    assert children(new_fp, "pad") == children(fp, "pad")
    assert child(new_fp, "at") == child(fp, "at")
    assert children(new, "segment") == children(tree, "segment")
