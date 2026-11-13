"""Opt-in native plane/contact/thermal qualification; no manufactured board claim."""

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from pcbsmith.kicad.final_fill_adapter import FillReachability, refill_and_read_kicad_board
from pcbsmith.kicad.final_fill_connectivity import (
    KiCadFinalFillConnectivityObservation,
    classify_final_fill_reachability,
)
from pcbsmith.kicad.final_fill_thermal import (
    ThermalSpokeDisposition,
    audit_kicad_thermal_spokes,
    thermal_rule_context,
)
from pcbsmith.kicad.library import _children, parse_sexpr, serialize_sexpr
from pcbsmith.kicad.reference_continuity_geometry import segment_fully_covered
from pcbsmith.whole_board_qualification import QualificationDisposition
from pcbsmith.whole_board_qualification_adapter import _fill_gate


@pytest.mark.skipif(
    not os.environ.get("PCBSMITH_NATIVE_FILL_PROOF"), reason="requires native KiCad"
)
@pytest.mark.parametrize(
    "variant",
    [
        "connected",
        "broken_chain",
        "island",
        "zone_overlap",
        "zone_gap",
        "zone_layer_gap",
        "zone_hole",
        "orphan_cluster",
        "fragmented",
        "fragmented_load",
        "fragmented_bridge",
        "thermal_good",
        "thermal_starved",
        "thermal_zero",
    ],
)
def test_native_four_layer_fill_contacts(tmp_path, variant):
    root = Path(os.environ.get("PCBSMITH_NATIVE_FILL_OUTPUT", str(tmp_path))) / variant
    root.mkdir(parents=True, exist_ok=False)
    python = Path("C:/Program Files/KiCad/10.0/bin/python.exe")
    board = root / "source.kicad_pcb"

    def run(label, command):
        result = subprocess.run(
            list(map(str, command)), capture_output=True, timeout=60, check=False
        )
        (root / f"{label}.stdout.log").write_bytes(result.stdout)
        (root / f"{label}.stderr.log").write_bytes(result.stderr)
        assert result.returncode == 0, result.stderr.decode(errors="replace")

    run("fixture", [python, "tests/fixtures/four_layer_fill_native.py", board, variant])
    original = board.read_bytes()
    filled, snapshot = refill_and_read_kicad_board(board, root / "fill")
    (root / "snapshot.json").write_text(snapshot.model_dump_json(indent=2))
    assert board.read_bytes() == original
    # Compare original native serialized copper/components and outline independently of refill.
    before, after = parse_sexpr(original.decode()), parse_sexpr(filled.read_text())
    for tag in ("footprint", "segment", "via", "gr_line", "layers"):
        assert sorted(map(serialize_sexpr, _children(before, tag))) == sorted(
            map(serialize_sexpr, _children(after, tag))
        ), f"native refill changed {tag}"
    observed_path = root / "contacts.json"
    filled_hash = hashlib.sha256(filled.read_bytes()).hexdigest()
    run(
        "contacts", [python, "tools/kicad_final_fill_connectivity_bridge.py", filled, observed_path]
    )
    assert hashlib.sha256(filled.read_bytes()).hexdigest() == filled_hash
    observation = KiCadFinalFillConnectivityObservation.model_validate_json(
        observed_path.read_bytes()
    )
    fixture = json.loads(board.with_suffix(".fixture.json").read_bytes())
    pads = fixture["pads"]
    sources = tuple(fixture["source_pads"])
    classified = classify_final_fill_reachability(
        snapshot, observation, declared_source_pad_ids=sources
    )
    (root / "classified.json").write_text(classified.model_dump_json(indent=2))
    main_regions = [
        r for r in observation.records if any(pads[p] == "LOAD.1" for p in r.connected_pad_ids)
    ]
    assert {r.layer for r in main_regions} == {"F.Cu", "In1.Cu", "In2.Cu", "B.Cu"}
    for region in main_regions:
        assert sum(pads[p] == "LOAD.1" for p in region.connected_pad_ids) == 2
        assert all(
            pads[p] not in {"FOREIGN.1", "NOZONE.1", "HOLE.1"} for p in region.connected_pad_ids
        )
        assert len(region.holes_nm) >= 4
        polygon = ((region.outline_nm, region.holes_nm),)
        assert segment_fully_covered((28_000_000, 30_000_000), (52_000_000, 30_000_000), polygon)
        assert not segment_fully_covered(
            (33_000_000, 25_000_000), (37_000_000, 25_000_000), polygon
        )
        for x, y in ((45_000_000, 20_000_000), (50_000_000, 25_000_000)):
            assert not segment_fully_covered((x, y), (x, y), polygon)
    for contact in observation.pad_zone_contacts:
        if contact.logical_pad_id == "NOZONE.1":
            assert contact.mode == "none" and not contact.contacting_region_ids
        if contact.logical_pad_id == "REMOVED.1" and contact.layer in {"In1.Cu", "In2.Cu"}:
            assert not contact.flashed and not contact.contacting_region_ids
    main_ids = {r.region_id for r in main_regions}
    classified_by_id = {r.region_id: r.reachability for r in classified.regions}
    assert observation.region_contact_graph is not None
    if variant == "island":
        # KiCad 10.0.6 does not set IsIsland for a wholly isolated zone. The
        # complete graph now positively identifies the isolated copper independently.
        isolated = [r for r in observation.records if not r.direct_contact_ids]
        assert len(isolated) == 1 and not isolated[0].reachable_pad_ids
        assert not isolated[0].is_island
        assert classified_by_id[isolated[0].region_id] == FillReachability.FLOATING
    if variant in {"zone_overlap", "zone_gap", "zone_layer_gap", "zone_hole"}:
        extras = [r for r in observation.records if r.region_id not in main_ids]
        inner = [r for r in extras if r.layer == "In1.Cu"]
        assert len(inner) == 1 and not inner[0].direct_contact_ids
        expected = (
            FillReachability.SOURCE_REACHABLE
            if variant == "zone_overlap"
            else FillReachability.FLOATING
        )
        assert classified_by_id[inner[0].region_id] == expected
        assert bool(observation.region_contact_graph.region_contacts) == (variant == "zone_overlap")
        if variant == "zone_layer_gap":
            back = [r for r in extras if r.layer == "B.Cu"]
            assert len(back) == 1
            assert classified_by_id[back[0].region_id] == FillReachability.SOURCE_REACHABLE
    if variant == "orphan_cluster":
        extras = [r for r in observation.records if r.region_id not in main_ids]
        assert len(extras) == 2 and len({r.zone_id for r in extras}) == 2
        assert len(observation.region_contact_graph.region_contacts) == 1
        assert all(not r.direct_contact_ids and not r.reachable_pad_ids for r in extras)
        assert all(classified_by_id[r.region_id] == FillReachability.FLOATING for r in extras)
    if variant.startswith("fragmented"):
        extras = [r for r in observation.records if r.region_id not in main_ids]
        assert len(extras) == 2 and len({r.zone_id for r in extras}) == 1
        assert not observation.region_contact_graph.region_contacts
        assert all(r.pad_mapping_exact for r in extras)
        results = [classified_by_id[r.region_id] for r in extras]
        if variant == "fragmented_bridge":
            assert results == [FillReachability.SOURCE_REACHABLE] * 2
        else:
            assert results.count(FillReachability.SOURCE_REACHABLE) == 1
            assert (
                results.count(
                    FillReachability.FLOATING
                    if variant == "fragmented"
                    else FillReachability.UNVERIFIED
                )
                == 1
            )
        if variant != "fragmented":
            fragment_pads = [r.connected_pad_ids for r in extras]
            assert all(len(p) == 1 for p in fragment_pads)
            assert fragment_pads[0] != fragment_pads[1]  # same logical number, different copper
    for region in classified.regions:
        if region.region_id in main_ids:
            expected = (
                FillReachability.UNVERIFIED
                if variant == "broken_chain"
                else FillReachability.SOURCE_REACHABLE
            )
            assert region.reachability == expected
    thermal = audit_kicad_thermal_spokes(
        observation,
        filled.parent / "fill-drc.json",
        drc_report_board_sha256=filled_hash,
        project_file=filled.with_suffix(".kicad_pro"),
    )
    (root / "thermal.json").write_text(thermal.model_dump_json(indent=2))
    if variant == "thermal_good":
        assert thermal.disposition == ThermalSpokeDisposition.PASS
    elif variant in {"thermal_starved", "thermal_zero"}:
        assert thermal.disposition == ThermalSpokeDisposition.FAIL
        assert thermal.evaluated_object_count == 1  # includes the zero-contact negative case
    else:
        assert thermal.disposition == ThermalSpokeDisposition.NOT_APPLICABLE
    gate = _fill_gate(
        filled_hash,
        snapshot,
        observation,
        thermal,
        declared_source_pad_ids=sources,
        thermal_rules_sha256=thermal_rule_context(filled.with_suffix(".kicad_pro")),
    )
    (root / "fill-gate.json").write_text(gate.model_dump_json(indent=2))
    expected_gate = (
        QualificationDisposition.UNVERIFIED
        if variant in {"broken_chain", "fragmented_load"}
        else QualificationDisposition.FAIL
        if variant
        in {
            "island",
            "zone_gap",
            "zone_layer_gap",
            "zone_hole",
            "orphan_cluster",
            "fragmented",
            "thermal_starved",
            "thermal_zero",
        }
        else QualificationDisposition.PASS
    )
    assert gate.disposition == expected_gate


