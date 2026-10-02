"""Fail-closed, replay-bound predesign approval bundle (version 2).

The legacy :mod:`pcbsmith.predesign_gate` module remains the byte-bound
compatibility authority for the retained Retro-Pad R002 identity. This module
is a prospective code-level authority for the explicitly declared predesign
scope: it binds typed artifacts, replays amendments and geometry checks, and
rejects inconsistent declared-demand identifiers. Its source-demand records
are self-declared associations whose fingerprints prove only identifier-level
consistency. They do not prove that cited text semantically supports a net,
that a terminal token names a real pad or pin, or that the declared electrical
demands are a complete future netlist. The contract also does not authenticate
an approver.
"""

from __future__ import annotations

import copy
import hashlib
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, JsonValue, model_validator

from pcbsmith.kicad.concept_review import ConceptReview, examine_concept
from pcbsmith.project_brief import (
    NormalizedProjectBrief,
    ProjectBriefDraft,
    normalize_project_brief,
)
from pcbsmith.prompt_examiner import PromptExamination, PromptResolution
from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel
from pcbsmith.workflow_feasibility import (
    FeasibilityOutcome,
    NeckSection,
    PlacementEnvelope,
    PreRouteFeasibilityReport,
    PreRouteNetDemand,
    evaluate_pre_route_feasibility,
)

_ZERO_SHA256 = "0" * 64
_JSON_POINTER_ESCAPE = re.compile(r"~(?![01])")
_TERMINAL_ID_PATTERN = re.compile(
    r"^(?P<component>[A-Za-z0-9][A-Za-z0-9._-]*)/"
    r"(?P<terminal>[A-Za-z0-9][A-Za-z0-9._-]*)$"
)
_CONCEPT_TIGHT_CLEARANCE_MM = 0.5
_FEASIBILITY_ATTENTION_UTILIZATION = 0.70


def artifact_sha256(value: BaseModel) -> str:
    """Return the canonical complete-object identity used by this contract."""

    return fingerprint(value.model_dump(mode="json"))


