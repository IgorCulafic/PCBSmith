"""Synthetic source-reuse controls, never board qualification evidence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcbsmith import readiness_preflight as preflight
from pcbsmith.kicad.board import parse_board_netlist
from pcbsmith.kicad.board_serialization import canonical_board_netlist_snapshot_json


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    board = tmp_path / "synthetic.kicad_pcb"
    model = tmp_path / "synthetic.step"
    model.write_bytes(b"synthetic model bytes; not a STEP qualification")
    board.write_text(
        '(kicad_pcb (footprint "Test:OnePin" '
        '(property "Reference" "U1") (property "Value" "TEST1") '
        '(property "MPN" "TEST1") (pad "1" thru_hole circle (net 1 "/V")) '
        f'(model "{model.as_posix()}")))'
    )
    netlist = tmp_path / "source.xml"
    netlist.write_text(
        '<export><components><comp ref="U1"><value>TEST1</value>'
        "<footprint>Test:OnePin</footprint><tstamps>new-id</tstamps>"
        '<fields><field name="MPN">TEST1</field></fields></comp></components>'
        '<nets><net name="/V"><node ref="U1" pin="1"/></net></nets></export>'
    )
    source = tmp_path / "datasheet.txt"
    source.write_text("Synthetic pin evidence, not a real datasheet")
    locator = {"local_file": str(source), "page": 1}
    evidence = {
        "manufacturer": "Synthetic",
        "part_number": "TEST1",
        "source_sha256": preflight.sha(source),
        "source_local_path": str(source),
        "extraction_status": "machine_extracted",
        "package": {
            "package_name": "ONE",
            "exact_variant": "TEST1",
            "pin_count": 1,
            "locator": locator,
        },
        "pins": [{"number": "1", "name": "V", "electrical_role": "supply", "locator": locator}],
    }
    snapshot = json.loads(
        canonical_board_netlist_snapshot_json(parse_board_netlist(netlist.read_text()))
    )
    snapshot["components"][0]["uuid_path"] = "old-id"
    prior = tmp_path / "prior.json"
    prior.write_text(
        json.dumps(
            {
                "board_netlist_snapshot_json": json.dumps(snapshot),
                "pin_evidence_by_reference": {"U1": evidence},
                "results_by_obligation": {"old": {"disposition": "pass"}},
            }
        )
    )
    registry = tmp_path / "registry.json"
    registry.write_text(
        json.dumps(
            [
                {
                    "raw_path": model.as_posix(),
                    "local_path": str(model),
                    "classification": "proxy",
                    "license_status": "synthetic",
                    "expected_sha256": preflight.sha(model),
                }
            ]
        )
    )
    requirements = tmp_path / "requirements.json"
    requirements.write_text(
        json.dumps([{"reference": "U1", "accepted_classifications": ["proxy"]}])
    )
    monkeypatch.setattr(
        preflight, "native_project_hashes", lambda path: {path.name: preflight.sha(path)}
    )
    return dict(
        board=board,
        netlist_file=netlist,
        prior_component_input=prior,
        registry_file=registry,
        requirements_file=requirements,
    )


def test_uuid_only_difference_reuses_sources_but_never_old_approvals(inputs):
    result = preflight.prepare_readiness_preflight(**inputs)
    assert result["report"]["electrical_intent_matches_prior"]
    assert result["report"]["reusable_pin_evidence"] == ["U1"]
    assert result["report"]["model_preflight_status"] == "passed"
    assert result["report"]["proxy_references"] == ["U1"]
    assert not result["report"]["production_accepted"]
    assert result["component-review-input"]["results_by_obligation"] == {}
    assert result["component-review-input"]["board_revision"] == preflight.sha(inputs["board"])


def test_changed_pinned_datasheet_is_not_reused(inputs):
    data = json.loads(inputs["prior_component_input"].read_text())
    Path(data["pin_evidence_by_reference"]["U1"]["source_local_path"]).write_text("changed")
    result = preflight.prepare_readiness_preflight(**inputs)
    assert result["report"]["reusable_pin_evidence"] == []
    assert any("changed pinned" in x for x in result["report"]["remaining_gaps"])


def test_changed_historical_value_prevents_automatic_pin_reuse(inputs):
    path = inputs["prior_component_input"]
    data = json.loads(path.read_text())
    snapshot = json.loads(data["board_netlist_snapshot_json"])
    snapshot["components"][0]["value"] = "OTHER"
    data["board_netlist_snapshot_json"] = json.dumps(snapshot)
    path.write_text(json.dumps(data))
    result = preflight.prepare_readiness_preflight(**inputs)
    assert not result["report"]["electrical_intent_matches_prior"]
    assert result["component-review-input"]["pin_evidence_by_reference"] == {}


def test_wrong_current_connectivity_fails_before_draft(inputs):
    path = inputs["netlist_file"]
    path.write_text(path.read_text().replace("/V", "/OTHER"))
    with pytest.raises(ValueError, match="connectivity differ"):
        preflight.prepare_readiness_preflight(**inputs)


def test_model_hash_mismatch_is_retained_as_failure(inputs):
    registry = json.loads(inputs["registry_file"].read_text())
    Path(registry[0]["local_path"]).write_bytes(b"changed model")
    result = preflight.prepare_readiness_preflight(**inputs)
    assert result["report"]["model_preflight_status"] == "failed"
    assert not result["report"]["production_accepted"]


def test_incomplete_model_requirements_cannot_pass_vacuously(inputs):
    inputs["requirements_file"].write_text("[]")
    with pytest.raises(ValueError, match="cover every"):
        preflight.prepare_readiness_preflight(**inputs)


def test_native_source_is_unchanged(inputs):
    before = inputs["board"].read_bytes()
    preflight.prepare_readiness_preflight(**inputs)
    assert inputs["board"].read_bytes() == before


def test_duplicate_netlist_terminal_is_rejected(inputs):
    path = inputs["netlist_file"]
    path.write_text(
        path.read_text().replace(
            '<node ref="U1" pin="1"/>', '<node ref="U1" pin="1"/><node ref="U1" pin="1"/>'
        )
    )
    with pytest.raises(ValueError, match="duplicate netlist terminal"):
        preflight.prepare_readiness_preflight(**inputs)


def test_cli_refuses_existing_output_without_touching_board(inputs, tmp_path):
    output = tmp_path / "prior-output"
    output.mkdir()
    before = inputs["board"].read_bytes()
    args = [
        arg for key, value in inputs.items() for arg in ("--" + key.replace("_", "-"), str(value))
    ]
    with pytest.raises(SystemExit):
        preflight.main([*args, "--output", str(output)])
    assert inputs["board"].read_bytes() == before
