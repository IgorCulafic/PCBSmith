"""Engine-neutral classification of outer-copper solder-mask exposure.

This module joins exact copper regions to physical solder-mask apertures.  It
does not parse EDA data and it deliberately reports ``unknown`` whenever the
available geometry cannot prove a stronger result.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pcbsmith.mask_geometry import (
    MASK_GEOMETRY_EPSILON_MM,
    ApertureRelation,
    Compound,
    ContainmentProof,
    MaskAperture,
    MaskGeometry,
    MaskPrimitive,
    MaskSide,
    MaskVerification,
    geometry_has_interior_overlap,
    measure_geometry,
    primitive_contains,
)
from pcbsmith.rule_profiles import CopperRole, OuterCopperMaskState

COPPER_EXPOSURE_SCHEMA_ID: Literal["pcbsmith-copper-exposure"] = "pcbsmith-copper-exposure"
COPPER_EXPOSURE_SCHEMA_VERSION: Literal[1] = 1


class CopperGeometryVerification(StrEnum):
    EXACT = "exact"
    UNSUPPORTED = "unsupported"


class CopperExposureModel(BaseModel):
    """Frozen base with deterministic, explicitly versioned serialization."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)

    schema_id: Literal["pcbsmith-copper-exposure"] = COPPER_EXPOSURE_SCHEMA_ID
    schema_version: Literal[1] = COPPER_EXPOSURE_SCHEMA_VERSION

    def semantic_json(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def semantic_fingerprint(self) -> str:
        return hashlib.sha256(self.semantic_json().encode("utf-8")).hexdigest()


class OuterCopperRegion(CopperExposureModel):
    source_id: str = Field(min_length=1)
    parent_source_id: str | None = None
    side: MaskSide
    net_name: str
    owner_ref: str | None = None
    role: CopperRole
    geometry: MaskGeometry | None = None
    verification: CopperGeometryVerification = CopperGeometryVerification.EXACT
    unsupported_reason: str | None = None

    @model_validator(mode="after")
    def verification_fields_are_coherent(self) -> Self:
        if self.parent_source_id == "":
            raise ValueError("parent_source_id must be non-empty when supplied")
        if self.owner_ref == "":
            raise ValueError("owner_ref must be non-empty when supplied")
        if self.verification is CopperGeometryVerification.EXACT:
            if self.geometry is None:
                raise ValueError("exact copper verification requires geometry")
            if self.unsupported_reason is not None:
                raise ValueError("exact copper verification cannot carry an unsupported reason")
        elif not self.unsupported_reason:
            raise ValueError("unsupported copper verification requires a reason")
        return self


class CopperExposureResult(CopperExposureModel):
    copper_source_id: str = Field(min_length=1)
    side: MaskSide
    state: OuterCopperMaskState
    role: CopperRole
    aperture_source_ids: tuple[str, ...] = ()
    unresolved_aperture_source_ids: tuple[str, ...] = ()
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def source_ids_are_unique(self) -> Self:
        if len(set(self.aperture_source_ids)) != len(self.aperture_source_ids):
            raise ValueError("aperture_source_ids must be unique")
        if len(set(self.unresolved_aperture_source_ids)) != len(
            self.unresolved_aperture_source_ids
        ):
            raise ValueError("unresolved_aperture_source_ids must be unique")
        return self


def classify_outer_copper_exposure(
    copper: Iterable[OuterCopperRegion],
    apertures: Iterable[MaskAperture],
) -> tuple[CopperExposureResult, ...]:
    """Classify each unique outer-copper identity conservatively and deterministically."""
    copper_by_identity: dict[tuple[str, MaskSide], list[OuterCopperRegion]] = defaultdict(list)
    for region in copper:
        copper_by_identity[(region.source_id, region.side)].append(region)

    apertures_by_side: dict[MaskSide, list[MaskAperture]] = defaultdict(list)
    for aperture in apertures:
        apertures_by_side[aperture.side].append(aperture)
    for side_apertures in apertures_by_side.values():
        side_apertures.sort(key=lambda item: (item.source_id, item.semantic_json()))

    results: list[CopperExposureResult] = []
    for identity in sorted(copper_by_identity, key=lambda item: (item[0], item[1].value)):
        definitions = copper_by_identity[identity]
        distinct = {item.semantic_json(): item for item in definitions}
        if len(distinct) > 1:
            results.append(
                CopperExposureResult(
                    copper_source_id=identity[0],
                    side=identity[1],
                    state="unknown",
                    role="unknown",
                    reason="duplicate copper identity has conflicting definitions",
                )
            )
            continue
        region = next(iter(distinct.values()))
        results.append(_classify_region(region, apertures_by_side[region.side]))
    return tuple(results)


def _classify_region(
    region: OuterCopperRegion, apertures: list[MaskAperture]
) -> CopperExposureResult:
    if region.verification is not CopperGeometryVerification.EXACT or region.geometry is None:
        return CopperExposureResult(
            copper_source_id=region.source_id,
            side=region.side,
            state="unknown",
            role=region.role,
            unresolved_aperture_source_ids=tuple(
                sorted(
                    {
                        aperture.source_id
                        for aperture in apertures
                        if aperture.verification is not MaskVerification.EXACT
                    }
                )
            ),
            reason="copper geometry is unsupported",
        )

    copper_parts = _primitive_parts(region.geometry)
    overlapping_parts: list[tuple[str, MaskPrimitive]] = []
    unresolved_ids: set[str] = set()
    for aperture in apertures:
        if aperture.verification is MaskVerification.EXACT:
            if aperture.geometry is None:  # guaranteed by the aperture model
                continue
            overlapping_parts.extend(
                (aperture.source_id, part)
                for part in _primitive_parts(aperture.geometry)
                if geometry_has_interior_overlap(region.geometry, part)
            )
        elif _unresolved_aperture_is_relevant(region.geometry, aperture):
            unresolved_ids.add(aperture.source_id)

    aperture_ids = tuple(sorted({source_id for source_id, _ in overlapping_parts}))
    unresolved = tuple(sorted(unresolved_ids))
    containment = [
        _primitive_contains_all(aperture_part, copper_parts)
        for _, aperture_part in overlapping_parts
    ]
    if ContainmentProof.CONTAINED in containment:
        return CopperExposureResult(
            copper_source_id=region.source_id,
            side=region.side,
            state="fully_exposed",
            role=region.role,
            aperture_source_ids=aperture_ids,
            unresolved_aperture_source_ids=unresolved,
            reason="one exact aperture primitive contains the complete copper region",
        )

    if unresolved:
        return CopperExposureResult(
            copper_source_id=region.source_id,
            side=region.side,
            state="unknown",
            role=region.role,
            aperture_source_ids=aperture_ids,
            unresolved_aperture_source_ids=unresolved,
            reason="a relevant aperture has unresolved geometry",
        )
    if not overlapping_parts:
        return CopperExposureResult(
            copper_source_id=region.source_id,
            side=region.side,
            state="masked",
            role=region.role,
            reason="no exact mask aperture has positive-area overlap",
        )
    if len(overlapping_parts) > 1:
        return CopperExposureResult(
            copper_source_id=region.source_id,
            side=region.side,
            state="unknown",
            role=region.role,
            aperture_source_ids=aperture_ids,
            reason="multiple aperture primitives overlap and union containment is unproven",
        )
    if containment[0] is ContainmentProof.UNKNOWN:
        return CopperExposureResult(
            copper_source_id=region.source_id,
            side=region.side,
            state="unknown",
            role=region.role,
            aperture_source_ids=aperture_ids,
            reason="primitive containment is unproven",
        )
    return CopperExposureResult(
        copper_source_id=region.source_id,
        side=region.side,
        state="partially_exposed",
        role=region.role,
        aperture_source_ids=aperture_ids,
        reason="one exact aperture primitive overlaps without containing the copper region",
    )


def _primitive_parts(geometry: MaskGeometry) -> tuple[MaskPrimitive, ...]:
    return geometry.parts if isinstance(geometry, Compound) else (geometry,)


def _unresolved_aperture_is_relevant(copper: MaskGeometry, aperture: MaskAperture) -> bool:
    if aperture.verification is MaskVerification.UNSUPPORTED:
        # Unsupported geometry has no quantitative error contract. Even when
        # nominal geometry is present, it cannot localize the uncertainty.
        return True
    if aperture.verification is not MaskVerification.BOUNDED_APPROXIMATION:
        return False
    if aperture.geometry is None or aperture.maximum_error_mm is None:
        return True  # Defensive fallback; the MaskAperture model rejects this.
    measurement = measure_geometry(copper, aperture.geometry)
    if measurement.relation is not ApertureRelation.SEPARATED:
        return True
    if measurement.web_mm is None:
        return True  # Defensive fallback; separated measurements always have a web.
    return measurement.web_mm <= (aperture.maximum_error_mm + MASK_GEOMETRY_EPSILON_MM)


def _primitive_contains_all(
    aperture: MaskPrimitive, copper_parts: tuple[MaskPrimitive, ...]
) -> ContainmentProof:
    proofs = tuple(primitive_contains(aperture, part) for part in copper_parts)
    if all(proof is ContainmentProof.CONTAINED for proof in proofs):
        return ContainmentProof.CONTAINED
    if any(proof is ContainmentProof.NOT_CONTAINED for proof in proofs):
        return ContainmentProof.NOT_CONTAINED
    return ContainmentProof.UNKNOWN
