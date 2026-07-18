"""Measured shaped-placement corpus for R5 reproducibility evidence.

The corpus deliberately measures retained neutral layouts only after each case
passes the real KiCad save/read-back and DRC gate.  It is compatibility
evidence, not a placement optimizer benchmark.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.kicad.board import BoardLayout
from pcbsmith.kicad.board_serialization import parse_canonical_board_layout_snapshot
from pcbsmith.kicad.placement_readback import (
    PlacementKiCadSaveRoundtripAuthority,
    verify_placement_kicad_save_roundtrip,
)
from pcbsmith.placement_ir import PlacementIrModel
from pcbsmith.placement_serialization_ir import PlacementSerializationAuthority

_LENGTH_BOUND_DENOMINATOR = 10**12
_NO_INFERENCE_STATEMENT = (
    "These measurements authorize only reproducibility and KiCad compatibility evidence; "
    "they authorize no performance, optimization, quality, or algorithm-superiority inference."
)
_DRC_PROJECT_POLICY = {
    "board": {
        "design_settings": {
            "rule_severities": {
                "footprint_filters_mismatch": "warning",
                "footprint_type_mismatch": "warning",
                "lib_footprint_mismatch": "ignore",
                "missing_courtyard": "warning",
                "track_not_centered_on_via": "warning",
                "tuning_profile_track_geometries": "warning",
            },
        }
    },
    "meta": {"version": 1},
}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# Defined after the canonical renderer without hiding a mutable module object
# inside retained evidence.
_DRC_PROJECT_POLICY_JSON = _canonical_json(_DRC_PROJECT_POLICY)


def _fraction(value: float) -> Fraction:
    """Interpret the neutral IR's shortest decimal float spelling exactly."""

    if not math.isfinite(value):
        raise ValueError("measured neutral-layout coordinate must be finite")
    return Fraction(str(value))


class RationalMeasurement(PlacementIrModel):
    """One exact, reduced rational in the declared unit."""

    schema_id: Literal["pcbsmith-rational-measurement"] = "pcbsmith-rational-measurement"
    schema_version: Literal[1] = 1
    numerator: int
    denominator: int = Field(gt=0)
    unit: Literal["mm", "mm2"]
    interpretation: Literal["exact_from_neutral_decimal_coordinates"] = (
        "exact_from_neutral_decimal_coordinates"
    )

    @model_validator(mode="after")
    def value_is_reduced(self) -> Self:
        reduced = Fraction(self.numerator, self.denominator)
        if (reduced.numerator, reduced.denominator) != (self.numerator, self.denominator):
            raise ValueError("rational measurement must be reduced")
        return self

    @classmethod
    def from_fraction(cls, value: Fraction, unit: Literal["mm", "mm2"]) -> Self:
        return cls(numerator=value.numerator, denominator=value.denominator, unit=unit)

    def as_fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)


class RoutedLengthInterval(PlacementIrModel):
    """Conservative routed-length interval, never a binary-float exact claim."""

    schema_id: Literal["pcbsmith-routed-length-interval"] = "pcbsmith-routed-length-interval"
    schema_version: Literal[1] = 1
    lower: RationalMeasurement
    upper: RationalMeasurement
    per_segment_bound_denominator: Literal[1000000000000] = 1000000000000
    interpretation: Literal["conservative_rational_bounds_from_neutral_decimal_coordinates"] = (
        "conservative_rational_bounds_from_neutral_decimal_coordinates"
    )

    @model_validator(mode="after")
    def bounds_are_coherent(self) -> Self:
        if self.lower.unit != "mm" or self.upper.unit != "mm":
            raise ValueError("routed-length interval bounds must use mm")
        if self.lower.as_fraction() > self.upper.as_fraction():
            raise ValueError("routed-length lower bound exceeds upper bound")
        return self


