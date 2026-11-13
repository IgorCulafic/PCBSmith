from __future__ import annotations

from pathlib import Path

import pytest
from tests.unit.production_evidence_fixtures import filled_region_example, write_empty_drc

from pcbsmith.automatic_review_gate import ProductionMarkingAudit, qualify_automatic_review
from pcbsmith.kicad.routing_evidence import inspect_kicad_drc_report
from pcbsmith.power_topology_ir import BoardPowerTopology
from pcbsmith.review.visual_package import RenderProfile, ReviewArtifact, VisualReviewManifest
from pcbsmith.whole_board_qualification import QualificationDisposition
from pcbsmith.whole_board_qualification_adapter import qualify_production_board

BOARD = "a" * 64


def _qualify(**changes: object):
    values: dict[str, object] = {
        "case_id": "W7-adapter",
        "refilled_board_sha256": BOARD,
        "drc_evidence": None,
        "drc_board_sha256": None,
        "routing_evidence": None,
        "fill_snapshot": None,
        "fill_connectivity": None,
        "thermal_audit": None,
        "topology": None,
        "current_paths": (),
        "fabrication_profile": None,
        "reference_continuity": None,
        "automatic_review": None,
        "craft": None,
    }
    values.update(changes)
    return qualify_production_board(**values)  # type: ignore[arg-type]


def test_missing_production_evidence_is_unverified_and_never_fabricated_pass() -> None:
    result = _qualify()
    assert not result.release_qualified
    assert "kicad_integrity" in result.unverified_gate_ids
    assert "filled_region_connectivity" in result.unverified_gate_ids
    assert "routing_craft:craft_evidence_missing" in result.blocker_ids


def test_bound_evidence_drives_filled_region_gate(tmp_path: Path) -> None:
    snapshot, observation, thermal = filled_region_example(tmp_path)
    result = _qualify(
        refilled_board_sha256=snapshot.filled_board_sha256,
        fill_snapshot=snapshot,
        fill_connectivity=observation,
        thermal_audit=thermal,
        fill_source_pad_ids=("J1.2",),
    )
    gate = next(item for item in result.gates if item.gate_id == "filled_region_connectivity")
    assert gate.disposition is QualificationDisposition.PASS
    assert gate.evaluated_object_count == 1


def _retained_fill():
    root = ROOT / "experiments/phase17-w3-final-fill-connectivity-real-test-2026-08-19"
    return (
        KiCadFinalFillSnapshot.model_validate_json(
            (root / "classified-final-fill-snapshot.json").read_bytes()
        ),
        KiCadFinalFillConnectivityObservation.model_validate_json(
            (root / "connectivity-observation.json").read_bytes()
        ),
        KiCadThermalSpokeAudit.model_validate_json(
            (root / "thermal-spoke-audit.json").read_bytes()
        ),
    )


@pytest.mark.parametrize("updates", [{"refilled_by_kicad": False}, {"regions": ()}])
def test_stale_or_empty_declared_plane_cannot_pass_or_be_not_applicable(updates):
    from pcbsmith.whole_board_qualification_adapter import _fill_gate

    snapshot, observation, thermal = _retained_fill()
    excluded = {
        "snapshot_fingerprint",
        "zone_intent_unchanged",
        "stale_fill",
        "unverified_region_ids",
    }
    fields = {n: getattr(snapshot, n) for n in type(snapshot).model_fields if n not in excluded}
    broken = KiCadFinalFillSnapshot.build(**(fields | updates))
    result = _fill_gate(
        broken.filled_board_sha256, broken, observation, thermal, declared_source_pad_ids=("J1.2",)
    )
    assert result.disposition is QualificationDisposition.UNVERIFIED
    assert result.applicable


def test_filled_region_classification_is_replayed_against_declared_source():
    from pcbsmith.whole_board_qualification_adapter import _fill_gate

    snapshot, observation, thermal = _retained_fill()
    for sources in ((), ("nonexistent.source",)):
        gate = _fill_gate(
            snapshot.filled_board_sha256,
            snapshot,
            observation,
            thermal,
            declared_source_pad_ids=sources,
        )
        assert gate.disposition is QualificationDisposition.UNVERIFIED
    missing = observation.model_copy(update={"records": ()})
    with pytest.raises(ValueError, match="exact region set"):
        _fill_gate(
            snapshot.filled_board_sha256,
            snapshot,
            missing,
            thermal,
            declared_source_pad_ids=("J1.2",),
        )


def test_reference_evidence_requires_exact_current_context():
    from tests.unit.kicad.test_reference_continuity import _evidence

    from pcbsmith.kicad.reference_continuity import (
        ReferenceContinuityContext,
        ReferenceContinuityEvidence,
    )
    from pcbsmith.whole_board_qualification_adapter import _reference_gate

    context = ReferenceContinuityContext(
        board_sha256=BOARD,
        native_inputs_sha256="b" * 64,
        stackup_sha256="c" * 64,
        policy_sha256="d" * 64,
    )
    legacy = ReferenceContinuityEvidence.model_validate(_evidence())
    assert (
        _reference_gate(BOARD, None, legacy, context).disposition
        is QualificationDisposition.UNVERIFIED
    )
    bound = ReferenceContinuityEvidence.model_validate(
        _evidence(context=context.model_dump(mode="json"))
    )
    assert _reference_gate(BOARD, None, bound, context).disposition is QualificationDisposition.PASS
    for field in type(context).model_fields:
        changed = context.model_copy(update={field: "f" * 64})
        with pytest.raises(ValueError, match="another board, stackup, rules or policy"):
            _reference_gate(BOARD, None, bound, changed)