@pytest.mark.skipif(
    not os.environ.get("PCBSMITH_NATIVE_FILL_PROOF"), reason="requires native KiCad"
)
@pytest.mark.parametrize(
    ("variant", "error"),
    [("unsupported_copper", "copper graphics"), ("unsupported_jumpers", "logical jumper")],
)
def test_native_contact_observer_rejects_unqualified_conductors(tmp_path, variant, error):
    root = Path(os.environ.get("PCBSMITH_NATIVE_FILL_OUTPUT", str(tmp_path))) / variant
    root.mkdir(parents=True, exist_ok=False)
    python = Path("C:/Program Files/KiCad/10.0/bin/python.exe")
    board = root / "source.kicad_pcb"
    result = subprocess.run(
        [str(python), "tests/fixtures/four_layer_fill_native.py", str(board), variant],
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    before = board.read_bytes()
    output = root / "contacts.json"
    result = subprocess.run(
        [str(python), "tools/kicad_final_fill_connectivity_bridge.py", str(board), str(output)],
        capture_output=True,
        timeout=60,
        check=False,
    )
    (root / "rejection.stderr.log").write_bytes(result.stderr)
    assert result.returncode != 0 and error in result.stderr.decode(errors="replace")
    assert not output.exists() and board.read_bytes() == before