class ShapedPlacementMeasurements(PlacementIrModel):
    """Exactly rederivable measurements for one retained final neutral layout."""

    schema_id: Literal["pcbsmith-shaped-placement-measurements"] = (
        "pcbsmith-shaped-placement-measurements"
    )
    schema_version: Literal[1] = 1
    has_custom_outline: bool
    has_cutouts: bool
    has_mask_apertures: bool
    cutout_count: int = Field(ge=0)
    mask_aperture_count: int = Field(ge=0)
    front_placement_count: int = Field(ge=0)
    back_placement_count: int = Field(ge=0)
    placement_count: int = Field(ge=0)
    segment_count: int = Field(ge=0)
    via_count: int = Field(ge=0)
    zone_count: int = Field(ge=0)
    total_routed_length: RoutedLengthInterval
    outline_bounding_area: RationalMeasurement
    outer_outline_area: RationalMeasurement
    substrate_area_after_cutouts: RationalMeasurement
    drc_status: Literal["passed"] = "passed"
    drc_finding_count: Literal[0] = 0

    @model_validator(mode="after")
    def counts_are_coherent(self) -> Self:
        if self.front_placement_count + self.back_placement_count != self.placement_count:
            raise ValueError("front/back placement counts do not sum to placement_count")
        if self.has_cutouts != (self.cutout_count > 0):
            raise ValueError("cutout presence is inconsistent with cutout_count")
        if self.has_mask_apertures != (self.mask_aperture_count > 0):
            raise ValueError("mask-aperture presence is inconsistent with its count")
        if self.substrate_area_after_cutouts.as_fraction() <= 0:
            raise ValueError("measured substrate area must be positive")
        return self


class PlacementCorpusArtifactHashes(PlacementIrModel):
    schema_id: Literal["pcbsmith-placement-corpus-artifact-hashes"] = (
        "pcbsmith-placement-corpus-artifact-hashes"
    )
    schema_version: Literal[1] = 1
    final_layout_snapshot_sha256: str
    rendered_board_sha256: str
    saved_board_sha256: str
    drc_report_sha256: str
    drc_project_policy_sha256: str

    @field_validator(
        "final_layout_snapshot_sha256",
        "rendered_board_sha256",
        "saved_board_sha256",
        "drc_report_sha256",
        "drc_project_policy_sha256",
    )
    @classmethod
    def hashes_are_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("artifact hash must be lowercase SHA-256")
        return value


class PlacementCorpusDrcPolicy(PlacementIrModel):
    """Exact narrow KiCad policy used for generated embedded footprints."""

    schema_id: Literal["pcbsmith-placement-corpus-drc-policy"] = (
        "pcbsmith-placement-corpus-drc-policy"
    )
    schema_version: Literal[1] = 1
    project_json: str
    project_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    ignored_rule_ids: tuple[Literal["lib_footprint_mismatch"], ...] = ("lib_footprint_mismatch",)
    enforced_rule_ids: tuple[
        Literal[
            "footprint_filters_mismatch",
            "footprint_type_mismatch",
            "missing_courtyard",
            "track_not_centered_on_via",
            "tuning_profile_track_geometries",
        ],
        ...,
    ] = (
        "footprint_filters_mismatch",
        "footprint_type_mismatch",
        "missing_courtyard",
        "track_not_centered_on_via",
        "tuning_profile_track_geometries",
    )
    rationale: Literal[
        "Generated embedded footprints are authoritative; installed-library copy mismatch is "
        "not a physical geometry, connectivity, clearance, or manufacturability finding."
    ] = (
        "Generated embedded footprints are authoritative; installed-library copy mismatch is "
        "not a physical geometry, connectivity, clearance, or manufacturability finding."
    )

    @model_validator(mode="after")
    def policy_is_exact_and_narrow(self) -> Self:
        if self.project_json != _DRC_PROJECT_POLICY_JSON:
            raise ValueError("corpus DRC project policy differs from the exact narrow policy")
        if self.project_sha256 != _sha256_text(self.project_json):
            raise ValueError("corpus DRC project policy checksum is stale")
        if self.ignored_rule_ids != ("lib_footprint_mismatch",):
            raise ValueError("corpus DRC policy may ignore only lib_footprint_mismatch")
        if self.enforced_rule_ids != (
            "footprint_filters_mismatch",
            "footprint_type_mismatch",
            "missing_courtyard",
            "track_not_centered_on_via",
            "tuning_profile_track_geometries",
        ):
            raise ValueError("corpus DRC policy must enable every pinned default-ignored check")
        return self


_CORPUS_DRC_POLICY = PlacementCorpusDrcPolicy(
    project_json=_DRC_PROJECT_POLICY_JSON,
    project_sha256=_sha256_text(_DRC_PROJECT_POLICY_JSON),
)