def test_explicitly_not_applicable_topology_marks_all_topology_gates_not_applicable() -> None:
    topology = BoardPowerTopology.build(
        topology_id="logic-only",
        board_sha256=BOARD,
        fabrication_profile_sha256="b" * 64,
        applicability="not_applicable",
        applicability_rationale="This fixture declares no power or return-topology claims.",
        terminals=(),
        regions=(),
        paths=(),
        return_relationships=(),
    )
    result = _qualify(topology=topology)
    by_id = {item.gate_id: item for item in result.gates}
    assert by_id["functional_topology"].disposition is QualificationDisposition.NOT_APPLICABLE
    assert by_id["current_path_ledger"].disposition is QualificationDisposition.NOT_APPLICABLE
    assert by_id["current_environment_model"].disposition is QualificationDisposition.NOT_APPLICABLE
    assert by_id["reference_continuity"].disposition is QualificationDisposition.NOT_APPLICABLE


def test_drc_report_requires_explicit_same_revision_binding(tmp_path: Path) -> None:
    report = write_empty_drc(tmp_path)
    evidence = inspect_kicad_drc_report(report)
    with pytest.raises(ValueError, match="another board revision"):
        _qualify(drc_evidence=evidence, drc_board_sha256="b" * 64)


def test_empty_applicable_topology_is_rejected_as_vacuous() -> None:
    with pytest.raises(ValueError, match="cannot be an empty declaration"):
        BoardPowerTopology.build(
            topology_id="vacuous",
            board_sha256=BOARD,
            fabrication_profile_sha256="b" * 64,
            terminals=(),
            regions=(),
            paths=(),
            return_relationships=(),
        )


def _automatic_review_for_inspection(
    inspection: str,
    package_status: str,
):
    artifact_ids = (
        "2d:front-design:png",
        "2d:back-design:png",
        "2d:front-copper:png",
        "2d:back-copper:png",
        "2d:combined-copper:png",
    )
    manifest = VisualReviewManifest(
        schema_id="pcbsmith-visual-review-manifest-v1",
        render_profile=RenderProfile(),
        stage="final",
        board_file="board.kicad_pcb",
        board_sha256=BOARD,
        copper_sha256="c" * 64,
        kicad_version="10.0",
        renderer_version="fixture",
        model_preflight_status="passed",
        workflow_conformance_status="conformant",
        package_status=package_status,
        artifacts=tuple(
            ReviewArtifact(
                artifact_id=artifact_id,
                category="fixture",
                relative_path=f"{index}.png",
                media_type="image/png",
                required=True,
                state="generated",
                inspection=inspection,
                sha256="d" * 64,
            )
            for index, artifact_id in enumerate(artifact_ids)
        ),
    )
    audit = ProductionMarkingAudit.build(
        board_sha256=BOARD,
        drc_report_sha256="1" * 64,
        requirements_fingerprint="2" * 64,
        inventory_fingerprint="3" * 64,
        inspected_mark_count=1,
    )
    return qualify_automatic_review(
        manifest=manifest,
        manifest_fingerprint="4" * 64,
        marking_audit=audit,
    )


def test_w7_visual_gate_distinguishes_pending_inspection_from_hard_attention() -> None:
    pending = _qualify(
        automatic_review=_automatic_review_for_inspection(
            "uninspected", "generated_pending_inspection"
        )
    )
    pending_gate = next(item for item in pending.gates if item.gate_id == "visual_review")
    assert pending_gate.disposition is QualificationDisposition.UNVERIFIED
    assert any("pending_inspection" in item for item in pending_gate.notes)

    attention = _qualify(
        automatic_review=_automatic_review_for_inspection(
            "attention_required", "attention_required"
        )
    )
    attention_gate = next(item for item in attention.gates if item.gate_id == "visual_review")
    assert attention_gate.disposition is QualificationDisposition.FAIL
    assert any("visual_inspection:" in item for item in attention_gate.finding_ids)


def test_explicit_unresolved_topology_keeps_all_topology_gates_unverified() -> None:
    topology = BoardPowerTopology.build(
        topology_id="incomplete-power-ledger",
        board_sha256=BOARD,
        fabrication_profile_sha256="b" * 64,
        applicability="unresolved",
        applicability_rationale="Power semantics exist but have not been compiled into paths.",
        terminals=(),
        regions=(),
        paths=(),
        return_relationships=(),
    )

    result = _qualify(topology=topology)
    by_id = {item.gate_id: item for item in result.gates}
    for gate_id in (
        "functional_topology",
        "current_path_ledger",
        "current_environment_model",
        "reference_continuity",
    ):
        assert by_id[gate_id].disposition is QualificationDisposition.UNVERIFIED
