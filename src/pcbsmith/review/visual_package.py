"""Versioned, fail-closed visual review package for a saved KiCad board."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import xml.etree.ElementTree as ET
from collections.abc import Callable, Sequence
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pcbsmith.kicad.cli import (
    KiCadInstall,
    KiCadProcessResult,
    find_kicad_cli,
    run_kicad_process,
)
from pcbsmith.kicad.library import QuotedString, SExpr, SList, parse_sexpr, serialize_sexpr
from pcbsmith.kicad.model_preflight import ModelPreflightReport
from pcbsmith.kicad.routing_evidence import (
    RoutingArtifactState,
    SavedBoardRoutingEvidence,
    inspect_saved_board_routing,
)
from pcbsmith.workflow_conformance import (
    ArtifactConstraint,
    ConformanceDisposition,
    DeviationLevel,
    WorkflowArtifactObservation,
    WorkflowConformanceReport,
    WorkflowDeviation,
    WorkflowProfile,
    WorkflowRequirement,
    evaluate_workflow_conformance,
)

ReviewStage = Literal["placement", "final"]
ArtifactState = Literal["generated", "missing"]
InspectionState = Literal["uninspected", "accepted", "attention_required"]
PackageStatus = Literal[
    "generation_failed",
    "generated_pending_inspection",
    "accepted",
    "attention_required",
]
WorkflowConformanceStatus = Literal[
    "not_evaluated",
    "conformant",
    "conformant_with_waivers",
    "nonconformant",
]


class DetailRegion(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    region_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    bounds_mm: tuple[float, float, float, float]
    reason: str = Field(min_length=1)
    side: Literal["front", "back"] = "front"


class DiagnosticViewDeclaration(BaseModel):
    """One triggered diagnostic view with explicit applicability authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    view_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    kind: Literal[
        "stackup_reference",
        "return_current",
        "power_domain",
        "thermal_current_density",
        "high_speed",
        "bga",
        "dfm",
    ]
    applicability: Literal["applicable", "not_applicable", "unresolved"]
    trigger_ids: tuple[str, ...] = ()
    source_image: str | None = None
    authority_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def declaration_is_truthful(self) -> DiagnosticViewDeclaration:
        triggers = tuple(sorted(self.trigger_ids))
        if len(triggers) != len(set(triggers)):
            raise ValueError("diagnostic trigger identities must be unique")
        if self.applicability == "applicable":
            if not triggers or self.source_image is None or self.authority_sha256 is None:
                raise ValueError(
                    "applicable diagnostic requires triggers, source, and authority"
                )
        elif self.applicability == "unresolved":
            if not triggers or self.source_image is not None:
                raise ValueError(
                    "unresolved diagnostic requires triggers and no invented source"
                )
        elif self.source_image is not None or triggers:
            raise ValueError(
                "not-applicable diagnostic cannot retain triggers or a source"
            )
        object.__setattr__(self, "trigger_ids", triggers)
        return self


