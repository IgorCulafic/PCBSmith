"""Synthetic source-bound provenance tests; no production approval is generated."""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.unit.test_production_generators import _routing_execution

import pcbsmith.routing_revision as owner
from pcbsmith.production_generators import (
    RegisteredRoutingPublicationEvidence,
    persist_registered_routed_candidate,
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    before = (
        b'(kicad_pcb (footprint "Test:R" (at 2 2) (layer "F.Cu") '
        b'(property "Value" "1k") (pad "1" thru_hole circle (at 0 0) '
        b'(size 2 2) (drill 1) (layers "*.Cu") (net "V"))) '
        b'(segment (start 2 2) (end 4 2) (width 0.3) (layer "F.Cu") (net "V")))'
    )
    after = before.replace(b'"1k"', b'"2k"')
    revision = tmp_path / "revision"
    for child in ("before", "design", "checks"):
        (revision / child).mkdir(parents=True)
    candidate = revision / "design/board.kicad_pcb"
    candidate.write_bytes(after)
    (revision / "before/board.kicad_pcb").write_bytes(before)
    result = tmp_path / "routing.json"
    result.write_text("{}")
    (revision / "revision.json").write_text("{}")
    native_inputs = {candidate.name: sha(candidate)}
    summary = dict(passed=True, validation_stage="routed", native_inputs=native_inputs)
    erc = {
        "$schema": "https://schemas.kicad.org/erc.v1.json",
        "source": "board.kicad_sch",
        "kicad_version": "synthetic-test",
        "sheets": [{"violations": []}],
    }
    drc = {
        "$schema": "https://schemas.kicad.org/drc.v1.json",
        "source": "board.kicad_pcb",
        "kicad_version": "synthetic-test",
        "violations": [],
        "unconnected_items": [],
        "schematic_parity": [],
    }
    for name, data in [("summary", summary), ("erc", erc), ("drc", drc)]:
        (revision / "checks" / f"{name}.json").write_text(json.dumps(data))
    request = SimpleNamespace(substitutions=(object(),), edits=(), validation_stage="routed")
    record = dict(
        candidate_inputs=native_inputs,
        check_files={
            f"checks/{name}.json": sha(revision / "checks" / f"{name}.json")
            for name in ("summary", "erc", "drc")
        },
    )
    predecessor = _routing_execution(before)
    transaction = SimpleNamespace(
        generation_transaction=SimpleNamespace(
            retained_directory=str(revision / "before"),
            manifest=SimpleNamespace(
                artifacts=[
                    SimpleNamespace(
                        relative_path=candidate.name,
                        content_sha256=hashlib.sha256(before).hexdigest(),
                    )
                ]
            ),
        )
    )
    # Only isolate the already-tested transaction/revision authorities. Exercise
    # real file hashing, copper comparison, report parsing and consumer binding.
    monkeypatch.setattr(
        owner.RoutingCandidateTransactionResult, "model_validate_json", lambda _: transaction
    )
    monkeypatch.setattr(owner.AcceptedRoutingExecution, "from_transaction", lambda _: predecessor)
    monkeypatch.setattr(
        "pcbsmith.board_revision.replay_board_revision", lambda _: (candidate, request, record)
    )
    kwargs = dict(
        routing_result=result,
        routing_result_sha256=sha(result),
        revision_directory=revision,
        revision_sha256=sha(revision / "revision.json"),
    )
    return kwargs, candidate, request, record


def test_revision_is_distinct_and_replays(fixture):
    args, board, _, _ = fixture
    proof = owner.derive_unchanged_copper_revision(**args)
    assert proof.predecessor.board_sha256 != proof.board_sha256
    assert owner.parse_routing_publication_proof(proof.model_dump_json()) == proof
    owner.require_unchanged_copper_revision(proof, board.read_bytes())
    publication = RegisteredRoutingPublicationEvidence.build(
        generator_id="synthetic", board_sha256=sha(board), routing_execution=proof
    )
    assert publication.routing_execution.predecessor == proof.predecessor
    with pytest.raises(ValueError, match="publication board"):
        owner.require_unchanged_copper_revision(proof, b"changed")


@pytest.mark.parametrize(
    "mutation",
    ["source", "predecessor", "pad", "track", "scope", "erc", "drc", "summary", "check-inputs"],
)
def test_bad_revision_cannot_become_provenance(fixture, mutation):
    args, board, request, record = fixture
    if mutation == "source":
        args["routing_result"].write_text("changed")
    elif mutation == "predecessor":
        (args["revision_directory"] / "before" / board.name).write_bytes(b"changed")
    elif mutation == "pad":
        board.write_bytes(board.read_bytes().replace(b"(size 2 2)", b"(size 3 3)"))
    elif mutation == "track":
        board.write_bytes(board.read_bytes().replace(b"(width 0.3)", b"(width 0.1)"))
    elif mutation == "scope":
        request.substitutions = ()
    elif mutation == "check-inputs":
        record["candidate_inputs"] = {board.name: "0" * 64}
    else:
        path = args["revision_directory"] / "checks" / f"{mutation}.json"
        data = json.loads(path.read_text())
        if mutation == "erc":
            data["sheets"][0]["violations"] = [{"type": "test"}]
        elif mutation == "drc":
            data["unconnected_items"] = [{"type": "test"}]
        else:
            data["passed"] = False
        path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        owner.derive_unchanged_copper_revision(**args)


def test_publication_keeps_readiness_gate_and_live_worker(fixture, tmp_path, monkeypatch):
    args, board, _, _ = fixture
    proof = owner.derive_unchanged_copper_revision(**args)
    kwargs = dict(
        generator_id="pcbsmith.kicad.aerosense_2f_board:generate_aerosense_routed_board",
        transaction_root=tmp_path / "publish",
        project_id="test",
        generation_id="test",
        generation_sha256="a" * 64,
        board_relative_path=board.name,
        board_payload=board.read_bytes(),
        routing_execution=proof,
        review_generator=lambda *a: None,
        drc_generator=lambda *a: None,
    )
    with pytest.raises((ValueError, RuntimeError)):
        persist_registered_routed_candidate(**kwargs)
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    with pytest.raises(ValueError, match="requires fresh engineering"):
        persist_registered_routed_candidate(**kwargs)
    assert not (tmp_path / "publish").exists()


def test_changed_or_missing_support_inputs_block_publication(fixture, tmp_path, monkeypatch):
    args, board, _, record = fixture
    record["candidate_inputs"]["board.kicad_pro"] = "a" * 64
    proof = owner.derive_unchanged_copper_revision(**args)
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    with pytest.raises(ValueError, match="exact checked substitution inputs"):
        persist_registered_routed_candidate(
            generator_id="pcbsmith.kicad.aerosense_2f_board:generate_aerosense_routed_board",
            transaction_root=tmp_path / "publish",
            project_id="test",
            generation_id="test",
            generation_sha256="a" * 64,
            board_relative_path=board.name,
            board_payload=board.read_bytes(),
            routing_execution=proof,
            review_generator=lambda *a: None,
            drc_generator=lambda *a: None,
        )


def test_revised_proof_cannot_inherit_old_synthetic_readiness_publication(tmp_path, monkeypatch):
    from tests.unit import test_production_readiness as integration

    from pcbsmith.kicad.library import parse_sexpr
    from pcbsmith.review.visual_package import _copper_hash
    from pcbsmith.routed_copper_graph_ir import fingerprint

    proofs = []

    def revised_proof(payload):
        board = tmp_path / "input/board.kicad_pcb"
        fields = dict(
            board_sha256=hashlib.sha256(payload).hexdigest(),
            copper_sha256=_copper_hash(parse_sexpr(payload.decode())),
            predecessor=_routing_execution(payload + b" "),
            routing_result=tmp_path / "synthetic-routing-source.json",
            routing_result_sha256="a" * 64,
            revision_directory=tmp_path / "synthetic-revision",
            revision_sha256="b" * 64,
            candidate_inputs={p.name: sha(p) for p in board.parent.iterdir()},
            check_files={"synthetic-check": "c" * 64},
        )
        provisional = owner.UnchangedCopperRevision.model_construct(
            **fields, receipt_fingerprint="0" * 64
        )
        proof = owner.UnchangedCopperRevision(
            **fields,
            receipt_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"receipt_fingerprint"})
            ),
        )
        proofs.append(proof)
        return proof

    replay_calls = []

    def replay(**kwargs):
        replay_calls.append(kwargs)
        return proofs[-1]

    monkeypatch.setattr(integration, "_routing_execution", revised_proof)
    # Source replay has independent tests above; use the existing full synthetic
    # readiness/native/render fixture to exercise this consumer's transaction.
    monkeypatch.setattr(owner, "derive_unchanged_copper_revision", replay)
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    with pytest.raises(ValueError, match="requires fresh engineering"):
        integration.publish_fixture(tmp_path, routed=True)
    assert len(replay_calls) == 1
    assert not (tmp_path / "transactions/CURRENT.json").exists()


