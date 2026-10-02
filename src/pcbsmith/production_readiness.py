"""Bind the existing predesign/readiness evaluators to saved production inputs.

This is an adapter to the production transaction owner, not a router or a new
acceptance algorithm. Evidence references remain declared engineering claims;
file presence and deterministic replay do not establish their physical truth.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.design_readiness import (
    DesignReadinessReport,
    DesignReadinessStage,
    VisualSubjectRequirement,
    evaluate_design_readiness,
    inspect_visual_subject_crop,
    require_design_readiness,
    review_visual_subjects,
    visual_model_state_from_preflight,
)
from pcbsmith.kicad.component_readiness import SelectedModelPolicy
from pcbsmith.kicad.library import QuotedString, parse_sexpr
from pcbsmith.kicad.model_preflight import (
    ModelInventoryAssessment,
    ModelPreflightReport,
    ModelResolution,
    preflight_board_models,
)
from pcbsmith.manufacturing_lineage import file_sha256, native_input_hashes, saved_assembly_rows
from pcbsmith.operations.file_transaction import atomic_write
from pcbsmith.predesign_contract import PredesignApprovalContractV2, require_predesign_approval
from pcbsmith.review.visual_package import VisualReviewManifest
from pcbsmith.routed_copper_graph_ir import fingerprint, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel

READINESS_PATH = "review/design-readiness.json"


def _relative_file(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if (
        path.is_absolute()
        or ".." in path.parts
        or ":" in relative
        or "\\" in relative
        or path.as_posix() in {"", "."}
    ):
        raise ValueError("readiness evidence path is not confined")
    candidate = root / path
    if not candidate.resolve().is_relative_to(root.resolve()) or not candidate.is_file():
        raise ValueError(f"readiness evidence file is missing or outside its root: {relative}")
    return candidate


class ReadinessEvidenceFile(SemanticIrModel):
    relative_path: str
    sha256: str

    @model_validator(mode="after")
    def valid_digest(self) -> Self:
        require_sha256(self.sha256, "readiness evidence sha256")
        return self


class PredesignReadinessBundle(SemanticIrModel):
    schema_id: Literal["pcbsmith-predesign-readiness-bundle-v1"] = (
        "pcbsmith-predesign-readiness-bundle-v1"
    )
    approval: PredesignApprovalContractV2
    readiness: DesignReadinessReport
    evidence_files: dict[str, ReadinessEvidenceFile]


def _evidence_ids(value: Any) -> set[str]:
    if isinstance(value, dict):
        found = {
            entry
            for key, entries in value.items()
            if key in {"evidence_ids", "source_ids"}
            for entry in entries
        }
        return found | set().union(*(_evidence_ids(item) for item in value.values()))
    if isinstance(value, list):
        return set().union(*(_evidence_ids(item) for item in value))
    return set()


def require_predesign_bundle(bundle: PredesignReadinessBundle, artifact_root: Path) -> None:
    require_predesign_approval(bundle.approval, artifact_root=artifact_root)
    report = bundle.readiness
    if report.stage is not DesignReadinessStage.PREDESIGN:
        raise ValueError("predesign boundary requires a predesign-stage report")
    require_design_readiness(report)
    require_readiness_evidence(report, bundle.evidence_files, artifact_root)
    _selected_model_binding(bundle, artifact_root)
    from pcbsmith.mandatory_review import require_mandatory_review

    require_mandatory_review(bundle, artifact_root)


def require_readiness_evidence(
    report: DesignReadinessReport,
    evidence_files: Mapping[str, ReadinessEvidenceFile],
    artifact_root: Path,
) -> None:
    """Check declared data and retained files without granting design approval.

    File identity does not verify a caller's interpretation of its contents.
    Preview and approval consumers share this validation.
    """
    if not report.component_reviews or not report.power_review.loads:
        raise ValueError("production readiness requires component alternatives and power loads")
    intents = tuple(item.intent.intent_id for item in report.component_reviews)
    if len(intents) != len(set(intents)):
        raise ValueError("production readiness has duplicate component intents")
    declared_support = {item.requirement_id for item in report.support_review.requirements}
    for review in report.component_reviews:
        selected = next(
            item for item in review.candidates if item.candidate_id == review.selected_candidate_id
        )
        if not set(selected.support_requirement_ids) <= declared_support:
            raise ValueError("selected component support obligations are omitted")
    missing = _evidence_ids(report.model_dump(mode="json")) - set(evidence_files)
    if missing:
        raise ValueError(
            "readiness evidence IDs lack retained files: " + ", ".join(sorted(missing))
        )
    for binding in evidence_files.values():
        path = _relative_file(artifact_root, binding.relative_path)
        if file_sha256(path) != binding.sha256:
            raise ValueError(f"readiness source evidence changed: {binding.relative_path}")

    from pcbsmith.circuit_patterns import require_bound_circuit_patterns

    require_bound_circuit_patterns(report, evidence_files, artifact_root)


def _selected_model_binding(
    bundle: PredesignReadinessBundle,
    artifact_root: Path,
) -> tuple[SelectedModelPolicy, ModelInventoryAssessment]:
    binding = bundle.evidence_files.get("component-readiness")
    if binding is None:
        raise ValueError("new production requires explicit component/model readiness")
    payload = json.loads(_relative_file(artifact_root, binding.relative_path).read_bytes())
    if payload.get("schema_id") != "pcbsmith-preplacement-component-readiness-v1":
        raise ValueError("Unsupported pre-placement component readiness evidence")
    selected = payload.get("selected_models", {})
    if selected.get("status") not in {"passed", "not_applicable"}:
        raise ValueError("Component readiness requires an explicit selected model policy")
    policy = SelectedModelPolicy.model_validate(selected["policy"])
    assessment = ModelInventoryAssessment.model_validate(selected["assessment"])
    if assessment.status != selected["status"] or assessment.applicability != policy.applicability:
        raise ValueError("Selected model assessment differs from policy")
    return policy, assessment


def prepare_selected_board_models(
    bundle: PredesignReadinessBundle,
    artifact_root: Path,
    board_file: Path,
) -> ModelPreflightReport:
    require_predesign_bundle(bundle, artifact_root)
    binding = _selected_model_binding(bundle, artifact_root)
    policy, early = binding
    actual = preflight_board_models(
        board_file,
        registry=policy.registry,
        requirements=policy.requirements,
        applicability=policy.applicability,
        applicability_rationale=policy.rationale,
    )
    if actual.status not in {"passed", "not_applicable"}:
        raise ValueError("Saved board violates the selected pre-placement model policy")
    if policy.applicability == "applicable":

        def identities(
            models: tuple[ModelResolution, ...],
        ) -> list[tuple[str, str, str, str | None, str]]:
            return sorted(
                (item.reference, item.footprint, item.raw_path, item.sha256, item.classification)
                for item in models
            )

        if identities(actual.models) != identities(early.models) or any(
            item.transform_alignment != "passed" for item in actual.models
        ):
            raise ValueError("Saved board model selection differs from pre-placement selection")
    return actual


def _require_selected_board_models(
    bundle: PredesignReadinessBundle,
    artifact_root: Path,
    board_file: Path,
    claimed: ModelPreflightReport,
) -> None:
    actual = prepare_selected_board_models(bundle, artifact_root, board_file)
    excluded = {"board_file", "board_sha256", "schema_id"}
    if actual.model_dump(exclude=excluded) != claimed.model_dump(exclude=excluded):
        raise ValueError("Model preflight claim differs from replay of the selected policy")


class PublicationReadinessRequest(SemanticIrModel):
    schema_id: Literal["pcbsmith-publication-readiness-request-v1"] = (
        "pcbsmith-publication-readiness-request-v1"
    )
    predesign: PredesignReadinessBundle
    native_inputs: dict[str, str]
    reference_intents: dict[str, str]
    visual_requirements: tuple[VisualSubjectRequirement, ...] = Field(min_length=1)
    visual_crops: dict[str, tuple[int, int, int, int]]
    model_preflight: ModelPreflightReport


def require_publication_request(
    request: PublicationReadinessRequest,
    *,
    board_file: Path,
    artifact_root: Path,
    project_id: str,
) -> None:
    require_predesign_bundle(request.predesign, artifact_root)
    if request.predesign.approval.project_id != project_id:
        raise ValueError("predesign approval belongs to another project")
    current_inputs = native_input_hashes(board_file)
    if request.native_inputs != current_inputs:
        raise ValueError("readiness request targets different or changed native inputs")
    for suffix in (".kicad_sch", ".kicad_pro"):
        if board_file.with_suffix(suffix).name not in current_inputs:
            raise ValueError("production publication requires the exact schematic and project")
    native = parse_sexpr(board_file.read_text(encoding="utf-8"))
    layers = next(
        (node for node in native if isinstance(node, list) and node and node[0] == "layers"), []
    )
    copper_layers = {
        node[1].value if isinstance(node[1], QuotedString) else str(node[1])
        for node in layers[1:]
        if isinstance(node, list) and len(node) > 2 and node[2] == "signal"
    }
    if copper_layers != {"F.Cu", "B.Cu"}:
        raise ValueError("supported production scope requires exactly two copper layers")
    references = {row.reference for row in saved_assembly_rows(board_file) if row.in_bom}
    if set(request.reference_intents) != references:
        raise ValueError("component intent coverage differs from populated board references")
    intents = {item.intent.intent_id for item in request.predesign.readiness.component_reviews}
    if set(request.reference_intents.values()) != intents:
        raise ValueError("component intents are absent or unused")
    brief_refs = {
        item.component_id for item in request.predesign.approval.amended_brief.draft.components
    }
    if not references <= brief_refs:
        raise ValueError("saved components are absent from the approved brief")
    requirements = request.visual_requirements
    if {item.subject_id for item in requirements} != set(request.visual_crops):
        raise ValueError("required visual subjects lack exact crops")
    if any(item.component_reference not in references for item in requirements):
        raise ValueError("visual requirement references an absent populated component")
    model = request.model_preflight
    if model.board_sha256 != file_sha256(board_file):
        raise ValueError("model preflight targets another board")
    if model.status not in {"passed", "not_applicable"}:
        raise ValueError("model preflight is unresolved or failed")
    verified_model_subjects = {
        item.component_reference
        for item in requirements
        if item.model_required and item.aligned_model_required
    }
    if not set(model.required_references) <= verified_model_subjects:
        raise ValueError("required models lack presence/alignment visual subjects")
    for resolution in model.models:
        if resolution.status == "resolved":
            if (
                not resolution.resolved_path
                or not Path(resolution.resolved_path).is_file()
                or file_sha256(Path(resolution.resolved_path)) != resolution.sha256
            ):
                raise ValueError("resolved model file changed or is unavailable")

    _require_selected_board_models(request.predesign, artifact_root, board_file, model)


class PublicationReadinessReceipt(SemanticIrModel):
    schema_id: Literal["pcbsmith-publication-readiness-receipt-v1"] = (
        "pcbsmith-publication-readiness-receipt-v1"
    )
    project_id: str
    board_sha256: str
    request: PublicationReadinessRequest
    report: DesignReadinessReport
    visual_artifact_sha256s: dict[str, str]
    receipt_fingerprint: str

    @model_validator(mode="after")
    def replay_bound(self) -> Self:
        require_sha256(self.board_sha256, "board_sha256")
        require_design_readiness(self.request.predesign.readiness)
        require_design_readiness(self.report)
        if self.report.stage is not DesignReadinessStage.SAVED_CANDIDATE:
            raise ValueError("publication requires saved-candidate readiness")
        source = self.request.predesign.readiness
        expected = evaluate_design_readiness(
            stage=DesignReadinessStage.SAVED_CANDIDATE,
            component_reviews=source.component_reviews,
            support_review=source.support_review,
            power_review=source.power_review,
            visual_review=self.report.visual_review,
        )
        if expected != self.report:
            raise ValueError("publication readiness changed its predesign authorities")
        if self.receipt_fingerprint != fingerprint(
            self.model_dump(mode="json", exclude={"receipt_fingerprint"})
        ):
            raise ValueError("publication readiness receipt fingerprint is stale")
        return self


def evaluate_saved_readiness(
    request: PublicationReadinessRequest,
    *,
    board_file: Path,
    artifact_root: Path,
    review_directory: Path,
    review: VisualReviewManifest,
    project_id: str,
) -> PublicationReadinessReceipt:
    require_publication_request(
        request, board_file=board_file, artifact_root=artifact_root, project_id=project_id
    )
    board_sha = file_sha256(board_file)
    if review.board_sha256 != board_sha:
        raise ValueError("visual review targets another readiness board")
    from pcbsmith.mandatory_review import require_diagnostic_coverage, require_mandatory_review

    mandatory = require_mandatory_review(request.predesign, artifact_root)
    require_diagnostic_coverage(mandatory, review)
    artifacts = {item.artifact_id: item for item in review.artifacts}
    observations = []
    artifact_hashes: dict[str, str] = {}
    for requirement in request.visual_requirements:
        artifact = artifacts.get(requirement.artifact_id)
        if artifact is None or artifact.media_type != "image/png" or artifact.state == "missing":
            raise ValueError("required readiness crop lacks its generated PNG")
        path = _relative_file(review_directory, artifact.relative_path)
        digest = file_sha256(path)
        if artifact.sha256 != digest:
            raise ValueError("readiness visual artifact is stale")
        presence, alignment = visual_model_state_from_preflight(
            request.model_preflight, requirement.component_reference
        )
        observations.append(
            inspect_visual_subject_crop(
                subject_id=requirement.subject_id,
                image_file=path,
                crop_px=request.visual_crops[requirement.subject_id],
                model_presence=presence,
                model_alignment=alignment,
            )
        )
        artifact_hashes[requirement.artifact_id] = digest
    visual = review_visual_subjects(
        requirements=request.visual_requirements, observations=tuple(observations)
    )
    original = request.predesign.readiness
    report = evaluate_design_readiness(
        stage=DesignReadinessStage.SAVED_CANDIDATE,
        component_reviews=original.component_reviews,
        support_review=original.support_review,
        power_review=original.power_review,
        visual_review=visual,
    )
    require_design_readiness(report)
    fields: dict[str, Any] = dict(
        project_id=project_id,
        board_sha256=board_sha,
        request=request,
        report=report,
        visual_artifact_sha256s=artifact_hashes,
    )
    provisional = PublicationReadinessReceipt.model_construct(
        **fields, receipt_fingerprint="0" * 64
    )
    return PublicationReadinessReceipt(
        **fields,
        receipt_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"receipt_fingerprint"})
        ),
    )


def retain_readiness_inputs(
    bundle: PredesignReadinessBundle, source: Path, destination: Path
) -> None:
    require_predesign_bundle(bundle, source)
    paths = {item.relative_path for item in bundle.evidence_files.values()}
    paths.update(
        path
        for overlay in bundle.approval.overlay_manifests
        for path in (overlay.svg_path, overlay.png_path)
    )
    for relative in sorted(paths):
        original = _relative_file(source, relative)
        target = destination / PurePosixPath(relative)
        if target.exists():
            raise ValueError("readiness evidence target already exists")
        atomic_write(target, original.read_bytes())
    require_predesign_bundle(bundle, destination)


def readiness_blockers(
    *,
    generation_root: Path | None,
    project_id: str,
    board_sha256: str,
    board_relative_path: str,
    retained_artifacts: Mapping[str, str],
) -> tuple[str, ...]:
    """Recheck actual retained inputs at routing/release, including pixel crops."""
    if generation_root is None:
        return ("production readiness requires the retained generation directory",)
    try:
        receipt_path = _relative_file(generation_root, READINESS_PATH)
        if retained_artifacts.get(READINESS_PATH) != file_sha256(receipt_path):
            raise ValueError("transaction does not retain the exact readiness receipt")
        receipt = PublicationReadinessReceipt.model_validate_json(receipt_path.read_bytes())
        if receipt.project_id != project_id or receipt.board_sha256 != board_sha256:
            raise ValueError("readiness receipt targets another project or board")
        board = _relative_file(generation_root, board_relative_path)
        for path in (board.parent / name for name in receipt.request.native_inputs):
            relative = path.relative_to(generation_root).as_posix()
            if retained_artifacts.get(relative) != file_sha256(path):
                raise ValueError("transaction omits or changed an exact native input")
        review_path = _relative_file(generation_root, "review/manifest.json")
        if retained_artifacts.get("review/manifest.json") != file_sha256(review_path):
            raise ValueError("transaction visual manifest is stale")
        review = VisualReviewManifest.model_validate_json(review_path.read_bytes())
        replay = evaluate_saved_readiness(
            receipt.request,
            board_file=board,
            artifact_root=generation_root / "review/readiness-inputs",
            review_directory=generation_root / "review",
            review=review,
            project_id=project_id,
        )
        if replay != receipt:
            raise ValueError("saved readiness did not replay against the retained artifacts")
        return ()
    except (ValueError, RuntimeError, OSError, KeyError, IndexError) as exc:
        return (f"production readiness blocked: {exc}",)


def main() -> None:
    """Prepare saved-board model inputs from the exact retained selection policy."""
    import argparse

    parser = argparse.ArgumentParser(description=main.__doc__)
    parser.add_argument("action", choices=["models"])
    for name in ("board", "bundle", "artifact-root", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("model input output must be new")
    bundle = PredesignReadinessBundle.model_validate_json(args.bundle.read_bytes())
    report = prepare_selected_board_models(bundle, args.artifact_root, args.board)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        stream.write(report.model_dump_json(indent=2) + "\n")
    print("Exact selected-policy model inputs prepared; visual inspection remains required.")


if __name__ == "__main__":
    main()