class ReviewFeatures(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    has_bottom_components: bool = False
    has_holes: bool = False
    has_zones: bool = False
    has_keepouts: bool = False
    has_cutouts: bool = False
    has_vias: bool = False
    declared_classes: tuple[
        Literal[
            "power_ground",
            "high_current",
            "sensitive_analog_sensor",
            "fast_bus",
            "matched_pair",
            "rf_filtered",
        ],
        ...,
    ] = ()
    class_overlays: dict[str, str] = Field(default_factory=dict)
    detail_regions: tuple[DetailRegion, ...] = ()
    diagnostic_images: tuple[str, ...] = ()
    diagnostic_views: tuple[DiagnosticViewDeclaration, ...] = ()
    predecessor_board: str | None = None

    @model_validator(mode="after")
    def diagnostic_view_ids_are_unique(self) -> ReviewFeatures:
        ids = tuple(item.view_id for item in self.diagnostic_views)
        if len(ids) != len(set(ids)):
            raise ValueError("diagnostic view identities must be unique")
        return self


class RenderProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["pcbsmith-render-profile-v1"] = "pcbsmith-render-profile-v1"
    minimum_full_board_long_edge_px: int = Field(default=3840, ge=1080)
    overview_pixels_per_mm: float = Field(default=30.0, ge=20.0, le=40.0)
    detail_pixels_per_mm: float = Field(default=100.0, ge=80.0, le=120.0)
    tile_max_edge_px: int = Field(default=4096, ge=2048)
    tile_overlap_mm: float = Field(default=5.0, gt=0)
    three_d_long_edge_px: int = Field(default=3840, ge=1080)


class ReviewArtifact(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_id: str
    category: str
    relative_path: str
    media_type: Literal["image/png", "image/svg+xml"]
    required: bool
    state: ArtifactState
    inspection: InspectionState = "uninspected"
    layers: tuple[str, ...] = ()
    side: Literal["front", "back", "both", "none"] = "none"
    mirrored: bool = False
    camera: str | None = None
    pixels_per_mm: float | None = None
    pixel_size: tuple[int, int] | None = None
    bounds_mm: tuple[float, float, float, float] | None = None
    sha256: str | None = None
    reviewer: str | None = None
    inspection_mechanism: str | None = None
    findings: tuple[str, ...] = ()


class VisualReviewManifest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    schema_id: Literal["pcbsmith-visual-review-manifest-v1"] = Field(
        validation_alias="schema", serialization_alias="schema"
    )
    render_profile: RenderProfile
    stage: ReviewStage
    board_file: str
    board_sha256: str
    copper_sha256: str
    routing_evidence: SavedBoardRoutingEvidence | None = None
    source_revision: str | None = None
    kicad_version: str
    renderer_version: str
    model_preflight_status: str
    workflow_profile_id: str = "pcbsmith.visual-review.standard"
    workflow_profile_version: int = 1
    workflow_conformance_status: WorkflowConformanceStatus = "not_evaluated"
    package_status: PackageStatus
    artifacts: tuple[ReviewArtifact, ...]
    findings: tuple[str, ...] = ()


Rasterizer = Callable[[Path, Path, int, int, tuple[float, float, float, float] | None], None]
ProcessRunner = Callable[[Sequence[str | Path]], KiCadProcessResult]
ProgressReporter = Callable[[str], None]


_TWO_D_PROFILES: tuple[
    tuple[str, str, tuple[str, ...], Literal["front", "back", "both"], bool], ...
] = (
    (
        "overview/front",
        "front-design",
        ("F.Cu", "F.Mask", "F.Silkscreen", "Edge.Cuts"),
        "front",
        False,
    ),
    (
        "overview/back",
        "back-design",
        ("B.Cu", "B.Mask", "B.Silkscreen", "Edge.Cuts"),
        "back",
        True,
    ),
    ("fabrication/front", "front-fabrication", ("F.Cu", "F.Mask", "Edge.Cuts"), "front", False),
    ("fabrication/back", "back-fabrication", ("B.Cu", "B.Mask", "Edge.Cuts"), "back", True),
    ("assembly/front", "front-assembly", ("F.Fab", "F.Courtyard", "Edge.Cuts"), "front", False),
    ("assembly/back", "back-assembly", ("B.Fab", "B.Courtyard", "Edge.Cuts"), "back", True),
    ("routing", "front-copper", ("F.Cu", "Edge.Cuts"), "front", False),
    ("routing", "back-copper", ("B.Cu", "Edge.Cuts"), "back", True),
    ("routing", "combined-copper", ("F.Cu", "B.Cu", "Edge.Cuts"), "both", False),
    ("electrical", "holes-vias", ("F.Cu", "B.Cu", "Edge.Cuts"), "both", False),
    (
        "electrical",
        "courtyards-keepouts",
        ("F.Courtyard", "B.Courtyard", "Margin", "Edge.Cuts"),
        "both",
        False,
    ),
)

_CAMERAS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("top", ("--side", "top")),
    ("bottom", ("--side", "bottom")),
    ("perspective", ("--perspective", "--rotate", "-30,0,-20", "--zoom", "0.9")),
    ("front-low", ("--perspective", "--side", "front", "--rotate", "-18,0,0")),
    ("rear-low", ("--perspective", "--side", "back", "--rotate", "18,0,180")),
)

_COMPARISON_SIDES: tuple[
    tuple[Literal["front", "back"], tuple[str, ...], bool], ...
] = (
    ("front", ("F.Cu", "F.Mask", "F.Silkscreen", "Edge.Cuts"), False),
    ("back", ("B.Cu", "B.Mask", "B.Silkscreen", "Edge.Cuts"), True),
)


def generate_visual_review_package(
    *,
    board_file: Path,
    output_dir: Path,
    stage: ReviewStage,
    features: ReviewFeatures,
    model_preflight: ModelPreflightReport,
    profile: RenderProfile | None = None,
    source_revision: str | None = None,
    finder: Callable[[], KiCadInstall | None] = find_kicad_cli,
    runner: ProcessRunner = run_kicad_process,
    rasterizer: Rasterizer | None = None,
    progress: ProgressReporter | None = None,
    deviations: tuple[WorkflowDeviation, ...] = (),
    conformance_date: date | None = None,
) -> VisualReviewManifest:
    profile = profile or RenderProfile()
    report_progress = progress or (lambda _message: None)
    board = board_file.resolve()
    review_dir = output_dir.resolve() / "review"
    review_dir.mkdir(parents=True, exist_ok=True)
    install = finder()
    if install is None:
        raise RuntimeError("KiCad CLI is required to generate the visual review package.")
    raster = rasterizer or rasterize_svg_with_resvg
    board_payload = board.read_bytes()
    board_sha256 = hashlib.sha256(board_payload).hexdigest()
    if model_preflight.board_sha256 != board_sha256:
        raise ValueError(
            "3D model preflight belongs to a different saved board revision."
        )
    board_root = parse_sexpr(board_payload.decode("utf-8"))
    routing_evidence = inspect_saved_board_routing(board)
    features = _augment_features_from_board(features, board_root)
    artifacts: list[ReviewArtifact] = []
    package_findings: list[str] = [
        (
            "Saved-board routing state "
            f"{routing_evidence.state.value}: "
            f"{routing_evidence.segment_count} segments, "
            f"{routing_evidence.via_count} vias, "
            f"{routing_evidence.copper_carrier_net_count}/"
            f"{routing_evidence.routable_net_count} routable nets with a "
            "copper carrier. Carrier presence is not connectivity proof."
        )
    ]
    kicad_version = _kicad_version(install, runner)

    base_svg_by_side: dict[str, Path] = {}
    for category, name, layers, side, mirrored in _TWO_D_PROFILES:
        report_progress(f"2D profile {name}: exporting vector and raster evidence")
        required = _profile_required(name, features)
        svg_path = review_dir / category / f"{name}.svg"
        png_path = svg_path.with_suffix(".png")
        svg_result = _export_svg(
            install=install,
            runner=runner,
            board=board,
            output=svg_path,
            layers=layers,
            mirrored=mirrored,
        )
        if svg_result is not None:
            package_findings.append(svg_result)
        routing_artifact_findings = (
            _routing_artifact_findings(stage, routing_evidence)
            if category == "routing"
            else ()
        )
        if (
            svg_path.exists()
            and category == "routing"
            and stage == "placement"
            and routing_evidence.state is RoutingArtifactState.PLACEMENT_ONLY
        ):
            _add_svg_watermark(svg_path, "UNROUTED PLACEMENT")
        svg_artifact = _artifact_from_file(
            review_dir=review_dir,
            path=svg_path,
            artifact_id=f"2d:{name}:svg",
            category=category,
            media_type="image/svg+xml",
            required=required,
            layers=layers,
            side=side,
            mirrored=mirrored,
            findings=routing_artifact_findings,
        )
        artifacts.append(svg_artifact)
        if svg_path.exists():
            width_mm, height_mm = _svg_size_mm(svg_path)
            width_px, height_px, ppm = _full_board_pixels(width_mm, height_mm, profile)
            try:
                raster(svg_path, png_path, width_px, height_px, None)
            except Exception as exc:
                package_findings.append(f"Rasterization failed for {name}: {exc}")
            artifacts.append(
                _artifact_from_file(
                    review_dir=review_dir,
                    path=png_path,
                    artifact_id=f"2d:{name}:png",
                    category=category,
                    media_type="image/png",
                    required=required,
                    layers=layers,
                    side=side,
                    mirrored=mirrored,
                    pixels_per_mm=ppm,
                    pixel_size=(width_px, height_px),
                    bounds_mm=(0.0, 0.0, width_mm, height_mm),
                    findings=routing_artifact_findings,
                )
            )
            if name in {"front-design", "back-design"}:
                base_svg_by_side[side] = svg_path
                artifacts.extend(
                    _render_tiles(
                        svg_path=svg_path,
                        review_dir=review_dir,
                        side=side,
                        width_mm=width_mm,
                        height_mm=height_mm,
                        pixels_per_mm=ppm,
                        mirrored=mirrored,
                        profile=profile,
                        rasterizer=raster,
                        findings=package_findings,
                    )
                )
        else:
            artifacts.append(
                ReviewArtifact(
                    artifact_id=f"2d:{name}:png",
                    category=category,
                    relative_path=png_path.relative_to(review_dir).as_posix(),
                    media_type="image/png",
                    required=required,
                    state="missing",
                    layers=layers,
                    side=side,
                    mirrored=mirrored,
                    findings=(
                        "Source SVG was not generated.",
                        *routing_artifact_findings,
                    ),
                )
            )

    artifacts.extend(
        _render_details(
            features=features,
            base_svg_by_side=base_svg_by_side,
            review_dir=review_dir,
            profile=profile,
            rasterizer=raster,
            findings=package_findings,
        )
    )
    if features.predecessor_board is not None:
        artifacts.extend(
            _render_comparisons(
                predecessor=Path(features.predecessor_board),
                board=board,
                review_dir=review_dir,
                current_svg_by_side=base_svg_by_side,
                install=install,
                runner=runner,
                profile=profile,
                rasterizer=raster,
                findings=package_findings,
            )
        )
    artifacts.extend(_collect_declared_overlays(features, review_dir))
    artifacts.extend(_collect_diagnostics(features, review_dir))

    if model_preflight.status == "failed":
        package_findings.append("Required 3D model preflight failed; 3D renders are withheld.")
        artifacts.extend(_missing_3d_artifacts(review_dir))
    else:
        report_progress("3D profiles: starting populated and bare-board camera set")
        artifacts.extend(
            _render_three_d(
                board=board,
                board_root=board_root,
                model_preflight=model_preflight,
                review_dir=review_dir,
                install=install,
                runner=runner,
                profile=profile,
                findings=package_findings,
                progress=report_progress,
            )
        )

    routing_incomplete = (
        stage == "final"
        and routing_evidence.state is not RoutingArtifactState.ROUTED_CANDIDATE
    )
    if routing_incomplete:
        package_findings.append(
            "Final review refused: the saved board is not a routed candidate."
        )
    generation_failed = (
        routing_incomplete
        or any(item.required and item.state == "missing" for item in artifacts)
    )
    manifest = VisualReviewManifest(
        schema_id="pcbsmith-visual-review-manifest-v1",
        render_profile=profile,
        stage=stage,
        board_file=str(board),
        board_sha256=board_sha256,
        copper_sha256=_copper_hash(board_root),
        routing_evidence=routing_evidence,
        source_revision=source_revision,
        kicad_version=kicad_version,
        renderer_version="kicad-cli-svg+render/resvg_py-v1",
        model_preflight_status=model_preflight.status,
        package_status=(
            "generation_failed" if generation_failed else "generated_pending_inspection"
        ),
        artifacts=tuple(sorted(artifacts, key=lambda item: item.artifact_id)),
        findings=tuple(package_findings),
    )
    # The package-level manifest and report are baseline requirements too.  Write
    # provisional copies so conformance tests their real presence rather than an
    # intention to create them later.
    write_visual_review_manifest(review_dir / "manifest.json", manifest)
    _write_review_report(review_dir / "review-report.md", manifest)
    conformance = _evaluate_visual_conformance(
        manifest=manifest,
        review_dir=review_dir,
        features=features,
        deviations=deviations,
        evaluated_on=conformance_date or date.today(),
    )
    conformance_status: WorkflowConformanceStatus = conformance.disposition.value
    if conformance.disposition is ConformanceDisposition.NONCONFORMANT:
        failed_requirements = tuple(
            item.requirement_id
            for item in conformance.evaluations
            if item.state.value in {"missing", "invalid"}
        )
        summary = "Workflow conformance failed"
        if failed_requirements:
            summary += ": " + ", ".join(failed_requirements)
        manifest = manifest.model_copy(
            update={
                "workflow_conformance_status": conformance_status,
                "package_status": "generation_failed",
                "findings": (*manifest.findings, summary),
            }
        )
    else:
        manifest = manifest.model_copy(
            update={"workflow_conformance_status": conformance_status}
        )
    write_visual_review_manifest(review_dir / "manifest.json", manifest)
    _write_review_report(review_dir / "review-report.md", manifest)
    _write_conformance_report(review_dir / "conformance.json", conformance)
    return manifest


def record_visual_inspection(
    manifest_path: Path,
    *,
    reviewer: str,
    mechanism: str,
    decisions: dict[str, tuple[InspectionState, tuple[str, ...]]],
) -> VisualReviewManifest:
    manifest = VisualReviewManifest.model_validate_json(manifest_path.read_text("utf-8"))
    artifacts: list[ReviewArtifact] = []
    for artifact in manifest.artifacts:
        decision = decisions.get(artifact.artifact_id)
        if decision is None:
            artifacts.append(artifact)
            continue
        state, findings = decision
        if state == "uninspected":
            artifacts.append(
                artifact.model_copy(update={"inspection": state, "findings": findings})
            )
        else:
            artifacts.append(
                artifact.model_copy(
                    update={
                        "inspection": state,
                        "reviewer": reviewer,
                        "inspection_mechanism": mechanism,
                        "findings": findings,
                    }
                )
            )
    required = tuple(item for item in artifacts if item.required)
    if _routing_blocks_final_acceptance(manifest):
        status: PackageStatus = "generation_failed"
    elif manifest.workflow_conformance_status == "nonconformant":
        status = "generation_failed"
    elif any(item.state == "missing" for item in required):
        status = "generation_failed"
    elif any(item.inspection == "attention_required" for item in required):
        status = "attention_required"
    elif required and all(item.inspection == "accepted" for item in required):
        status = "accepted"
    else:
        status = "generated_pending_inspection"
    updated = manifest.model_copy(update={"artifacts": tuple(artifacts), "package_status": status})
    write_visual_review_manifest(manifest_path, updated)
    _write_review_report(manifest_path.parent / "review-report.md", updated)
    return updated


def write_visual_review_manifest(path: Path, manifest: VisualReviewManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.model_dump(mode="json", by_alias=True), indent=2) + "\n",
        encoding="utf-8",
    )