@pytest.fixture
def authority_fixture(tmp_path):
    from dataclasses import replace

    from tests.unit.kicad.test_native_layout_input import fixture as layout_fixture
    from tests.unit.test_production_readiness import readiness_fixture

    from pcbsmith.component_review_execution import execute_project_component_reviews
    from pcbsmith.kicad.board import render_board_from_layout
    from pcbsmith.kicad.board_serialization import (
        board_layout_snapshot_fingerprint,
        canonical_board_layout_snapshot_json,
    )
    from pcbsmith.project_engineering_gate import evaluate_project_engineering_gate
    from pcbsmith.project_engineering_gate_ir import (
        InventoryStatus,
        Phase14EvaluationBundle,
        ProjectComponentProfile,
        ProjectEngineeringContext,
    )
    from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

    base, netlist = layout_fixture()
    part = replace(netlist.components[0], fields=(("MPN", "SYNTHETIC-0603"),))
    netlist = replace(netlist, components=(part,))
    layout = replace(base, placements=((part, base.placements[0][1]),))
    snapshot = canonical_board_layout_snapshot_json(layout)
    payload = render_board_from_layout(netlist, layout, profile=DEFAULT_PCB_RULE_PROFILE).encode()
    review = execute_project_component_reviews(
        project_id="fixture",
        board_revision="revised",
        netlist=netlist,
        pin_evidence_by_reference={},
        reviewer=lambda _: pytest.fail("passive fixture has no IC obligations"),
    )
    context = ProjectEngineeringContext.build(
        project_id="fixture",
        complexity_level="L0",
        board_layout_snapshot_fingerprint=board_layout_snapshot_fingerprint(snapshot),
        board_netlist=netlist,
        inventory_status=InventoryStatus.COMPLETE_REVIEWED,
        component_profiles=(
            ProjectComponentProfile(reference="R1", identity_status="generic_value"),
        ),
        phase14_features=(),
        source_context_ids=("synthetic-passive-facts",),
        reviewer_record_id="synthetic-test",
        intended_consumer="unit test only",
    )
    authority = owner.RevisionPublicationAuthority(
        board_sha256=hashlib.sha256(payload).hexdigest(),
        layout_snapshot_json=snapshot,
        profile=DEFAULT_PCB_RULE_PROFILE,
        engineering_gate=evaluate_project_engineering_gate(context, Phase14EvaluationBundle()),
        component_review=review,
    )
    _, _, readiness = readiness_fixture(tmp_path / "readiness")
    readiness = readiness.model_copy(update={"reference_intents": {"R1": "fixture-resistance"}})
    from pcbsmith.production_readiness import ReadinessEvidenceFile

    readiness.predesign.evidence_files["design-spec"] = ReadinessEvidenceFile(
        relative_path="design-spec.json", sha256="a" * 64
    )
    proof = SimpleNamespace(
        board_sha256=authority.board_sha256,
        revision_directory=tmp_path,
        candidate_inputs={"design-spec.json": "a" * 64},
    )
    return authority, proof, payload, readiness