class MeasuredShapedPlacementCase(PlacementIrModel):
    schema_id: Literal["pcbsmith-measured-shaped-placement-case"] = (
        "pcbsmith-measured-shaped-placement-case"
    )
    schema_version: Literal[1] = 1
    case_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    roundtrip_authority: PlacementKiCadSaveRoundtripAuthority
    drc_policy: PlacementCorpusDrcPolicy
    measurements: ShapedPlacementMeasurements
    artifact_hashes: PlacementCorpusArtifactHashes
    case_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def retained_case_is_rederivable(self) -> Self:
        roundtrip = PlacementKiCadSaveRoundtripAuthority.model_validate_json(
            self.roundtrip_authority.model_dump_json()
        )
        if roundtrip != self.roundtrip_authority:
            raise ValueError("roundtrip authority failed exact reconstruction")
        if not roundtrip.require_drc_pass or roundtrip.drc_status != "passed":
            raise ValueError("corpus case requires a passing mandatory DRC gate")
        if roundtrip.drc_findings:
            raise ValueError("corpus case cannot retain DRC findings")
        if self.drc_policy != _CORPUS_DRC_POLICY:
            raise ValueError("corpus case does not retain the exact narrow DRC policy")
        try:
            report = json.loads(roundtrip.drc_report_json)
        except json.JSONDecodeError as error:
            raise ValueError("corpus case DRC report is invalid JSON") from error
        ignored = report.get("ignored_checks") if isinstance(report, dict) else None
        if not isinstance(ignored, list) or any(not isinstance(item, dict) for item in ignored):
            raise ValueError("corpus case DRC report lacks typed ignored checks")
        ignored_ids = tuple(sorted(str(item.get("key", "")) for item in ignored))
        if ignored_ids != self.drc_policy.ignored_rule_ids:
            raise ValueError("corpus DRC report ignored checks differ from retained policy")
        layout = parse_canonical_board_layout_snapshot(
            roundtrip.serialization_authority.final_layout_snapshot_json
        )
        expected_measurements = _measure_layout(layout, roundtrip)
        if self.measurements != expected_measurements:
            raise ValueError("corpus case measurements are stale")
        expected_hashes = _artifact_hashes(roundtrip)
        if self.artifact_hashes != expected_hashes:
            raise ValueError("corpus case artifact hashes are stale")
        if len(roundtrip.saved_snapshot.footprints) != len(layout.placements):
            raise ValueError("saved KiCad footprint count differs from the neutral layout")
        if len(roundtrip.saved_snapshot.segments) != len(layout.segments):
            raise ValueError("saved KiCad segment count differs from the neutral layout")
        if len(roundtrip.saved_snapshot.vias) != len(layout.vias):
            raise ValueError("saved KiCad via count differs from the neutral layout")
        if len(roundtrip.saved_snapshot.zones) != len(layout.zones):
            raise ValueError("saved KiCad zone count differs from the neutral layout")
        expected_fingerprint = _case_fingerprint(
            self.case_id,
            roundtrip,
            self.drc_policy,
            expected_measurements,
            expected_hashes,
        )
        if self.case_fingerprint != expected_fingerprint:
            raise ValueError("corpus case fingerprint is stale")
        return self


class MeasuredShapedPlacementCorpus(PlacementIrModel):
    """Canonical multi-case KiCad compatibility evidence."""

    schema_id: Literal["pcbsmith-measured-shaped-placement-corpus"] = (
        "pcbsmith-measured-shaped-placement-corpus"
    )
    schema_version: Literal[1] = 1
    cases: tuple[MeasuredShapedPlacementCase, ...] = Field(min_length=2)
    kicad_cli_versions: tuple[str, ...] = Field(min_length=1)
    corpus_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorized_inference: Literal[
        "These measurements authorize only reproducibility and KiCad compatibility evidence; "
        "they authorize no performance, optimization, quality, or algorithm-superiority inference."
    ] = (
        "These measurements authorize only reproducibility and KiCad compatibility evidence; "
        "they authorize no performance, optimization, quality, or algorithm-superiority inference."
    )

    @model_validator(mode="after")
    def corpus_is_canonical_and_rederivable(self) -> Self:
        case_ids = tuple(case.case_id for case in self.cases)
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("measured corpus case IDs must be unique")
        canonical_cases = tuple(sorted(self.cases, key=lambda case: case.case_id))
        if self.cases != canonical_cases:
            raise ValueError("measured corpus cases must be ordered by case_id")
        versions = tuple(
            sorted({case.roundtrip_authority.kicad_cli_version for case in self.cases})
        )
        if self.kicad_cli_versions != versions:
            raise ValueError("measured corpus KiCad tool versions are stale")
        expected = _corpus_fingerprint(canonical_cases, versions)
        if self.corpus_fingerprint != expected:
            raise ValueError("measured corpus fingerprint is stale")
        return self