def audit_visual_review_package(
    manifest_path: Path,
    *,
    evaluated_on: date,
) -> WorkflowConformanceReport:
    """Re-evaluate retained files against the originally retained profile."""

    manifest = VisualReviewManifest.model_validate_json(manifest_path.read_text("utf-8"))
    conformance_path = manifest_path.parent / "conformance.json"
    retained = WorkflowConformanceReport.model_validate_json(
        conformance_path.read_text("utf-8")
    )
    report = evaluate_workflow_conformance(
        profile=retained.profile,
        observations=_visual_observations(manifest, manifest_path.parent),
        deviations=retained.deviations,
        evaluated_on=evaluated_on,
    )
    required = tuple(item for item in manifest.artifacts if item.required)
    if (
        _routing_blocks_final_acceptance(manifest)
        or report.disposition is ConformanceDisposition.NONCONFORMANT
        or any(item.state == "missing" for item in required)
    ):
        package_status: PackageStatus = "generation_failed"
    elif any(item.inspection == "attention_required" for item in required):
        package_status = "attention_required"
    elif required and all(item.inspection == "accepted" for item in required):
        package_status = "accepted"
    else:
        package_status = "generated_pending_inspection"
    updated = manifest.model_copy(
        update={
            "workflow_profile_id": report.profile.profile_id,
            "workflow_profile_version": report.profile.profile_version,
            "workflow_conformance_status": report.disposition.value,
            "package_status": package_status,
        }
    )
    write_visual_review_manifest(manifest_path, updated)
    _write_review_report(manifest_path.parent / "review-report.md", updated)
    _write_conformance_report(conformance_path, report)
    return report


def _routing_blocks_final_acceptance(manifest: VisualReviewManifest) -> bool:
    return manifest.stage == "final" and (
        manifest.routing_evidence is None
        or manifest.routing_evidence.state is not RoutingArtifactState.ROUTED_CANDIDATE
    )


def reprofile_visual_review_package(
    manifest_path: Path,
    *,
    features: ReviewFeatures,
    evaluated_on: date,
    deviations: tuple[WorkflowDeviation, ...] = (),
) -> WorkflowConformanceReport:
    """Apply corrected applicability facts without pretending to regenerate files."""

    manifest = VisualReviewManifest.model_validate_json(manifest_path.read_text("utf-8"))
    board = Path(manifest.board_file)
    root = parse_sexpr(board.read_text("utf-8"))
    effective_features = _augment_features_from_board(features, root)
    profile = build_visual_review_workflow_profile(
        manifest=manifest,
        features=effective_features,
    )
    required_artifacts = {item.expected_artifact_id for item in profile.requirements}
    artifacts = tuple(
        item.model_copy(update={"required": item.artifact_id in required_artifacts})
        for item in manifest.artifacts
    )
    provisional = manifest.model_copy(
        update={
            "workflow_profile_id": profile.profile_id,
            "workflow_profile_version": profile.profile_version,
            "workflow_conformance_status": "not_evaluated",
            "package_status": "generated_pending_inspection",
            "artifacts": artifacts,
        }
    )
    write_visual_review_manifest(manifest_path, provisional)
    _write_review_report(manifest_path.parent / "review-report.md", provisional)
    report = _evaluate_visual_conformance(
        manifest=provisional,
        review_dir=manifest_path.parent,
        features=effective_features,
        deviations=deviations,
        evaluated_on=evaluated_on,
    )
    status: PackageStatus = (
        "generation_failed"
        if report.disposition is ConformanceDisposition.NONCONFORMANT
        else "generated_pending_inspection"
    )
    updated = provisional.model_copy(
        update={
            "workflow_conformance_status": report.disposition.value,
            "package_status": status,
        }
    )
    write_visual_review_manifest(manifest_path, updated)
    _write_review_report(manifest_path.parent / "review-report.md", updated)
    _write_conformance_report(manifest_path.parent / "conformance.json", report)
    return report


