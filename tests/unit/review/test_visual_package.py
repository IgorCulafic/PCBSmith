from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pytest

from pcbsmith.kicad.cli import KiCadInstall, KiCadProcessResult
from pcbsmith.kicad.model_preflight import ModelPreflightReport
from pcbsmith.review.visual_package import (
    DetailRegion,
    DiagnosticViewDeclaration,
    RenderProfile,
    ReviewFeatures,
    VisualReviewManifest,
    audit_visual_review_package,
    build_visual_review_workflow_profile,
    generate_visual_review_package,
    record_visual_inspection,
    reprofile_visual_review_package,
    write_visual_review_manifest,
)
from pcbsmith.workflow_conformance import (
    ConformanceDisposition,
    DeviationLevel,
    RequirementState,
    WorkflowArtifactObservation,
    WorkflowDeviation,
    evaluate_workflow_conformance,
)


def _board(tmp_path: Path) -> Path:
    path = tmp_path / "board.kicad_pcb"
    path.write_text(
        """(kicad_pcb
  (version 20241229)
  (generator pcbnew)
  (net 1 "SIG")
  (footprint "Sensor"
    (layer "F.Cu")
    (at 5 5)
    (property "Reference" "U1")
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG")))
  (footprint "Sensor"
    (layer "F.Cu")
    (at 10 5)
    (property "Reference" "U2")
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG")))
  (segment (start 5 5) (end 10 5) (width 0.25) (layer "F.Cu") (net 1))
)""",
        encoding="utf-8",
    )
    return path


def _bottom_hole_board(tmp_path: Path) -> Path:
    path = tmp_path / "bottom-hole.kicad_pcb"
    path.write_text(
        """(kicad_pcb
  (version 20241229)
  (generator pcbnew)
  (footprint "BottomPart"
    (layer "B.Cu")
    (at 5 5)
    (property "Reference" "J1")
    (pad "1" thru_hole circle (at 0 0) (size 2 2) (drill 1) (layers "*.Cu")))
)""",
        encoding="utf-8",
    )
    return path


def _unrouted_board(tmp_path: Path) -> Path:
    path = tmp_path / "unrouted.kicad_pcb"
    path.write_text(
        """(kicad_pcb
  (version 20241229)
  (generator pcbnew)
  (net 1 "SIG")
  (footprint "A" (layer "F.Cu") (at 1 1)
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG")))
  (footprint "B" (layer "F.Cu") (at 5 1)
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "SIG")))
)""",
        encoding="utf-8",
    )
    return path