def _canonical_identities(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    canonical = tuple(sorted(require_identity(value, field_name) for value in values))
    if len(canonical) != len(set(canonical)):
        raise ValueError(f"{field_name} must contain unique identities")
    return canonical


def _terminal_component_id(terminal_id: str) -> str:
    match = _TERMINAL_ID_PATTERN.fullmatch(terminal_id)
    if match is None:
        raise ValueError(
            "terminal identity must use the fixed '<component_id>/<terminal_id>' syntax"
        )
    return match.group("component")


def _fingerprinted_payload(value: BaseModel, fingerprint_field: str) -> dict[str, Any]:
    return value.model_dump(mode="json", exclude={fingerprint_field})


def _require_fingerprint(value: BaseModel, field_name: str, actual: str) -> None:
    require_sha256(actual, field_name)
    if actual != fingerprint(_fingerprinted_payload(value, field_name)):
        raise ValueError(f"{field_name} is stale")


def _decode_pointer(path: str) -> tuple[str, ...]:
    require_identity(path, "amendment path")
    if path == "/" or not path.startswith("/") or _JSON_POINTER_ESCAPE.search(path):
        raise ValueError("amendment path must be a non-root canonical JSON pointer")
    tokens = tuple(token.replace("~1", "/").replace("~0", "~") for token in path[1:].split("/"))
    if not tokens or any(not token for token in tokens):
        raise ValueError("amendment path contains an empty token")
    if tokens[0] in {"project_id", "original_text"}:
        raise ValueError("an amendment cannot replace prompt or project identity")
    return tokens


def _list_index(token: str, size: int) -> int:
    if not token.isdigit() or (len(token) > 1 and token.startswith("0")):
        raise ValueError("array JSON-pointer tokens must be canonical indexes")
    index = int(token)
    if index >= size:
        raise ValueError("amendment path indexes outside the original brief")
    return index


def _pointer_value(document: JsonValue, tokens: tuple[str, ...]) -> JsonValue:
    current: JsonValue = document
    for token in tokens:
        if isinstance(current, dict):
            if token not in current:
                raise ValueError("amendment path does not exist in the original brief")
            current = current[token]
        elif isinstance(current, list):
            current = current[_list_index(token, len(current))]
        else:
            raise ValueError("amendment path traverses a scalar value")
    return current


def _replace_pointer(
    document: JsonValue,
    tokens: tuple[str, ...],
    replacement: JsonValue,
) -> None:
    parent = _pointer_value(document, tokens[:-1]) if len(tokens) > 1 else document
    token = tokens[-1]
    if isinstance(parent, dict):
        if token not in parent:
            raise ValueError("amendment path does not exist in the original brief")
        parent[token] = replacement
    elif isinstance(parent, list):
        parent[_list_index(token, len(parent))] = replacement
    else:
        raise ValueError("amendment path parent is a scalar value")


class BriefAmendmentPatchV2(SemanticIrModel):
    """One deterministic replacement against an existing draft JSON pointer."""

    schema_id: Literal["pcbsmith-brief-amendment-patch-v2"] = (
        "pcbsmith-brief-amendment-patch-v2"
    )
    schema_version: Literal[2] = 2
    amendment_id: str
    decision_id: str
    path: str
    before_sha256: str
    replacement: JsonValue
    replacement_sha256: str
    patch_fingerprint: str

    @model_validator(mode="after")
    def patch_is_bound(self) -> Self:
        require_identity(self.amendment_id, "amendment_id")
        require_identity(self.decision_id, "decision_id")
        _decode_pointer(self.path)
        require_sha256(self.before_sha256, "before_sha256")
        require_sha256(self.replacement_sha256, "replacement_sha256")
        if self.replacement_sha256 != fingerprint(self.replacement):
            raise ValueError("amendment replacement hash is stale")
        if self.before_sha256 == self.replacement_sha256:
            raise ValueError("an amendment must change the bound value")
        _require_fingerprint(self, "patch_fingerprint", self.patch_fingerprint)
        return self

    @classmethod
    def build(
        cls,
        *,
        amendment_id: str,
        decision_id: str,
        path: str,
        before: JsonValue,
        replacement: JsonValue,
    ) -> BriefAmendmentPatchV2:
        fields: dict[str, Any] = {
            "amendment_id": amendment_id,
            "decision_id": decision_id,
            "path": path,
            "before_sha256": fingerprint(before),
            "replacement": replacement,
            "replacement_sha256": fingerprint(replacement),
        }
        provisional = cls.model_construct(**fields, patch_fingerprint=_ZERO_SHA256)
        return cls(
            **fields,
            patch_fingerprint=fingerprint(
                _fingerprinted_payload(provisional, "patch_fingerprint")
            ),
        )


class BriefAmendmentSetV2(SemanticIrModel):
    schema_id: Literal["pcbsmith-brief-amendment-set-v2"] = (
        "pcbsmith-brief-amendment-set-v2"
    )
    schema_version: Literal[2] = 2
    project_id: str
    prompt_examination_sha256: str
    board_outline_sha256: str
    original_brief_sha256: str
    amended_brief_sha256: str
    patches: tuple[BriefAmendmentPatchV2, ...] = ()
    amendment_set_fingerprint: str

    @model_validator(mode="after")
    def amendment_set_is_canonical(self) -> Self:
        require_identity(self.project_id, "project_id")
        for name in (
            "prompt_examination_sha256",
            "board_outline_sha256",
            "original_brief_sha256",
            "amended_brief_sha256",
        ):
            require_sha256(getattr(self, name), name)
        patches = tuple(sorted(self.patches, key=lambda item: item.path))
        amendment_ids = tuple(item.amendment_id for item in patches)
        paths = tuple(item.path for item in patches)
        if len(amendment_ids) != len(set(amendment_ids)):
            raise ValueError("amendment identities must be unique")
        if len(paths) != len(set(paths)):
            raise ValueError("amendment paths must be unique")
        decoded = tuple(_decode_pointer(path) for path in paths)
        for index, left in enumerate(decoded):
            for right in decoded[index + 1 :]:
                common = min(len(left), len(right))
                if left[:common] == right[:common]:
                    raise ValueError("amendment paths must not overlap")
        object.__setattr__(self, "patches", patches)
        _require_fingerprint(
            self, "amendment_set_fingerprint", self.amendment_set_fingerprint
        )
        return self

    @classmethod
    def build(
        cls,
        *,
        project_id: str,
        prompt_examination_sha256: str,
        board_outline_sha256: str,
        original_brief_sha256: str,
        amended_brief_sha256: str,
        patches: tuple[BriefAmendmentPatchV2, ...],
    ) -> BriefAmendmentSetV2:
        fields: dict[str, Any] = {
            "project_id": project_id,
            "prompt_examination_sha256": prompt_examination_sha256,
            "board_outline_sha256": board_outline_sha256,
            "original_brief_sha256": original_brief_sha256,
            "amended_brief_sha256": amended_brief_sha256,
            "patches": tuple(sorted(patches, key=lambda item: item.path)),
        }
        provisional = cls.model_construct(
            **fields, amendment_set_fingerprint=_ZERO_SHA256
        )
        return cls(
            **fields,
            amendment_set_fingerprint=fingerprint(
                _fingerprinted_payload(provisional, "amendment_set_fingerprint")
            ),
        )


class AmendmentDecisionV2(SemanticIrModel):
    """A typed decision; intentionally contains no free-text acceptance field."""

    schema_id: Literal["pcbsmith-amendment-decision-v2"] = (
        "pcbsmith-amendment-decision-v2"
    )
    schema_version: Literal[2] = 2
    project_id: str
    prompt_examination_sha256: str
    board_outline_sha256: str
    amendment_set_sha256: str
    decision_id: str
    amendment_ids: tuple[str, ...] = Field(min_length=1)
    resolved_prompt_claim_ids: tuple[str, ...] = ()
    resolved_prompt_issue_ids: tuple[str, ...] = ()
    resolved_brief_requirement_ids: tuple[str, ...] = ()
    resolved_brief_finding_ids: tuple[str, ...] = ()
    approved: Literal[True] = True
    decision_fingerprint: str

    @model_validator(mode="after")
    def decision_is_bound(self) -> Self:
        require_identity(self.project_id, "project_id")
        require_identity(self.decision_id, "decision_id")
        for name in (
            "prompt_examination_sha256",
            "board_outline_sha256",
            "amendment_set_sha256",
        ):
            require_sha256(getattr(self, name), name)
        for name in (
            "amendment_ids",
            "resolved_prompt_claim_ids",
            "resolved_prompt_issue_ids",
            "resolved_brief_requirement_ids",
            "resolved_brief_finding_ids",
        ):
            object.__setattr__(
                self,
                name,
                _canonical_identities(getattr(self, name), name),
            )
        _require_fingerprint(self, "decision_fingerprint", self.decision_fingerprint)
        return self

    @classmethod
    def build(
        cls,
        *,
        project_id: str,
        prompt_examination_sha256: str,
        board_outline_sha256: str,
        amendment_set_sha256: str,
        decision_id: str,
        amendment_ids: tuple[str, ...],
        resolved_prompt_claim_ids: tuple[str, ...] = (),
        resolved_prompt_issue_ids: tuple[str, ...] = (),
        resolved_brief_requirement_ids: tuple[str, ...] = (),
        resolved_brief_finding_ids: tuple[str, ...] = (),
    ) -> AmendmentDecisionV2:
        fields: dict[str, Any] = {
            "project_id": project_id,
            "prompt_examination_sha256": prompt_examination_sha256,
            "board_outline_sha256": board_outline_sha256,
            "amendment_set_sha256": amendment_set_sha256,
            "decision_id": decision_id,
            "amendment_ids": tuple(sorted(amendment_ids)),
            "resolved_prompt_claim_ids": tuple(sorted(resolved_prompt_claim_ids)),
            "resolved_prompt_issue_ids": tuple(sorted(resolved_prompt_issue_ids)),
            "resolved_brief_requirement_ids": tuple(
                sorted(resolved_brief_requirement_ids)
            ),
            "resolved_brief_finding_ids": tuple(sorted(resolved_brief_finding_ids)),
            "approved": True,
        }
        provisional = cls.model_construct(**fields, decision_fingerprint=_ZERO_SHA256)
        return cls(
            **fields,
            decision_fingerprint=fingerprint(
                _fingerprinted_payload(provisional, "decision_fingerprint")
            ),
        )


class ConceptOverlayManifestV2(SemanticIrModel):
    """Exact side-specific SVG and PNG overlay identities."""

    schema_id: Literal["pcbsmith-concept-overlay-manifest-v2"] = (
        "pcbsmith-concept-overlay-manifest-v2"
    )
    schema_version: Literal[2] = 2
    project_id: str
    prompt_examination_sha256: str
    board_outline_sha256: str
    concept_review_sha256: str
    side: Literal["front", "back"]
    svg_path: str
    svg_sha256: str
    svg_bytes: int = Field(gt=0)
    png_path: str
    png_sha256: str
    png_bytes: int = Field(gt=0)
    manifest_fingerprint: str

    @model_validator(mode="after")
    def manifest_is_exact(self) -> Self:
        require_identity(self.project_id, "project_id")
        for name in (
            "prompt_examination_sha256",
            "board_outline_sha256",
            "concept_review_sha256",
            "svg_sha256",
            "png_sha256",
        ):
            require_sha256(getattr(self, name), name)
        for path, suffix, field_name in (
            (self.svg_path, ".svg", "svg_path"),
            (self.png_path, ".png", "png_path"),
        ):
            require_identity(path, field_name)
            normalized = path.replace("\\", "/")
            if (
                normalized.startswith("/")
                or ":" in normalized
                or ".." in normalized.split("/")
                or not normalized.endswith(suffix)
            ):
                raise ValueError(f"{field_name} must be a safe relative {suffix} path")
        if self.svg_path == self.png_path:
            raise ValueError("overlay SVG and PNG paths must differ")
        _require_fingerprint(self, "manifest_fingerprint", self.manifest_fingerprint)
        return self

    @classmethod
    def build(
        cls,
        *,
        project_id: str,
        prompt_examination_sha256: str,
        board_outline_sha256: str,
        concept_review_sha256: str,
        side: Literal["front", "back"],
        svg_path: str,
        svg_sha256: str,
        svg_bytes: int,
        png_path: str,
        png_sha256: str,
        png_bytes: int,
    ) -> ConceptOverlayManifestV2:
        fields: dict[str, Any] = {
            "project_id": project_id,
            "prompt_examination_sha256": prompt_examination_sha256,
            "board_outline_sha256": board_outline_sha256,
            "concept_review_sha256": concept_review_sha256,
            "side": side,
            "svg_path": svg_path,
            "svg_sha256": svg_sha256,
            "svg_bytes": svg_bytes,
            "png_path": png_path,
            "png_sha256": png_sha256,
            "png_bytes": png_bytes,
        }
        provisional = cls.model_construct(**fields, manifest_fingerprint=_ZERO_SHA256)
        return cls(
            **fields,
            manifest_fingerprint=fingerprint(
                _fingerprinted_payload(provisional, "manifest_fingerprint")
            ),
        )


class PreRouteFeasibilityInputsV2(SemanticIrModel):
    """Deterministic inputs for replay over a nonempty declared demand set.

    The demand set is an explicit, self-declared pre-route inventory. Its
    presence and exact replay do not establish completeness against a later
    schematic or netlist, or prove that terminal suffixes name real pads or
    pins.
    """

    schema_id: Literal["pcbsmith-pre-route-feasibility-inputs-v2"] = (
        "pcbsmith-pre-route-feasibility-inputs-v2"
    )
    schema_version: Literal[2] = 2
    project_id: str
    prompt_examination_sha256: str
    amended_brief_sha256: str
    board_outline: tuple[tuple[float, float], ...] = Field(min_length=3)
    board_outline_sha256: str
    keepout_polygons: tuple[tuple[tuple[float, float], ...], ...] = ()
    envelopes: tuple[PlacementEnvelope, ...]
    necks: tuple[NeckSection, ...]
    net_demands: tuple[PreRouteNetDemand, ...] = Field(min_length=1)
    policy_id: Literal["pcbsmith-pre-route-feasibility-policy-v1"] = (
        "pcbsmith-pre-route-feasibility-policy-v1"
    )
    attention_utilization: float = Field(gt=0, le=1)
    search_state_budget: int = Field(gt=0)
    inputs_fingerprint: str

    @model_validator(mode="after")
    def inputs_are_replayable(self) -> Self:
        require_identity(self.project_id, "project_id")
        for name in (
            "prompt_examination_sha256",
            "amended_brief_sha256",
            "board_outline_sha256",
        ):
            require_sha256(getattr(self, name), name)
        canonical_outline = tuple(
            (round(x, 4), round(y, 4)) for x, y in self.board_outline
        )
        if any(not math.isfinite(value) for point in self.board_outline for value in point):
            raise ValueError("feasibility board outline coordinates must be finite")
        if any(
            len(polygon) < 3
            or any(not math.isfinite(value) for point in polygon for value in point)
            for polygon in self.keepout_polygons
        ):
            raise ValueError("feasibility keepouts must contain finite polygons")
        if canonical_outline != self.board_outline:
            raise ValueError("feasibility board outline must be canonical to four decimals")
        if fingerprint(canonical_outline) != self.board_outline_sha256:
            raise ValueError("feasibility input outline hash is stale")
        identity_groups = (
            ("envelope", tuple(item.envelope_id for item in self.envelopes)),
            ("neck", tuple(item.neck_id for item in self.necks)),
            ("net demand", tuple(item.net_name for item in self.net_demands)),
        )
        for label, identities in identity_groups:
            if len(identities) != len(set(identities)):
                raise ValueError(f"feasibility {label} identities must be unique")
        for demand in self.net_demands:
            for terminal_id in demand.terminal_ids:
                _terminal_component_id(terminal_id)
        if self.attention_utilization != _FEASIBILITY_ATTENTION_UTILIZATION:
            raise ValueError("feasibility acceptance threshold must use the frozen policy")
        _require_fingerprint(self, "inputs_fingerprint", self.inputs_fingerprint)
        return self

    @classmethod
    def build(
        cls,
        *,
        project_id: str,
        prompt_examination_sha256: str,
        amended_brief_sha256: str,
        board_outline: tuple[tuple[float, float], ...],
        board_outline_sha256: str,
        keepout_polygons: tuple[tuple[tuple[float, float], ...], ...],
        envelopes: tuple[PlacementEnvelope, ...],
        necks: tuple[NeckSection, ...],
        net_demands: tuple[PreRouteNetDemand, ...],
        attention_utilization: float = _FEASIBILITY_ATTENTION_UTILIZATION,
        search_state_budget: int = 50_000,
    ) -> PreRouteFeasibilityInputsV2:
        fields: dict[str, Any] = {
            "project_id": project_id,
            "prompt_examination_sha256": prompt_examination_sha256,
            "amended_brief_sha256": amended_brief_sha256,
            "board_outline": board_outline,
            "board_outline_sha256": board_outline_sha256,
            "keepout_polygons": keepout_polygons,
            "envelopes": envelopes,
            "necks": necks,
            "net_demands": net_demands,
            "policy_id": "pcbsmith-pre-route-feasibility-policy-v1",
            "attention_utilization": attention_utilization,
            "search_state_budget": search_state_budget,
        }
        provisional = cls.model_construct(**fields, inputs_fingerprint=_ZERO_SHA256)
        return cls(
            **fields,
            inputs_fingerprint=fingerprint(
                _fingerprinted_payload(provisional, "inputs_fingerprint")
            ),
        )

    def evaluate(self) -> PreRouteFeasibilityReport:
        return evaluate_pre_route_feasibility(
            board_outline=self.board_outline,
            board_outline_sha256=self.board_outline_sha256,
            keepout_polygons=self.keepout_polygons,
            envelopes=self.envelopes,
            necks=self.necks,
            net_demands=self.net_demands,
            attention_utilization=self.attention_utilization,
            search_state_budget=self.search_state_budget,
        )


class ComponentGeometryBindingV2(SemanticIrModel):
    """Explicit brief-component to concept-item and feasibility-envelope link."""

    schema_id: Literal["pcbsmith-component-geometry-binding-v2"] = (
        "pcbsmith-component-geometry-binding-v2"
    )
    schema_version: Literal[2] = 2
    component_id: str
    concept_item_ids: tuple[str, ...] = Field(min_length=1)
    feasibility_envelope_ids: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def binding_is_canonical(self) -> Self:
        require_identity(self.component_id, "component_id")
        object.__setattr__(
            self,
            "concept_item_ids",
            _canonical_identities(self.concept_item_ids, "concept_item_ids"),
        )
        object.__setattr__(
            self,
            "feasibility_envelope_ids",
            _canonical_identities(
                self.feasibility_envelope_ids, "feasibility_envelope_ids"
            ),
        )
        return self


class ElectricalDemandInventoryRecordV2(SemanticIrModel):
    """One self-declared demand with identifier-level source associations.

    Validation checks terminal syntax and later checks each component-name
    prefix against the amended brief. It does not resolve the terminal suffix
    against a footprint or prove that a cited claim or requirement semantically
    supports this electrical demand.
    """

    schema_id: Literal["pcbsmith-electrical-demand-inventory-record-v2"] = (
        "pcbsmith-electrical-demand-inventory-record-v2"
    )
    schema_version: Literal[2] = 2
    net_name: str
    terminal_ids: tuple[str, ...] = Field(min_length=2)
    source_claim_ids: tuple[str, ...] = ()
    source_requirement_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def inventory_record_is_sourced(self) -> Self:
        require_identity(self.net_name, "net_name")
        for name in ("terminal_ids", "source_claim_ids", "source_requirement_ids"):
            object.__setattr__(
                self,
                name,
                _canonical_identities(getattr(self, name), name),
            )
        for terminal_id in self.terminal_ids:
            _terminal_component_id(terminal_id)
        if not (self.source_claim_ids or self.source_requirement_ids):
            raise ValueError("electrical demand inventory requires a claim or requirement source")
        return self


class SourceDemandCoverageRecordV2(SemanticIrModel):
    """Fingerprint self-declared links across artifact identifiers.

    The fingerprint detects later changes to the association. It is not an
    authority for the association's engineering meaning.
    """

    schema_id: Literal["pcbsmith-source-demand-coverage-record-v2"] = (
        "pcbsmith-source-demand-coverage-record-v2"
    )
    schema_version: Literal[2] = 2
    demand_id: str
    source_span_ids: tuple[str, ...] = ()
    claim_ids: tuple[str, ...] = ()
    anchor_ids: tuple[str, ...] = ()
    requirement_ids: tuple[str, ...] = ()
    component_ids: tuple[str, ...] = ()
    placement_ids: tuple[str, ...] = ()
    artwork_ids: tuple[str, ...] = ()
    asset_ids: tuple[str, ...] = ()
    concept_item_ids: tuple[str, ...] = ()
    feasibility_envelope_ids: tuple[str, ...] = ()
    feasibility_net_names: tuple[str, ...] = ()
    evidence_fingerprint: str

    @model_validator(mode="after")
    def coverage_record_is_typed(self) -> Self:
        require_identity(self.demand_id, "demand_id")
        for name in (
            "source_span_ids",
            "claim_ids",
            "anchor_ids",
            "requirement_ids",
            "component_ids",
            "placement_ids",
            "artwork_ids",
            "asset_ids",
            "concept_item_ids",
            "feasibility_envelope_ids",
            "feasibility_net_names",
        ):
            object.__setattr__(
                self,
                name,
                _canonical_identities(getattr(self, name), name),
            )
        if not (self.claim_ids or self.anchor_ids):
            raise ValueError("coverage record requires a source claim or anchor")
        if not (
            self.requirement_ids
            or self.component_ids
            or self.placement_ids
            or self.artwork_ids
            or self.asset_ids
            or self.concept_item_ids
            or self.feasibility_envelope_ids
            or self.feasibility_net_names
        ):
            raise ValueError("coverage record requires at least one downstream demand")
        _require_fingerprint(self, "evidence_fingerprint", self.evidence_fingerprint)
        return self

    @classmethod
    def build(
        cls,
        *,
        demand_id: str,
        source_span_ids: tuple[str, ...] = (),
        claim_ids: tuple[str, ...] = (),
        anchor_ids: tuple[str, ...] = (),
        requirement_ids: tuple[str, ...] = (),
        component_ids: tuple[str, ...] = (),
        placement_ids: tuple[str, ...] = (),
        artwork_ids: tuple[str, ...] = (),
        asset_ids: tuple[str, ...] = (),
        concept_item_ids: tuple[str, ...] = (),
        feasibility_envelope_ids: tuple[str, ...] = (),
        feasibility_net_names: tuple[str, ...] = (),
    ) -> SourceDemandCoverageRecordV2:
        fields: dict[str, Any] = {
            "demand_id": demand_id,
            "source_span_ids": tuple(sorted(source_span_ids)),
            "claim_ids": tuple(sorted(claim_ids)),
            "anchor_ids": tuple(sorted(anchor_ids)),
            "requirement_ids": tuple(sorted(requirement_ids)),
            "component_ids": tuple(sorted(component_ids)),
            "placement_ids": tuple(sorted(placement_ids)),
            "artwork_ids": tuple(sorted(artwork_ids)),
            "asset_ids": tuple(sorted(asset_ids)),
            "concept_item_ids": tuple(sorted(concept_item_ids)),
            "feasibility_envelope_ids": tuple(sorted(feasibility_envelope_ids)),
            "feasibility_net_names": tuple(sorted(feasibility_net_names)),
        }
        provisional = cls.model_construct(**fields, evidence_fingerprint=_ZERO_SHA256)
        return cls(
            **fields,
            evidence_fingerprint=fingerprint(
                _fingerprinted_payload(provisional, "evidence_fingerprint")
            ),
        )


class SourceDemandCoverageV2(SemanticIrModel):
    """Identifier-level consistency for the self-declared pre-route scope."""

    schema_id: Literal["pcbsmith-source-demand-coverage-v2"] = (
        "pcbsmith-source-demand-coverage-v2"
    )
    schema_version: Literal[2] = 2
    project_id: str
    prompt_examination_sha256: str
    amended_brief_sha256: str
    board_outline_sha256: str
    concept_review_sha256: str
    pre_route_inputs_sha256: str
    pre_route_feasibility_sha256: str
    component_geometry_bindings: tuple[ComponentGeometryBindingV2, ...]
    electrical_demand_inventory: tuple[ElectricalDemandInventoryRecordV2, ...] = Field(
        min_length=1
    )
    records: tuple[SourceDemandCoverageRecordV2, ...] = Field(min_length=1)
    coverage_fingerprint: str

    @model_validator(mode="after")
    def coverage_is_bound(self) -> Self:
        require_identity(self.project_id, "project_id")
        for name in (
            "prompt_examination_sha256",
            "amended_brief_sha256",
            "board_outline_sha256",
            "concept_review_sha256",
            "pre_route_inputs_sha256",
            "pre_route_feasibility_sha256",
        ):
            require_sha256(getattr(self, name), name)
        records = tuple(sorted(self.records, key=lambda item: item.demand_id))
        ids = tuple(item.demand_id for item in records)
        if len(ids) != len(set(ids)):
            raise ValueError("source-demand identities must be unique")
        object.__setattr__(self, "records", records)
        component_bindings = tuple(
            sorted(self.component_geometry_bindings, key=lambda item: item.component_id)
        )
        component_ids = tuple(item.component_id for item in component_bindings)
        if len(component_ids) != len(set(component_ids)):
            raise ValueError("component geometry binding identities must be unique")
        bound_concept_ids = tuple(
            identity for item in component_bindings for identity in item.concept_item_ids
        )
        bound_envelope_ids = tuple(
            identity
            for item in component_bindings
            for identity in item.feasibility_envelope_ids
        )
        if len(bound_concept_ids) != len(set(bound_concept_ids)) or len(
            bound_envelope_ids
        ) != len(set(bound_envelope_ids)):
            raise ValueError("component geometry targets cannot bind multiple components")
        inventory = tuple(
            sorted(self.electrical_demand_inventory, key=lambda item: item.net_name)
        )
        inventory_names = tuple(item.net_name for item in inventory)
        if len(inventory_names) != len(set(inventory_names)):
            raise ValueError("electrical demand inventory identities must be unique")
        object.__setattr__(self, "component_geometry_bindings", component_bindings)
        object.__setattr__(self, "electrical_demand_inventory", inventory)
        _require_fingerprint(self, "coverage_fingerprint", self.coverage_fingerprint)
        return self

    @classmethod
    def build(
        cls,
        *,
        project_id: str,
        prompt_examination_sha256: str,
        amended_brief_sha256: str,
        board_outline_sha256: str,
        concept_review_sha256: str,
        pre_route_inputs_sha256: str,
        pre_route_feasibility_sha256: str,
        component_geometry_bindings: tuple[ComponentGeometryBindingV2, ...],
        electrical_demand_inventory: tuple[ElectricalDemandInventoryRecordV2, ...],
        records: tuple[SourceDemandCoverageRecordV2, ...],
    ) -> SourceDemandCoverageV2:
        fields: dict[str, Any] = {
            "project_id": project_id,
            "prompt_examination_sha256": prompt_examination_sha256,
            "amended_brief_sha256": amended_brief_sha256,
            "board_outline_sha256": board_outline_sha256,
            "concept_review_sha256": concept_review_sha256,
            "pre_route_inputs_sha256": pre_route_inputs_sha256,
            "pre_route_feasibility_sha256": pre_route_feasibility_sha256,
            "component_geometry_bindings": tuple(
                sorted(component_geometry_bindings, key=lambda item: item.component_id)
            ),
            "electrical_demand_inventory": tuple(
                sorted(electrical_demand_inventory, key=lambda item: item.net_name)
            ),
            "records": tuple(sorted(records, key=lambda item: item.demand_id)),
        }
        provisional = cls.model_construct(**fields, coverage_fingerprint=_ZERO_SHA256)
        return cls(
            **fields,
            coverage_fingerprint=fingerprint(
                _fingerprinted_payload(provisional, "coverage_fingerprint")
            ),
        )


class ApproverMetadataV2(SemanticIrModel):
    """Self-asserted traceability metadata, not authenticated identity.

    The fingerprints detect later payload changes. They do not verify a human,
    session, authorization policy, digital signature, or external identity.
    """

    schema_id: Literal["pcbsmith-predesign-approver-v2"] = (
        "pcbsmith-predesign-approver-v2"
    )
    schema_version: Literal[2] = 2
    asserted_approver_id: str
    asserted_approver_role: Literal["requester", "authorized_delegate"]
    recorded_at: datetime
    capture_method: Literal["interactive_assertion", "imported_assertion"]
    approval_payload_sha256: str
    traceability_fingerprint: str

    @model_validator(mode="after")
    def traceability_assertion_is_bound(self) -> Self:
        require_identity(self.asserted_approver_id, "asserted_approver_id")
        require_sha256(self.approval_payload_sha256, "approval_payload_sha256")
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must include a timezone offset")
        _require_fingerprint(
            self, "traceability_fingerprint", self.traceability_fingerprint
        )
        return self

    @classmethod
    def build(
        cls,
        *,
        asserted_approver_id: str,
        asserted_approver_role: Literal["requester", "authorized_delegate"],
        recorded_at: datetime,
        capture_method: Literal["interactive_assertion", "imported_assertion"],
        approval_payload_sha256: str,
    ) -> ApproverMetadataV2:
        fields: dict[str, Any] = {
            "asserted_approver_id": asserted_approver_id,
            "asserted_approver_role": asserted_approver_role,
            "recorded_at": recorded_at,
            "capture_method": capture_method,
            "approval_payload_sha256": approval_payload_sha256,
        }
        provisional = cls.model_construct(
            **fields, traceability_fingerprint=_ZERO_SHA256
        )
        return cls(
            **fields,
            traceability_fingerprint=fingerprint(
                _fingerprinted_payload(provisional, "traceability_fingerprint")
            ),
        )


def _require_artifact_hash(label: str, value: BaseModel, expected: str) -> None:
    require_sha256(expected, f"{label}_sha256")
    if artifact_sha256(value) != expected:
        raise ValueError(f"{label} artifact hash is stale")


def _require_normalized_brief(label: str, brief: NormalizedProjectBrief) -> None:
    require_sha256(brief.semantic_sha256, f"{label} semantic_sha256")
    finding_ids = tuple(item.finding_id for item in brief.findings)
    if len(finding_ids) != len(set(finding_ids)):
        raise ValueError(f"{label} finding identities must be unique")
    examiner_findings = tuple(
        item for item in brief.findings if item.finding_id != "asset.missing-reference"
    )
    replayed = normalize_project_brief(
        brief.draft,
        examiner_findings=examiner_findings,
    )
    if replayed.model_dump(mode="json") != brief.model_dump(mode="json"):
        raise ValueError(f"{label} does not replay through brief normalization")


def _require_concept_replay(review: ConceptReview, tight_clearance_mm: float) -> None:
    from pcbsmith.kicad.library import _PROJECT_FOOTPRINTS

    # Source locations are part of the fingerprinted concept. Replay the exact
    # retained dependencies even when this model is loaded before a CLI project
    # context is available. Native source hashes remain independently required.
    sources: dict[str, Path] = {}
    for result in review.items:
        if result.item.footprint_id and result.footprint_source_file:
            source = Path(result.footprint_source_file)
            prior = sources.get(result.item.footprint_id)
            if prior is not None and prior != source:
                raise ValueError("concept uses conflicting sources for one footprint")
            sources[result.item.footprint_id] = source
    token = _PROJECT_FOOTPRINTS.set(sources)
    try:
        replayed = examine_concept(
            review.project_id,
            review.outline,
            tuple(result.item for result in review.items),
            tight_clearance_mm=tight_clearance_mm,
            hard_conflicts=review.hard_conflicts,
            assumptions=review.assumptions,
        )
    finally:
        _PROJECT_FOOTPRINTS.reset(token)
    if replayed.model_dump(mode="json") != review.model_dump(mode="json"):
        raise ValueError("concept review does not replay from its full typed inputs")


def _require_feasibility_ready(report: PreRouteFeasibilityReport) -> None:
    if report.outcome is not FeasibilityOutcome.READY:
        raise ValueError("pre-route feasibility is not ready")
    if not report.search_complete:
        raise ValueError("pre-route feasibility search is incomplete")
    if (
        report.failing_nets
        or report.uncontained_envelope_ids
        or report.access_conflict_envelope_ids
        or report.findings
    ):
        raise ValueError("pre-route feasibility retains a failure or conflict")
    if report.search_states_explored > report.search_state_budget:
        raise ValueError("pre-route feasibility search accounting is invalid")
    if report.usable_area_mm2 <= 0 or report.usable_area_mm2 > report.board_area_mm2:
        raise ValueError("pre-route feasibility usable area is invalid")
    expected_utilization = report.envelope_area_mm2 / report.usable_area_mm2
    if not math.isclose(report.area_utilization, expected_utilization, abs_tol=1e-12):
        raise ValueError("pre-route feasibility area utilization is stale")
    assignments = {item.net_name: item for item in report.assignments}
    records = {item.neck_id: item for item in report.neck_records}
    if len(assignments) != len(report.assignments) or len(records) != len(report.neck_records):
        raise ValueError("pre-route feasibility identities must be unique")
    if any(item.neck_id not in records for item in report.assignments):
        raise ValueError("pre-route assignment references an unknown neck")
    for neck_id, record in records.items():
        assigned = tuple(
            sorted(item.net_name for item in report.assignments if item.neck_id == neck_id)
        )
        committed = sum(
            item.committed_units for item in report.assignments if item.neck_id == neck_id
        )
        if (
            tuple(record.demand_net_names) != assigned
            or record.committed_units != committed
            or record.over_capacity_units != 0
            or committed > record.capacity_units
        ):
            raise ValueError("pre-route neck accounting is stale")


def _brief_requirement_ids(draft: ProjectBriefDraft) -> set[str]:
    requirements = {
        *(item.requirement_id for item in draft.functional_requirements),
        *(item.requirement_id for item in draft.electrical_requirements),
        *(item.requirement_id for item in draft.manufacturing_requirements),
        draft.mechanics.maximum_width_mm.requirement_id,
        draft.mechanics.maximum_height_mm.requirement_id,
        draft.mechanics.board_thickness_mm.requirement_id,
        draft.mechanics.layer_count.requirement_id,
    }
    if draft.mechanics.mounting_hole_diameter_mm is not None:
        requirements.add(draft.mechanics.mounting_hole_diameter_mm.requirement_id)
    return requirements


def _record_union(
    records: tuple[SourceDemandCoverageRecordV2, ...], field_name: str
) -> set[str]:
    return {
        identity
        for record in records
        for identity in getattr(record, field_name)
    }


class PredesignApprovalContractV2(SemanticIrModel):
    """Code-level approval bundle for the explicitly declared predesign scope.

    Approval closes typed identifiers and deterministic checks over the supplied
    records. It does not convert self-declared source-demand associations into
    evidence of semantic support, pad/pin existence, or full-netlist coverage.
    """

    schema_id: Literal["pcbsmith-predesign-approval-contract-v2"] = (
        "pcbsmith-predesign-approval-contract-v2"
    )
    schema_version: Literal[2] = 2
    project_id: str
    board_outline_sha256: str
    approved: Literal[True] = True
    prompt_examination: PromptExamination
    prompt_examination_sha256: str
    original_brief: NormalizedProjectBrief
    original_brief_sha256: str
    amended_brief: NormalizedProjectBrief
    amended_brief_sha256: str
    amendment_set: BriefAmendmentSetV2
    amendment_set_sha256: str
    decisions: tuple[AmendmentDecisionV2, ...] = ()
    decisions_sha256: str
    accepted_decision_ids: tuple[str, ...] = ()
    accepted_amendment_ids: tuple[str, ...] = ()
    concept_review: ConceptReview
    concept_review_sha256: str
    concept_policy_id: Literal["pcbsmith-concept-clearance-policy-v1"] = (
        "pcbsmith-concept-clearance-policy-v1"
    )
    concept_tight_clearance_mm: float = Field(gt=0)
    overlay_manifests: tuple[ConceptOverlayManifestV2, ...] = Field(
        min_length=2, max_length=2
    )
    overlay_manifests_sha256: str
    pre_route_inputs: PreRouteFeasibilityInputsV2
    pre_route_inputs_sha256: str
    pre_route_feasibility: PreRouteFeasibilityReport
    pre_route_feasibility_sha256: str
    source_demand_coverage: SourceDemandCoverageV2
    source_demand_coverage_sha256: str
    approver: ApproverMetadataV2
    contract_fingerprint: str

    @model_validator(mode="after")
    def contract_is_approval_ready(self) -> Self:
        require_identity(self.project_id, "project_id")
        require_sha256(self.board_outline_sha256, "board_outline_sha256")
        artifact_bindings: tuple[tuple[str, BaseModel, str], ...] = (
            (
                "prompt examination",
                self.prompt_examination,
                self.prompt_examination_sha256,
            ),
            ("original brief", self.original_brief, self.original_brief_sha256),
            ("amended brief", self.amended_brief, self.amended_brief_sha256),
            ("amendment set", self.amendment_set, self.amendment_set_sha256),
            ("concept review", self.concept_review, self.concept_review_sha256),
            (
                "pre-route inputs",
                self.pre_route_inputs,
                self.pre_route_inputs_sha256,
            ),
            (
                "pre-route feasibility",
                self.pre_route_feasibility,
                self.pre_route_feasibility_sha256,
            ),
            (
                "source-demand coverage",
                self.source_demand_coverage,
                self.source_demand_coverage_sha256,
            ),
        )
        for label, artifact, expected_hash in artifact_bindings:
            _require_artifact_hash(label, artifact, expected_hash)

        projects = {
            self.prompt_examination.project_id,
            self.original_brief.draft.project_id,
            self.amended_brief.draft.project_id,
            self.amendment_set.project_id,
            self.concept_review.project_id,
            self.source_demand_coverage.project_id,
            self.pre_route_inputs.project_id,
            *(decision.project_id for decision in self.decisions),
            *(manifest.project_id for manifest in self.overlay_manifests),
        }
        if projects != {self.project_id}:
            raise ValueError("predesign artifacts do not share one project identity")
        if (
            self.original_brief.draft.original_text
            != self.prompt_examination.original_text
            or self.amended_brief.draft.original_text
            != self.prompt_examination.original_text
        ):
            raise ValueError("briefs do not retain the exact examined prompt")

        _require_normalized_brief("original brief", self.original_brief)
        _require_normalized_brief("amended brief", self.amended_brief)
        if (
            self.amended_brief.outcome != "ready_for_concept"
            or self.amended_brief.unresolved_requirement_ids
            or any(item.blocking for item in self.amended_brief.findings)
        ):
            raise ValueError("amended brief is not fully approval-ready")

        _require_concept_replay(self.concept_review, self.concept_tight_clearance_mm)
        if self.concept_tight_clearance_mm != _CONCEPT_TIGHT_CLEARANCE_MM:
            raise ValueError("concept clearance threshold must use the frozen policy")
        if (
            self.concept_review.outcome != "ready_for_approval"
            or self.concept_review.hard_conflicts
            or any(item.status == "conflict" for item in self.concept_review.items)
        ):
            raise ValueError("concept review is not fully approval-ready")
        if (
            self.concept_review.outline_sha256 != self.board_outline_sha256
            or self.pre_route_inputs.board_outline_sha256
            != self.board_outline_sha256
            or self.pre_route_feasibility.board_outline_sha256
            != self.board_outline_sha256
        ):
            raise ValueError("concept and feasibility do not share the approved outline")
        if (
            self.pre_route_inputs.prompt_examination_sha256
            != self.prompt_examination_sha256
            or self.pre_route_inputs.amended_brief_sha256
            != self.amended_brief_sha256
        ):
            raise ValueError("pre-route inputs are stale or cross-project")
        replayed_feasibility = self.pre_route_inputs.evaluate()
        if replayed_feasibility.model_dump(mode="json") != self.pre_route_feasibility.model_dump(
            mode="json"
        ):
            raise ValueError("pre-route feasibility does not replay from its full inputs")
        _require_feasibility_ready(self.pre_route_feasibility)
        if {item.net_name for item in self.pre_route_feasibility.assignments} != {
            item.net_name for item in self.pre_route_inputs.net_demands
        }:
            raise ValueError("not every declared pre-route demand has a capacity assignment")

        manifests = tuple(sorted(self.overlay_manifests, key=lambda item: item.side))
        if {item.side for item in manifests} != {"front", "back"}:
            raise ValueError("approval requires exactly one front and one back overlay")
        if len({item.svg_path for item in manifests} | {item.png_path for item in manifests}) != 4:
            raise ValueError("front/back overlays must bind four distinct files")
        for manifest in manifests:
            if (
                manifest.prompt_examination_sha256
                != self.prompt_examination_sha256
                or manifest.board_outline_sha256 != self.board_outline_sha256
                or manifest.concept_review_sha256 != self.concept_review_sha256
            ):
                raise ValueError("overlay manifest is stale or belongs to another authority")
        object.__setattr__(self, "overlay_manifests", manifests)
        require_sha256(self.overlay_manifests_sha256, "overlay_manifests_sha256")
        expected_manifest_hash = fingerprint(
            [item.model_dump(mode="json") for item in manifests]
        )
        if self.overlay_manifests_sha256 != expected_manifest_hash:
            raise ValueError("overlay manifest set hash is stale")

        self._require_amendments_and_decisions()
        self._require_declared_scope_coverage()
        if self.approver.approval_payload_sha256 != self._approval_payload_sha256():
            raise ValueError("approval traceability metadata is stale for this payload")
        _require_fingerprint(self, "contract_fingerprint", self.contract_fingerprint)
        return self

    def _approval_payload_sha256(self) -> str:
        return fingerprint(
            {
                "schema_id": "pcbsmith-predesign-approval-payload-v2",
                "project_id": self.project_id,
                "board_outline_sha256": self.board_outline_sha256,
                "prompt_examination_sha256": self.prompt_examination_sha256,
                "original_brief_sha256": self.original_brief_sha256,
                "amended_brief_sha256": self.amended_brief_sha256,
                "amendment_set_sha256": self.amendment_set_sha256,
                "decisions_sha256": self.decisions_sha256,
                "accepted_decision_ids": self.accepted_decision_ids,
                "accepted_amendment_ids": self.accepted_amendment_ids,
                "concept_review_sha256": self.concept_review_sha256,
                "concept_policy_id": self.concept_policy_id,
                "concept_tight_clearance_mm": self.concept_tight_clearance_mm,
                "overlay_manifests_sha256": self.overlay_manifests_sha256,
                "pre_route_inputs_sha256": self.pre_route_inputs_sha256,
                "pre_route_feasibility_sha256": self.pre_route_feasibility_sha256,
                "source_demand_coverage_sha256": self.source_demand_coverage_sha256,
                "asserted_approver_id": self.approver.asserted_approver_id,
                "asserted_approver_role": self.approver.asserted_approver_role,
                "recorded_at": self.approver.recorded_at.isoformat(),
                "capture_method": self.approver.capture_method,
            }
        )

    def _require_amendments_and_decisions(self) -> None:
        amendment_set = self.amendment_set
        expected_amendment_binding = (
            amendment_set.prompt_examination_sha256 == self.prompt_examination_sha256
            and amendment_set.board_outline_sha256 == self.board_outline_sha256
            and amendment_set.original_brief_sha256 == self.original_brief_sha256
            and amendment_set.amended_brief_sha256 == self.amended_brief_sha256
        )
        if not expected_amendment_binding:
            raise ValueError("amendment set is stale or belongs to another authority")
        if not amendment_set.patches and (
            self.original_brief_sha256 != self.amended_brief_sha256
        ):
            raise ValueError("a zero-amendment contract requires identical full briefs")

        original_json: JsonValue = self.original_brief.draft.model_dump(mode="json")
        replayed_json = copy.deepcopy(original_json)
        for patch in amendment_set.patches:
            tokens = _decode_pointer(patch.path)
            before = _pointer_value(original_json, tokens)
            if patch.before_sha256 != fingerprint(before):
                raise ValueError("amendment before-value hash is stale")
            _replace_pointer(replayed_json, tokens, copy.deepcopy(patch.replacement))
        replayed = ProjectBriefDraft.model_validate(replayed_json)
        if replayed.model_dump(mode="json") != self.amended_brief.draft.model_dump(
            mode="json"
        ):
            raise ValueError("amendments do not replay to the exact amended brief")

        decisions = tuple(sorted(self.decisions, key=lambda item: item.decision_id))
        decision_ids = tuple(item.decision_id for item in decisions)
        if len(decision_ids) != len(set(decision_ids)):
            raise ValueError("decision identities must be unique")
        object.__setattr__(self, "decisions", decisions)
        require_sha256(self.decisions_sha256, "decisions_sha256")
        expected_decisions_hash = fingerprint(
            [item.model_dump(mode="json") for item in decisions]
        )
        if self.decisions_sha256 != expected_decisions_hash:
            raise ValueError("decision set hash is stale")
        amendment_ids = tuple(item.amendment_id for item in amendment_set.patches)
        accepted_decisions = _canonical_identities(
            self.accepted_decision_ids, "accepted_decision_ids"
        )
        accepted_amendments = _canonical_identities(
            self.accepted_amendment_ids, "accepted_amendment_ids"
        )
        object.__setattr__(self, "accepted_decision_ids", accepted_decisions)
        object.__setattr__(self, "accepted_amendment_ids", accepted_amendments)
        if set(accepted_decisions) != set(decision_ids):
            raise ValueError("accepted decisions do not exactly cover decision records")
        if set(accepted_amendments) != set(amendment_ids):
            raise ValueError("accepted amendments do not exactly cover applied patches")

        patch_ids_by_decision = {
            decision_id: {
                patch.amendment_id
                for patch in amendment_set.patches
                if patch.decision_id == decision_id
            }
            for decision_id in decision_ids
        }
        if any(
            decision.project_id != self.project_id
            or decision.prompt_examination_sha256 != self.prompt_examination_sha256
            or decision.board_outline_sha256 != self.board_outline_sha256
            or decision.amendment_set_sha256 != self.amendment_set_sha256
            or set(decision.amendment_ids)
            != patch_ids_by_decision[decision.decision_id]
            for decision in decisions
        ):
            raise ValueError("decision records do not exactly cover their applied amendments")
        if any(patch.decision_id not in patch_ids_by_decision for patch in amendment_set.patches):
            raise ValueError("an amendment references an unrelated decision")

        exact_resolution_sets: tuple[tuple[str, set[str]], ...] = (
            (
                "resolved_prompt_claim_ids",
                {
                    item.claim_id
                    for item in self.prompt_examination.claims
                    if item.resolution in {PromptResolution.UNKNOWN, PromptResolution.CONFLICT}
                },
            ),
            (
                "resolved_prompt_issue_ids",
                {
                    item.issue_id
                    for item in self.prompt_examination.issues
                    if item.hard_conflict
                },
            ),
            (
                "resolved_brief_requirement_ids",
                set(self.original_brief.unresolved_requirement_ids),
            ),
            (
                "resolved_brief_finding_ids",
                {item.finding_id for item in self.original_brief.findings if item.blocking},
            ),
        )
        for field_name, required in exact_resolution_sets:
            recorded = {
                identity
                for decision in decisions
                for identity in getattr(decision, field_name)
            }
            if recorded != required:
                raise ValueError(f"{field_name} does not exactly cover resolved identities")

    def _require_declared_scope_coverage(self) -> None:
        coverage = self.source_demand_coverage
        if (
            coverage.project_id != self.project_id
            or coverage.prompt_examination_sha256 != self.prompt_examination_sha256
            or coverage.amended_brief_sha256 != self.amended_brief_sha256
            or coverage.board_outline_sha256 != self.board_outline_sha256
            or coverage.concept_review_sha256 != self.concept_review_sha256
            or coverage.pre_route_inputs_sha256 != self.pre_route_inputs_sha256
            or coverage.pre_route_feasibility_sha256
            != self.pre_route_feasibility_sha256
        ):
            raise ValueError("source-demand coverage is stale or cross-project")
        claims = {item.claim_id: item for item in self.prompt_examination.claims}
        anchors = {item.anchor_id: item for item in self.prompt_examination.anchors}
        requirement_ids = _brief_requirement_ids(self.amended_brief.draft)
        components = {
            item.component_id: item for item in self.amended_brief.draft.components
        }
        concept_items = {
            item.item.item_id: item.item for item in self.concept_review.items
        }
        concept_results = {
            item.item.item_id: item for item in self.concept_review.items
        }
        envelopes = {
            item.envelope_id: item for item in self.pre_route_inputs.envelopes
        }
        bindings = {
            item.component_id: item for item in coverage.component_geometry_bindings
        }
        if set(bindings) != set(components):
            raise ValueError("every brief component requires one geometry binding")
        for component_id, binding in bindings.items():
            if binding.concept_item_ids != (component_id,):
                raise ValueError(
                    "component geometry binding must use the exact component identity"
                )
            if not set(binding.concept_item_ids).issubset(concept_items) or not set(
                binding.feasibility_envelope_ids
            ).issubset(envelopes):
                raise ValueError("component geometry binding cites an unknown target")
            concept_item = concept_items[component_id]
            if concept_item.kind != "footprint":
                raise ValueError("a component-bound concept item must be a footprint")
            declared_footprint = components[component_id].footprint_id
            if (
                declared_footprint is not None
                and concept_item.footprint_id != declared_footprint
            ):
                raise ValueError("component-bound concept footprint identity is stale")
            if len(binding.feasibility_envelope_ids) != 1:
                raise ValueError("each component requires one exact feasibility envelope")
            if any(
                envelopes[envelope_id].subject_id != component_id
                for envelope_id in binding.feasibility_envelope_ids
            ):
                raise ValueError(
                    "component geometry envelope subject is not the exact component"
                )
            envelope = envelopes[binding.feasibility_envelope_ids[0]]
            if tuple(envelope.polygon) != tuple(concept_results[component_id].envelope):
                raise ValueError("component feasibility envelope differs from concept geometry")
            if envelope.source_geometry_sha256 != self.concept_review_sha256:
                raise ValueError("component feasibility envelope has stale concept provenance")
            if not any(
                component_id in record.component_ids
                and set(binding.concept_item_ids).issubset(record.concept_item_ids)
                and set(binding.feasibility_envelope_ids).issubset(
                    record.feasibility_envelope_ids
                )
                for record in coverage.records
            ):
                raise ValueError(
                    "component geometry binding lacks one declared source-demand link"
                )

        net_demands = {
            item.net_name: item for item in self.pre_route_inputs.net_demands
        }
        inventory = {
            item.net_name: item for item in coverage.electrical_demand_inventory
        }
        if not net_demands or not inventory:
            raise ValueError("approval requires a nonempty declared electrical demand inventory")
        if set(inventory) != set(net_demands):
            raise ValueError(
                "electrical demand inventory does not exactly match declared feasibility inputs"
            )
        for net_name, inventory_record in inventory.items():
            if tuple(inventory_record.terminal_ids) != tuple(
                net_demands[net_name].terminal_ids
            ):
                raise ValueError("electrical demand inventory terminal identity is stale")
            terminal_components = {
                _terminal_component_id(terminal_id)
                for terminal_id in inventory_record.terminal_ids
            }
            if not terminal_components.issubset(components):
                raise ValueError(
                    "electrical demand terminal references an undeclared brief component"
                )
            if not set(inventory_record.source_claim_ids).issubset(claims) or not set(
                inventory_record.source_requirement_ids
            ).issubset(requirement_ids):
                raise ValueError("electrical demand inventory cites an unknown source")
            if not any(
                net_name in record.feasibility_net_names
                and set(inventory_record.source_claim_ids).issubset(record.claim_ids)
                and set(inventory_record.source_requirement_ids).issubset(
                    record.requirement_ids
                )
                for record in coverage.records
            ):
                raise ValueError(
                    "electrical demand inventory lacks one declared source-demand link"
                )
        for record in coverage.records:
            if not set(record.claim_ids).issubset(claims) or not set(
                record.anchor_ids
            ).issubset(anchors):
                raise ValueError("coverage record cites an unknown source identity")
            compatible_spans = {
                span_id
                for claim_id in record.claim_ids
                for span_id in claims[claim_id].source_span_ids
            } | {
                span_id
                for anchor_id in record.anchor_ids
                for span_id in anchors[anchor_id].source_span_ids
            }
            if set(record.source_span_ids) != compatible_spans:
                raise ValueError(
                    "coverage source spans do not exactly match cited claims and anchors"
                )

        demand_spans = {
            span_id
            for claim in self.prompt_examination.claims
            for span_id in claim.source_span_ids
        } | {
            span_id
            for anchor in self.prompt_examination.anchors
            for span_id in anchor.source_span_ids
        }
        expected: tuple[tuple[str, set[str]], ...] = (
            ("source_span_ids", demand_spans),
            ("claim_ids", {item.claim_id for item in self.prompt_examination.claims}),
            ("anchor_ids", {item.anchor_id for item in self.prompt_examination.anchors}),
            ("requirement_ids", _brief_requirement_ids(self.amended_brief.draft)),
            ("component_ids", {item.component_id for item in self.amended_brief.draft.components}),
            ("placement_ids", {item.placement_id for item in self.amended_brief.draft.placements}),
            ("artwork_ids", {item.artwork_id for item in self.amended_brief.draft.artwork}),
            ("asset_ids", {item.asset_id for item in self.amended_brief.draft.assets}),
            ("concept_item_ids", {item.item.item_id for item in self.concept_review.items}),
            (
                "feasibility_envelope_ids",
                {item.envelope_id for item in self.pre_route_inputs.envelopes},
            ),
            (
                "feasibility_net_names",
                {item.net_name for item in self.pre_route_inputs.net_demands},
            ),
        )
        for field_name, identities in expected:
            if _record_union(coverage.records, field_name) != identities:
                raise ValueError(f"source-demand coverage is incomplete for {field_name}")

    @classmethod
    def build(
        cls,
        *,
        project_id: str,
        prompt_examination: PromptExamination,
        original_brief: NormalizedProjectBrief,
        amended_brief: NormalizedProjectBrief,
        amendment_set: BriefAmendmentSetV2,
        decisions: tuple[AmendmentDecisionV2, ...],
        concept_review: ConceptReview,
        concept_tight_clearance_mm: float,
        overlay_manifests: tuple[ConceptOverlayManifestV2, ...],
        pre_route_inputs: PreRouteFeasibilityInputsV2,
        pre_route_feasibility: PreRouteFeasibilityReport,
        source_demand_coverage: SourceDemandCoverageV2,
        asserted_approver_id: str,
        asserted_approver_role: Literal["requester", "authorized_delegate"],
        recorded_at: datetime,
        capture_method: Literal["interactive_assertion", "imported_assertion"],
    ) -> PredesignApprovalContractV2:
        prompt_hash = artifact_sha256(prompt_examination)
        original_hash = artifact_sha256(original_brief)
        amended_hash = artifact_sha256(amended_brief)
        amendment_hash = artifact_sha256(amendment_set)
        concept_hash = artifact_sha256(concept_review)
        inputs_hash = artifact_sha256(pre_route_inputs)
        feasibility_hash = artifact_sha256(pre_route_feasibility)
        coverage_hash = artifact_sha256(source_demand_coverage)
        canonical_decisions = tuple(sorted(decisions, key=lambda item: item.decision_id))
        canonical_manifests = tuple(sorted(overlay_manifests, key=lambda item: item.side))
        fields: dict[str, Any] = {
            "project_id": project_id,
            "board_outline_sha256": concept_review.outline_sha256,
            "approved": True,
            "prompt_examination": prompt_examination,
            "prompt_examination_sha256": prompt_hash,
            "original_brief": original_brief,
            "original_brief_sha256": original_hash,
            "amended_brief": amended_brief,
            "amended_brief_sha256": amended_hash,
            "amendment_set": amendment_set,
            "amendment_set_sha256": amendment_hash,
            "decisions": canonical_decisions,
            "decisions_sha256": fingerprint(
                [item.model_dump(mode="json") for item in canonical_decisions]
            ),
            "accepted_decision_ids": tuple(item.decision_id for item in canonical_decisions),
            "accepted_amendment_ids": tuple(
                sorted(patch.amendment_id for patch in amendment_set.patches)
            ),
            "concept_review": concept_review,
            "concept_review_sha256": concept_hash,
            "concept_policy_id": "pcbsmith-concept-clearance-policy-v1",
            "concept_tight_clearance_mm": concept_tight_clearance_mm,
            "overlay_manifests": canonical_manifests,
            "overlay_manifests_sha256": fingerprint(
                [item.model_dump(mode="json") for item in canonical_manifests]
            ),
            "pre_route_inputs": pre_route_inputs,
            "pre_route_inputs_sha256": inputs_hash,
            "pre_route_feasibility": pre_route_feasibility,
            "pre_route_feasibility_sha256": feasibility_hash,
            "source_demand_coverage": source_demand_coverage,
            "source_demand_coverage_sha256": coverage_hash,
        }
        unbound_approver = ApproverMetadataV2.build(
            asserted_approver_id=asserted_approver_id,
            asserted_approver_role=asserted_approver_role,
            recorded_at=recorded_at,
            capture_method=capture_method,
            approval_payload_sha256=_ZERO_SHA256,
        )
        unbound_contract = cls.model_construct(
            **fields,
            approver=unbound_approver,
            contract_fingerprint=_ZERO_SHA256,
        )
        fields["approver"] = ApproverMetadataV2.build(
            asserted_approver_id=asserted_approver_id,
            asserted_approver_role=asserted_approver_role,
            recorded_at=recorded_at,
            capture_method=capture_method,
            approval_payload_sha256=unbound_contract._approval_payload_sha256(),
        )
        provisional = cls.model_construct(**fields, contract_fingerprint=_ZERO_SHA256)
        return cls(
            **fields,
            contract_fingerprint=fingerprint(
                _fingerprinted_payload(provisional, "contract_fingerprint")
            ),
        )


def require_predesign_approval(
    contract: PredesignApprovalContractV2,
    *,
    artifact_root: Path,
) -> PredesignApprovalContractV2:
    """Revalidate the contract and verify all four live overlay artifacts."""

    validated = PredesignApprovalContractV2.model_validate_json(contract.model_dump_json())
    if artifact_root.is_symlink():
        raise RuntimeError("overlay artifact root must not be a symbolic link")
    try:
        resolved_root = artifact_root.resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(f"overlay artifact root is unavailable: {artifact_root}") from exc
    if not resolved_root.is_dir():
        raise RuntimeError(f"overlay artifact root is not a directory: {artifact_root}")

    expected_files = tuple(
        (path, digest, size)
        for manifest in validated.overlay_manifests
        for path, digest, size in (
            (manifest.svg_path, manifest.svg_sha256, manifest.svg_bytes),
            (manifest.png_path, manifest.png_sha256, manifest.png_bytes),
        )
    )
    if len({path for path, _, _ in expected_files}) != 4:
        raise RuntimeError("approval must bind exactly four distinct overlay files")
    for relative_path, expected_sha256, expected_bytes in expected_files:
        candidate = artifact_root.joinpath(*relative_path.replace("\\", "/").split("/"))
        cursor = artifact_root
        for part in Path(relative_path).parts:
            cursor /= part
            if cursor.is_symlink():
                raise RuntimeError(f"overlay artifact path contains a symlink: {relative_path}")
        try:
            resolved = candidate.resolve(strict=True)
        except OSError as exc:
            raise RuntimeError(f"overlay artifact is unavailable: {relative_path}") from exc
        if not resolved.is_relative_to(resolved_root) or not resolved.is_file():
            raise RuntimeError(f"overlay artifact escapes its root: {relative_path}")
        try:
            payload = resolved.read_bytes()
        except OSError as exc:
            raise RuntimeError(f"cannot read overlay artifact: {relative_path}") from exc
        if len(payload) != expected_bytes:
            raise RuntimeError(f"overlay artifact byte length changed: {relative_path}")
        if hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise RuntimeError(f"overlay artifact hash changed: {relative_path}")
    return validated