def build_visual_review_workflow_profile(
    *,
    manifest: VisualReviewManifest,
    features: ReviewFeatures,
) -> WorkflowProfile:
    """Build the applicable baseline independently of generated file success."""

    requirements: list[WorkflowRequirement] = [
        _visual_requirement(
            requirement_id="visual.review.manifest",
            artifact_id="package:manifest",
            constraint=ArtifactConstraint(
                media_type="application/json",
                board_sha256=manifest.board_sha256,
                stage=manifest.stage,
            ),
            rationale="Machine-readable package identity and artifact state authority.",
        ),
        _visual_requirement(
            requirement_id="visual.review.report",
            artifact_id="package:report",
            constraint=ArtifactConstraint(
                media_type="text/markdown",
                board_sha256=manifest.board_sha256,
                stage=manifest.stage,
            ),
            rationale="Human-readable review inventory and retained findings.",
        ),
    ]
    expected_artifacts = {"package:manifest", "package:report"}
    for _category, name, layers, side, mirrored in _TWO_D_PROFILES:
        if not _profile_required(name, features):
            continue
        for extension, media_type in (("svg", "image/svg+xml"), ("png", "image/png")):
            artifact_id = f"2d:{name}:{extension}"
            constraint = ArtifactConstraint(
                media_type=media_type,
                side=side,
                mirrored=mirrored,
                population="not_applicable",
                layers_exact=layers,
                minimum_long_edge_px=(
                    manifest.render_profile.minimum_full_board_long_edge_px
                    if extension == "png"
                    else None
                ),
                minimum_pixels_per_mm=(
                    manifest.render_profile.overview_pixels_per_mm
                    if extension == "png"
                    else None
                ),
                board_sha256=manifest.board_sha256,
                stage=manifest.stage,
            )
            requirements.append(
                _visual_requirement(
                    requirement_id=_visual_requirement_id(artifact_id),
                    artifact_id=artifact_id,
                    constraint=constraint,
                    rationale=f"Canonical {name} {extension.upper()} review view.",
                )
            )
            expected_artifacts.add(artifact_id)
    for population in ("populated", "bare"):
        for camera, _args in _CAMERAS:
            artifact_id = f"3d:{population}:{camera}"
            requirements.append(
                _visual_requirement(
                    requirement_id=_visual_requirement_id(artifact_id),
                    artifact_id=artifact_id,
                    constraint=ArtifactConstraint(
                        media_type="image/png",
                        side="back" if camera in {"bottom", "rear-low"} else "front",
                        camera=camera,
                        population=population,
                        minimum_long_edge_px=manifest.render_profile.three_d_long_edge_px,
                        board_sha256=manifest.board_sha256,
                        stage=manifest.stage,
                    ),
                    rationale=f"Canonical {population} {camera} 3D inspection camera.",
                )
            )
            expected_artifacts.add(artifact_id)
    for region in features.detail_regions:
        artifact_id = f"detail:{region.side}:{region.region_id}"
        requirements.append(
            _visual_requirement(
                requirement_id=_visual_requirement_id(artifact_id),
                artifact_id=artifact_id,
                constraint=ArtifactConstraint(
                    media_type="image/png",
                    side=region.side,
                    population="not_applicable",
                    minimum_pixels_per_mm=manifest.render_profile.detail_pixels_per_mm,
                    board_sha256=manifest.board_sha256,
                    stage=manifest.stage,
                ),
                rationale=region.reason,
            )
        )
        expected_artifacts.add(artifact_id)
    for class_name in features.declared_classes:
        artifact_id = f"electrical:{class_name}"
        requirements.append(
            _visual_requirement(
                requirement_id=_visual_requirement_id(artifact_id),
                artifact_id=artifact_id,
                constraint=ArtifactConstraint(
                    media_type="image/png",
                    side="both",
                    board_sha256=manifest.board_sha256,
                    stage=manifest.stage,
                ),
                rationale=f"Declared {class_name} electrical-class overlay.",
            )
        )
        expected_artifacts.add(artifact_id)
    for index, _source in enumerate(features.diagnostic_images, start=1):
        artifact_id = f"diagnostic:{index:02d}"
        requirements.append(
            _visual_requirement(
                requirement_id=_visual_requirement_id(artifact_id),
                artifact_id=artifact_id,
                constraint=ArtifactConstraint(
                    media_type="image/png",
                    board_sha256=manifest.board_sha256,
                    stage=manifest.stage,
                ),
                rationale="Declared diagnostic evidence retained with the package.",
            )
        )
        expected_artifacts.add(artifact_id)
    for declaration in features.diagnostic_views:
        if declaration.applicability == "not_applicable":
            continue
        artifact_id = (
            f"diagnostic:{declaration.kind}:{declaration.view_id}"
        )
        requirements.append(
            _visual_requirement(
                requirement_id=_visual_requirement_id(artifact_id),
                artifact_id=artifact_id,
                constraint=ArtifactConstraint(
                    media_type="image/png",
                    board_sha256=manifest.board_sha256,
                    stage=manifest.stage,
                ),
                rationale=declaration.rationale,
            )
        )
        expected_artifacts.add(artifact_id)
    if features.predecessor_board is not None:
        for side, _layers, _mirrored in _COMPARISON_SIDES:
            for suffix, media_type in (
                ("previous-svg", "image/svg+xml"),
                ("previous-png", "image/png"),
                ("side-by-side", "image/png"),
            ):
                artifact_id = f"comparison:{side}:{suffix}"
                requirements.append(
                    _visual_requirement(
                        requirement_id=_visual_requirement_id(artifact_id),
                        artifact_id=artifact_id,
                        constraint=ArtifactConstraint(
                            media_type=media_type,
                            side=side,
                            board_sha256=manifest.board_sha256,
                            stage=manifest.stage,
                        ),
                        rationale=f"Predecessor/current {side} comparison evidence.",
                    )
                )
                expected_artifacts.add(artifact_id)
    # Tile identities depend on board dimensions.  They are still mandatory once
    # the standard renderer determines that tiling is needed; no custom camera or
    # similarly named crop may satisfy them.
    for artifact in manifest.artifacts:
        if not artifact.required or not artifact.artifact_id.startswith("detail:tile:"):
            continue
        requirements.append(
            _visual_requirement(
                requirement_id=_visual_requirement_id(artifact.artifact_id),
                artifact_id=artifact.artifact_id,
                constraint=_constraint_from_artifact(manifest, artifact),
                rationale="High-resolution full-board tile required by the render profile.",
            )
        )
        expected_artifacts.add(artifact.artifact_id)
    return WorkflowProfile(
        profile_id="pcbsmith.visual-review.standard",
        profile_version=1,
        requirements=tuple(requirements),
    )


