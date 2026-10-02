"""Synthetic adapter controls; these are not human-approved DR7 board proofs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from tests.unit.test_predesign_contract import _build_contract
from tests.unit.test_production_generators import _routing_execution
from tests.unit.test_production_workflow import _empty_component_review

from pcbsmith.design_readiness import (
    ComponentCandidate,
    ComponentUseIntent,
    DesignReadinessStage,
    PowerRailLoad,
    PowerSourceContract,
    SourceCurrentAuthority,
    VisualSubjectRequirement,
    evaluate_design_readiness,
    require_design_readiness,
    review_component_alternatives,
    review_power_path,
    review_support_circuits,
)
from pcbsmith.kicad.model_preflight import ModelPreflightReport
from pcbsmith.kicad.routing_evidence import inspect_saved_board_routing
from pcbsmith.manufacturing_lineage import file_sha256, native_input_hashes
from pcbsmith.production_generators import (
    generate_registered_board_candidate,
    persist_registered_placement_candidate,
    persist_registered_routed_candidate,
)
from pcbsmith.production_readiness import (
    READINESS_PATH,
    PredesignReadinessBundle,
    PublicationReadinessRequest,
    ReadinessEvidenceFile,
    readiness_blockers,
    require_predesign_bundle,
)
from pcbsmith.review.visual_package import RenderProfile, ReviewArtifact, VisualReviewManifest
from pcbsmith.routed_copper_graph_ir import fingerprint

BOARD = """(kicad_pcb (version 20260206) (generator "pcbsmith-test")
 (general (thickness 1.6)) (paper "A4")
 (layers (0 "F.Cu" signal) (31 "B.Cu" signal))
 (net 1 "SIG")
 (footprint "Resistor_SMD:R_0603_1608Metric" (layer "F.Cu") (at 5 5)
  (uuid "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
  (property "Reference" "U1") (property "Value" "1k") (attr smd)
  (pad "1" smd rect (at -1 0) (size 1 1) (layers "F.Cu") (net 1 "SIG"))
  (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu") (net 1 "SIG")))
 (segment (start 4 5) (end 6 5) (width 0.4) (layer "F.Cu") (net 1))
)\n"""


def readiness_fixture(tmp_path: Path):
    evidence = tmp_path / "engineering"
    evidence.mkdir(parents=True)
    contract = _build_contract(evidence, with_amendment=False).contract
    note = evidence / "synthetic-engineering.txt"
    note.write_text(
        "Synthetic test observations only. No physical qualification or human approval."
    )
    intent = ComponentUseIntent(
        intent_id="fixture-resistance",
        role_id="fixture-passive",
        required_capabilities=("resistance",),
        evidence_ids=("fixture:source",),
    )
    candidates = tuple(
        ComponentCandidate(
            candidate_id=name,
            manufacturer_part_number=name,
            capabilities=("resistance",),
            mounting="smd",
            body_width_mm=width,
            body_height_mm=1,
            pin_count=2,
            maximum_unit_current_a=0.02,
            hand_assembly_suitable=True,
            model_classification="none",
            evidence_ids=("fixture:source",),
        )
        for name, width in [("SYNTHETIC-0603", 1.6), ("SYNTHETIC-0805", 2.0)]
    )
    alternatives = review_component_alternatives(
        intent=intent, candidates=candidates, selected_candidate_id="SYNTHETIC-0603"
    )
    power = review_power_path(
        source=PowerSourceContract(
            source_id="fixture-supply",
            rail_id="+5V",
            voltage_v=5,
            available_continuous_current_a=0.1,
            available_peak_current_a=0.1,
            current_authority=SourceCurrentAuthority.DEDICATED_SUPPLY,
            current_detection_verified=True,
            direct_input_capacitance_uf=0,
            direct_input_capacitance_limit_uf=10,
            evidence_ids=("fixture:source",),
        ),
        loads=(
            PowerRailLoad(
                load_id="U1",
                rail_id="+5V",
                continuous_current_a=0.005,
                peak_current_a=0.005,
                evidence_ids=("fixture:source",),
            ),
        ),
        conversions=(),
    )
    predesign = evaluate_design_readiness(
        stage=DesignReadinessStage.PREDESIGN,
        component_reviews=(alternatives,),
        support_review=review_support_circuits(requirements=(), observations=()),
        power_review=power,
    )
    bundle = PredesignReadinessBundle(
        approval=contract,
        readiness=predesign,
        evidence_files={
            "fixture:source": ReadinessEvidenceFile(
                relative_path=note.name, sha256=file_sha256(note)
            )
        },
    )
    design = tmp_path / "input"
    design.mkdir()
    board = design / "board.kicad_pcb"
    board.write_text(BOARD)
    board.with_suffix(".kicad_pro").write_text("{}")
    board.with_suffix(".kicad_sch").write_text("(kicad_sch)")
    preflight = ModelPreflightReport(
        schema="pcbsmith-kicad-model-preflight-v1",
        board_file=str(board),
        board_sha256=file_sha256(board),
        status="not_applicable",
        applicability="not_applicable",
        applicability_rationale="Synthetic 2D adapter control",
        models=(),
    )
    from tests.unit.mandatory_review_fixtures import bind_mandatory_fixture

    from pcbsmith.kicad.model_preflight import preflight_board_models

    preflight = preflight_board_models(
        board,
        applicability="not_applicable",
        applicability_rationale="Synthetic 2D adapter control",
    )
    bundle = bind_mandatory_fixture(bundle, evidence, preflight)
    board.with_suffix(".kicad_pro").write_text(
        json.dumps(
            {
                "board": {
                    "design_settings": {
                        "rules": {
                            "min_clearance": 0.1,
                            "min_track_width": 0.1,
                            "min_copper_edge_clearance": 0.1,
                        }
                    }
                }
            }
        )
    )
    request = PublicationReadinessRequest(
        predesign=bundle,
        native_inputs=native_input_hashes(board),
        reference_intents={"U1": intent.intent_id},
        model_preflight=preflight,
        visual_requirements=(
            VisualSubjectRequirement(
                subject_id="U1-visible",
                component_reference="U1",
                artifact_id="2d:front:png",
                minimum_crop_width_px=32,
                minimum_crop_height_px=32,
                minimum_occupancy_fraction=0.2,
            ),
        ),
        visual_crops={"U1-visible": (0, 0, 64, 64)},
    )
    return board, evidence, request


def fixture_review(board: Path, output: Path, *, stage="placement", blank=False):
    output.mkdir(parents=True)
    image = Image.new("RGB", (64, 64), "white")
    if not blank:
        ImageDraw.Draw(image).rectangle((12, 12, 52, 52), fill="black")
    image.save(output / "front.png")
    return VisualReviewManifest(
        schema="pcbsmith-visual-review-manifest-v1",
        render_profile=RenderProfile(),
        stage=stage,
        board_file=str(board),
        board_sha256=file_sha256(board),
        copper_sha256="b" * 64,
        routing_evidence=inspect_saved_board_routing(board),
        kicad_version="10.0-test",
        renderer_version="synthetic-test",
        model_preflight_status="not_applicable",
        workflow_conformance_status="conformant",
        package_status="generated_pending_inspection",
        artifacts=(
            ReviewArtifact(
                artifact_id="2d:front:png",
                category="2d",
                relative_path="front.png",
                media_type="image/png",
                required=True,
                state="generated",
                sha256=file_sha256(output / "front.png"),
            ),
        ),
    )


def publish_fixture(tmp_path, *, routed=False, blank=False):
    board, evidence, request = readiness_fixture(tmp_path)
    common = dict(
        transaction_root=tmp_path / "transactions",
        project_id="fixture",
        generation_id="candidate-1",
        generation_sha256="a" * 64,
        board_relative_path="design/board.kicad_pcb",
        board_payload=board.read_bytes(),
        support_payloads={
            "design/" + path.name: path.read_bytes()
            for path in board.parent.iterdir()
            if path != board
        },
        readiness_request=request,
        readiness_artifact_root=evidence,
    )
    if routed:

        def native_report(board, path, kind):
            # Synthetic process boundary only; provenance and publication are real owners.
            source = board.with_suffix(".kicad_sch") if kind == "erc" else board
            data = {
                "$schema": f"https://schemas.kicad.org/{kind}.v1.json",
                "source": source.name,
                "kicad_version": "10.0-test",
                "ignored_checks": [],
            }
            data.update(
                {"sheets": [{"violations": []}]}
                if kind == "erc"
                else {"violations": [], "unconnected_items": [], "schematic_parity": []}
            )
            path.write_text(json.dumps(data))
            path.with_suffix(".process.json").write_text(
                json.dumps(
                    {
                        "command": [
                            "synthetic-kicad",
                            "sch" if kind == "erc" else "pcb",
                            kind,
                            "--severity-all",
                            "--schematic-parity",
                        ],
                        "returncode": 0,
                        "report_sha256": file_sha256(path),
                        "input_sha256s": {
                            str(p): file_sha256(p)
                            for p in (
                                board,
                                board.with_suffix(".kicad_sch"),
                                board.with_suffix(".kicad_pro"),
                            )
                        },
                    }
                )
            )

        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(
                "pcbsmith.kicad.kicad_validate.run_native_erc_check",
                lambda source, output: native_report(
                    source.with_suffix(".kicad_pcb"), output, "erc"
                ),
            )
            result = persist_registered_routed_candidate(
                generator_id="pcbsmith.kicad.retro_pad_r003_board:generate_retro_pad_r003_routed_board",
                review_generator=lambda b, o: fixture_review(b, o, stage="final", blank=blank),
                drc_generator=lambda b, o: native_report(b, o, "drc"),
                routing_execution=_routing_execution(board.read_bytes()),
                **common,
            )

    else:
        result = persist_registered_placement_candidate(
            generator_id="pcbsmith.kicad.board:generate_board",
            review_generator=lambda b, o: fixture_review(b, o, blank=blank),
            component_review_generator=lambda _b: _empty_component_review("fixture"),
            **common,
        )
    return result, board, tmp_path / "transactions/generations/candidate-1"


@pytest.mark.parametrize("routed", [False, True])
def test_publication_retains_replayable_native_and_visual_readiness(tmp_path, routed):
    result, board, generation = publish_fixture(tmp_path, routed=routed)
    manifest = result.transaction.manifest
    assert (
        readiness_blockers(
            generation_root=generation,
            project_id="fixture",
            board_sha256=file_sha256(board),
            board_relative_path="design/board.kicad_pcb",
            retained_artifacts={a.relative_path: a.content_sha256 for a in manifest.artifacts},
        )
        == ()
    )
    assert result.review_manifest.package_status == "generated_pending_inspection"
    assert (generation / READINESS_PATH).is_file()


@pytest.mark.parametrize("changed", ["board", "project", "schematic", "crop", "source", "receipt"])
def test_retained_readiness_rejects_each_changed_input(tmp_path, changed):
    result, board, generation = publish_fixture(tmp_path)
    paths = {
        "board": "design/board.kicad_pcb",
        "project": "design/board.kicad_pro",
        "schematic": "design/board.kicad_sch",
        "crop": "review/front.png",
        "source": "review/readiness-inputs/synthetic-engineering.txt",
        "receipt": READINESS_PATH,
    }
    target = generation / paths[changed]
    target.write_bytes(target.read_bytes() + b"\n")
    assert readiness_blockers(
        generation_root=generation,
        project_id="fixture",
        board_sha256=file_sha256(board),
        board_relative_path="design/board.kicad_pcb",
        retained_artifacts={
            a.relative_path: a.content_sha256 for a in result.transaction.manifest.artifacts
        },
    )


def test_blank_subject_blocks_publication_and_retains_failed_attempt(tmp_path):
    with pytest.raises(ValueError, match="not_measurably_visible"):
        publish_fixture(tmp_path, blank=True)
    assert not (tmp_path / "transactions/CURRENT.json").exists()
    failures = list((tmp_path / "transactions/.failed-reviews").iterdir())
    assert len(failures) == 1
    assert (failures[0] / "review-output/front.png").is_file()
    assert (failures[0] / "failure.json").is_file()


def test_self_reported_ready_cannot_override_replayed_power_failure(tmp_path):
    _, _, request = readiness_fixture(tmp_path)
    report = request.predesign.readiness
    bad_source = report.power_review.source.model_copy(
        update={"available_continuous_current_a": 0.0001}
    )
    claimed = report.power_review.model_copy(update={"source": bad_source})
    claimed = claimed.model_copy(
        update={
            "review_fingerprint": fingerprint(
                claimed.model_dump(mode="json", exclude={"review_fingerprint"})
            )
        }
    )
    false_report = report.model_copy(update={"power_review": claimed})
    false_report = false_report.model_copy(
        update={
            "report_fingerprint": fingerprint(
                false_report.model_dump(mode="json", exclude={"report_fingerprint"})
            )
        }
    )
    with pytest.raises(ValueError, match="do not replay"):
        require_design_readiness(false_report)


def test_predesign_requires_retained_engineering_sources(tmp_path):
    _, evidence, request = readiness_fixture(tmp_path)
    (evidence / "synthetic-engineering.txt").unlink()
    with pytest.raises(ValueError, match="missing"):
        require_predesign_bundle(request.predesign, evidence)


def fixture_rebuild_decision(board):
    from pcbsmith.board_rebuild import RebuildDecision
    from pcbsmith.manufacturing_lineage import native_input_hashes

    return RebuildDecision(
        source_inputs=native_input_hashes(board),
        reason="invalid_predecessor",
        rationale="Synthetic fixture rebuild for isolated generation boundary tests",
        authorization_reference="unit-test-only",
        invalidated_requirements=("fixture placement",),
        local_alternatives=("native editing tested in the dedicated revision suite",),
    )


def test_supported_builder_blocks_before_invocation_or_existing_target_mutation(
    tmp_path, monkeypatch
):
    import pcbsmith.kicad.board as module

    board, evidence, request = readiness_fixture(tmp_path)
    monkeypatch.setattr(
        module, "generate_board", lambda **_: pytest.fail("must not invoke builder")
    )
    target = tmp_path / "existing"
    target.mkdir()
    (target / "retained").write_bytes(b"keep")
    with pytest.raises(ValueError, match="target already exists"):
        generate_registered_board_candidate(
            generator_id="pcbsmith.kicad.board:generate_board",
            schematic_file=board.with_suffix(".kicad_sch"),
            output_directory=target,
            predesign=request.predesign,
            artifact_root=evidence,
            rebuild_decision=fixture_rebuild_decision(board),
        )
    assert (target / "retained").read_bytes() == b"keep"
    bad = request.predesign.model_copy(update={"evidence_files": {}})
    with pytest.raises(ValueError, match="lack retained files"):
        generate_registered_board_candidate(
            generator_id="pcbsmith.kicad.board:generate_board",
            schematic_file=board.with_suffix(".kicad_sch"),
            output_directory=tmp_path / "new",
            predesign=bad,
            artifact_root=evidence,
            rebuild_decision=fixture_rebuild_decision(board),
        )
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("fail", [False, True])
def test_supported_builder_isolates_inputs_and_retains_failure(tmp_path, monkeypatch, fail):
    import pcbsmith.kicad.board as module

    board, evidence, request = readiness_fixture(tmp_path)
    original = board.with_suffix(".kicad_sch").read_bytes()

    def builder(*, schematic_file, board_file, **kwargs):
        assert schematic_file.parent == board_file.parent
        assert schematic_file != board.with_suffix(".kicad_sch")
        board_file.write_bytes(board.read_bytes())
        if fail:
            raise RuntimeError("synthetic builder failure")

    monkeypatch.setattr(module, "generate_board", builder)
    target = tmp_path / "new-candidate"
    args = dict(
        generator_id="pcbsmith.kicad.board:generate_board",
        schematic_file=board.with_suffix(".kicad_sch"),
        output_directory=target,
        predesign=request.predesign,
        artifact_root=evidence,
        rebuild_decision=fixture_rebuild_decision(board),
    )
    if fail:
        with pytest.raises(RuntimeError, match="synthetic builder"):
            generate_registered_board_candidate(**args)
        assert (target / "builder-failure.json").exists()
    else:
        assert generate_registered_board_candidate(**args).is_file()
        receipt = json.loads((target / "builder-receipt.json").read_bytes())
        assert receipt["workflow_mode"] == "rebuild"
        assert receipt["production_accepted"] is False
        assert (target / "predecessor.kicad_pcb").read_bytes() == board.read_bytes()
        assert (target / "predecessor-inputs" / board.name).read_bytes() == board.read_bytes()
        assert (
            target / "predecessor-inputs" / board.with_suffix(".kicad_sch").name
        ).read_bytes() == original
    assert board.with_suffix(".kicad_sch").read_bytes() == original


def accepted_synthetic_release(tmp_path):
    # Test-only asserted verification. Never qualifies a physical board or a DR7 proof.
    from tests.unit.test_routed_board_release_gate import _applicability_execution, _verification

    from pcbsmith.production_workflow import (
        GenerationTransactionManifest,
        evaluate_routed_board_release_gate,
    )

    result, source, generation = publish_fixture(tmp_path, routed=True)
    board = generation / "design/board.kicad_pcb"
    (board.parent / "drc.json").write_bytes((generation / "verification/drc.json").read_bytes())
    review = result.review_manifest.model_copy(
        update={
            "package_status": "accepted",
            "artifacts": tuple(
                a.model_copy(
                    update={
                        "inspection": "accepted",
                        "reviewer": "fixture",
                        "inspection_mechanism": "synthetic software test",
                        "findings": ("Synthetic fixture: populated rectangle occupies crop.",),
                    }
                )
                for a in result.review_manifest.artifacts
            ),
        }
    )
    review_file = generation / "review/manifest.json"
    review_file.write_bytes(
        (json.dumps(review.model_dump(mode="json", by_alias=True), indent=2) + "\n").encode()
    )
    artifacts = tuple(
        a.model_copy(update={"content_sha256": file_sha256(review_file)})
        if a.relative_path == "review/manifest.json"
        else a
        for a in result.transaction.manifest.artifacts
    )
    old = result.transaction.manifest
    transaction = GenerationTransactionManifest.build(
        project_id=old.project_id,
        generation_id=old.generation_id,
        generation_sha256=old.generation_sha256,
        stage=old.stage,
        status="committed",
        artifacts=artifacts,
    )
    (generation / "transaction.json").write_text(transaction.model_dump_json(indent=2))
    kwargs = dict(
        board_file=board,
        drc_report_file=generation / "verification/drc.json",
        final_review=review,
        committed_transaction=transaction,
        verification_evidence=_verification(board),
        applicability_execution=_applicability_execution(board),
    )
    missing = evaluate_routed_board_release_gate(**kwargs)
    assert not missing.allowed and any("readiness" in x for x in missing.blockers)
    report = evaluate_routed_board_release_gate(**kwargs, generation_root=generation)
    assert report.allowed, report.blockers
    report_file = tmp_path / "synthetic-release.json"
    report_file.write_text(report.model_dump_json(indent=2))
    return source, generation, report_file


@pytest.mark.parametrize("fault", [None, "changed_bytes", "different_model", "missing"])
def test_routed_release_binds_retained_crlf_manifest(tmp_path, fault):
    from pcbsmith.production_workflow import (
        GenerationTransactionManifest,
        RoutedBoardReleaseGateReport,
        evaluate_routed_board_release_gate,
    )

    # Synthetic software fixture only; no production review decisions are manufactured.
    _, generation, report_file = accepted_synthetic_release(tmp_path)
    previous = RoutedBoardReleaseGateReport.model_validate_json(report_file.read_bytes())
    manifest_file = generation / "review/manifest.json"
    review = VisualReviewManifest.model_validate_json(manifest_file.read_bytes())
    manifest_file.write_bytes(manifest_file.read_bytes().replace(b"\n", b"\r\n"))
    digest = file_sha256(manifest_file)
    original = GenerationTransactionManifest.model_validate_json(
        (generation / "transaction.json").read_bytes()
    )
    transaction = GenerationTransactionManifest.build(
        project_id=original.project_id,
        generation_id=original.generation_id,
        generation_sha256=original.generation_sha256,
        stage=original.stage,
        status=original.status,
        artifacts=tuple(
            a.model_copy(update={"content_sha256": digest})
            if a.relative_path == "review/manifest.json"
            else a
            for a in original.artifacts
        ),
    )
    if fault == "changed_bytes":
        manifest_file.write_bytes(manifest_file.read_bytes() + b"\r\n")
    elif fault == "different_model":
        review = review.model_copy(update={"renderer_version": "different-renderer"})
    elif fault == "missing":
        manifest_file.unlink()
    result = evaluate_routed_board_release_gate(
        board_file=generation / "design/board.kicad_pcb",
        drc_report_file=generation / "verification/drc.json",
        final_review=review,
        committed_transaction=transaction,
        verification_evidence=previous.verification_evidence,
        applicability_execution=previous.applicability_execution,
        generation_root=generation,
    )
    assert result.allowed is (fault is None), result.blockers
    if fault is None:
        assert result.final_review_sha256 == digest
    else:
        assert any("review manifest" in blocker for blocker in result.blockers)


@pytest.mark.parametrize("changed", [None, "board", "evidence", "report"])
def test_manufacturing_replays_actual_retained_release(tmp_path, changed):
    from pcbsmith.production_workflow import retained_production_release_evidence

    board, generation, report = accepted_synthetic_release(tmp_path)
    target = {"board": board, "evidence": generation / "review/front.png", "report": report}
    if changed is not None:
        path = target[changed]
        path.write_bytes(path.read_bytes() + (b"bad-json" if changed == "report" else b"\n"))
        with pytest.raises(ValueError):
            retained_production_release_evidence(
                generation_root=generation, release_report_file=report, board_file=board
            )
    else:
        assert (
            len(
                retained_production_release_evidence(
                    generation_root=generation, release_report_file=report, board_file=board
                )
            )
            == 3
        )


@pytest.fixture(autouse=True)
def isolated_producer_contracts(monkeypatch):
    """Synthetic inner-contract tests; real job authorization is tested separately."""
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    monkeypatch.setattr(
        "pcbsmith.kicad.native_format.upgrade_generated_native_file", lambda *a: None
    )
    # These are inner generation/retention contracts, not floorplan acceptance tests.
    monkeypatch.setattr(
        "pcbsmith.kicad.floorplan.require_floorplan",
        lambda *a: {"width_mm": 1, "height_mm": 1, "placements": {}},
    )
    monkeypatch.setattr("pcbsmith.kicad.floorplan.require_native_floorplan", lambda *a, **k: None)


@pytest.mark.parametrize(
    "fault", [None, "missing_file", "changed_schematic", "stale_erc", "no_holds"]
)
def test_handover_replays_release_and_rejects_changed_delivery(tmp_path, fault):
    """Software integration fixture; no real-board approval."""
    import shutil

    from pcbsmith.board_handover import inspect_handover
    from pcbsmith.kicad.kicad_backend import KiCadInstall
    from pcbsmith.kicad.kicad_validate import KiCadProcessResult, run_kicad_validation

    _, generation, release = accepted_synthetic_release(tmp_path)
    board = generation / "design/board.kicad_pcb"
    checks = tmp_path / "native-checks"

    def runner(command):
        path = Path(command[command.index("--output") + 1])
        kind = command[2]
        data = {
            "$schema": f"https://schemas.kicad.org/{kind}.v1.json",
            "source": Path(command[-1]).name,
            "kicad_version": "10.0-software-fixture",
        }
        if kind == "erc":
            data["sheets"] = [{"violations": []}]
        else:
            data.update(violations=[], unconnected_items=[], schematic_parity=[])
        path.write_text(json.dumps(data))
        return KiCadProcessResult(returncode=0, stdout="synthetic test", stderr="")

    native = run_kicad_validation(
        board.parent,
        report_dir=checks,
        runner=runner,
        finder=lambda: KiCadInstall(cli_path=Path("test-only"), source="fixture"),
    )
    assert native.ready
    delivery = tmp_path / "delivery"
    shutil.copytree(board.parent, delivery)
    files = {
        role: {
            "relative_path": "board" + suffix,
            "sha256": file_sha256(delivery / ("board" + suffix)),
        }
        for role, suffix in (
            ("pcb", ".kicad_pcb"),
            ("schematic", ".kicad_sch"),
            ("project", ".kicad_pro"),
        )
    }
    from tests.unit.test_manufacturing_release import _attach_ibom_receipt

    for role, name in (("floorplan", "floorplan.svg"), ("floorplan_preview", "floorplan.png")):
        shutil.copy2(generation / "review/readiness-inputs" / name, delivery / name)
        files[role] = {"relative_path": name, "sha256": file_sha256(delivery / name)}
    html = delivery / "ibom.html"
    html.write_text("synthetic iBOM fixture")
    _attach_ibom_receipt(board, html)
    files["interactive_bom"] = {"relative_path": html.name, "sha256": file_sha256(html)}
    request = {
        "generation_root": str(generation),
        "board": str(board),
        "release_report": str(release),
        "delivery_root": str(delivery),
        "files": files,
        "erc_report": str(checks / "erc.json"),
        "erc_process": str(checks / "erc.process.json"),
        "physical_holds": [
            {
                "board_sha256": file_sha256(board),
                "owner": "fixture",
                "method": "not built",
                "acceptance_criterion": "test only",
                "required_inputs": "no physical inputs in this software test",
            }
        ],
    }
    if fault == "missing_file":
        request["files"].pop("project")
    elif fault == "changed_schematic":
        path = delivery / "board.kicad_sch"
        path.write_bytes(path.read_bytes() + b" ")
        request["files"]["schematic"]["sha256"] = file_sha256(path)
    elif fault == "stale_erc":
        path = checks / "erc.json"
        path.write_bytes(path.read_bytes() + b" ")
    elif fault == "no_holds":
        request["physical_holds"] = []
    path = tmp_path / "handover.json"
    path.write_text(json.dumps(request))
    result = inspect_handover(path)
    assert result["cad_handover_ready"] is (fault is None), result["blockers"]


@pytest.mark.parametrize("back_id", [31, 2])
def test_publication_accepts_native_layer_numbering(tmp_path, monkeypatch, back_id):
    monkeypatch.setattr(
        "tests.unit.test_production_readiness.BOARD",
        BOARD.replace('(31 "B.Cu" signal)', f'({back_id} "B.Cu" signal)'),
    )
    result, _, _ = publish_fixture(tmp_path)
    assert result.transaction.manifest.generation_id == "candidate-1"


def test_publication_rejects_extra_copper_layer(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "tests.unit.test_production_readiness.BOARD",
        BOARD.replace('(31 "B.Cu" signal)', '(2 "B.Cu" signal) (4 "In1.Cu" signal)'),
    )
    with pytest.raises(ValueError, match="exactly two copper layers"):
        publish_fixture(tmp_path)