def test_fresh_passive_authority_matches_actual_geometry(authority_fixture):
    authority, proof, payload, readiness = authority_fixture
    owner.require_revision_publication_authority(authority, proof, payload, "fixture", readiness)


@pytest.mark.parametrize("change", ["board", "project", "part", "spec", "layout", "missing"])
def test_revised_authority_rejects_old_or_mismatched_inputs(authority_fixture, change):
    authority, proof, payload, readiness = authority_fixture
    project = "fixture"
    if change == "board":
        payload += b" "
    elif change == "project":
        project = "other"
    elif change == "part":
        readiness.reference_intents["R1"] = "missing"
    elif change == "spec":
        proof.candidate_inputs["design-spec.json"] = "b" * 64
    elif change == "layout":
        authority = authority.model_copy(
            update={
                "layout_snapshot_json": authority.layout_snapshot_json.replace(
                    '"width_mm":30.0', '"width_mm":31.0'
                )
            }
        )
    else:
        authority = None
    with pytest.raises(ValueError):
        owner.require_revision_publication_authority(authority, proof, payload, project, readiness)


@pytest.mark.parametrize("fault", [None, "reserved_collision", "stale_authority"])
def test_revised_producer_commits_through_transaction_owner(
    authority_fixture, tmp_path, monkeypatch, fault
):
    """Software-only integration across both owners, not a board acceptance proof.

    Source replay/readiness/native rendering have their own suites. Here those
    external stages are isolated, but authority validation, reserved-directory
    handling and the actual atomic transaction are exercised together.
    """
    from dataclasses import replace

    from tests.unit.test_production_readiness import fixture_review

    import pcbsmith.production_generators as producer
    from pcbsmith.component_review_execution import execute_project_component_reviews
    from pcbsmith.kicad.board import BoardNet, TrackSegment, render_board_from_layout
    from pcbsmith.kicad.board_serialization import (
        board_layout_snapshot_fingerprint,
        canonical_board_layout_snapshot_json,
        parse_canonical_board_layout_snapshot,
        parse_canonical_board_netlist_snapshot,
    )
    from pcbsmith.kicad.library import parse_sexpr
    from pcbsmith.review.visual_package import _copper_hash
    from pcbsmith.routed_copper_graph_ir import fingerprint

    authority, _, _, readiness = authority_fixture
    old_component = authority.component_review
    netlist = parse_canonical_board_netlist_snapshot(old_component.board_netlist_snapshot_json)
    netlist = replace(netlist, nets=(BoardNet("SIG", (("R1", "1"), ("R1", "2"))),))
    layout = parse_canonical_board_layout_snapshot(authority.layout_snapshot_json)
    layout = replace(layout, segments=(TrackSegment(9, 10, 11, 10, "F.Cu", "SIG", 0.3),))
    payload = render_board_from_layout(netlist, layout, profile=authority.profile).encode()
    component = execute_project_component_reviews(
        project_id="fixture",
        board_revision="test-revised",
        netlist=netlist,
        pin_evidence_by_reference={},
        reviewer=lambda _: pytest.fail("no ICs"),
    )
    snapshot = canonical_board_layout_snapshot_json(layout)
    gate = authority.engineering_gate.model_copy(
        update={
            "context": authority.engineering_gate.context.model_copy(
                update={
                    "board_netlist_snapshot_fingerprint": (
                        component.board_netlist_snapshot_fingerprint
                    ),
                    "board_layout_snapshot_fingerprint": board_layout_snapshot_fingerprint(
                        snapshot
                    ),
                }
            ),
        }
    )
    authority = authority.model_copy(
        update={
            "board_sha256": hashlib.sha256(payload).hexdigest(),
            "component_review": component,
            "engineering_gate": gate,
            "layout_snapshot_json": snapshot,
        }
    )
    spec = b"synthetic specification"
    from pcbsmith.production_readiness import ReadinessEvidenceFile

    readiness.predesign.evidence_files["design-spec"] = ReadinessEvidenceFile(
        relative_path="design-spec.json", sha256=hashlib.sha256(spec).hexdigest()
    )
    fields = dict(
        board_sha256=authority.board_sha256,
        copper_sha256=_copper_hash(parse_sexpr(payload.decode())),
        predecessor=_routing_execution(payload + b" "),
        routing_result=tmp_path / "test-routing.json",
        routing_result_sha256="a" * 64,
        revision_directory=tmp_path,
        revision_sha256="b" * 64,
        candidate_inputs={
            "board.kicad_pcb": authority.board_sha256,
            "design-spec.json": hashlib.sha256(spec).hexdigest(),
        },
        check_files={"test-check": "c" * 64},
    )
    provisional = owner.UnchangedCopperRevision.model_construct(
        **fields, receipt_fingerprint="0" * 64
    )
    proof = owner.UnchangedCopperRevision(
        **fields,
        receipt_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"receipt_fingerprint"})
        ),
    )
    monkeypatch.setattr(owner, "derive_unchanged_copper_revision", lambda **_: proof)
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    monkeypatch.setattr(producer, "_guarded_readiness_review", lambda **kw: kw["review_generator"])
    monkeypatch.setattr(producer, "_guarded_readiness_drc", lambda r, a, p, b, o, g: g(b, o))
    support = {"design/design-spec.json": spec}
    if fault == "reserved_collision":
        support["evidence/revision-publication-authority.json"] = b"injected"
    elif fault == "stale_authority":
        authority = authority.model_copy(update={"board_sha256": "f" * 64})

    def publish():
        return producer.persist_registered_routed_candidate(
            generator_id="pcbsmith.kicad.aerosense_2f_board:generate_aerosense_routed_board",
            transaction_root=tmp_path / "publish",
            project_id="fixture",
            generation_id="test-revised",
            generation_sha256="a" * 64,
            board_relative_path="design/board.kicad_pcb",
            board_payload=payload,
            support_payloads=support,
            routing_execution=proof,
            revision_authority=authority,
            readiness_request=readiness,
            readiness_artifact_root=tmp_path,
            review_generator=lambda b, o: fixture_review(b, o, stage="final"),
            drc_generator=lambda b, o: o.write_text(
                json.dumps(dict(violations=[], unconnected_items=[], schematic_parity=[]))
            ),
        )

    if fault:
        with pytest.raises(ValueError, match="transaction-owned|stale"):
            publish()
        assert not (tmp_path / "publish/CURRENT.json").exists()
        return
    result = publish()
    assert result.transaction.manifest.status == "committed"
    root = Path(result.transaction.retained_directory)
    for relative, expected in {
        "evidence/revision-publication-authority.json": authority,
        "evidence/component-review/execution.json": component,
    }.items():
        item = next(a for a in result.transaction.manifest.artifacts if a.relative_path == relative)
        assert item.role == "evidence"
        assert item.content_sha256 == sha(root / relative)
        assert json.loads((root / relative).read_text()) == expected.model_dump(mode="json")
    assert result.review_manifest.package_status == "generated_pending_inspection"