def _evaluate_visual_conformance(
    *,
    manifest: VisualReviewManifest,
    review_dir: Path,
    features: ReviewFeatures,
    deviations: tuple[WorkflowDeviation, ...],
    evaluated_on: date,
) -> WorkflowConformanceReport:
    profile = build_visual_review_workflow_profile(manifest=manifest, features=features)
    expected = {item.expected_artifact_id for item in profile.requirements}
    declared = {item.artifact_id for item in deviations if item.artifact_id is not None}
    additions = tuple(
        WorkflowDeviation(
            deviation_id=f"auto:d0:{artifact.artifact_id}",
            level=DeviationLevel.ADDITION,
            artifact_id=artifact.artifact_id,
            reason="Standard generator emitted non-applicable or supplemental evidence.",
            consequence="Baseline coverage is unchanged.",
            residual_risk="Supplemental evidence does not satisfy another requirement.",
        )
        for artifact in manifest.artifacts
        if artifact.artifact_id not in expected and artifact.artifact_id not in declared
    )
    return evaluate_workflow_conformance(
        profile=profile,
        observations=_visual_observations(manifest, review_dir),
        deviations=(*deviations, *additions),
        evaluated_on=evaluated_on,
    )


def _visual_observations(
    manifest: VisualReviewManifest,
    review_dir: Path,
) -> tuple[WorkflowArtifactObservation, ...]:
    board = Path(manifest.board_file)
    board_integrity = board.is_file() and hashlib.sha256(board.read_bytes()).hexdigest() == (
        manifest.board_sha256
    )
    observations = [
        _package_observation(
            artifact_id="package:manifest",
            path=review_dir / "manifest.json",
            media_type="application/json",
            manifest=manifest,
            board_integrity=board_integrity,
        ),
        _package_observation(
            artifact_id="package:report",
            path=review_dir / "review-report.md",
            media_type="text/markdown",
            manifest=manifest,
            board_integrity=board_integrity,
        ),
    ]
    root = review_dir.resolve()
    for artifact in manifest.artifacts:
        finding_list: list[str] = []
        try:
            path = (root / artifact.relative_path).resolve()
            path.relative_to(root)
            inside = True
        except ValueError:
            path = root
            inside = False
            finding_list.append("Artifact path escapes the review package.")
        exists = inside and path.is_file()
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if exists else None
        integrity = (
            board_integrity
            and inside
            and ((artifact.state == "generated") == exists)
            and (not exists or artifact.sha256 == digest)
        )
        if not board_integrity:
            finding_list.append("Saved board hash no longer matches the manifest.")
        if exists and artifact.sha256 != digest:
            finding_list.append("Artifact SHA-256 no longer matches the manifest.")
        observations.append(
            WorkflowArtifactObservation(
                artifact_id=artifact.artifact_id,
                generated=exists,
                media_type=artifact.media_type,
                side=artifact.side,
                mirrored=artifact.mirrored,
                camera=artifact.camera,
                population=_artifact_population(artifact.artifact_id),
                layers=artifact.layers,
                pixels_per_mm=artifact.pixels_per_mm,
                pixel_size=artifact.pixel_size,
                board_sha256=manifest.board_sha256,
                stage=manifest.stage,
                content_sha256=digest,
                integrity_valid=integrity,
                findings=tuple(finding_list),
            )
        )
    return tuple(observations)


def _package_observation(
    *,
    artifact_id: str,
    path: Path,
    media_type: str,
    manifest: VisualReviewManifest,
    board_integrity: bool,
) -> WorkflowArtifactObservation:
    exists = path.is_file()
    return WorkflowArtifactObservation(
        artifact_id=artifact_id,
        generated=exists,
        media_type=media_type,
        board_sha256=manifest.board_sha256,
        stage=manifest.stage,
        content_sha256=hashlib.sha256(path.read_bytes()).hexdigest() if exists else None,
        integrity_valid=board_integrity,
        findings=() if board_integrity else ("Saved board hash no longer matches the manifest.",),
    )


def _constraint_from_artifact(
    manifest: VisualReviewManifest,
    artifact: ReviewArtifact,
) -> ArtifactConstraint:
    return ArtifactConstraint(
        media_type=artifact.media_type,
        side=artifact.side,
        mirrored=artifact.mirrored,
        camera=artifact.camera,
        population=_artifact_population(artifact.artifact_id),
        layers_exact=artifact.layers,
        minimum_pixels_per_mm=artifact.pixels_per_mm,
        minimum_long_edge_px=(
            None if artifact.pixel_size is None else max(artifact.pixel_size)
        ),
        board_sha256=manifest.board_sha256,
        stage=manifest.stage,
    )


def _visual_requirement(
    *,
    requirement_id: str,
    artifact_id: str,
    constraint: ArtifactConstraint,
    rationale: str,
) -> WorkflowRequirement:
    return WorkflowRequirement(
        requirement_id=requirement_id,
        expected_artifact_id=artifact_id,
        constraint=constraint,
        rationale=rationale,
    )


def _visual_requirement_id(artifact_id: str) -> str:
    return "visual." + artifact_id.replace(":", ".")


def _artifact_population(
    artifact_id: str,
) -> Literal["populated", "bare", "not_applicable"]:
    if artifact_id.startswith("3d:populated:"):
        return "populated"
    if artifact_id.startswith("3d:bare:"):
        return "bare"
    return "not_applicable"


