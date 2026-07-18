"""Evidence-bound deterministic metrics for complete R4 bus route bundles."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from decimal import Decimal
from enum import StrEnum
from fractions import Fraction
from typing import Literal, Self

from pydantic import Field, model_validator

from pcbsmith.bus_allocator import BusLaneAllocationResult, allocate_bus_lanes
from pcbsmith.bus_geometry import CertifiedLaneGeometry, CertifiedLaneGeometryRegistry
from pcbsmith.bus_ir import BusGroup, ConstraintAuthority, CorridorCapacityCertificate
from pcbsmith.kicad.board import TrackSegment
from pcbsmith.kicad.bus_integration import CertifiedBusMemberPrefix
from pcbsmith.kicad.bus_transaction import BusRouteBundle
from pcbsmith.routing_ir import RoutingIrModel


class MetricAuthority(StrEnum):
    EXACT = "exact"
    BOUNDED = "bounded"
    UNVERIFIED = "unverified"


class RuleDisposition(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    ADVISORY = "advisory"
    HARD_CONSTRAINT_UNVERIFIED = "hard_constraint_unverified"
    NOT_APPLICABLE = "not_applicable"


class BusMetricsDisposition(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    HARD_CONSTRAINT_UNVERIFIED = "hard_constraint_unverified"


def _fraction_text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


class ExactAlgebraicWitness(RoutingIrModel):
    """Exact value ``rational + sqrt2 * sqrt(2)`` in the stated unit."""

    rational: str
    sqrt2: str
    unit: Literal["mm", "ps"]
    reporting_value: float

    @model_validator(mode="after")
    def fractions_are_canonical(self) -> Self:
        for field_name in ("rational", "sqrt2"):
            try:
                value = Fraction(getattr(self, field_name))
            except (ValueError, ZeroDivisionError) as error:
                raise ValueError(f"{field_name} must be a rational fraction") from error
            if getattr(self, field_name) != _fraction_text(value):
                raise ValueError(f"{field_name} must be a canonical rational fraction")
        expected = float(Fraction(self.rational)) + float(Fraction(self.sqrt2)) * math.sqrt(2)
        if not math.isclose(self.reporting_value, expected, rel_tol=0, abs_tol=1e-12):
            raise ValueError("algebraic reporting value does not match its exact witness")
        return self


class AlgebraicGridLength(RoutingIrModel):
    """Exact grid_mm * (orthogonal + diagonal * sqrt(2)) witness."""

    authority: MetricAuthority
    grid_mm: float = Field(gt=0)
    orthogonal_grid_units: int = Field(ge=0)
    diagonal_grid_units: int = Field(ge=0)
    value_mm: float = Field(ge=0)

    @model_validator(mode="after")
    def value_matches_witness(self) -> Self:
        expected = self.grid_mm * (
            self.orthogonal_grid_units + self.diagonal_grid_units * math.sqrt(2.0)
        )
        if self.authority is MetricAuthority.EXACT and not math.isclose(
            self.value_mm, expected, rel_tol=0, abs_tol=1e-12
        ):
            raise ValueError("exact length does not match its lattice witness")
        return self


class BusMemberMetrics(RoutingIrModel):
    member_id: str
    net_name: str
    trunk_length: AlgebraicGridLength
    pigtail_length: AlgebraicGridLength
    total_length: AlgebraicGridLength
    via_count: int = Field(ge=0)
    transition_count: int = Field(ge=0)
    realized_transition_via_count: int = Field(ge=0)


class AdjacentPitchMetric(RoutingIrModel):
    section_id: str
    layer: Literal["F.Cu", "B.Cu"]
    first_member_id: str
    second_member_id: str
    authority: MetricAuthority
    translation_grid: tuple[int, int] | None = None
    pitch_squared_grid_units: int | None = Field(default=None, ge=0)
    pitch_mm: float | None = Field(default=None, ge=0)
    edge_clearance_mm: float | None = None
    parallel_length_mm: float | None = Field(default=None, ge=0)


class SectionPitchMetrics(RoutingIrModel):
    section_id: str
    layer: Literal["F.Cu", "B.Cu"]
    authority: MetricAuthority
    adjacent: tuple[AdjacentPitchMetric, ...]
    minimum_pitch_mm: float | None = Field(default=None, ge=0)
    maximum_pitch_mm: float | None = Field(default=None, ge=0)
    maximum_pitch_deviation_mm: float | None = Field(default=None, ge=0)
    maximum_pitch_deviation_witness: ExactAlgebraicWitness | None = None
    minimum_edge_clearance_mm: float | None = None


class BusOrderMetrics(RoutingIrModel):
    authority: MetricAuthority
    declared_boundary_orders: tuple[tuple[str, tuple[str, ...]], ...]
    realized_section_entry_orders: tuple[tuple[str, str, tuple[str, ...]], ...]
    realized_final_exit_order: tuple[str, tuple[str, ...]] | None
    permutation_boundary_ids: tuple[str, ...]
    reversal_allowed: bool
    allocation_reversal_count: int = Field(ge=0)
    declared_swap_window_ids: tuple[str, ...]
    allocation_swap_count: int = Field(ge=0)
    allocation_swap_window_ids: tuple[str, ...]
    physical_swap_count: Literal[0] = 0
    order_violation_count: int = Field(ge=0)
    unverified_reasons: tuple[str, ...] = ()


class BusAggregateMetrics(RoutingIrModel):
    member_length_spread_mm: float = Field(ge=0)
    member_length_spread_witness: ExactAlgebraicWitness | None = None
    member_length_spread_authority: MetricAuthority
    via_count_spread: int = Field(ge=0)
    transition_count_spread: int = Field(ge=0)
    maximum_parallel_run_mm: float | None = Field(default=None, ge=0)
    maximum_parallel_run_witness: ExactAlgebraicWitness | None = None
    parallel_run_authority: MetricAuthority
    pairwise_coherent_length_mm: float | None = Field(default=None, ge=0)
    pairwise_coherent_length_witness: ExactAlgebraicWitness | None = None
    pairwise_eligible_length_mm: float = Field(ge=0)
    pairwise_eligible_length_witness: ExactAlgebraicWitness | None = None
    pairwise_coherence_fraction: float | None = Field(default=None, ge=0, le=1)
    coherence_semantics: Literal["adjacent_pair_length_weighted-v1"] = (
        "adjacent_pair_length_weighted-v1"
    )
    coherence_authority: MetricAuthority
    certificate_span_length_mm: float = Field(ge=0)
    certificate_span_length_witness: ExactAlgebraicWitness | None = None
    certificate_span_authority: MetricAuthority
    modeled_delay_spread_ps: float | None = Field(default=None, ge=0)
    modeled_delay_spread_witness: ExactAlgebraicWitness | None = None
    modeled_delay_authority: MetricAuthority


class PropagationDelayModel(RoutingIrModel):
    model_id: str
    delay_ps_per_mm_by_member: tuple[tuple[str, str], ...]

    @model_validator(mode="after")
    def canonical(self) -> Self:
        entries = tuple(sorted(self.delay_ps_per_mm_by_member))
        if not entries or len({key for key, _ in entries}) != len(entries):
            raise ValueError("propagation entries must uniquely cover members")
        for key, value in entries:
            try:
                decimal = Decimal(value)
            except Exception as error:
                raise ValueError("propagation entries must be canonical decimals") from error
            canonical = format(decimal.normalize(), "f")
            if decimal == 0:
                canonical = "0"
            if not key or not decimal.is_finite() or decimal < 0 or value != canonical:
                raise ValueError("propagation entries must be canonical non-negative decimals")
        object.__setattr__(self, "delay_ps_per_mm_by_member", entries)
        return self


class BusMetricValidationContext(RoutingIrModel):
    confirmed_applicability_conditions: tuple[str, ...] = ()
    completed_validation_method_ids: tuple[str, ...] = ()
    validated_stackup_ids: tuple[str, ...] = ()
    validated_reference_structure_ids: tuple[str, ...] = ()
    propagation_models: tuple[PropagationDelayModel, ...] = ()
    coherence_model_id: str | None = None

    @model_validator(mode="after")
    def canonical(self) -> Self:
        for name in (
            "confirmed_applicability_conditions",
            "completed_validation_method_ids",
            "validated_stackup_ids",
            "validated_reference_structure_ids",
        ):
            original = getattr(self, name)
            values = tuple(sorted(set(original)))
            if len(values) != len(original) or any(not item for item in values):
                raise ValueError(f"{name} must be unique non-empty identities")
            object.__setattr__(self, name, values)
        models = tuple(sorted(self.propagation_models, key=lambda item: item.model_id))
        if len({item.model_id for item in models}) != len(models):
            raise ValueError("propagation model IDs must be unique")
        object.__setattr__(self, "propagation_models", models)
        return self


class BusRuleEvaluation(RoutingIrModel):
    rule_id: str
    disposition: RuleDisposition
    enforcement: Literal["intrinsic", "advisory", "hard"]
    metric_authority: MetricAuthority
    measured_value: float | None = None
    limit_value: float | None = None
    satisfied: bool | None = None
    evidence_ids: tuple[str, ...] = ()
    applicability_condition_ids: tuple[str, ...] = ()
    validation_method_ids: tuple[str, ...] = ()
    missing_inputs: tuple[str, ...] = ()


class BusMetricsInputEnvelope(RoutingIrModel):
    bundle: BusRouteBundle
    certificate: CorridorCapacityCertificate
    geometry_registry: CertifiedLaneGeometryRegistry
    prefixes: tuple[CertifiedBusMemberPrefix, ...]
    validation_context: BusMetricValidationContext

    @model_validator(mode="after")
    def prefixes_are_canonical(self) -> Self:
        prefixes = tuple(sorted(self.prefixes, key=lambda item: item.member_id))
        if len({item.member_id for item in prefixes}) != len(prefixes):
            raise ValueError("metric input prefixes must be unique per member")
        object.__setattr__(self, "prefixes", prefixes)
        return self


class BusMetricsReport(RoutingIrModel):
    schema_id: Literal["pcbsmith-bus-metrics-report"] = "pcbsmith-bus-metrics-report"
    schema_version: Literal[1] = 1
    inputs: BusMetricsInputEnvelope
    disposition: BusMetricsDisposition
    bundle_fingerprint: str
    certificate_fingerprint: str
    geometry_registry_fingerprint: str
    prefix_fingerprints: tuple[tuple[str, str], ...]
    members: tuple[BusMemberMetrics, ...]
    section_pitch: tuple[SectionPitchMetrics, ...]
    order: BusOrderMetrics
    aggregate: BusAggregateMetrics
    rules: tuple[BusRuleEvaluation, ...]
    report_fingerprint: str

    @model_validator(mode="after")
    def complete_report_replays_exactly(self) -> Self:
        expected = _measure(self.inputs, validate=False)
        if self.model_dump(mode="json") != expected.model_dump(mode="json"):
            raise ValueError("bus metrics report fails complete deterministic replay")
        return self


def _hash(payload: object) -> str:
    raw = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def _reconstructs_integer_grid(value: float, index: int, grid_mm: float) -> bool:
    reconstructed = index * grid_mm
    envelope = 8 * max(
        math.ulp(value),
        math.ulp(reconstructed),
        abs(index) * math.ulp(grid_mm),
    )
    return math.isfinite(value) and abs(value - reconstructed) <= envelope


def _length(segments: Sequence[TrackSegment], grid_mm: float) -> AlgebraicGridLength:
    orthogonal = diagonal = 0
    fallback = 0.0
    exact = True
    for segment in segments:
        fallback += math.hypot(segment.x2 - segment.x1, segment.y2 - segment.y1)
        coords = (segment.x1, segment.y1, segment.x2, segment.y2)
        indexes = tuple(round(value / grid_mm) for value in coords)
        if any(
            not _reconstructs_integer_grid(value, index, grid_mm)
            for value, index in zip(coords, indexes, strict=True)
        ):
            exact = False
            continue
        dx, dy = abs(indexes[2] - indexes[0]), abs(indexes[3] - indexes[1])
        if not dx or not dy:
            orthogonal += dx + dy
        elif dx == dy:
            diagonal += dx
        else:
            exact = False
    value = grid_mm * (orthogonal + diagonal * math.sqrt(2)) if exact else fallback
    return AlgebraicGridLength(
        authority=MetricAuthority.EXACT if exact else MetricAuthority.UNVERIFIED,
        grid_mm=grid_mm,
        orthogonal_grid_units=orthogonal,
        diagonal_grid_units=diagonal,
        value_mm=value,
    )


def _subtract(whole: AlgebraicGridLength, part: AlgebraicGridLength) -> AlgebraicGridLength:
    orthogonal = whole.orthogonal_grid_units - part.orthogonal_grid_units
    diagonal = whole.diagonal_grid_units - part.diagonal_grid_units
    exact = (
        whole.authority is part.authority is MetricAuthority.EXACT
        and orthogonal >= 0
        and diagonal >= 0
    )
    if not exact:
        orthogonal, diagonal = max(0, orthogonal), max(0, diagonal)
    value = (
        whole.grid_mm * (orthogonal + diagonal * math.sqrt(2))
        if exact
        else max(0.0, whole.value_mm - part.value_mm)
    )
    return AlgebraicGridLength(
        authority=MetricAuthority.EXACT if exact else MetricAuthority.UNVERIFIED,
        grid_mm=whole.grid_mm,
        orthogonal_grid_units=orthogonal,
        diagonal_grid_units=diagonal,
        value_mm=value,
    )


def _geometry_segments(
    geometry: CertifiedLaneGeometry, net: str, width: float
) -> tuple[TrackSegment, ...]:
    return tuple(
        TrackSegment(
            x1=a[0] * geometry.grid_mm,
            y1=a[1] * geometry.grid_mm,
            x2=b[0] * geometry.grid_mm,
            y2=b[1] * geometry.grid_mm,
            layer=geometry.layer,
            net_name=net,
            width_mm=width,
        )
        for a, b in zip(geometry.points, geometry.points[1:], strict=False)
    )


def _pitch(
    first: CertifiedLaneGeometry,
    second: CertifiedLaneGeometry,
    first_id: str,
    second_id: str,
    first_width: float,
    second_width: float,
) -> AdjacentPitchMetric:
    deltas = (
        tuple((b[0] - a[0], b[1] - a[1]) for a, b in zip(first.points, second.points, strict=True))
        if len(first.points) == len(second.points)
        else ()
    )
    vectors = tuple(
        (b[0] - a[0], b[1] - a[1]) for a, b in zip(first.points, first.points[1:], strict=False)
    )
    second_vectors = tuple(
        (b[0] - a[0], b[1] - a[1]) for a, b in zip(second.points, second.points[1:], strict=False)
    )
    if (
        not deltas
        or len(set(deltas)) != 1
        or deltas[0] == (0, 0)
        or vectors != second_vectors
        or any(deltas[0][0] * dx + deltas[0][1] * dy != 0 for dx, dy in vectors)
    ):
        return AdjacentPitchMetric(
            section_id=first.section_id,
            layer=first.layer,
            first_member_id=first_id,
            second_member_id=second_id,
            authority=MetricAuthority.UNVERIFIED,
        )
    delta = deltas[0]
    squared = delta[0] ** 2 + delta[1] ** 2
    pitch = first.grid_mm * math.sqrt(squared)
    first_length = _length(_geometry_segments(first, first_id, first_width), first.grid_mm)
    second_length = _length(_geometry_segments(second, second_id, second_width), second.grid_mm)
    parallel = first_length.value_mm if first_length == second_length else None
    return AdjacentPitchMetric(
        section_id=first.section_id,
        layer=first.layer,
        first_member_id=first_id,
        second_member_id=second_id,
        authority=MetricAuthority.EXACT,
        translation_grid=delta,
        pitch_squared_grid_units=squared,
        pitch_mm=pitch,
        edge_clearance_mm=pitch - (first_width + second_width) / 2,
        parallel_length_mm=parallel,
    )


def _pitch_clearance_satisfied(
    sections: Sequence[SectionPitchMetrics],
    limit: float | None,
    member_widths: Mapping[str, float],
    grid_mm: float,
) -> bool | None:
    if limit is None:
        return None
    grid = Fraction(str(grid_mm))
    seen = False
    for section in sections:
        for metric in section.adjacent:
            seen = True
            if (
                metric.authority is not MetricAuthority.EXACT
                or metric.pitch_squared_grid_units is None
            ):
                return None
            required = (
                Fraction(str(limit))
                + (
                    Fraction(str(member_widths[metric.first_member_id]))
                    + Fraction(str(member_widths[metric.second_member_id]))
                )
                / 2
            )
            if required > 0 and grid * grid * metric.pitch_squared_grid_units < required * required:
                return False
    return True if seen else None


def _evidence_ids(authority: ConstraintAuthority) -> tuple[str, ...]:
    return tuple(
        sorted(
            item.source_id or item.local_sha256 or _hash(item.model_dump(mode="json"))
            for item in authority.evidence
        )
    )


def _authority_missing(
    authority: ConstraintAuthority, context: BusMetricValidationContext, extra: Sequence[str]
) -> tuple[str, ...]:
    missing = list(extra)
    applied = set(context.confirmed_applicability_conditions)
    completed = set(context.completed_validation_method_ids)
    missing.extend(
        f"applicability:{item}"
        for item in authority.applicability_conditions
        if item not in applied
    )
    missing.extend(
        f"validation:{item}" for item in authority.validation_method_ids if item not in completed
    )
    return tuple(sorted(set(missing)))


def _algebraic_sign(rational: Fraction, sqrt2: Fraction) -> int:
    if sqrt2 == 0:
        return (rational > 0) - (rational < 0)
    if rational == 0 or (rational > 0) == (sqrt2 > 0):
        return (sqrt2 > 0) - (sqrt2 < 0)
    rational_dominates = rational * rational > 2 * sqrt2 * sqrt2
    dominant = rational if rational_dominates else sqrt2
    return (dominant > 0) - (dominant < 0)


def _algebraic_compare(first: tuple[Fraction, Fraction], second: tuple[Fraction, Fraction]) -> int:
    return _algebraic_sign(first[0] - second[0], first[1] - second[1])


def _length_coefficients(length: AlgebraicGridLength) -> tuple[Fraction, Fraction] | None:
    if length.authority is not MetricAuthority.EXACT:
        return None
    grid = Fraction(str(length.grid_mm))
    return grid * length.orthogonal_grid_units, grid * length.diagonal_grid_units


def _spread_witness(
    values: Sequence[tuple[Fraction, Fraction]], unit: Literal["mm", "ps"]
) -> ExactAlgebraicWitness | None:
    if not values:
        return None
    low = high = values[0]
    for value in values[1:]:
        if _algebraic_compare(value, low) < 0:
            low = value
        if _algebraic_compare(value, high) > 0:
            high = value
    rational, sqrt2 = high[0] - low[0], high[1] - low[1]
    return ExactAlgebraicWitness(
        rational=_fraction_text(rational),
        sqrt2=_fraction_text(sqrt2),
        unit=unit,
        reporting_value=float(rational) + float(sqrt2) * math.sqrt(2),
    )


def _sum_witness(
    values: Sequence[tuple[Fraction, Fraction]], unit: Literal["mm", "ps"]
) -> ExactAlgebraicWitness | None:
    if not values:
        return None
    rational = sum((item[0] for item in values), start=Fraction())
    sqrt2 = sum((item[1] for item in values), start=Fraction())
    return ExactAlgebraicWitness(
        rational=_fraction_text(rational),
        sqrt2=_fraction_text(sqrt2),
        unit=unit,
        reporting_value=float(rational) + float(sqrt2) * math.sqrt(2),
    )


def _maximum_witness(
    values: Sequence[tuple[Fraction, Fraction]], unit: Literal["mm", "ps"]
) -> ExactAlgebraicWitness | None:
    if not values:
        return None
    maximum = values[0]
    for value in values[1:]:
        if _algebraic_compare(value, maximum) > 0:
            maximum = value
    return ExactAlgebraicWitness(
        rational=_fraction_text(maximum[0]),
        sqrt2=_fraction_text(maximum[1]),
        unit=unit,
        reporting_value=float(maximum[0]) + float(maximum[1]) * math.sqrt(2),
    )


def _pitch_coefficients(
    metric: AdjacentPitchMetric, grid_mm: float
) -> tuple[Fraction, Fraction] | None:
    if metric.authority is not MetricAuthority.EXACT or metric.translation_grid is None:
        return None
    dx, dy = abs(metric.translation_grid[0]), abs(metric.translation_grid[1])
    grid = Fraction(str(grid_mm))
    if dx == 0 or dy == 0:
        return grid * (dx + dy), Fraction()
    if dx == dy:
        return Fraction(), grid * dx
    return None


def _ratio_satisfies_minimum(
    numerator: ExactAlgebraicWitness | None,
    denominator: ExactAlgebraicWitness | None,
    limit: float | None,
) -> bool | None:
    if numerator is None or denominator is None or limit is None:
        return None
    factor = Fraction(str(limit))
    return (
        _algebraic_sign(
            Fraction(numerator.rational) - factor * Fraction(denominator.rational),
            Fraction(numerator.sqrt2) - factor * Fraction(denominator.sqrt2),
        )
        >= 0
    )


def _witness_satisfies_limit(
    witness: ExactAlgebraicWitness | None,
    limit: float | None,
    comparison: Literal["maximum", "minimum"],
) -> bool | None:
    if witness is None or limit is None:
        return None
    sign = _algebraic_sign(
        Fraction(witness.rational) - Fraction(str(limit)),
        Fraction(witness.sqrt2),
    )
    return sign <= 0 if comparison == "maximum" else sign >= 0


def _rule(
    *,
    rule_id: str,
    authority: ConstraintAuthority | None,
    metric_authority: MetricAuthority,
    measured: float | None,
    limit: float | None,
    comparison: Literal["maximum", "minimum"],
    context: BusMetricValidationContext,
    extra: Sequence[str] = (),
    intrinsic: bool = False,
    empty_is_not_applicable: bool = False,
    exact_satisfied: bool | None = None,
) -> BusRuleEvaluation:
    enforcement: Literal["intrinsic", "advisory", "hard"] = (
        "intrinsic" if intrinsic else (authority.enforcement if authority else "advisory")
    )
    evidence = () if authority is None else _evidence_ids(authority)
    conditions = () if authority is None else authority.applicability_conditions
    methods = () if authority is None else authority.validation_method_ids
    if limit is None or (empty_is_not_applicable and measured is None):
        return BusRuleEvaluation(
            rule_id=rule_id,
            disposition=RuleDisposition.NOT_APPLICABLE,
            enforcement=enforcement,
            metric_authority=metric_authority,
            evidence_ids=evidence,
            applicability_condition_ids=conditions,
            validation_method_ids=methods,
        )
    missing = () if intrinsic else _authority_missing(authority, context, extra)  # type: ignore[arg-type]
    if measured is None or metric_authority is not MetricAuthority.EXACT:
        missing = tuple(sorted(set((*missing, "exact_metric"))))
    if intrinsic and measured is not None:
        left, right = Decimal(str(measured)), Decimal(str(limit))
        satisfied = left <= right if comparison == "maximum" else left >= right
    elif exact_satisfied is not None:
        satisfied = exact_satisfied
    elif enforcement == "advisory" and measured is not None:
        left, right = Decimal(str(measured)), Decimal(str(limit))
        satisfied = left <= right if comparison == "maximum" else left >= right
    else:
        satisfied = None
        missing = tuple(sorted(set((*missing, "exact_comparison"))))
    if enforcement == "hard" and missing:
        disposition = RuleDisposition.HARD_CONSTRAINT_UNVERIFIED
    elif enforcement == "advisory":
        disposition = RuleDisposition.ADVISORY
    else:
        disposition = RuleDisposition.PASS if satisfied else RuleDisposition.FAIL
    return BusRuleEvaluation(
        rule_id=rule_id,
        disposition=disposition,
        enforcement=enforcement,
        metric_authority=metric_authority,
        measured_value=measured,
        limit_value=limit,
        satisfied=satisfied if not missing or enforcement == "advisory" else None,
        evidence_ids=evidence,
        applicability_condition_ids=conditions,
        validation_method_ids=methods,
        missing_inputs=missing,
    )


def _measure_order(
    bus: BusGroup,
    certificate: CorridorCapacityCertificate,
    allocation: BusLaneAllocationResult,
) -> BusOrderMetrics:
    boundaries = tuple(bus.boundaries)
    sections = certificate.sections
    if len(boundaries) != len(sections) + 1:
        raise ValueError("bus boundaries must equal certificate sections plus one")
    normalized_orders = tuple(allocation.normalized_boundary_orders)
    if len(normalized_orders) != len(boundaries):
        raise ValueError("allocation boundary orders do not exactly cover bus boundaries")
    boundary_by_portal = {item.corridor_portal_id: item for item in boundaries}
    if len(boundary_by_portal) != len(boundaries):
        raise ValueError("bus boundary portal identities must be unique")
    order_by_boundary_id = {
        boundary.boundary_id: normalized_orders[index] for index, boundary in enumerate(boundaries)
    }
    assignments = tuple(allocation.assignments)
    realized_entries: list[tuple[str, str, tuple[str, ...]]] = []
    violations = 0
    unverified: list[str] = []
    for index, section in enumerate(sections):
        entry_boundary = boundary_by_portal.get(section.entry_portal_id)
        if entry_boundary is None:
            raise ValueError(f"section {section.section_id!r} has no entry boundary portal")
        if index > 0 and sections[index - 1].exit_portal_id != section.entry_portal_id:
            raise ValueError("certificate section chain has an explicit portal mismatch")
        actual = tuple(
            item.member_id
            for item in sorted(
                (item for item in assignments if item.section_id == section.section_id),
                key=lambda item: item.order_index,
            )
        )
        declared = order_by_boundary_id[entry_boundary.boundary_id]
        entry_events = tuple(
            item
            for item in allocation.activations
            if item.boundary_id == entry_boundary.boundary_id
        )
        if entry_events:
            complete = len(actual) == len(declared) and set(actual) == set(declared)
            if not complete:
                event_kinds = {
                    "activation" if item.kind == "activate" else "deactivation"
                    for item in entry_events
                }
                unverified.extend(
                    f"boundary_{kind}_geometry_unreplayed" for kind in sorted(event_kinds)
                )
            else:
                violations += actual != declared
        else:
            expected = tuple(member_id for member_id in declared if member_id in set(actual))
            violations += actual != expected
        realized_entries.append((section.section_id, entry_boundary.boundary_id, actual))
    final_boundary = boundary_by_portal.get(sections[-1].exit_portal_id)
    if final_boundary is None:
        raise ValueError("final certificate exit portal has no bus boundary")
    if final_boundary.boundary_id in {item[1] for item in realized_entries}:
        raise ValueError("final exit boundary cannot also be a section entry boundary")
    swap_count = int(allocation.swap_count)
    final_order: tuple[str, tuple[str, ...]] | None = None
    if swap_count:
        unverified.append("physical_swap_carriers_absent")
    final_events = tuple(
        item for item in allocation.activations if item.boundary_id == final_boundary.boundary_id
    )
    if final_events:
        unverified.append("final_boundary_activation_geometry_unreplayed")
    if allocation.permutation_boundary_ids:
        unverified.append("physical_boundary_permutation_unreplayed")
    authority = MetricAuthority.UNVERIFIED if unverified else MetricAuthority.EXACT
    if authority is MetricAuthority.EXACT:
        final_actual = realized_entries[-1][2]
        final_expected = order_by_boundary_id[final_boundary.boundary_id]
        violations += final_actual != final_expected
        final_order = (final_boundary.boundary_id, final_actual)
    reasons = tuple(sorted(set(unverified)))
    return BusOrderMetrics(
        authority=authority,
        declared_boundary_orders=tuple(
            (boundary.boundary_id, order_by_boundary_id[boundary.boundary_id])
            for boundary in boundaries
        ),
        realized_section_entry_orders=tuple(realized_entries),
        realized_final_exit_order=final_order,
        permutation_boundary_ids=tuple(allocation.permutation_boundary_ids),
        reversal_allowed=bool(bus.permutation_policy.allow_whole_bundle_reversal),
        allocation_reversal_count=int(allocation.reversal_count),
        declared_swap_window_ids=tuple(
            item.window_id for item in bus.permutation_policy.swap_windows
        ),
        allocation_swap_count=swap_count,
        allocation_swap_window_ids=tuple(sorted({item.window_id for item in allocation.swaps})),
        order_violation_count=violations,
        unverified_reasons=reasons,
    )


def measure_bus_route_bundle(
    bundle: BusRouteBundle,
    certificate: CorridorCapacityCertificate,
    geometry_registry: CertifiedLaneGeometryRegistry,
    prefixes_by_member: Mapping[str, CertifiedBusMemberPrefix],
    *,
    context: BusMetricValidationContext | None = None,
) -> BusMetricsReport:
    """Measure a complete bundle and retain every replay authority."""
    fixed_context = context or BusMetricValidationContext()
    inputs = BusMetricsInputEnvelope(
        bundle=bundle,
        certificate=certificate,
        geometry_registry=geometry_registry,
        prefixes=tuple(prefixes_by_member.values()),
        validation_context=fixed_context,
    )
    return _measure(inputs, validate=True)


def _measure(inputs: BusMetricsInputEnvelope, *, validate: bool) -> BusMetricsReport:
    bundle = inputs.bundle
    certificate = inputs.certificate
    geometry_registry = inputs.geometry_registry
    context = inputs.validation_context
    prefixes_by_member = {item.member_id: item for item in inputs.prefixes}
    bus, allocation = bundle.bus, bundle.allocation
    certificate_fp = certificate.semantic_fingerprint()
    if allocation != allocate_bus_lanes(bus, certificate, budget=allocation.budget):
        raise ValueError("lane allocation fails deterministic nested replay")
    if allocation.certificate_fingerprint != certificate_fp:
        raise ValueError("bundle allocation is stale against its certificate")
    if (
        geometry_registry.certificate_fingerprint != certificate_fp
        or geometry_registry.allocation_fingerprint != allocation.allocation_fingerprint
        or geometry_registry.grid_mm != certificate.grid_mm
    ):
        raise ValueError("lane geometry registry authority is stale")
    members_by_id = {item.member_id: item for item in bus.members}
    if set(prefixes_by_member) != set(members_by_id):
        raise ValueError("certified prefixes must exactly cover bus members")
    routes_by_net = bundle.by_net()
    for member_id, prefix in prefixes_by_member.items():
        prefix.require_authority(bus, certificate, allocation, geometry_registry)
        route = routes_by_net[prefix.net_name]
        if (
            route.prefix_alternative_id != prefix.prefix.alternative_id
            or route.prefix_fingerprint != prefix.prefix_fingerprint
        ):
            raise ValueError(f"route prefix binding is stale for {member_id}")

    geometry_by_id = {item.centerline_geometry_id: item for item in geometry_registry.geometries}
    section_index = {item.section_id: index for index, item in enumerate(certificate.sections)}
    assignments = tuple(
        sorted(
            allocation.assignments,
            key=lambda item: (section_index[item.section_id], item.order_index),
        )
    )
    slots = {
        (section.section_id, slot.slot_id): slot
        for section in certificate.sections
        for slot in section.lane_slots
    }
    member_metrics: list[BusMemberMetrics] = []
    for member_id in sorted(members_by_id):
        member = members_by_id[member_id]
        prefix = prefixes_by_member[member_id]
        route = routes_by_net[member.net_name]
        active = tuple(item for item in assignments if item.member_id == member_id)
        trunk_segments = tuple(
            segment
            for item in active
            for segment in _geometry_segments(
                geometry_by_id[slots[(item.section_id, item.slot_id)].centerline_geometry_id],
                member.net_name,
                member.width_mm,
            )
        )
        trunk = _length(trunk_segments, certificate.grid_mm)
        pigtail = _subtract(_length(prefix.prefix.segments, certificate.grid_mm), trunk)
        total = _length(route.result.segments, certificate.grid_mm)
        member_metrics.append(
            BusMemberMetrics(
                member_id=member_id,
                net_name=member.net_name,
                trunk_length=trunk,
                pigtail_length=pigtail,
                total_length=total,
                via_count=len(route.result.vias),
                transition_count=sum(
                    item.member_id == member_id for item in allocation.layer_transitions
                ),
                realized_transition_via_count=len(prefix.transition_via_fingerprints),
            )
        )

    pitch_sections: list[SectionPitchMetrics] = []
    pairwise_eligible_values: list[tuple[Fraction, Fraction]] = []
    pairwise_coherent_values: list[tuple[Fraction, Fraction]] = []
    parallel_values: list[tuple[Fraction, Fraction]] = []
    certificate_span_values: list[tuple[Fraction, Fraction]] = []
    pairwise_supported = True
    certificate_span_supported = True
    for section in certificate.sections:
        section_assignments = tuple(
            item for item in assignments if item.section_id == section.section_id
        )
        if section_assignments:
            span_assignment = min(section_assignments, key=lambda item: item.order_index)
            span_geometry = geometry_by_id[
                slots[(section.section_id, span_assignment.slot_id)].centerline_geometry_id
            ]
            span_length = _length(
                _geometry_segments(
                    span_geometry,
                    span_assignment.member_id,
                    members_by_id[span_assignment.member_id].width_mm,
                ),
                span_geometry.grid_mm,
            )
            span_coefficients = _length_coefficients(span_length)
            if span_coefficients is None:
                certificate_span_supported = False
            else:
                certificate_span_values.append(span_coefficients)
        for layer in ("F.Cu", "B.Cu"):
            layered = tuple(
                sorted(
                    (item for item in section_assignments if item.layer == layer),
                    key=lambda item: item.order_index,
                )
            )
            if len(layered) < 2:
                continue
            adjacent: list[AdjacentPitchMetric] = []
            pitch_values: list[tuple[Fraction, Fraction]] = []
            for first, second in zip(layered, layered[1:], strict=False):
                first_geometry = geometry_by_id[
                    slots[(section.section_id, first.slot_id)].centerline_geometry_id
                ]
                second_geometry = geometry_by_id[
                    slots[(section.section_id, second.slot_id)].centerline_geometry_id
                ]
                baseline = _length(
                    _geometry_segments(
                        first_geometry,
                        first.member_id,
                        members_by_id[first.member_id].width_mm,
                    ),
                    first_geometry.grid_mm,
                )
                baseline_coefficients = _length_coefficients(baseline)
                if baseline_coefficients is None:
                    pairwise_supported = False
                else:
                    pairwise_eligible_values.append(baseline_coefficients)
                metric = _pitch(
                    first_geometry,
                    second_geometry,
                    first.member_id,
                    second.member_id,
                    members_by_id[first.member_id].width_mm,
                    members_by_id[second.member_id].width_mm,
                )
                adjacent.append(metric)
                pitch_coefficients = _pitch_coefficients(metric, first_geometry.grid_mm)
                if pitch_coefficients is not None:
                    pitch_values.append(pitch_coefficients)
                if (
                    metric.authority is MetricAuthority.EXACT
                    and metric.parallel_length_mm is not None
                    and baseline_coefficients is not None
                ):
                    pairwise_coherent_values.append(baseline_coefficients)
                    parallel_values.append(baseline_coefficients)
                else:
                    pairwise_supported = False
            exact = len(pitch_values) == len(adjacent)
            pitches = [item.pitch_mm for item in adjacent if item.pitch_mm is not None]
            clearances = [
                item.edge_clearance_mm for item in adjacent if item.edge_clearance_mm is not None
            ]
            deviation_witness = _spread_witness(pitch_values, "mm") if exact else None
            pitch_sections.append(
                SectionPitchMetrics(
                    section_id=section.section_id,
                    layer=layer,
                    authority=(MetricAuthority.EXACT if exact else MetricAuthority.UNVERIFIED),
                    adjacent=tuple(adjacent),
                    minimum_pitch_mm=min(pitches) if exact else None,
                    maximum_pitch_mm=max(pitches) if exact else None,
                    maximum_pitch_deviation_mm=(
                        None if deviation_witness is None else deviation_witness.reporting_value
                    ),
                    maximum_pitch_deviation_witness=deviation_witness,
                    minimum_edge_clearance_mm=min(clearances) if exact else None,
                )
            )

    order = _measure_order(bus, certificate, allocation)

    lengths = [item.total_length.value_mm for item in member_metrics]
    vias = [item.via_count for item in member_metrics]
    transitions = [item.transition_count for item in member_metrics]
    all_pitch_exact = all(item.authority is MetricAuthority.EXACT for item in pitch_sections)
    pairwise_eligible_witness = _sum_witness(pairwise_eligible_values, "mm")
    pairwise_coherent_witness = _sum_witness(pairwise_coherent_values, "mm")
    maximum_parallel_witness = _maximum_witness(parallel_values, "mm")
    certificate_span_witness = (
        _sum_witness(certificate_span_values, "mm") if certificate_span_supported else None
    )
    pairwise_fraction = (
        pairwise_coherent_witness.reporting_value / pairwise_eligible_witness.reporting_value
        if pairwise_supported
        and pairwise_coherent_witness is not None
        and pairwise_eligible_witness is not None
        and pairwise_eligible_witness.reporting_value > 0
        else None
    )
    length_coefficients = [
        coefficients
        for item in member_metrics
        if (coefficients := _length_coefficients(item.total_length)) is not None
    ]
    length_spread_witness = (
        _spread_witness(length_coefficients, "mm")
        if len(length_coefficients) == len(member_metrics)
        else None
    )

    timing = bus.timing_budget
    delay_spread_witness: ExactAlgebraicWitness | None = None
    propagation_missing: tuple[str, ...] = ()
    if timing and (
        timing.maximum_skew_ps is not None or timing.maximum_delay_spread_ps is not None
    ):
        model = next(
            (
                item
                for item in context.propagation_models
                if item.model_id == timing.propagation_model_id
            ),
            None,
        )
        if timing.propagation_model_id is None:
            propagation_missing = ("propagation_model_id",)
        elif model is None:
            propagation_missing = (f"propagation_model:{timing.propagation_model_id}",)
        else:
            rates = {
                member_id: Fraction(value) for member_id, value in model.delay_ps_per_mm_by_member
            }
            if set(rates) != set(members_by_id):
                propagation_missing = ("propagation_model_member_coverage",)
            else:
                delay_values: list[tuple[Fraction, Fraction]] = []
                for item in member_metrics:
                    coefficients = _length_coefficients(item.total_length)
                    if coefficients is None:
                        break
                    rate = rates[item.member_id]
                    delay_values.append((coefficients[0] * rate, coefficients[1] * rate))
                if len(delay_values) == len(member_metrics):
                    delay_spread_witness = _spread_witness(delay_values, "ps")
    delay_spread = None if delay_spread_witness is None else delay_spread_witness.reporting_value

    aggregate = BusAggregateMetrics(
        member_length_spread_mm=(
            max(lengths) - min(lengths)
            if length_spread_witness is None
            else length_spread_witness.reporting_value
        ),
        member_length_spread_witness=length_spread_witness,
        member_length_spread_authority=(
            MetricAuthority.EXACT
            if length_spread_witness is not None
            else MetricAuthority.UNVERIFIED
        ),
        via_count_spread=max(vias) - min(vias),
        transition_count_spread=max(transitions) - min(transitions),
        maximum_parallel_run_mm=(
            None if maximum_parallel_witness is None else maximum_parallel_witness.reporting_value
        ),
        maximum_parallel_run_witness=maximum_parallel_witness,
        parallel_run_authority=(
            MetricAuthority.EXACT
            if maximum_parallel_witness is not None and pairwise_supported
            else MetricAuthority.UNVERIFIED
        ),
        pairwise_coherent_length_mm=(
            None if pairwise_coherent_witness is None else pairwise_coherent_witness.reporting_value
        ),
        pairwise_coherent_length_witness=pairwise_coherent_witness,
        pairwise_eligible_length_mm=(
            0.0 if pairwise_eligible_witness is None else pairwise_eligible_witness.reporting_value
        ),
        pairwise_eligible_length_witness=pairwise_eligible_witness,
        pairwise_coherence_fraction=pairwise_fraction,
        coherence_authority=(
            MetricAuthority.EXACT
            if pairwise_supported and pairwise_eligible_witness is not None
            else MetricAuthority.UNVERIFIED
        ),
        certificate_span_length_mm=(
            0.0 if certificate_span_witness is None else certificate_span_witness.reporting_value
        ),
        certificate_span_length_witness=certificate_span_witness,
        certificate_span_authority=(
            MetricAuthority.EXACT
            if certificate_span_witness is not None
            else MetricAuthority.UNVERIFIED
        ),
        modeled_delay_spread_ps=delay_spread,
        modeled_delay_spread_witness=delay_spread_witness,
        modeled_delay_authority=(
            MetricAuthority.EXACT
            if delay_spread_witness is not None
            else MetricAuthority.UNVERIFIED
        ),
    )
    rules: list[BusRuleEvaluation] = []
    via_policy = bus.layer_policy.via_policy
    rules.append(
        _rule(
            rule_id="bus.via.maximum_per_member",
            authority=None,
            metric_authority=MetricAuthority.EXACT,
            measured=float(max(vias)),
            limit=float(via_policy.maximum_vias_per_member),
            comparison="maximum",
            context=context,
            intrinsic=True,
        )
    )
    rules.append(
        _rule(
            rule_id="bus.via.maximum_count_spread",
            authority=None,
            metric_authority=MetricAuthority.EXACT,
            measured=float(aggregate.via_count_spread),
            limit=None
            if via_policy.maximum_via_count_spread is None
            else float(via_policy.maximum_via_count_spread),
            comparison="maximum",
            context=context,
            intrinsic=True,
        )
    )
    if timing:
        rules.extend(
            (
                _rule(
                    rule_id="bus.timing.maximum_length_spread_mm",
                    authority=timing.authority,
                    metric_authority=aggregate.member_length_spread_authority,
                    measured=aggregate.member_length_spread_mm,
                    limit=timing.maximum_length_spread_mm,
                    comparison="maximum",
                    context=context,
                    exact_satisfied=_witness_satisfies_limit(
                        aggregate.member_length_spread_witness,
                        timing.maximum_length_spread_mm,
                        "maximum",
                    ),
                ),
                _rule(
                    rule_id="bus.timing.maximum_skew_ps",
                    authority=timing.authority,
                    metric_authority=aggregate.modeled_delay_authority,
                    measured=delay_spread,
                    limit=timing.maximum_skew_ps,
                    comparison="maximum",
                    context=context,
                    extra=propagation_missing,
                    exact_satisfied=_witness_satisfies_limit(
                        aggregate.modeled_delay_spread_witness,
                        timing.maximum_skew_ps,
                        "maximum",
                    ),
                ),
                _rule(
                    rule_id="bus.timing.maximum_delay_spread_ps",
                    authority=timing.authority,
                    metric_authority=aggregate.modeled_delay_authority,
                    measured=delay_spread,
                    limit=timing.maximum_delay_spread_ps,
                    comparison="maximum",
                    context=context,
                    extra=propagation_missing,
                    exact_satisfied=_witness_satisfies_limit(
                        aggregate.modeled_delay_spread_witness,
                        timing.maximum_delay_spread_ps,
                        "maximum",
                    ),
                ),
            )
        )
    coupling = bus.coupling_budget
    if coupling:
        missing: list[str] = []
        if coupling.stackup_id is None:
            missing.append("stackup_id")
        elif coupling.stackup_id not in context.validated_stackup_ids:
            missing.append(f"stackup:{coupling.stackup_id}")
        if coupling.reference_structure_id is None:
            missing.append("reference_structure_id")
        elif coupling.reference_structure_id not in context.validated_reference_structure_ids:
            missing.append(f"reference_structure:{coupling.reference_structure_id}")
        clearances = [
            item.minimum_edge_clearance_mm
            for item in pitch_sections
            if item.minimum_edge_clearance_mm is not None
        ]
        clearance_authority = (
            MetricAuthority.EXACT if all_pitch_exact and clearances else MetricAuthority.UNVERIFIED
        )
        rules.extend(
            (
                _rule(
                    rule_id="bus.coupling.adjacent_member_clearance_mm",
                    authority=coupling.authority,
                    metric_authority=clearance_authority,
                    measured=min(clearances) if clearances else None,
                    limit=coupling.adjacent_member_clearance_mm,
                    comparison="minimum",
                    context=context,
                    extra=missing,
                    exact_satisfied=_pitch_clearance_satisfied(
                        pitch_sections,
                        coupling.adjacent_member_clearance_mm,
                        {key: value.width_mm for key, value in members_by_id.items()},
                        certificate.grid_mm,
                    ),
                ),
                _rule(
                    rule_id="bus.coupling.maximum_parallel_run_mm",
                    authority=coupling.authority,
                    metric_authority=aggregate.parallel_run_authority,
                    measured=aggregate.maximum_parallel_run_mm,
                    limit=coupling.maximum_parallel_run_mm,
                    comparison="maximum",
                    context=context,
                    extra=missing,
                    exact_satisfied=_witness_satisfies_limit(
                        aggregate.maximum_parallel_run_witness,
                        coupling.maximum_parallel_run_mm,
                        "maximum",
                    ),
                ),
            )
        )
    coherence = bus.coherence_policy
    if coherence:
        deviation_values = [
            (
                Fraction(section.maximum_pitch_deviation_witness.rational),
                Fraction(section.maximum_pitch_deviation_witness.sqrt2),
            )
            for section in pitch_sections
            if section.maximum_pitch_deviation_witness is not None
        ]
        maximum_deviation_witness = (
            _maximum_witness(deviation_values, "mm")
            if len(deviation_values) == len(pitch_sections) and pitch_sections
            else None
        )
        coherence_model_missing = (
            ()
            if context.coherence_model_id == "adjacent_pair_length_weighted-v1"
            else ("coherence_model:adjacent_pair_length_weighted-v1",)
        )
        rules.extend(
            (
                _rule(
                    rule_id="bus.coherence.maximum_pitch_deviation_mm",
                    authority=coherence.authority,
                    metric_authority=(
                        MetricAuthority.EXACT
                        if maximum_deviation_witness is not None
                        else MetricAuthority.UNVERIFIED
                    ),
                    measured=(
                        None
                        if maximum_deviation_witness is None
                        else maximum_deviation_witness.reporting_value
                    ),
                    limit=coherence.maximum_pitch_deviation_mm,
                    comparison="maximum",
                    context=context,
                    exact_satisfied=_witness_satisfies_limit(
                        maximum_deviation_witness,
                        coherence.maximum_pitch_deviation_mm,
                        "maximum",
                    ),
                ),
                _rule(
                    rule_id="bus.coherence.minimum_pairwise_fraction",
                    authority=coherence.authority,
                    metric_authority=aggregate.coherence_authority,
                    measured=aggregate.pairwise_coherence_fraction,
                    limit=coherence.minimum_coherence_fraction,
                    comparison="minimum",
                    context=context,
                    extra=coherence_model_missing,
                    empty_is_not_applicable=(aggregate.pairwise_eligible_length_witness is None),
                    exact_satisfied=_ratio_satisfies_minimum(
                        aggregate.pairwise_coherent_length_witness,
                        aggregate.pairwise_eligible_length_witness,
                        coherence.minimum_coherence_fraction,
                    ),
                ),
                _rule(
                    rule_id="bus.coherence.maximum_order_violations",
                    authority=coherence.authority,
                    metric_authority=order.authority,
                    measured=float(order.order_violation_count),
                    limit=float(coherence.maximum_order_violations),
                    comparison="maximum",
                    context=context,
                    exact_satisfied=(
                        order.order_violation_count <= coherence.maximum_order_violations
                        if order.authority is MetricAuthority.EXACT
                        else None
                    ),
                ),
            )
        )
    rules.sort(key=lambda item: item.rule_id)
    disposition = (
        BusMetricsDisposition.FAIL
        if any(item.disposition is RuleDisposition.FAIL for item in rules)
        else BusMetricsDisposition.HARD_CONSTRAINT_UNVERIFIED
        if any(item.disposition is RuleDisposition.HARD_CONSTRAINT_UNVERIFIED for item in rules)
        else BusMetricsDisposition.PASS
    )
    canonical_members = tuple(member_metrics)
    canonical_pitch = tuple(sorted(pitch_sections, key=lambda item: (item.section_id, item.layer)))
    canonical_rules = tuple(rules)
    prefix_fingerprints = tuple(
        (member_id, prefixes_by_member[member_id].composition_fingerprint)
        for member_id in sorted(prefixes_by_member)
    )
    provisional = BusMetricsReport.model_construct(
        inputs=inputs,
        disposition=disposition,
        bundle_fingerprint=bundle.semantic_fingerprint(),
        certificate_fingerprint=certificate_fp,
        geometry_registry_fingerprint=geometry_registry.semantic_fingerprint(),
        prefix_fingerprints=prefix_fingerprints,
        members=canonical_members,
        section_pitch=canonical_pitch,
        order=order,
        aggregate=aggregate,
        rules=canonical_rules,
        report_fingerprint="0" * 64,
    )
    payload = provisional.model_dump(mode="json")
    payload.pop("report_fingerprint")
    fingerprint = _hash(payload)
    fields = dict(
        inputs=inputs,
        disposition=disposition,
        bundle_fingerprint=bundle.semantic_fingerprint(),
        certificate_fingerprint=certificate_fp,
        geometry_registry_fingerprint=geometry_registry.semantic_fingerprint(),
        prefix_fingerprints=prefix_fingerprints,
        members=canonical_members,
        section_pitch=canonical_pitch,
        order=order,
        aggregate=aggregate,
        rules=canonical_rules,
        report_fingerprint=fingerprint,
    )
    if validate:
        return BusMetricsReport(**fields)
    return BusMetricsReport.model_construct(**fields)  # type: ignore[arg-type]