@pytest.mark.parametrize("attribute", ["exclude_from_bom", "dnp"])
def test_native_non_bom_features_do_not_require_purchased_part_selection(
    authority_fixture, monkeypatch, attribute
):
    authority, proof, payload, readiness = authority_fixture
    assert b"(attr smd)" in payload
    payload = payload.replace(b"(attr smd)", f"(attr smd {attribute})".encode())
    digest = hashlib.sha256(payload).hexdigest()
    authority = authority.model_copy(update={"board_sha256": digest})
    proof.board_sha256 = digest
    readiness = readiness.model_copy(update={"reference_intents": {}})
    # Geometry replay is independently covered above; isolate actual native
    # inclusion parsing without teaching the detached fixture custom attributes.
    monkeypatch.setattr(
        "pcbsmith.kicad.routing_candidate_transaction.require_saved_layout_matches",
        lambda *args: None,
    )
    owner.require_revision_publication_authority(authority, proof, payload, "fixture", readiness)


@pytest.mark.parametrize("fault", ["missing", "extra", "position_only_exclusion"])
def test_populated_selection_cannot_be_omitted_or_invented(authority_fixture, monkeypatch, fault):
    authority, proof, payload, readiness = authority_fixture
    refs = dict(readiness.reference_intents)
    if fault == "extra":
        refs["J99"] = "fixture-resistance"
    else:
        refs.clear()
    if fault == "position_only_exclusion":
        payload = payload.replace(b"(attr smd)", b"(attr smd exclude_from_pos_files)")
        digest = hashlib.sha256(payload).hexdigest()
        authority = authority.model_copy(update={"board_sha256": digest})
        proof.board_sha256 = digest
        monkeypatch.setattr(
            "pcbsmith.kicad.routing_candidate_transaction.require_saved_layout_matches",
            lambda *args: None,
        )
    readiness = readiness.model_copy(update={"reference_intents": refs})
    with pytest.raises(ValueError, match="exact populated component set"):
        owner.require_revision_publication_authority(
            authority, proof, payload, "fixture", readiness
        )