def _write_conformance_report(path: Path, report: WorkflowConformanceReport) -> None:
    path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def rasterize_svg_with_resvg(
    source: Path,
    destination: Path,
    width_px: int,
    height_px: int,
    view_box: tuple[float, float, float, float] | None,
) -> None:
    try:
        import resvg_py
    except ImportError as exc:
        raise RuntimeError("Install the review extra: pip install 'pcbsmith[review]'.") from exc
    root = ET.fromstring(source.read_text(encoding="utf-8"))
    root.set("width", str(width_px))
    root.set("height", str(height_px))
    if view_box is not None:
        root.set("viewBox", " ".join(_number(value) for value in view_box))
    rendered = resvg_py.svg_to_bytes(svg_string=ET.tostring(root, encoding="unicode"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(bytes(rendered))


def _export_svg(
    *,
    install: KiCadInstall,
    runner: ProcessRunner,
    board: Path,
    output: Path,
    layers: tuple[str, ...],
    mirrored: bool,
) -> str | None:
    output.parent.mkdir(parents=True, exist_ok=True)
    command: list[str | Path] = [
        install.path,
        "pcb",
        "export",
        "svg",
        "--output",
        output,
        "--layers",
        ",".join(layers),
        "--mode-single",
        "--page-size-mode",
        "2",
        "--exclude-drawing-sheet",
    ]
    if mirrored:
        command.append("--mirror")
    command.append(board)
    result = runner(command)
    if result.returncode == 0 and output.exists():
        return None
    detail = result.stderr.strip() or result.stdout.strip() or "no output"
    return f"KiCad SVG export failed for {output.name}: {detail}"


def _render_three_d(
    *,
    board: Path,
    board_root: SList,
    model_preflight: ModelPreflightReport,
    review_dir: Path,
    install: KiCadInstall,
    runner: ProcessRunner,
    profile: RenderProfile,
    findings: list[str],
    progress: ProgressReporter,
) -> tuple[ReviewArtifact, ...]:
    artifacts: list[ReviewArtifact] = []
    render_input = review_dir / ".render-input"
    populated_board = render_input / f"{board.stem}-resolved.kicad_pcb"
    resolved_paths = {
        item.raw_path: item.resolved_path
        for item in model_preflight.models
        if item.status == "resolved" and item.resolved_path is not None
    }
    resolved_root = _with_resolved_models(board_root, resolved_paths)
    populated_board.parent.mkdir(parents=True, exist_ok=True)
    populated_board.write_text(serialize_sexpr(resolved_root) + "\n", encoding="utf-8")
    bare_board = render_input / f"{board.stem}-bare.kicad_pcb"
    bare_board.parent.mkdir(parents=True, exist_ok=True)
    bare_board.write_text(serialize_sexpr(_without_models(resolved_root)) + "\n", encoding="utf-8")
    for population, source_board in (("populated", populated_board), ("bare", bare_board)):
        for camera, camera_args in _CAMERAS:
            progress(f"3D {population}/{camera}: rendering")
            width, height = _three_d_pixels(camera, profile.three_d_long_edge_px)
            output = review_dir / "3d" / population / f"{camera}.png"
            output.parent.mkdir(parents=True, exist_ok=True)
            result = runner(
                (
                    install.path,
                    "pcb",
                    "render",
                    "--output",
                    output,
                    "--width",
                    str(width),
                    "--height",
                    str(height),
                    "--quality",
                    "high",
                    "--background",
                    "opaque",
                    *camera_args,
                    source_board,
                )
            )
            if result.returncode != 0 or not output.exists():
                detail = result.stderr.strip() or result.stdout.strip() or "no output"
                findings.append(f"3D {population}/{camera} render failed: {detail}")
            artifacts.append(
                _artifact_from_file(
                    review_dir=review_dir,
                    path=output,
                    artifact_id=f"3d:{population}:{camera}",
                    category=f"3d/{population}",
                    media_type="image/png",
                    required=True,
                    side=("back" if camera in {"bottom", "rear-low"} else "front"),
                    camera=camera,
                    pixel_size=(width, height),
                )
            )
            progress(f"3D {population}/{camera}: {'generated' if output.exists() else 'missing'}")
    return tuple(artifacts)


def _render_tiles(
    *,
    svg_path: Path,
    review_dir: Path,
    side: str,
    width_mm: float,
    height_mm: float,
    pixels_per_mm: float,
    mirrored: bool,
    profile: RenderProfile,
    rasterizer: Rasterizer,
    findings: list[str],
) -> tuple[ReviewArtifact, ...]:
    tile_mm = profile.tile_max_edge_px / pixels_per_mm
    if width_mm <= tile_mm and height_mm <= tile_mm:
        return ()
    step = tile_mm - profile.tile_overlap_mm
    columns = max(1, math.ceil((width_mm - profile.tile_overlap_mm) / step))
    rows = max(1, math.ceil((height_mm - profile.tile_overlap_mm) / step))
    artifacts: list[ReviewArtifact] = []
    for row in range(rows):
        for column in range(columns):
            x = min(column * step, max(0.0, width_mm - tile_mm))
            y = min(row * step, max(0.0, height_mm - tile_mm))
            width = min(tile_mm, width_mm - x)
            height = min(tile_mm, height_mm - y)
            label = f"{chr(65 + row)}{column + 1}"
            path = review_dir / "details" / "tiles" / side / f"{label}.png"
            try:
                rasterizer(
                    svg_path,
                    path,
                    max(1, round(width * pixels_per_mm)),
                    max(1, round(height * pixels_per_mm)),
                    (x, y, width, height),
                )
            except Exception as exc:
                findings.append(f"Tile {side}/{label} failed: {exc}")
            artifacts.append(
                _artifact_from_file(
                    review_dir=review_dir,
                    path=path,
                    artifact_id=f"detail:tile:{side}:{label}",
                    category=f"details/tiles/{side}",
                    media_type="image/png",
                    required=True,
                    side="front" if side == "front" else "back",
                    mirrored=mirrored,
                    pixels_per_mm=pixels_per_mm,
                    pixel_size=(
                        max(1, round(width * pixels_per_mm)),
                        max(1, round(height * pixels_per_mm)),
                    ),
                    bounds_mm=(x, y, width, height),
                )
            )
    return tuple(artifacts)


def _render_details(
    *,
    features: ReviewFeatures,
    base_svg_by_side: dict[str, Path],
    review_dir: Path,
    profile: RenderProfile,
    rasterizer: Rasterizer,
    findings: list[str],
) -> tuple[ReviewArtifact, ...]:
    artifacts: list[ReviewArtifact] = []
    for region in features.detail_regions:
        source = base_svg_by_side.get(region.side)
        x, y, width, height = region.bounds_mm
        path = review_dir / "details" / region.side / f"{region.region_id}.png"
        if source is not None and width > 0 and height > 0:
            try:
                rasterizer(
                    source,
                    path,
                    max(1, round(width * profile.detail_pixels_per_mm)),
                    max(1, round(height * profile.detail_pixels_per_mm)),
                    region.bounds_mm,
                )
            except Exception as exc:
                findings.append(f"Detail {region.region_id} failed: {exc}")
        artifacts.append(
            _artifact_from_file(
                review_dir=review_dir,
                path=path,
                artifact_id=f"detail:{region.side}:{region.region_id}",
                category=f"details/{region.side}",
                media_type="image/png",
                required=True,
                side=region.side,
                pixels_per_mm=profile.detail_pixels_per_mm,
                pixel_size=(
                    max(1, round(width * profile.detail_pixels_per_mm)),
                    max(1, round(height * profile.detail_pixels_per_mm)),
                ),
                bounds_mm=region.bounds_mm,
                findings=(region.reason,),
            )
        )
    return tuple(artifacts)


def _collect_declared_overlays(
    features: ReviewFeatures,
    review_dir: Path,
) -> tuple[ReviewArtifact, ...]:
    artifacts: list[ReviewArtifact] = []
    for class_name in sorted(features.declared_classes):
        source_text = features.class_overlays.get(class_name)
        destination = review_dir / "electrical" / f"{class_name}.png"
        if source_text is not None and Path(source_text).is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_text, destination)
        artifacts.append(
            _artifact_from_file(
                review_dir=review_dir,
                path=destination,
                artifact_id=f"electrical:{class_name}",
                category="electrical",
                media_type="image/png",
                required=True,
                side="both",
                findings=(f"Declared electrical class: {class_name}",),
            )
        )
    return tuple(artifacts)


def _render_comparisons(
    *,
    predecessor: Path,
    board: Path,
    review_dir: Path,
    current_svg_by_side: dict[str, Path],
    install: KiCadInstall,
    runner: ProcessRunner,
    profile: RenderProfile,
    rasterizer: Rasterizer,
    findings: list[str],
) -> tuple[ReviewArtifact, ...]:
    artifacts: list[ReviewArtifact] = []
    if not predecessor.is_file():
        findings.append(f"Declared predecessor board does not exist: {predecessor}")
    for side, layers, mirrored in _COMPARISON_SIDES:
        previous_svg = review_dir / "comparisons" / f"previous-{side}.svg"
        previous_png = previous_svg.with_suffix(".png")
        comparison_png = review_dir / "comparisons" / f"previous-current-{side}.png"
        if predecessor.is_file():
            export_finding = _export_svg(
                install=install,
                runner=runner,
                board=predecessor,
                output=previous_svg,
                layers=layers,
                mirrored=mirrored,
            )
            if export_finding is not None:
                findings.append(export_finding)
        if previous_svg.is_file():
            width_mm, height_mm = _svg_size_mm(previous_svg)
            width_px, height_px, ppm = _full_board_pixels(width_mm, height_mm, profile)
            try:
                rasterizer(previous_svg, previous_png, width_px, height_px, None)
            except Exception as exc:
                findings.append(f"Previous {side} rasterization failed: {exc}")
            artifacts.extend(
                (
                    _artifact_from_file(
                        review_dir=review_dir,
                        path=previous_svg,
                        artifact_id=f"comparison:{side}:previous-svg",
                        category="comparisons",
                        media_type="image/svg+xml",
                        required=True,
                        layers=layers,
                        side=side,
                        mirrored=mirrored,
                    ),
                    _artifact_from_file(
                        review_dir=review_dir,
                        path=previous_png,
                        artifact_id=f"comparison:{side}:previous-png",
                        category="comparisons",
                        media_type="image/png",
                        required=True,
                        layers=layers,
                        side=side,
                        mirrored=mirrored,
                        pixels_per_mm=ppm,
                        pixel_size=(width_px, height_px),
                    ),
                )
            )
        else:
            artifacts.extend(
                _missing_comparison_sources(review_dir=review_dir, side=side, layers=layers)
            )
        current_svg = current_svg_by_side.get(side)
        current_png = None if current_svg is None else current_svg.with_suffix(".png")
        if previous_png.is_file() and current_png is not None and current_png.is_file():
            try:
                _write_side_by_side_comparison(previous_png, current_png, comparison_png)
            except Exception as exc:
                findings.append(f"Previous/current {side} comparison failed: {exc}")
        artifacts.append(
            _artifact_from_file(
                review_dir=review_dir,
                path=comparison_png,
                artifact_id=f"comparison:{side}:side-by-side",
                category="comparisons",
                media_type="image/png",
                required=True,
                side=side,
                findings=(
                    f"Left: {predecessor.name}; right: {board.name}. "
                    "This is a visual comparison, not an exact registered geometry diff.",
                ),
            )
        )
    return tuple(artifacts)


def _write_side_by_side_comparison(
    previous: Path,
    current: Path,
    destination: Path,
) -> None:
    from PIL import Image, ImageOps

    with Image.open(previous) as previous_image, Image.open(current) as current_image:
        height = max(previous_image.height, current_image.height)
        previous_fitted = ImageOps.contain(previous_image.convert("RGB"), (4096, height))
        current_fitted = ImageOps.contain(current_image.convert("RGB"), (4096, height))
        canvas = Image.new(
            "RGB",
            (previous_fitted.width + current_fitted.width, height),
            (255, 255, 255),
        )
        canvas.paste(previous_fitted, (0, (height - previous_fitted.height) // 2))
        canvas.paste(
            current_fitted,
            (previous_fitted.width, (height - current_fitted.height) // 2),
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(destination)


def _missing_comparison_sources(
    *,
    review_dir: Path,
    side: Literal["front", "back"],
    layers: tuple[str, ...],
) -> tuple[ReviewArtifact, ...]:
    return (
        ReviewArtifact(
            artifact_id=f"comparison:{side}:previous-svg",
            category="comparisons",
            relative_path=f"comparisons/previous-{side}.svg",
            media_type="image/svg+xml",
            required=True,
            state="missing",
            layers=layers,
            side=side,
            findings=("Declared predecessor vector export is missing.",),
        ),
        ReviewArtifact(
            artifact_id=f"comparison:{side}:previous-png",
            category="comparisons",
            relative_path=f"comparisons/previous-{side}.png",
            media_type="image/png",
            required=True,
            state="missing",
            layers=layers,
            side=side,
            findings=("Declared predecessor raster is missing.",),
        ),
    )


def _collect_diagnostics(
    features: ReviewFeatures,
    review_dir: Path,
) -> tuple[ReviewArtifact, ...]:
    artifacts: list[ReviewArtifact] = []
    for index, source_text in enumerate(features.diagnostic_images, start=1):
        source = Path(source_text)
        destination = review_dir / "diagnostics" / f"{index:02d}-{source.name}"
        if source.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        artifacts.append(
            _artifact_from_file(
                review_dir=review_dir,
                path=destination,
                artifact_id=f"diagnostic:{index:02d}",
                category="diagnostics",
                media_type="image/png",
                required=True,
                findings=(f"Diagnostic source: {source}",),
            )
        )
    for declaration in features.diagnostic_views:
        if declaration.applicability == "not_applicable":
            continue
        artifact_id = f"diagnostic:{declaration.kind}:{declaration.view_id}"
        destination = (
            review_dir
            / "diagnostics"
            / declaration.kind
            / f"{declaration.view_id}.png"
        )
        findings = [
            f"Applicability: {declaration.applicability}.",
            f"Rationale: {declaration.rationale}",
            f"Triggers: {', '.join(declaration.trigger_ids)}",
        ]
        if declaration.authority_sha256 is not None:
            findings.append(
                f"Applicability authority: {declaration.authority_sha256}"
            )
        if declaration.source_image is not None:
            source = Path(declaration.source_image)
            if source.is_file():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            findings.append(f"Diagnostic source: {source}")
        artifacts.append(
            _artifact_from_file(
                review_dir=review_dir,
                path=destination,
                artifact_id=artifact_id,
                category=f"diagnostics/{declaration.kind}",
                media_type="image/png",
                required=True,
                findings=tuple(findings),
            )
        )
    return tuple(artifacts)


def _missing_3d_artifacts(review_dir: Path) -> tuple[ReviewArtifact, ...]:
    return tuple(
        ReviewArtifact(
            artifact_id=f"3d:{population}:{camera}",
            category=f"3d/{population}",
            relative_path=f"3d/{population}/{camera}.png",
            media_type="image/png",
            required=True,
            state="missing",
            side="back" if camera in {"bottom", "rear-low"} else "front",
            camera=camera,
            findings=("Required 3D model preflight failed.",),
        )
        for population in ("populated", "bare")
        for camera, _args in _CAMERAS
    )


def _artifact_from_file(
    *,
    review_dir: Path,
    path: Path,
    artifact_id: str,
    category: str,
    media_type: Literal["image/png", "image/svg+xml"],
    required: bool,
    layers: tuple[str, ...] = (),
    side: Literal["front", "back", "both", "none"] = "none",
    mirrored: bool = False,
    camera: str | None = None,
    pixels_per_mm: float | None = None,
    pixel_size: tuple[int, int] | None = None,
    bounds_mm: tuple[float, float, float, float] | None = None,
    findings: tuple[str, ...] = (),
) -> ReviewArtifact:
    exists = path.is_file()
    return ReviewArtifact(
        artifact_id=artifact_id,
        category=category,
        relative_path=path.relative_to(review_dir).as_posix(),
        media_type=media_type,
        required=required,
        state="generated" if exists else "missing",
        layers=layers,
        side=side,
        mirrored=mirrored,
        camera=camera,
        pixels_per_mm=pixels_per_mm,
        pixel_size=pixel_size,
        bounds_mm=bounds_mm,
        sha256=hashlib.sha256(path.read_bytes()).hexdigest() if exists else None,
        findings=findings,
    )


def _profile_required(name: str, features: ReviewFeatures) -> bool:
    if name == "back-assembly":
        return features.has_bottom_components
    if name == "courtyards-keepouts":
        return features.has_keepouts or features.has_cutouts
    if name == "holes-vias":
        return features.has_holes or features.has_vias or features.has_cutouts
    return True


def _routing_artifact_findings(
    stage: ReviewStage,
    evidence: SavedBoardRoutingEvidence,
) -> tuple[str, ...]:
    scope = (
        "This is placement-stage copper context, not routing-completion evidence."
        if stage == "placement"
        else "This final-stage view remains subordinate to connectivity and DRC."
    )
    return (
        scope,
        (
            f"Saved board: {evidence.segment_count} segments, "
            f"{evidence.via_count} vias, state={evidence.state.value}."
        ),
    )


def _add_svg_watermark(path: Path, label: str) -> None:
    """Add an unmistakable stage warning before rasterization."""

    text = path.read_text(encoding="utf-8")
    closing = text.rfind("</svg>")
    if closing < 0:
        raise ValueError(f"SVG lacks a closing element: {path}")
    escaped = (
        label.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )
    overlay = (
        '<g id="pcbsmith-routing-stage-watermark" pointer-events="none">'
        '<rect x="20%" y="2%" width="60%" height="9%" rx="4" '
        'fill="#fff4cc" fill-opacity="0.94" stroke="#b00020" stroke-width="1"/>'
        '<text x="50%" y="8%" text-anchor="middle" '
        'font-family="sans-serif" font-size="18" font-weight="700" '
        f'fill="#b00020">{escaped}</text></g>'
    )
    path.write_text(text[:closing] + overlay + text[closing:], encoding="utf-8")


def _augment_features_from_board(features: ReviewFeatures, root: SList) -> ReviewFeatures:
    """Strengthen caller declarations with objective saved-board facts."""

    direct = tuple(child for child in root if isinstance(child, list) and child)
    footprints = tuple(
        child for child in direct if _atom(child[0]) in {"footprint", "module"}
    )
    has_bottom_components = any(
        any(
            isinstance(item, list)
            and item
            and _atom(item[0]) == "layer"
            and len(item) > 1
            and _atom(item[1]) == "B.Cu"
            for item in footprint
        )
        for footprint in footprints
    )
    has_holes = any(
        isinstance(item, list)
        and len(item) > 2
        and _atom(item[0]) == "pad"
        and _atom(item[2]) in {"thru_hole", "np_thru_hole"}
        for footprint in footprints
        for item in footprint
    )
    has_vias = any(_atom(child[0]) == "via" for child in direct)
    has_zones = any(_atom(child[0]) == "zone" for child in direct)
    has_keepouts = any(
        isinstance(item, list) and item and _atom(item[0]) == "keepout"
        for child in direct
        if _atom(child[0]) == "zone"
        for item in child
    )
    return features.model_copy(
        update={
            "has_bottom_components": (
                features.has_bottom_components or has_bottom_components
            ),
            "has_holes": features.has_holes or has_holes,
            "has_vias": features.has_vias or has_vias,
            "has_zones": features.has_zones or has_zones,
            "has_keepouts": features.has_keepouts or has_keepouts,
        }
    )


def _svg_size_mm(path: Path) -> tuple[float, float]:
    root = ET.fromstring(path.read_text(encoding="utf-8"))
    view_box = tuple(float(item) for item in root.attrib["viewBox"].replace(",", " ").split())
    if len(view_box) != 4 or view_box[2] <= 0 or view_box[3] <= 0:
        raise ValueError(f"SVG has an invalid viewBox: {path}")
    return view_box[2], view_box[3]


def _full_board_pixels(
    width_mm: float,
    height_mm: float,
    profile: RenderProfile,
) -> tuple[int, int, float]:
    long_mm = max(width_mm, height_mm)
    pixels_per_mm = max(
        profile.overview_pixels_per_mm,
        profile.minimum_full_board_long_edge_px / long_mm,
    )
    return (
        max(1, round(width_mm * pixels_per_mm)),
        max(1, round(height_mm * pixels_per_mm)),
        pixels_per_mm,
    )


def _three_d_pixels(camera: str, long_edge: int) -> tuple[int, int]:
    if camera in {"top", "bottom"}:
        return (long_edge, long_edge)
    return (long_edge, round(long_edge * 9 / 16))


def _kicad_version(install: KiCadInstall, runner: ProcessRunner) -> str:
    result = runner((install.path, "version"))
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _without_models(node: SExpr) -> SExpr:
    if not isinstance(node, list):
        return node
    return [
        _without_models(child)
        for child in node
        if not (isinstance(child, list) and child and _atom(child[0]) == "model")
    ]


def _with_resolved_models(node: SExpr, resolved_paths: dict[str, str]) -> SExpr:
    if not isinstance(node, list):
        return node
    copied = [_with_resolved_models(child, resolved_paths) for child in node]
    if copied and _atom(copied[0]) == "model" and len(copied) > 1:
        raw_path = _atom(copied[1])
        resolved = resolved_paths.get(raw_path)
        if resolved is not None:
            copied[1] = QuotedString(resolved.replace("\\", "/"))
    return copied


def _copper_hash(root: SList) -> str:
    carriers: list[str] = []
    for child in root:
        if not isinstance(child, list) or not child:
            continue
        head = _atom(child[0])
        if head in {"segment", "via", "zone"}:
            carriers.append(serialize_sexpr(child))
        elif head in {"footprint", "module"}:
            footprint_parts = [
                item
                for item in child
                if (
                    not isinstance(item, list)
                    or not item
                    or _atom(item[0]) in {"at", "layer", "pad"}
                )
            ]
            carriers.append(serialize_sexpr(footprint_parts))
    canonical = "\n".join(sorted(carriers)).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _write_review_report(path: Path, manifest: VisualReviewManifest) -> None:
    lines = [
        f"# Visual review: {Path(manifest.board_file).name}",
        "",
        f"Package status: **{manifest.package_status}**",
        "",
        f"Workflow conformance: **{manifest.workflow_conformance_status}**",
        "",
        (
            "Routing evidence: **legacy manifest without saved-board routing "
            "inventory**"
            if manifest.routing_evidence is None
            else (
                f"Routing evidence: **{manifest.routing_evidence.state.value}** — "
                f"{manifest.routing_evidence.segment_count} segments, "
                f"{manifest.routing_evidence.via_count} vias, "
                f"{manifest.routing_evidence.copper_carrier_net_count}/"
                f"{manifest.routing_evidence.routable_net_count} routable nets "
                "with a copper carrier."
            )
        ),
        "",
        "Rendering creates evidence; it does not perform visual acceptance. Required",
        "artifacts remain unaccepted until an inspection record names its reviewer or",
        "inspection mechanism.",
        "",
        "| Artifact | Generated | Inspection | Required |",
        "| --- | --- | --- | --- |",
    ]
    for artifact in manifest.artifacts:
        lines.append(
            f"| `{artifact.artifact_id}` | {artifact.state} | {artifact.inspection} "
            f"| {'yes' if artifact.required else 'no'} |"
        )
    if manifest.findings:
        lines.extend(("", "## Findings", ""))
        lines.extend(f"- {finding}" for finding in manifest.findings)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _atom(node: SExpr) -> str:
    if isinstance(node, QuotedString):
        return node.value
    if isinstance(node, str):
        return node
    raise ValueError("Expected an atom.")


def _number(value: float) -> str:
    return f"{value:.6f}".rstrip("0").rstrip(".")
