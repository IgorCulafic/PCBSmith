from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pytest

import pcbsmith.predesign_gate as legacy_gate
from pcbsmith.kicad.concept_review import examine_concept
from pcbsmith.predesign_gate import (
    ConceptApproval,
    file_sha256,
    require_concept_approval,
    write_approval_request,
)
from pcbsmith.project_brief import (
    AssetReference,
    MechanicalRequirement,
    ProjectBriefDraft,
    RequirementValue,
    normalize_project_brief,
)


@dataclass(frozen=True)
class LegacyInputs:
    brief: Path
    concept: Path
    approval: Path


@pytest.fixture
def legacy_inputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LegacyInputs:
    """Exercise byte-lock behavior with test-only inputs, never retained approvals."""
    def value(identity: str, number: float) -> RequirementValue:
        return RequirementValue(
            requirement_id=identity, value=number, source="user",
            resolution="explicit", source_text="Synthetic unit-test requirement",
        )

    draft = ProjectBriefDraft(
        project_id="legacy-fixture", title="Synthetic legacy fixture",
        original_text="Synthetic compatibility test, not a manufacturing approval.",
        functional_requirements=(), electrical_requirements=(),
        manufacturing_requirements=(), components=(), placements=(), artwork=(),
        mechanics=MechanicalRequirement(
            maximum_width_mm=value("width", 20.0),
            maximum_height_mm=value("height", 10.0),
            board_thickness_mm=value("thickness", 1.6),
            layer_count=value("layers", 2.0), outline_asset_id="outline",
        ),
        assets=(AssetReference(
            asset_id="outline", purpose="outline", source_file="synthetic.svg",
            source_sha256="a" * 64,
        ),),
    )
    paths = LegacyInputs(tmp_path / "brief.json", tmp_path / "concept.json",
                         tmp_path / "approved.json")
    paths.brief.write_text(normalize_project_brief(draft).model_dump_json(), encoding="utf-8")
    concept = examine_concept(
        "legacy-fixture", ((0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (0.0, 10.0)), (),
    )
    paths.concept.write_text(concept.model_dump_json(), encoding="utf-8")
    approval = ConceptApproval(
        project_id="legacy-fixture", approved=True, approved_by="unit-test-only",
        approved_at=datetime(2026, 7, 20, 15, 12, tzinfo=UTC),
        normalized_brief_sha256=file_sha256(paths.brief),
        concept_review_sha256=file_sha256(paths.concept),
        accepted_decisions=("Synthetic test input; no real approval is recorded.",),
    )
    paths.approval.write_text(approval.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(legacy_gate, "_HISTORICAL_R002_PROJECT_ID", "legacy-fixture")
    for name, path in (("BRIEF", paths.brief), ("CONCEPT", paths.concept),
                       ("APPROVAL", paths.approval)):
        monkeypatch.setattr(legacy_gate, f"_HISTORICAL_R002_{name}_SHA256", file_sha256(path))
    return paths


def test_exact_test_only_legacy_bytes_are_accepted(legacy_inputs: LegacyInputs) -> None:
    approval = require_concept_approval(
        project_id="legacy-fixture",
        normalized_brief_file=legacy_inputs.brief,
        concept_review_file=legacy_inputs.concept,
        approval_file=legacy_inputs.approval,
    )

    assert approval.approved
    assert approval.approved_at is not None
    assert approval.approved_at.utcoffset() is not None


def test_historical_exception_is_locked_against_one_byte_mutation(
    tmp_path: Path,
    legacy_inputs: LegacyInputs,
) -> None:
    brief = tmp_path / "normalized-brief.json"
    brief.write_bytes(legacy_inputs.brief.read_bytes() + b" ")

    with pytest.raises(RuntimeError, match="changed after concept approval"):
        require_concept_approval(
            project_id="legacy-fixture",
            normalized_brief_file=brief,
            concept_review_file=legacy_inputs.concept,
            approval_file=legacy_inputs.approval,
        )


def test_historical_approval_file_is_locked_against_whitespace_mutation(
    tmp_path: Path,
    legacy_inputs: LegacyInputs,
) -> None:
    approval_file = tmp_path / "concept-approval.json"
    approval_file.write_bytes(legacy_inputs.approval.read_bytes() + b" ")

    with pytest.raises(RuntimeError, match="exact retained Retro-Pad R002"):
        require_concept_approval(
            project_id="legacy-fixture",
            normalized_brief_file=legacy_inputs.brief,
            concept_review_file=legacy_inputs.concept,
            approval_file=approval_file,
        )


def test_pending_request_can_only_be_written_for_exact_locked_inputs(
    tmp_path: Path,
    legacy_inputs: LegacyInputs,
) -> None:
    approval_file = tmp_path / "approval.json"
    request = write_approval_request(
        project_id="legacy-fixture",
        normalized_brief_file=legacy_inputs.brief,
        concept_review_file=legacy_inputs.concept,
        output_file=approval_file,
    )

    assert not request.approved
    with pytest.raises(RuntimeError, match="pending"):
        require_concept_approval(
            project_id="legacy-fixture",
            normalized_brief_file=legacy_inputs.brief,
            concept_review_file=legacy_inputs.concept,
            approval_file=approval_file,
        )


def test_nonhistorical_v1_request_must_migrate_to_v2(tmp_path: Path,
    legacy_inputs: LegacyInputs,
) -> None:
    changed_brief = tmp_path / "normalized-brief.json"
    changed_brief.write_bytes(legacy_inputs.brief.read_bytes() + b" ")

    with pytest.raises(RuntimeError, match="migrate this request"):
        write_approval_request(
            project_id="legacy-fixture",
            normalized_brief_file=changed_brief,
            concept_review_file=legacy_inputs.concept,
            output_file=tmp_path / "approval.json",
        )


def test_forged_future_v1_approval_must_migrate_to_v2(tmp_path: Path,
    legacy_inputs: LegacyInputs,
) -> None:
    changed_brief = tmp_path / "normalized-brief.json"
    changed_brief.write_bytes(legacy_inputs.brief.read_bytes() + b" ")
    forged = ConceptApproval(
        project_id="legacy-fixture",
        approved=True,
        approved_by="requester",
        approved_at=datetime(2026, 7, 31, 12, 0, tzinfo=UTC),
        normalized_brief_sha256=file_sha256(changed_brief),
        concept_review_sha256=file_sha256(legacy_inputs.concept),
        accepted_decisions=("forged future decision",),
    )
    approval_file = tmp_path / "approval.json"
    approval_file.write_text(forged.model_dump_json(indent=2), encoding="utf-8")

    with pytest.raises(RuntimeError, match="migrate this request"):
        require_concept_approval(
            project_id="legacy-fixture",
            normalized_brief_file=changed_brief,
            concept_review_file=legacy_inputs.concept,
            approval_file=approval_file,
        )


def test_v1_request_rejects_partial_brief_instead_of_reading_loose_fields(
    tmp_path: Path,
    legacy_inputs: LegacyInputs,
) -> None:
    partial = tmp_path / "normalized-brief.json"
    partial.write_text('{"outcome":"ready_for_concept"}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="not a full typed artifact"):
        write_approval_request(
            project_id="legacy-fixture",
            normalized_brief_file=partial,
            concept_review_file=legacy_inputs.concept,
            output_file=tmp_path / "approval.json",
        )


def test_v1_approval_requires_timezone_aware_metadata(tmp_path: Path,
    legacy_inputs: LegacyInputs,
) -> None:
    payload = legacy_inputs.approval.read_text(encoding="utf-8").replace(
        "2026-07-20T15:12:00Z",
        "2026-07-20T15:12:00",
    )
    approval_file = tmp_path / "approval.json"
    approval_file.write_text(payload, encoding="utf-8")

    with pytest.raises(RuntimeError, match="valid typed v1 record"):
        require_concept_approval(
            project_id="legacy-fixture",
            normalized_brief_file=legacy_inputs.brief,
            concept_review_file=legacy_inputs.concept,
            approval_file=approval_file,
        )


def test_v1_approval_rejects_caller_project_mismatch(legacy_inputs: LegacyInputs) -> None:
    with pytest.raises(RuntimeError, match="different project"):
        require_concept_approval(
            project_id="retro-pad-r001",
            normalized_brief_file=legacy_inputs.brief,
            concept_review_file=legacy_inputs.concept,
            approval_file=legacy_inputs.approval,
        )


def test_production_legacy_allowlist_keeps_original_exact_hashes() -> None:
    """The synthetic fixture must not broaden the shipped historical exception."""
    assert legacy_gate._HISTORICAL_R002_PROJECT_ID == "retro-pad"
    assert legacy_gate._HISTORICAL_R002_BRIEF_SHA256 == (
        "a8205d92764f1e726c9fc8fdaeb26610856190a9b2b8080776977c403458a574"
    )
    assert legacy_gate._HISTORICAL_R002_CONCEPT_SHA256 == (
        "50885076eaebe624e1c5153ea6021fc021ed0acb70fe5dde7fa8f760c13d7d40"
    )
    assert legacy_gate._HISTORICAL_R002_APPROVAL_SHA256 == (
        "973cc03a72b92abf71dd982f77fbee2e4ff415ca8f951aaffcf8d69516258d3e"
    )
