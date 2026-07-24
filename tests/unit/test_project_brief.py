from __future__ import annotations

from pcbsmith.project_brief import (
    AssetReference,
    MechanicalRequirement,
    ProjectBriefDraft,
    RequirementValue,
    normalize_project_brief,
)


def _value(requirement_id: str, value: float | int) -> RequirementValue:
    return RequirementValue(
        requirement_id=requirement_id,
        value=value,
        unit="mm",
        source="user",
        resolution="explicit",
        source_text=requirement_id,
    )


def _draft() -> ProjectBriefDraft:
    return ProjectBriefDraft(
        project_id="fixture",
        title="Fixture",
        original_text="A small two-layer fixture.",
        functional_requirements=(),
        electrical_requirements=(),
        manufacturing_requirements=(),
        mechanics=MechanicalRequirement(
            maximum_width_mm=_value("max-width", 20.0),
            maximum_height_mm=_value("max-height", 10.0),
            board_thickness_mm=_value("thickness", 1.6),
            layer_count=_value("layers", 2),
            outline_asset_id="outline",
        ),
        components=(),
        placements=(),
        artwork=(),
        assets=(
            AssetReference(
                asset_id="outline",
                purpose="outline",
                source_file="outline.png",
                source_sha256="0" * 64,
                physical_width_mm=20.0,
            ),
        ),
    )


def test_normalization_is_repeatable_and_ready_only_when_resolved() -> None:
    first = normalize_project_brief(_draft())
    second = normalize_project_brief(_draft())

    assert first.outcome == "ready_for_concept"
    assert first.semantic_sha256 == second.semantic_sha256


def test_normalization_fails_closed_for_unknown_asset_reference() -> None:
    draft = _draft().model_copy(
        update={"mechanics": _draft().mechanics.model_copy(update={"outline_asset_id": "missing"})}
    )

    result = normalize_project_brief(draft)

    assert result.outcome == "blocked"
    assert result.findings[0].finding_id == "asset.missing-reference"
