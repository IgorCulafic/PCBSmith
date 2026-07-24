"""Versioned project-brief contracts and deterministic normalization.

Natural-language extraction is intentionally outside this module.  A caller may
use a person or an AI to prepare :class:`ProjectBriefDraft`, but normalization is
deterministic and every value retains its provenance and resolution state.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Resolution = Literal["explicit", "derived", "assumed", "decision_required", "conflict"]
RequirementSource = Literal["user", "source", "engineering", "tool"]
BriefOutcome = Literal["blocked", "needs_user_decision", "ready_for_concept"]


class RequirementValue(BaseModel):
    """One normalized value with an auditable origin and resolution."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    requirement_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    value: str | float | int | bool
    unit: str | None = None
    source: RequirementSource
    resolution: Resolution
    source_text: str
    rationale: str | None = None

    @model_validator(mode="after")
    def validate_numeric_value(self) -> RequirementValue:
        if isinstance(self.value, float) and not math.isfinite(self.value):
            raise ValueError("requirement values must be finite")
        if self.resolution in {"derived", "assumed"} and not self.rationale:
            raise ValueError(f"{self.resolution} values require a rationale")
        return self


class AssetReference(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    asset_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    purpose: Literal["outline", "silkscreen", "logo", "placement_reference", "other"]
    source_file: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    physical_width_mm: float | None = Field(default=None, gt=0)


class ComponentRequirement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    component_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    quantity: int = Field(gt=0)
    role: str
    selection: str | None = None
    footprint_id: str | None = None
    side: Literal["front", "back", "either"] = "either"
    mounting: Literal["smd", "tht", "either"] = "either"
    model_fidelity: Literal["exact", "package", "module", "proxy_allowed", "not_required"] = (
        "package"
    )
    source: RequirementSource = "user"
    resolution: Resolution = "explicit"


class MechanicalRequirement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    maximum_width_mm: RequirementValue
    maximum_height_mm: RequirementValue
    board_thickness_mm: RequirementValue
    layer_count: RequirementValue
    outline_asset_id: str
    mounting_hole_diameter_mm: RequirementValue | None = None
    mounting_hole_centers_mm: tuple[tuple[float, float], ...] = ()
    coordinate_origin: Literal["outline_bounding_box_top_left"] = "outline_bounding_box_top_left"


class ArtworkRequirement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artwork_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    asset_id: str
    side: Literal["front", "back"]
    anchor_mm: tuple[float, float] | None = None
    anchor_semantics: str
    width_mm: float = Field(gt=0)
    rotation_deg: float = 0.0
    mirrored: bool = False
    placement_resolution: Resolution


class PlacementRequirement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    placement_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    subject: str
    relation: str
    side: Literal["front", "back", "either"] = "either"
    anchor_semantics: str
    tolerance_mm: float | None = Field(default=None, ge=0)
    resolution: Resolution
    source_text: str


class ProjectBriefDraft(BaseModel):
    """Structured transcription of a request before deterministic normalization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    project_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str
    original_text: str = Field(min_length=1)
    functional_requirements: tuple[RequirementValue, ...]
    electrical_requirements: tuple[RequirementValue, ...]
    manufacturing_requirements: tuple[RequirementValue, ...]
    mechanics: MechanicalRequirement
    components: tuple[ComponentRequirement, ...]
    placements: tuple[PlacementRequirement, ...]
    artwork: tuple[ArtworkRequirement, ...]
    assets: tuple[AssetReference, ...]
    spirit_anchors: tuple[str, ...] = ()
    engineering_freedoms: tuple[str, ...] = ()


class BriefFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    finding_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    severity: Literal["info", "warning", "error"]
    category: Literal[
        "ambiguity", "conflict", "missing", "asset", "electrical", "mechanical", "process"
    ]
    requirement_ids: tuple[str, ...] = ()
    message: str
    blocking: bool = False
    alternatives: tuple[str, ...] = ()


class NormalizedProjectBrief(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["pcbsmith-project-brief-v1"] = "pcbsmith-project-brief-v1"
    draft: ProjectBriefDraft
    outcome: BriefOutcome
    findings: tuple[BriefFinding, ...]
    unresolved_requirement_ids: tuple[str, ...]
    semantic_sha256: str


def normalize_project_brief(
    draft: ProjectBriefDraft,
    *,
    examiner_findings: tuple[BriefFinding, ...] = (),
) -> NormalizedProjectBrief:
    """Validate identities and compute a fail-closed normalized outcome."""

    requirements = (
        *draft.functional_requirements,
        *draft.electrical_requirements,
        *draft.manufacturing_requirements,
        draft.mechanics.maximum_width_mm,
        draft.mechanics.maximum_height_mm,
        draft.mechanics.board_thickness_mm,
        draft.mechanics.layer_count,
    )
    if draft.mechanics.mounting_hole_diameter_mm is not None:
        requirements = (*requirements, draft.mechanics.mounting_hole_diameter_mm)
    ids = tuple(item.requirement_id for item in requirements)
    if len(set(ids)) != len(ids):
        raise ValueError("requirement_id values must be unique")
    asset_ids = tuple(asset.asset_id for asset in draft.assets)
    if len(set(asset_ids)) != len(asset_ids):
        raise ValueError("asset_id values must be unique")
    known_assets = set(asset_ids)
    referenced_assets = {draft.mechanics.outline_asset_id} | {
        artwork.asset_id for artwork in draft.artwork
    }
    missing_assets = tuple(sorted(referenced_assets - known_assets))
    findings = list(examiner_findings)
    if missing_assets:
        findings.append(
            BriefFinding(
                finding_id="asset.missing-reference",
                severity="error",
                category="asset",
                message=f"Brief references undeclared assets: {missing_assets!r}.",
                blocking=True,
            )
        )
    unresolved = tuple(
        sorted(
            {
                *(
                    item.requirement_id
                    for item in requirements
                    if item.resolution in {"decision_required", "conflict"}
                ),
                *(
                    item.placement_id
                    for item in draft.placements
                    if item.resolution in {"decision_required", "conflict"}
                ),
                *(
                    item.artwork_id
                    for item in draft.artwork
                    if item.placement_resolution in {"decision_required", "conflict"}
                ),
                *(
                    item.component_id
                    for item in draft.components
                    if item.resolution in {"decision_required", "conflict"}
                ),
            }
        )
    )
    if any(finding.blocking for finding in findings) or any(
        item.resolution == "conflict" for item in requirements
    ):
        outcome: BriefOutcome = "blocked"
    elif unresolved:
        outcome = "needs_user_decision"
    else:
        outcome = "ready_for_concept"
    payload = draft.model_dump(mode="json")
    semantic_sha256 = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return NormalizedProjectBrief(
        draft=draft,
        outcome=outcome,
        findings=tuple(sorted(findings, key=lambda item: item.finding_id)),
        unresolved_requirement_ids=unresolved,
        semantic_sha256=semantic_sha256,
    )