def _polygon_area(points: Sequence[tuple[float, float]]) -> Fraction:
    if len(points) < 3:
        raise ValueError("measured outline polygon requires at least three vertices")
    twice = Fraction(0)
    for index in range(len(points)):
        twice += _fraction(points[index][0]) * _fraction(
            points[(index + 1) % len(points)][1]
        ) - _fraction(points[(index + 1) % len(points)][0]) * _fraction(points[index][1])
    return abs(twice) / 2


def _length_interval(layout: BoardLayout) -> RoutedLengthInterval:
    lower = Fraction(0)
    upper = Fraction(0)
    scale = _LENGTH_BOUND_DENOMINATOR
    for segment in layout.segments:
        dx = _fraction(segment.x2) - _fraction(segment.x1)
        dy = _fraction(segment.y2) - _fraction(segment.y1)
        squared = dx * dx + dy * dy
        scaled_floor = math.isqrt((squared.numerator * scale * scale) // squared.denominator)
        segment_lower = Fraction(scaled_floor, scale)
        if segment_lower * segment_lower == squared:
            segment_upper = segment_lower
        else:
            segment_upper = Fraction(scaled_floor + 1, scale)
        lower += segment_lower
        upper += segment_upper
    return RoutedLengthInterval(
        lower=RationalMeasurement.from_fraction(lower, "mm"),
        upper=RationalMeasurement.from_fraction(upper, "mm"),
    )


def _measure_layout(
    layout: BoardLayout,
    roundtrip: PlacementKiCadSaveRoundtripAuthority,
) -> ShapedPlacementMeasurements:
    outline = layout.outline or (
        (0.0, 0.0),
        (layout.width_mm, 0.0),
        (layout.width_mm, layout.height_mm),
        (0.0, layout.height_mm),
    )
    xs = tuple(_fraction(point[0]) for point in outline)
    ys = tuple(_fraction(point[1]) for point in outline)
    bounding_area = (max(xs) - min(xs)) * (max(ys) - min(ys))
    outer_area = _polygon_area(outline)
    cutout_area = sum((_polygon_area(cutout.points) for cutout in layout.cutouts), Fraction(0))
    back = set(layout.part_flip)
    return ShapedPlacementMeasurements(
        has_custom_outline=layout.outline is not None,
        has_cutouts=bool(layout.cutouts),
        has_mask_apertures=bool(layout.mask_apertures),
        cutout_count=len(layout.cutouts),
        mask_aperture_count=len(layout.mask_apertures),
        front_placement_count=sum(
            component.reference not in back for component, _ in layout.placements
        ),
        back_placement_count=sum(component.reference in back for component, _ in layout.placements),
        placement_count=len(layout.placements),
        segment_count=len(layout.segments),
        via_count=len(layout.vias),
        zone_count=len(layout.zones),
        total_routed_length=_length_interval(layout),
        outline_bounding_area=RationalMeasurement.from_fraction(bounding_area, "mm2"),
        outer_outline_area=RationalMeasurement.from_fraction(outer_area, "mm2"),
        substrate_area_after_cutouts=RationalMeasurement.from_fraction(
            outer_area - cutout_area, "mm2"
        ),
        drc_status="passed",
        drc_finding_count=len(roundtrip.drc_findings),
    )


def _artifact_hashes(
    roundtrip: PlacementKiCadSaveRoundtripAuthority,
) -> PlacementCorpusArtifactHashes:
    serialization = roundtrip.serialization_authority
    return PlacementCorpusArtifactHashes(
        final_layout_snapshot_sha256=_sha256_text(serialization.final_layout_snapshot_json),
        rendered_board_sha256=serialization.rendered_board_sha256,
        saved_board_sha256=roundtrip.saved_board_sha256,
        drc_report_sha256=roundtrip.drc_report_sha256,
        drc_project_policy_sha256=_CORPUS_DRC_POLICY.project_sha256,
    )


def _case_fingerprint(
    case_id: str,
    roundtrip: PlacementKiCadSaveRoundtripAuthority,
    drc_policy: PlacementCorpusDrcPolicy,
    measurements: ShapedPlacementMeasurements,
    artifact_hashes: PlacementCorpusArtifactHashes,
) -> str:
    return _sha256_json(
        {
            "schema_id": "pcbsmith-measured-shaped-placement-case-fingerprint",
            "schema_version": 1,
            "case_id": case_id,
            "roundtrip_authority": roundtrip.model_dump(mode="json"),
            "drc_policy": drc_policy.model_dump(mode="json"),
            "measurements": measurements.model_dump(mode="json"),
            "artifact_hashes": artifact_hashes.model_dump(mode="json"),
        }
    )


def _build_case(
    case_id: str,
    roundtrip: PlacementKiCadSaveRoundtripAuthority,
) -> MeasuredShapedPlacementCase:
    layout = parse_canonical_board_layout_snapshot(
        roundtrip.serialization_authority.final_layout_snapshot_json
    )
    measurements = _measure_layout(layout, roundtrip)
    hashes = _artifact_hashes(roundtrip)
    return MeasuredShapedPlacementCase(
        case_id=case_id,
        roundtrip_authority=roundtrip,
        drc_policy=_CORPUS_DRC_POLICY,
        measurements=measurements,
        artifact_hashes=hashes,
        case_fingerprint=_case_fingerprint(
            case_id, roundtrip, _CORPUS_DRC_POLICY, measurements, hashes
        ),
    )


def _corpus_fingerprint(
    cases: tuple[MeasuredShapedPlacementCase, ...],
    versions: tuple[str, ...],
) -> str:
    return _sha256_json(
        {
            "schema_id": "pcbsmith-measured-shaped-placement-corpus-fingerprint",
            "schema_version": 1,
            "case_fingerprints": [case.case_fingerprint for case in cases],
            "kicad_cli_versions": versions,
            "authorized_inference": _NO_INFERENCE_STATEMENT,
        }
    )


def run_measured_shaped_placement_corpus(
    cases: Sequence[tuple[str, PlacementSerializationAuthority]],
    output_root: Path,
) -> MeasuredShapedPlacementCorpus:
    """Run two or more cases through real KiCad and retain exact measurements."""

    if len(cases) < 2:
        raise ValueError("measured shaped-placement corpus requires at least two cases")
    case_ids = tuple(case_id for case_id, _ in cases)
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("measured corpus case IDs must be unique")
    ordered: list[tuple[str, PlacementSerializationAuthority]] = []
    for case_id, authority in cases:
        if (
            not case_id
            or not case_id[0].isalnum()
            or any(not (character.isalnum() or character in "._-") for character in case_id)
        ):
            raise ValueError("measured corpus case_id is not a safe canonical identity")
        retained = PlacementSerializationAuthority.model_validate_json(authority.model_dump_json())
        if retained != authority:
            raise ValueError("corpus input serialization authority failed exact reconstruction")
        ordered.append((case_id, retained))
    measured: list[MeasuredShapedPlacementCase] = []
    for case_id, authority in sorted(ordered, key=lambda item: item[0]):
        case_root = output_root / case_id
        for run_index in (1, 2):
            run_root = case_root / f"run-{run_index}"
            run_root.mkdir(parents=True, exist_ok=True)
            (run_root / "placement-roundtrip.kicad_pro").write_text(
                _CORPUS_DRC_POLICY.project_json,
                encoding="utf-8",
            )
        roundtrip = verify_placement_kicad_save_roundtrip(
            authority,
            case_root,
            require_drc_pass=True,
        )
        measured.append(_build_case(case_id, roundtrip))
    canonical_cases = tuple(measured)
    versions = tuple(
        sorted({case.roundtrip_authority.kicad_cli_version for case in canonical_cases})
    )
    return MeasuredShapedPlacementCorpus(
        cases=canonical_cases,
        kicad_cli_versions=versions,
        corpus_fingerprint=_corpus_fingerprint(canonical_cases, versions),
    )
