"""Shared production route/fill transaction on synthetic fixtures, not board readiness.

Only the pre-route engineering fixture is stubbed. Freerouting, native fill,
contact/reference checks, readback and atomic candidate acceptance are real.
"""

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.unit.kicad.test_four_layer_logic import four_layer_profile

from pcbsmith.four_layer_publication import (
    FourLayerPublicationEvidence,
    require_four_layer_publication,
)
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNet,
    BoardNetlist,
    render_board_from_layout,
)
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.kicad.final_fill_adapter import refill_and_read_kicad_board
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.library import _atom, _children, parse_sexpr
from pcbsmith.kicad.reader_schematic import ReaderInstance, ReaderSpec, render_reader_schematic
from pcbsmith.production_planes import PostRoutePlanePlan
from pcbsmith.production_routing import route_saved_placement_candidate
from pcbsmith.production_workflow import RoutingEntryGateReport
from pcbsmith.routed_copper_graph_ir import fingerprint
from pcbsmith.routing_ir import RouteNetLayerConstraint


@pytest.mark.skipif(
    not os.environ.get("PCBSMITH_NATIVE_FILL_PROOF"),
    reason="requires native KiCad and pinned Freerouting",
)
@pytest.mark.parametrize("bad_source", [False, True])
def test_automatic_route_plane_fill_and_atomic_acceptance(tmp_path, monkeypatch, bad_source):
    root = Path(os.environ.get("PCBSMITH_NATIVE_FILL_OUTPUT", str(tmp_path))) / (
        "production-wrong-source" if bad_source else "production-connected"
    )
    root.mkdir(parents=True, exist_ok=False)
    # Synthetic test exemption; never an ordinary board job or acceptance record.
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    root_uuid = stable_kicad_uuid("schematic-root", "reader", "fixture", "native-plane-fixture")
    parts = tuple(
        BoardComponent(
            ref,
            "TEST",
            footprint,
            root_uuid
            + "/"
            + stable_kicad_uuid("schematic-symbol", "fixture", ref, "Connector:TestPoint"),
        )
        for ref, footprint in (
            ("J1", "TestPoint:TestPoint_Pad_D1.0mm"),
            ("J2", "TestPoint:TestPoint_Pad_D1.0mm"),
            ("G1", "TestPoint:TestPoint_THTPad_D2.0mm_Drill1.0mm"),
            ("G2", "TestPoint:TestPoint_THTPad_D2.0mm_Drill1.0mm"),
        )
    )
    netlist = BoardNetlist(
        parts,
        (
            BoardNet("/SIG", (("J1", "1"), ("J2", "1"))),
            BoardNet("/GND", (("G1", "1"), ("G2", "1"))),
        ),
    )
    layout = BoardLayout(
        tuple(zip(parts, (10.0, 30.0, 10.0, 30.0), strict=True)),
        (),
        (),
        40.0,
        30.0,
        part_y_mm=(("J1", 18.0), ("J2", 18.0), ("G1", 7.0), ("G2", 7.0)),
    )
    profile = four_layer_profile()
    source = root / "source" / "fixture.kicad_pcb"
    source.parent.mkdir()
    source.write_text(render_board_from_layout(netlist, layout, profile=profile), encoding="utf-8")
    schematic = render_reader_schematic(
        SimpleNamespace(
            components=parts, topology=SimpleNamespace(topology_id="native-plane-fixture")
        ),
        ReaderSpec(
            instances=tuple(
                ReaderInstance(ref, "Connector:TestPoint", point, in_bom=False)
                for ref, point in (
                    ("J1", (30.0, 30.0)),
                    ("J2", (60.0, 30.0)),
                    ("G1", (30.0, 50.0)),
                    ("G2", (60.0, 50.0)),
                )
            ),
            wires=(((30.0, 30.0), (60.0, 30.0)), ((30.0, 50.0), (60.0, 50.0))),
            labels=(("SIG", (30.0, 30.0)), ("GND", (30.0, 50.0))),
        ),
        project_name="fixture",
        pin_nets={"J1": {"1": "SIG"}, "J2": {"1": "SIG"}, "G1": {"1": "GND"}, "G2": {"1": "GND"}},
    )
    source.with_suffix(".kicad_sch").write_text(schematic, encoding="utf-8")
    source.with_suffix(".kicad_pro").write_text(
        json.dumps({"board_design_settings": {"rule_severities": {"starved_thermal": "error"}}})
    )
    board, _ = refill_and_read_kicad_board(source, root / "native-source")
    before = board.read_bytes()
    tree = parse_sexpr(before.decode())
    source_pad = None
    for fp in _children(tree, "footprint"):
        props = {_atom(p[1]): _atom(p[2]) for p in _children(fp, "property")}
        if props["Reference"] == ("J1" if bad_source else "G1"):
            source_pad = "pad:" + _atom(_children(_children(fp, "pad")[0], "uuid")[0][1])
    assert source_pad is not None
    plan = PostRoutePlanePlan.model_validate(
        {
            "schema_id": "pcbsmith-post-route-inner-planes-v1",
            "net_name": "/GND",
            "edge_inset_mm": 1,
            "reference_policy": {
                "schema_id": "pcbsmith-native-adjacent-reference-policy-v1",
                "layer_references": {"F.Cu": ["In1.Cu", "/GND"], "B.Cu": ["In2.Cu", "/GND"]},
                "source_pad_ids": {"/GND": [source_pad]},
                "maximum_stitch_distance_mm": 2,
                "rationale": "Synthetic through-pad fed planes and outer straight signal; "
                "no transition void allowance.",
            },
            "rationale": "Native pipeline research fixture, not a production delivery.",
        }
    )
    if not bad_source:
        policy_file = root / "placement-reference-policy.json"
        policy_file.write_text(plan.reference_policy.model_dump_json(indent=2))
        placement_proof = FourLayerPublicationEvidence(
            schema_id="pcbsmith-four-layer-publication-v1",
            plan=plan,
            reference_policy_relative_path=policy_file.name,
        )
        require_four_layer_publication(
            board,
            placement_proof,
            root,
            {
                policy_file.name: hashlib.sha256(policy_file.read_bytes()).hexdigest(),
            },
        )
    # Schema-valid synthetic entry authority is confined to this research test.
    entry_fields = dict(
        allowed=True,
        blockers=(),
        saved_board_sha256=hashlib.sha256(before).hexdigest(),
        saved_layout_fingerprint=board_layout_snapshot_fingerprint(
            canonical_board_layout_snapshot_json(layout)
        ),
        budget_profile_name="standard",
    )
    for field in (
        "generation_sha256",
        "prompt_examination_fingerprint",
        "context_fingerprint",
        "feasibility_fingerprint",
        "concept_drift_fingerprint",
        "review_transaction_fingerprint",
        "engineering_gate_fingerprint",
        "component_review_execution_fingerprint",
        "pre_route_integrity_fingerprint",
    ):
        entry_fields[field] = fingerprint(["synthetic-pre-route-fixture", field])
    provisional = RoutingEntryGateReport.model_construct(
        **entry_fields, report_fingerprint="0" * 64
    )
    entry_fields["report_fingerprint"] = fingerprint(
        provisional.model_dump(
            mode="json", exclude={"report_fingerprint", "deferred_routed_features"}
        )
    )
    entry = RoutingEntryGateReport(**entry_fields)
    gate = SimpleNamespace(
        evaluate=lambda: entry,
        engineering_gate=SimpleNamespace(
            context=SimpleNamespace(
                board_netlist_snapshot_json=canonical_board_netlist_snapshot_json(netlist)
            )
        ),
        context=SimpleNamespace(project_id="native-plane-fixture"),
        routed_engineering_source_sha256=None,
        model_dump_json=lambda **kw: '{"synthetic_pre_route_fixture":true}',
    )
    result = route_saved_placement_candidate(
        board=board,
        layout=layout,
        netlist=netlist,
        profile=profile,
        gate_inputs=gate,
        output=root / "transaction",
        post_route_planes=plan,
        net_layer_constraints=(
            RouteNetLayerConstraint(
                constraint_id="fixture-outer-signals",
                net_names=("/SIG",),
                allowed_layers=("F.Cu",),
                allow_vias=False,
            ),
        ),
    )
    assert board.read_bytes() == before
    assert result.status.value == ("rejected" if bad_source else "accepted"), result.failures
    assert (root / "transaction/CURRENT.json").exists() == (not bad_source)
    if not bad_source:
        assert result.validation is not None
        work = Path(result.retained_directory)
        ext = json.loads((work / "external-candidate-result.json").read_bytes())
        final = json.loads((work / "candidate-result.json").read_bytes())
        assert ext["segment_deltas"] == final["segment_deltas"]
        assert ext["via_deltas"] == final["via_deltas"]
        assert not ext["zone_deltas"] and len(final["zone_deltas"]) == 2
        assert ext["termination"] == final["termination"]
        assert ext["engine"]["engine_id"] == "freerouting-v2.3.0"
        assert json.loads((work / "verification/plane-reference.json").read_bytes())[
            "exact_pass_authorized"
        ]
        proof = FourLayerPublicationEvidence.model_validate(
            {
                "schema_id": "pcbsmith-four-layer-publication-v1",
                "plan": plan,
                "reference_policy_relative_path": "verification/reference-policy.json",
                "native_filled_copper": json.loads(
                    (work / "verification/plane-evidence.json").read_bytes()
                ),
                "thermal_drc_relative_path": "native-save-readback/fill-drc.json",
                "thermal_receipt_relative_path": "native-save-readback/final-fill-execution.json",
                "reference_evidence": json.loads(
                    (work / "verification/plane-reference.json").read_bytes()
                ),
            }
        )
        paths = (
            proof.reference_policy_relative_path,
            proof.thermal_drc_relative_path,
            proof.thermal_receipt_relative_path,
        )
        hashes = {p: hashlib.sha256((work / p).read_bytes()).hexdigest() for p in paths}
        final_board = work / "candidate/design/fixture.kicad_pcb"
        require_four_layer_publication(final_board, proof, work, hashes)
        for missing in paths:
            with pytest.raises(ValueError, match="unretained"):
                require_four_layer_publication(
                    final_board, proof, work, {p: h for p, h in hashes.items() if p != missing}
                )
        with pytest.raises(ValueError, match="complete native plane proof"):
            require_four_layer_publication(
                final_board, proof.model_copy(update={"native_filled_copper": None}), work, hashes
            )
        with pytest.raises(ValueError, match="frozen post-route plan"):
            changed = proof.model_copy(
                update={"plan": plan.model_copy(update={"edge_inset_mm": 2})}
            )
            require_four_layer_publication(final_board, changed, work, hashes)
        with pytest.raises(ValueError, match="different board bytes"):
            changed = proof.model_copy(
                update={
                    "native_filled_copper": proof.native_filled_copper.model_copy(
                        update={"board_text": proof.native_filled_copper.board_text + "\n"}
                    )
                }
            )
            require_four_layer_publication(final_board, changed, work, hashes)
        (work / "four-layer-publication-proof.json").write_text(proof.model_dump_json(indent=2))
    else:
        assert any("source pad" in f.message for f in result.failures)