def _model_report(board: Path, status: str = "passed") -> ModelPreflightReport:
    return ModelPreflightReport(
        schema_id="pcbsmith-kicad-model-preflight-v1",
        board_file=str(board),
        board_sha256=hashlib.sha256(board.read_bytes()).hexdigest(),
        status=status,
        models=(),
    )


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    def __call__(self, command: Sequence[str | Path]) -> KiCadProcessResult:
        text = tuple(str(item) for item in command)
        self.commands.append(text)
        if text[-1] == "version":
            return KiCadProcessResult(command=text, returncode=0, stdout="10.0.3\n", stderr="")
        output = Path(text[text.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        if "svg" in text:
            output.write_text(
                '<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="10mm" '
                'viewBox="0 0 20 10"><rect width="20" height="10"/></svg>',
                encoding="utf-8",
            )
        else:
            output.write_bytes(b"\x89PNG\r\n\x1a\nfixture")
        return KiCadProcessResult(command=text, returncode=0, stdout="ok", stderr="")


def _rasterize(
    _source: Path,
    destination: Path,
    _width: int,
    _height: int,
    _view_box: tuple[float, float, float, float] | None,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(b"\x89PNG\r\n\x1a\nfixture")


def test_generates_matrix_with_4k_scale_details_3d_and_pending_inspection(
    tmp_path: Path,
) -> None:
    board = _board(tmp_path)
    overlay = tmp_path / "sensor-overlay.png"
    overlay.write_bytes(b"\x89PNG\r\n\x1a\noverlay")
    runner = FakeRunner()
    manifest = generate_visual_review_package(
        board_file=board,
        output_dir=tmp_path / "out",
        stage="placement",
        features=ReviewFeatures(
            has_vias=True,
            declared_classes=("sensitive_analog_sensor",),
            class_overlays={"sensitive_analog_sensor": str(overlay)},
            detail_regions=(
                DetailRegion(
                    region_id="sensor-u1",
                    bounds_mm=(2.0, 2.0, 5.0, 4.0),
                    reason="sensor keepout and thermal isolation",
                ),
            ),
        ),
        model_preflight=_model_report(board),
        finder=lambda: KiCadInstall(path=Path("kicad-cli"), source="fixture"),
        runner=runner,
        rasterizer=_rasterize,
    )

    front = next(item for item in manifest.artifacts if item.artifact_id == "2d:front-design:png")
    detail = next(
        item for item in manifest.artifacts if item.artifact_id == "detail:front:sensor-u1"
    )
    assert manifest.package_status == "generated_pending_inspection"
    assert front.pixel_size == (3840, 1920)
    assert front.pixels_per_mm == 192.0
    assert detail.pixel_size == (500, 400)
    assert len([item for item in manifest.artifacts if item.artifact_id.startswith("3d:")]) == 10
    assert (tmp_path / "out" / "review" / "manifest.json").exists()
    assert (tmp_path / "out" / "review" / "review-report.md").exists()
    assert (tmp_path / "out" / "review" / "conformance.json").exists()
    assert manifest.workflow_conformance_status == "conformant"


def test_golden_render_contract_repeats_tiles_mirroring_cameras_and_diagnostics(
    tmp_path: Path,
) -> None:
    board = _board(tmp_path)
    diagnostic = tmp_path / "return-current.png"
    diagnostic.write_bytes(b"\x89PNG\r\n\x1a\ndiagnostic")
    profile = RenderProfile(tile_max_edge_px=2048)

    def generate(output: str) -> VisualReviewManifest:
        return generate_visual_review_package(
            board_file=board,
            output_dir=tmp_path / output,
            stage="placement",
            features=ReviewFeatures(diagnostic_images=(str(diagnostic),)),
            model_preflight=_model_report(board),
            profile=profile,
            finder=lambda: KiCadInstall(path=Path("kicad-cli"), source="fixture"),
            runner=FakeRunner(),
            rasterizer=_rasterize,
            conformance_date=date(2026, 7, 23),
        )

    first = generate("first")
    second = generate("second")
    first_by_id = {item.artifact_id: item for item in first.artifacts}
    second_by_id = {item.artifact_id: item for item in second.artifacts}

    assert first.board_sha256 == second.board_sha256
    assert first.copper_sha256 == second.copper_sha256
    assert set(first_by_id) == set(second_by_id)
    assert {
        artifact_id: item.sha256 for artifact_id, item in first_by_id.items()
    } == {
        artifact_id: item.sha256 for artifact_id, item in second_by_id.items()
    }
    front_tiles = tuple(
        item
        for item in first.artifacts
        if item.artifact_id.startswith("detail:tile:front:")
    )
    back_tiles = tuple(
        item
        for item in first.artifacts
        if item.artifact_id.startswith("detail:tile:back:")
    )
    assert len(front_tiles) > 1
    assert len(front_tiles) == len(back_tiles)
    assert all(not item.mirrored for item in front_tiles)
    assert all(item.mirrored for item in back_tiles)
    assert all(item.pixels_per_mm == 192.0 for item in (*front_tiles, *back_tiles))
    assert {
        item.camera
        for item in first.artifacts
        if item.artifact_id.startswith("3d:populated:")
    } == {"top", "bottom", "perspective", "front-low", "rear-low"}
    assert first_by_id["3d:populated:bottom"].side == "back"
    assert first_by_id["3d:populated:rear-low"].side == "back"
    retained_diagnostic = first_by_id["diagnostic:01"]
    assert retained_diagnostic.required
    assert retained_diagnostic.sha256 == hashlib.sha256(
        diagnostic.read_bytes()
    ).hexdigest()


def test_declared_class_without_overlay_fails_generation(tmp_path: Path) -> None:
    board = _board(tmp_path)

    manifest = generate_visual_review_package(
        board_file=board,
        output_dir=tmp_path / "out",
        stage="final",
        features=ReviewFeatures(declared_classes=("fast_bus",)),
        model_preflight=_model_report(board),
        finder=lambda: KiCadInstall(path=Path("kicad-cli"), source="fixture"),
        runner=FakeRunner(),
        rasterizer=_rasterize,
    )

    overlay = next(item for item in manifest.artifacts if item.artifact_id == "electrical:fast_bus")
    assert overlay.state == "missing"
    assert manifest.package_status == "generation_failed"


def test_triggered_diagnostic_views_are_required_and_unresolved_fails_closed(
    tmp_path: Path,
) -> None:
    board = _board(tmp_path)
    return_current = tmp_path / "return-current.png"
    return_current.write_bytes(b"\x89PNG\r\n\x1a\nreturn-current")
    manifest = generate_visual_review_package(
        board_file=board,
        output_dir=tmp_path / "out",
        stage="placement",
        features=ReviewFeatures(
            diagnostic_views=(
                DiagnosticViewDeclaration(
                    view_id="usb-return",
                    kind="return_current",
                    applicability="applicable",
                    trigger_ids=("netclass.usb",),
                    source_image=str(return_current),
                    authority_sha256="a" * 64,
                    rationale="USB return-current continuity is triggered.",
                ),
                DiagnosticViewDeclaration(
                    view_id="power-density",
                    kind="thermal_current_density",
                    applicability="unresolved",
                    trigger_ids=("power.current.high",),
                    rationale="Current-density evaluator has not produced evidence.",
                ),
                DiagnosticViewDeclaration(
                    view_id="bga-escape",
                    kind="bga",
                    applicability="not_applicable",
                    rationale="No BGA package is present.",
                ),
            )
        ),
        model_preflight=_model_report(board),
        finder=lambda: KiCadInstall(path=Path("kicad-cli"), source="fixture"),
        runner=FakeRunner(),
        rasterizer=_rasterize,
        conformance_date=date(2026, 7, 23),
    )

    available = next(
        item
        for item in manifest.artifacts
        if item.artifact_id == "diagnostic:return_current:usb-return"
    )
    unresolved = next(
        item
        for item in manifest.artifacts
        if item.artifact_id
        == "diagnostic:thermal_current_density:power-density"
    )
    assert available.required and available.state == "generated"
    assert unresolved.required and unresolved.state == "missing"
    assert all("bga-escape" not in item.artifact_id for item in manifest.artifacts)
    assert manifest.package_status == "generation_failed"


def test_saved_board_facts_strengthen_incomplete_feature_declaration(tmp_path: Path) -> None:
    board = _bottom_hole_board(tmp_path)

    manifest = generate_visual_review_package(
        board_file=board,
        output_dir=tmp_path / "out",
        stage="placement",
        features=ReviewFeatures(),
        model_preflight=_model_report(board),
        finder=lambda: KiCadInstall(path=Path("kicad-cli"), source="fixture"),
        runner=FakeRunner(),
        rasterizer=_rasterize,
        conformance_date=date(2026, 7, 22),
    )

    back_assembly = next(
        item for item in manifest.artifacts if item.artifact_id == "2d:back-assembly:png"
    )
    holes = next(item for item in manifest.artifacts if item.artifact_id == "2d:holes-vias:png")
    assert back_assembly.required
    assert holes.required
    conformance = json.loads(
        (tmp_path / "out" / "review" / "conformance.json").read_text("utf-8")
    )
    requirement_ids = {item["requirement_id"] for item in conformance["evaluations"]}
    assert "visual.2d.back-assembly.png" in requirement_ids
    assert "visual.2d.holes-vias.png" in requirement_ids


def test_reprofile_promotes_existing_supplement_when_applicability_is_corrected(
    tmp_path: Path,
) -> None:
    board = _board(tmp_path)
    generated = generate_visual_review_package(
        board_file=board,
        output_dir=tmp_path / "out",
        stage="placement",
        features=ReviewFeatures(),
        model_preflight=_model_report(board),
        finder=lambda: KiCadInstall(path=Path("kicad-cli"), source="fixture"),
        runner=FakeRunner(),
        rasterizer=_rasterize,
        conformance_date=date(2026, 7, 22),
    )
    assert not next(
        item for item in generated.artifacts if item.artifact_id == "2d:holes-vias:png"
    ).required

    report = reprofile_visual_review_package(
        tmp_path / "out" / "review" / "manifest.json",
        features=ReviewFeatures(has_holes=True),
        evaluated_on=date(2026, 7, 23),
    )

    assert report.disposition is ConformanceDisposition.CONFORMANT
    updated = VisualReviewManifest.model_validate_json(
        (tmp_path / "out" / "review" / "manifest.json").read_text("utf-8")
    )
    assert next(
        item for item in updated.artifacts if item.artifact_id == "2d:holes-vias:png"
    ).required


def test_failed_required_model_preflight_withholds_all_3d_artifacts(tmp_path: Path) -> None:
    board = _board(tmp_path)

    manifest = generate_visual_review_package(
        board_file=board,
        output_dir=tmp_path / "out",
        stage="final",
        features=ReviewFeatures(),
        model_preflight=_model_report(board, "failed"),
        finder=lambda: KiCadInstall(path=Path("kicad-cli"), source="fixture"),
        runner=FakeRunner(),
        rasterizer=_rasterize,
    )

    three_d = tuple(item for item in manifest.artifacts if item.artifact_id.startswith("3d:"))
    assert len(three_d) == 10
    assert all(item.state == "missing" for item in three_d)
    assert manifest.package_status == "generation_failed"


def test_review_rejects_model_preflight_from_another_board_revision(
    tmp_path: Path,
) -> None:
    board = _board(tmp_path)
    foreign = _model_report(board).model_copy(update={"board_sha256": "f" * 64})

    with pytest.raises(ValueError, match="different saved board"):
        generate_visual_review_package(
            board_file=board,
            output_dir=tmp_path / "out",
            stage="placement",
            features=ReviewFeatures(),
            model_preflight=foreign,
            finder=lambda: KiCadInstall(path=Path("kicad-cli"), source="fixture"),
            runner=FakeRunner(),
            rasterizer=_rasterize,
        )


def test_inspection_gate_requires_every_required_artifact_to_be_accepted(tmp_path: Path) -> None:
    board = _board(tmp_path)
    manifest = generate_visual_review_package(
        board_file=board,
        output_dir=tmp_path / "out",
        stage="final",
        features=ReviewFeatures(),
        model_preflight=_model_report(board),
        finder=lambda: KiCadInstall(path=Path("kicad-cli"), source="fixture"),
        runner=FakeRunner(),
        rasterizer=_rasterize,
    )
    path = tmp_path / "out" / "review" / "manifest.json"
    decisions = {item.artifact_id: ("accepted", ()) for item in manifest.artifacts if item.required}

    accepted = record_visual_inspection(
        path,
        reviewer="fixture-reviewer",
        mechanism="human visual inspection",
        decisions=decisions,
    )

    assert accepted.package_status == "accepted"
    required = tuple(item for item in accepted.artifacts if item.required)
    assert all(item.reviewer == "fixture-reviewer" for item in required)


def test_final_inspection_cannot_promote_an_unrouted_board(tmp_path: Path) -> None:
    board = _unrouted_board(tmp_path)
    manifest = generate_visual_review_package(
        board_file=board,
        output_dir=tmp_path / "out",
        stage="final",
        features=ReviewFeatures(),
        model_preflight=_model_report(board),
        finder=lambda: KiCadInstall(path=Path("kicad-cli"), source="fixture"),
        runner=FakeRunner(),
        rasterizer=_rasterize,
    )
    assert manifest.package_status == "generation_failed"
    path = tmp_path / "out" / "review" / "manifest.json"
    decisions = {
        item.artifact_id: ("accepted", ())
        for item in manifest.artifacts
        if item.required
    }

    inspected = record_visual_inspection(
        path,
        reviewer="fixture-reviewer",
        mechanism="human visual inspection",
        decisions=decisions,
    )

    assert inspected.package_status == "generation_failed"
    assert inspected.routing_evidence is not None
    assert inspected.routing_evidence.state.value == "placement_only"


def test_declared_missing_predecessor_fails_comparison_artifacts(tmp_path: Path) -> None:
    board = _board(tmp_path)

    manifest = generate_visual_review_package(
        board_file=board,
        output_dir=tmp_path / "out",
        stage="final",
        features=ReviewFeatures(predecessor_board=str(tmp_path / "missing.kicad_pcb")),
        model_preflight=_model_report(board),
        finder=lambda: KiCadInstall(path=Path("kicad-cli"), source="fixture"),
        runner=FakeRunner(),
        rasterizer=_rasterize,
    )

    comparisons = tuple(
        item for item in manifest.artifacts if item.artifact_id.startswith("comparison:")
    )
    assert manifest.package_status == "generation_failed"
    assert len(comparisons) == 6
    assert all(item.state == "missing" for item in comparisons)


def test_retained_profile_detects_deleted_file_and_reduces_package_status(tmp_path: Path) -> None:
    board = _board(tmp_path)
    generate_visual_review_package(
        board_file=board,
        output_dir=tmp_path / "out",
        stage="final",
        features=ReviewFeatures(),
        model_preflight=_model_report(board),
        finder=lambda: KiCadInstall(path=Path("kicad-cli"), source="fixture"),
        runner=FakeRunner(),
        rasterizer=_rasterize,
        conformance_date=date(2026, 7, 22),
    )
    manifest_path = tmp_path / "out" / "review" / "manifest.json"
    manifest = VisualReviewManifest.model_validate_json(manifest_path.read_text("utf-8"))
    target = next(
        item for item in manifest.artifacts if item.artifact_id == "3d:populated:rear-low"
    )
    (manifest_path.parent / target.relative_path).unlink()

    report = audit_visual_review_package(
        manifest_path,
        evaluated_on=date(2026, 7, 23),
    )

    assert report.disposition is ConformanceDisposition.NONCONFORMANT
    evaluation = next(
        item
        for item in report.evaluations
        if item.requirement_id == "visual.3d.populated.rear-low"
    )
    assert evaluation.state is RequirementState.INVALID
    updated = VisualReviewManifest.model_validate_json(manifest_path.read_text("utf-8"))
    assert updated.package_status == "generation_failed"


def test_retained_profile_rejects_manifest_layer_relabeling(tmp_path: Path) -> None:
    board = _board(tmp_path)
    generate_visual_review_package(
        board_file=board,
        output_dir=tmp_path / "out",
        stage="final",
        features=ReviewFeatures(),
        model_preflight=_model_report(board),
        finder=lambda: KiCadInstall(path=Path("kicad-cli"), source="fixture"),
        runner=FakeRunner(),
        rasterizer=_rasterize,
        conformance_date=date(2026, 7, 22),
    )
    manifest_path = tmp_path / "out" / "review" / "manifest.json"
    manifest = VisualReviewManifest.model_validate_json(manifest_path.read_text("utf-8"))
    altered = tuple(
        item.model_copy(update={"layers": ("F.Cu", "Edge.Cuts")})
        if item.artifact_id == "2d:combined-copper:png"
        else item
        for item in manifest.artifacts
    )
    write_visual_review_manifest(
        manifest_path,
        manifest.model_copy(update={"artifacts": altered}),
    )

    report = audit_visual_review_package(
        manifest_path,
        evaluated_on=date(2026, 7, 22),
    )

    evaluation = next(
        item
        for item in report.evaluations
        if item.requirement_id == "visual.2d.combined-copper.png"
    )
    assert evaluation.state is RequirementState.INVALID
    assert any("layer mismatch" in finding for finding in evaluation.findings)


def test_bldc_r002_legacy_custom_views_are_retained_as_failure_corpus(
    tmp_path: Path,
) -> None:
    board = _board(tmp_path)
    generated = generate_visual_review_package(
        board_file=board,
        output_dir=tmp_path / "out",
        stage="final",
        features=ReviewFeatures(),
        model_preflight=_model_report(board),
        finder=lambda: KiCadInstall(path=Path("kicad-cli"), source="fixture"),
        runner=FakeRunner(),
        rasterizer=_rasterize,
        conformance_date=date(2026, 7, 22),
    )
    profile = build_visual_review_workflow_profile(
        manifest=generated,
        features=ReviewFeatures(),
    )
    fixture = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "fixtures"
            / "review"
            / "bldc_r002_legacy_custom_review.json"
        ).read_text("utf-8")
    )
    observations = tuple(
        WorkflowArtifactObservation(
            artifact_id=artifact_id,
            generated=True,
            media_type="image/png",
            board_sha256=generated.board_sha256,
            stage="final",
            content_sha256="d" * 64,
        )
        for artifact_id in fixture["observed_artifact_ids"]
    )
    additions = tuple(
        WorkflowDeviation(
            deviation_id=f"d0:{item.artifact_id}",
            level=DeviationLevel.ADDITION,
            artifact_id=item.artifact_id,
            reason="Retained legacy thermal-mechanical visual aid.",
            consequence="Does not alter canonical coverage.",
            residual_risk="Cannot replace a canonical view.",
        )
        for item in observations
    )

    report = evaluate_workflow_conformance(
        profile=profile,
        observations=observations,
        deviations=additions,
        evaluated_on=date(2026, 7, 22),
    )

    assert report.disposition is ConformanceDisposition.NONCONFORMANT
    states = {item.requirement_id: item.state for item in report.evaluations}
    assert all(
        states[requirement_id] is RequirementState.MISSING
        for requirement_id in fixture["must_remain_missing"]
    )
