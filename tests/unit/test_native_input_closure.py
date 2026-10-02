"""Current native inputs are checked before any predesign artifacts are created."""

from __future__ import annotations

import json

import pytest

from pcbsmith.native_project import (
    NativeProjectSpec,
    inspect_native_input_closure,
    require_native_input_closure,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE


@pytest.fixture
def native(tmp_path):
    spec = NativeProjectSpec.model_validate(
        dict(
            project_id="closure",
            title="Fixture",
            user_request="Synthetic closure regression",
            width_mm=30,
            height_mm=30,
            profile=DEFAULT_PCB_RULE_PROFILE,
            parts=[
                dict(
                    reference="U1",
                    symbol="Test:Part",
                    value="PART",
                    footprint="Test:DIP",
                    mpn="PART-A",
                    role="fixture",
                    pins={"1": "V", "2": "GND", "3": None},
                    schematic_at=[12.7, 12.7],
                    board_at=[10, 10, 0],
                )
            ],
        )
    )
    schematic = tmp_path / "closure.kicad_sch"
    schematic.write_text("synthetic schematic, not native CAD proof", encoding="utf-8")
    xml = tmp_path / ".pcbsmith/kicad/closure.net.xml"
    xml.parent.mkdir(parents=True)
    xml.write_text(
        '<export><components><comp ref="U1"><value>PART</value>'
        '<footprint>Test:DIP</footprint><fields><field name="MPN">PART-A</field></fields>'
        '</comp></components><nets><net name="/V"><node ref="U1" pin="1"/></net>'
        '<net name="/GND"><node ref="U1" pin="2"/></net></nets></export>',
        encoding="utf-8",
    )
    _, report = inspect_native_input_closure(spec, schematic, xml)
    (tmp_path / "netlist-vs-intent.json").write_text(json.dumps(report), encoding="utf-8")
    (tmp_path / "design-spec.json").write_text(spec.model_dump_json(), encoding="utf-8")
    return spec, tmp_path, schematic, xml


def test_current_inputs_pass_without_mutation(native):
    spec, root, _, _ = native
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    result = require_native_input_closure(spec, root)
    assert result.components[0].reference == "U1"
    assert all(p.read_bytes() == data for p, data in before.items())


@pytest.mark.parametrize("target", ["schematic", "xml", "specification"])
def test_exact_changed_input_rejected(native, target):
    spec, root, schematic, xml = native
    if target == "specification":
        spec = spec.model_copy(update={"title": "changed"})
    else:
        path = schematic if target == "schematic" else xml
        path.write_text(path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="stale native input closure"):
        require_native_input_closure(spec, root)


@pytest.mark.parametrize(
    "old,new,expected",
    [
        ("<value>PART</value>", "<value>WRONG</value>", "value"),
        ("Test:DIP", "Test:OTHER", "footprint"),
        (">PART-A<", ">PART-B<", "MPN"),
        ('name="/V"', 'name="/OTHER"', "connectivity"),
        ('pin="1"', 'pin="3"', "connectivity"),
        ('pin="1"', 'pin="99"', "undeclared native terminal"),
        (
            '<node ref="U1" pin="1"/>',
            '<node ref="U1" pin="1"/><node ref="U1" pin="1"/>',
            "duplicate native terminal",
        ),
        ('<net name="/V">', '<net name="unconnected-U1-Pin_1">', "invalid native no-connect"),
    ],
)
def test_replay_rejects_semantic_mismatch_even_with_updated_hash(native, old, new, expected):
    spec, root, schematic, xml = native
    xml.write_text(xml.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    _, current = inspect_native_input_closure(spec, schematic, xml)
    assert current["status"] == "failed"
    assert any(expected in item for item in current["findings"])
    # A copied positive status plus current hashes cannot replace semantic replay.
    current["status"] = "passed"
    (root / "netlist-vs-intent.json").write_text(json.dumps(current), encoding="utf-8")
    with pytest.raises(ValueError, match="Native input closure failed"):
        require_native_input_closure(spec, root)


def test_deliberate_isolated_nc_is_valid(native):
    spec, _, schematic, xml = native
    xml.write_text(
        xml.read_text(encoding="utf-8").replace(
            "</nets>", '<net name="unconnected-U1-Pin_3"><node ref="U1" pin="3"/></net></nets>'
        ),
        encoding="utf-8",
    )
    _, report = inspect_native_input_closure(spec, schematic, xml)
    assert report["status"] == "passed"
    assert not report["production_accepted"]


@pytest.mark.parametrize(
    "pin,expected",
    [("3", None), ("1", "invalid native no-connect"), ("99", "undeclared native terminal")],
)
def test_filtered_explicit_nc_still_requires_declared_pin_intent(native, pin, expected):
    spec, _, schematic, xml = native
    xml.write_text(
        xml.read_text(encoding="utf-8").replace(
            "</nets>",
            f'<net name="unconnected-U1-Pin_{pin}"><node ref="U1" '
            f'pin="{pin}" pintype="passive+no_connect"/></net></nets>',
        ),
        encoding="utf-8",
    )
    netlist, report = inspect_native_input_closure(spec, schematic, xml)
    assert not any(n.name.startswith("unconnected-") for n in netlist.nets)
    if expected is None:
        assert report["status"] == "passed"
    else:
        assert report["status"] == "failed"
        assert any(expected in finding for finding in report["findings"])


def test_duplicate_filtered_nc_terminals_are_rejected(native):
    spec, _, schematic, xml = native
    entry = (
        '<net name="unconnected-U1-Pin_3"><node ref="U1" pin="3" '
        'pintype="passive+no_connect"/></net>'
    )
    xml.write_text(
        xml.read_text(encoding="utf-8").replace("</nets>", entry * 2 + "</nets>"), encoding="utf-8"
    )
    _, report = inspect_native_input_closure(spec, schematic, xml)
    assert "duplicate native terminal: U1.3" in report["findings"]


def test_legacy_report_cannot_silently_gain_new_authority(native):
    spec, root, _, _ = native
    path = root / "netlist-vs-intent.json"
    old = {"status": "passed", "schematic_sha256": "old"}
    path.write_text(json.dumps(old), encoding="utf-8")
    with pytest.raises(ValueError, match="refresh supported preparation"):
        require_native_input_closure(spec, root)
    assert json.loads(path.read_text(encoding="utf-8")) == old


def test_predesign_boundary_stops_before_artifacts_on_changed_xml(native, monkeypatch):
    from pcbsmith.predesign_preparation import prepare_predesign_inputs

    spec, root, _, xml = native
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    xml.write_text(xml.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    output = root / "must-not-exist"
    with pytest.raises(ValueError, match="netlist_sha256"):
        prepare_predesign_inputs(root / "design-spec.json", root, output)
    assert not output.exists()


@pytest.mark.parametrize(
    "addition,expected",
    [
        ('<net name="/V"><node ref="U1" pin="1"/></net>', "duplicate native net name"),
        ('<net name="/GHOST"><node ref="MISSING" pin="1"/></net>', "undeclared native reference"),
    ],
)
def test_parser_filtered_and_duplicate_nets_do_not_escape_closure(native, addition, expected):
    spec, _, schematic, xml = native
    xml.write_text(
        xml.read_text(encoding="utf-8").replace("</nets>", addition + "</nets>"), encoding="utf-8"
    )
    _, report = inspect_native_input_closure(spec, schematic, xml)
    assert report["status"] == "failed"
    assert any(expected in finding for finding in report["findings"])


def test_duplicate_components_are_not_hidden_by_reference_lookup(native):
    spec, _, schematic, xml = native
    text = xml.read_text(encoding="utf-8")
    component = text[text.index("<comp ref=") : text.index("</comp>") + len("</comp>")]
    xml.write_text(text.replace("</components>", component + "</components>"), encoding="utf-8")
    _, report = inspect_native_input_closure(spec, schematic, xml)
    assert report["status"] == "failed"
    assert "duplicate native component reference" in report["findings"]
