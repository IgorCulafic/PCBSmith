"""Exact evaluator for replay-bound package/class-specific neighbor overhang."""

from __future__ import annotations

from dataclasses import asdict
from fractions import Fraction
from math import isqrt
from typing import Any

from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.neighbor_overhang_ir import (
    ActiveElectricalClearance,
    BoardCoordinateNeighborGeometry,
    ExactCopperGapWitness,
    ExactPostToleranceGap,
    NeighborCopperGapFinding,
    NeighborGeometryRole,
    NeighborOverhangDeclaration,
    NeighborOverhangFinding,
    NeighborOverhangRequirement,
    NeighborOverhangResult,
    NeighborRuleVerdict,
    NeighborToleranceModel,
    OverhangDirection,
    fingerprint,
    neighbor_full_context_fingerprint,
)
from pcbsmith.placement_geometry import compound_distance_witness
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticVerification,
)

_EXCLUDED_CLAIMS = (
    "board_mutation",
    "manufacturing_process_reliability",
    "package_family_inference",
    "solder_joint_reliability",
)


def _binding_is_complete(
    binding: EvidenceApplicabilityBinding,
    reviewer_record_id: str,
) -> bool:
    evidence_conditions = {
        condition for item in binding.evidence for condition in item.required_conditions
    }
    return (
        binding.reviewer_record_id == reviewer_record_id
        and bool(binding.required_conditions)
        and not binding.unmatched_conditions
        and set(binding.matched_conditions) == set(binding.required_conditions)
        and evidence_conditions == set(binding.required_conditions)
        and bool(binding.evidence)
        and all(
            item.source_status == "pinned"
            and item.local_sha256 is not None
            and item.locator_status in {"text_verified", "figure_verified", "figure_bound"}
            and item.applicability_status == "confirmed"
            and bool(item.required_conditions)
            for item in binding.evidence
        )
    )


def _object_binding_complete(
    obj: Any,
    object_id: str,
    bindings: dict[str, EvidenceApplicabilityBinding],
    reviewer_record_id: str,
) -> bool:
    return bool(obj.source_binding_ids) and all(
        binding_id in bindings
        and _binding_is_complete(bindings[binding_id], reviewer_record_id)
        and bindings[binding_id].claim_id == object_id
        and bindings[binding_id].geometry_source_fingerprint == obj.semantic_fingerprint()
        for binding_id in obj.source_binding_ids
    )


def _axis_extrema_um(
    geometry: BoardCoordinateNeighborGeometry, direction: OverhangDirection
) -> tuple[int, int]:
    assert geometry.compound is not None
    axis = 0 if direction in {OverhangDirection.X_NEGATIVE, OverhangDirection.X_POSITIVE} else 1
    values = tuple(
        int(Fraction(str(point[axis])) * 1000)
        for polygon in geometry.compound.polygons
        for boundary in (polygon.outer, *polygon.holes)
        for point in boundary
    )
    return min(values), max(values)


def _overhang_um(
    terminal: BoardCoordinateNeighborGeometry,
    pad: BoardCoordinateNeighborGeometry,
    direction: OverhangDirection,
) -> tuple[int, int, int]:
    terminal_minimum, terminal_maximum = _axis_extrema_um(terminal, direction)
    pad_minimum, pad_maximum = _axis_extrema_um(pad, direction)
    if direction in {OverhangDirection.X_NEGATIVE, OverhangDirection.Y_NEGATIVE}:
        measured = max(0, pad_minimum - terminal_minimum)
    else:
        measured = max(0, terminal_maximum - pad_maximum)
    return (
        measured,
        terminal_maximum - terminal_minimum,
        pad_maximum - pad_minimum,
    )


def _fraction_text(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def _gap_witness(
    terminal: BoardCoordinateNeighborGeometry,
    adjacent: tuple[BoardCoordinateNeighborGeometry, ...],
) -> ExactCopperGapWitness | None:
    if terminal.compound is None or any(item.compound is None for item in adjacent):
        return None
    candidates = []
    for item in adjacent:
        assert item.compound is not None
        witness = compound_distance_witness(terminal.compound, item.compound)
        candidates.append((witness.squared_distance, item.geometry_id, item, witness))
    if not candidates:
        return None
    _, _, selected, witness = min(candidates, key=lambda item: (item[0], item[1]))
    squared_um = witness.squared_distance * 1_000_000
    points = tuple(
        coordinate * 1000
        for point in (witness.first_point, witness.second_point)
        for coordinate in point
    )
    return ExactCopperGapWitness(
        terminal_geometry_id=terminal.geometry_id,
        adjacent_copper_geometry_id=selected.geometry_id,
        adjacent_copper_source_geometry_id=selected.source_geometry_id,
        relation=witness.relation.value,
        squared_distance_um2_numerator=squared_um.numerator,
        squared_distance_um2_denominator=squared_um.denominator,
        terminal_point_x_um=_fraction_text(points[0]),
        terminal_point_y_um=_fraction_text(points[1]),
        copper_point_x_um=_fraction_text(points[2]),
        copper_point_y_um=_fraction_text(points[3]),
    )


def _post_gap(witness: ExactCopperGapWitness, deduction_um: int) -> ExactPostToleranceGap:
    numerator = witness.squared_distance_um2_numerator
    denominator = witness.squared_distance_um2_denominator
    root_numerator = isqrt(numerator)
    root_denominator = isqrt(denominator)
    exact = (
        root_numerator * root_numerator == numerator
        and root_denominator * root_denominator == denominator
        and root_numerator % root_denominator == 0
    )
    measured = root_numerator // root_denominator if exact else None
    return ExactPostToleranceGap(
        measured_squared_um2_numerator=numerator,
        measured_squared_um2_denominator=denominator,
        tolerance_deduction_um=deduction_um,
        exact_measured_gap_um=measured,
        exact_post_tolerance_gap_um=None if measured is None else measured - deduction_um,
    )


def _selected_context(
    declaration: NeighborOverhangDeclaration,
) -> tuple[
    NeighborOverhangRequirement | None,
    NeighborToleranceModel | None,
    ActiveElectricalClearance | None,
    tuple[str, ...],
]:
    reasons: list[str] = []
    if declaration.selected_acceptance_class is None:
        return None, None, None, ("selected_acceptance_class_missing",)
    matches = tuple(
        item
        for item in declaration.requirements
        if item.acceptance_class == declaration.selected_acceptance_class
        and item.package_geometry_kind is declaration.package_geometry_kind
        and item.package_identity == declaration.package_identity
        and item.component_reference == declaration.component_reference
    )
    if len(matches) != 1:
        return None, None, None, ("applicable_package_class_rule_missing_or_ambiguous",)
    rule = matches[0]
    tolerances = tuple(
        item
        for item in declaration.tolerance_models
        if item.tolerance_model_id == rule.tolerance_model_id
    )
    clearances = tuple(
        item for item in declaration.clearances if item.clearance_id == rule.clearance_id
    )
    if len(tolerances) != 1:
        reasons.append("tolerance_model_missing_or_ambiguous")
    if len(clearances) != 1:
        reasons.append("active_clearance_missing_or_ambiguous")
    return (
        rule,
        tolerances[0] if len(tolerances) == 1 else None,
        clearances[0] if len(clearances) == 1 else None,
        tuple(reasons),
    )


def _authority_reasons(
    declaration: NeighborOverhangDeclaration,
    rule: NeighborOverhangRequirement,
    tolerance: NeighborToleranceModel,
    clearance: ActiveElectricalClearance,
    geometries: tuple[BoardCoordinateNeighborGeometry, ...],
) -> tuple[str, ...]:
    if rule.authority is SemanticAuthorityClass.ADVISORY_HYPOTHESIS:
        return ("advisory_authority",)
    reasons: list[str] = []
    if rule.authority is SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT:
        reasons.append("qualified_process_record_missing")
    elif rule.authority is not SemanticAuthorityClass.HARD_GEOMETRY:
        reasons.append("hard_package_class_authority_missing")
    review = rule.review
    if review is None:
        reasons.append("review_missing")
        return tuple(reasons)
    if review.status != "active":
        reasons.append("review_not_active")
    netlist = parse_canonical_board_netlist_snapshot(declaration.board_netlist_snapshot_json)
    component = next(
        item for item in netlist.components if item.reference == declaration.component_reference
    )
    expected_context = neighbor_full_context_fingerprint(
        board_layout_snapshot_fingerprint_value=declaration.board_layout_snapshot_fingerprint,
        board_netlist_snapshot_fingerprint_value=declaration.board_netlist_snapshot_fingerprint,
        component_fingerprint=fingerprint(asdict(component)),
        package_geometry_kind=declaration.package_geometry_kind,
        package_identity=declaration.package_identity,
        acceptance_class=rule.acceptance_class,
        geometries=geometries,
        tolerance=tolerance,
        clearance=clearance,
        requirement=rule,
    )
    if review.full_context_fingerprint != expected_context:
        reasons.append("review_full_context_mismatch")
    bindings = {item.binding_id: item for item in declaration.evidence_bindings}
    objects = (
        *((item, item.geometry_id) for item in geometries),
        (tolerance, tolerance.tolerance_model_id),
        (clearance, clearance.clearance_id),
        (rule, rule.requirement_id),
        (review, review.review_id),
    )
    for obj, object_id in objects:
        if not _object_binding_complete(
            obj,
            object_id,
            bindings,
            review.reviewer_record_id,
        ):
            reasons.append(f"unconfirmed_object_binding:{object_id}")
    return tuple(sorted(set(reasons)))


def _unverified_findings(
    declaration: NeighborOverhangDeclaration,
    reasons: tuple[str, ...],
    *,
    rule: NeighborOverhangRequirement | None = None,
    measured: int | None = None,
    span: int | None = None,
    pad_span: int | None = None,
    witness: ExactCopperGapWitness | None = None,
    tolerance: NeighborToleranceModel | None = None,
    clearance: ActiveElectricalClearance | None = None,
) -> tuple[NeighborOverhangFinding, NeighborCopperGapFinding]:
    deduction = (
        None
        if tolerance is None
        else tolerance.placement_tolerance_um + tolerance.fabrication_tolerance_um
    )
    post = None if witness is None or deduction is None else _post_gap(witness, deduction)
    common = {
        "requirement_id": None if rule is None else rule.requirement_id,
        "acceptance_class": declaration.selected_acceptance_class,
        "package_geometry_kind": declaration.package_geometry_kind,
        "component_reference": declaration.component_reference,
        "verdict": NeighborRuleVerdict.PROCESS_REVIEW_REQUIRED,
        "disposition": SemanticDisposition.UNVERIFIED,
        "verification": SemanticVerification.UNSUPPORTED,
        "reason_ids": tuple(sorted(set(reasons))),
    }
    return (
        NeighborOverhangFinding(
            **common,
            direction=None if rule is None else rule.allowed_overhang_direction,
            measured_terminal_overhang_um=measured,
            terminal_span_um=span,
            pad_span_um=pad_span,
            fraction_reference_span_um=(
                None if span is None or pad_span is None else min(span, pad_span)
            ),
            allowed_terminal_overhang_numerator_um=None,
            allowed_terminal_overhang_denominator=None,
            placement_tolerance_um=None if tolerance is None else tolerance.placement_tolerance_um,
            fabrication_tolerance_um=(
                None if tolerance is None else tolerance.fabrication_tolerance_um
            ),
            total_tolerance_deduction_um=deduction,
            worst_case_terminal_overhang_um=(
                None if measured is None or deduction is None else measured + deduction
            ),
        ),
        NeighborCopperGapFinding(
            **common,
            witness=witness,
            placement_tolerance_um=None if tolerance is None else tolerance.placement_tolerance_um,
            fabrication_tolerance_um=(
                None if tolerance is None else tolerance.fabrication_tolerance_um
            ),
            total_tolerance_deduction_um=deduction,
            post_tolerance_gap=post,
            minimum_rule_gap_um=(
                None if rule is None else rule.minimum_post_tolerance_copper_gap_um
            ),
            active_electrical_clearance_um=(
                None if clearance is None else clearance.clearance_um
            ),
        ),
    )


def _derive_findings(
    declaration: NeighborOverhangDeclaration,
) -> tuple[NeighborOverhangFinding, NeighborCopperGapFinding]:
    rule, tolerance, clearance, context_reasons = _selected_context(declaration)
    roles = {
        role: tuple(item for item in declaration.geometries if item.role is role)
        for role in NeighborGeometryRole
    }
    geometry_reasons: list[str] = []
    if len(roles[NeighborGeometryRole.PAD]) != 1:
        geometry_reasons.append("pad_geometry_missing_or_ambiguous")
    if len(roles[NeighborGeometryRole.TERMINAL]) != 1:
        geometry_reasons.append("terminal_geometry_missing_or_ambiguous")
    if not roles[NeighborGeometryRole.ADJACENT_COPPER]:
        geometry_reasons.append("adjacent_copper_geometry_missing")
    if any(item.verification is not SemanticVerification.EXACT for item in declaration.geometries):
        geometry_reasons.append("unsupported_geometry")
    if geometry_reasons:
        return _unverified_findings(
            declaration,
            tuple((*context_reasons, *geometry_reasons)),
            rule=rule,
            tolerance=tolerance,
            clearance=clearance,
        )
    pad = roles[NeighborGeometryRole.PAD][0]
    terminal = roles[NeighborGeometryRole.TERMINAL][0]
    adjacent = roles[NeighborGeometryRole.ADJACENT_COPPER]
    assert pad.compound is not None and terminal.compound is not None
    witness = _gap_witness(terminal, adjacent)
    if witness is None:
        return _unverified_findings(
            declaration,
            tuple((*context_reasons, "gap_witness_unavailable")),
            rule=rule,
            tolerance=tolerance,
            clearance=clearance,
        )
    if rule is None:
        return _unverified_findings(declaration, context_reasons, witness=witness)
    measured, span, pad_span = _overhang_um(
        terminal,
        pad,
        rule.allowed_overhang_direction,
    )
    if tolerance is None or clearance is None:
        return _unverified_findings(
            declaration,
            context_reasons,
            rule=rule,
            measured=measured,
            span=span,
            pad_span=pad_span,
            witness=witness,
            tolerance=tolerance,
            clearance=clearance,
        )
    authority_reasons = _authority_reasons(
        declaration, rule, tolerance, clearance, declaration.geometries
    )
    if authority_reasons and authority_reasons != ("advisory_authority",):
        return _unverified_findings(
            declaration, authority_reasons, rule=rule, measured=measured, span=span,
            pad_span=pad_span,
            witness=witness, tolerance=tolerance, clearance=clearance
        )
    deduction = tolerance.placement_tolerance_um + tolerance.fabrication_tolerance_um
    absolute_limit = rule.maximum_terminal_overhang_um
    fraction_numerator = rule.maximum_terminal_overhang_fraction_numerator
    fraction_denominator = rule.maximum_terminal_overhang_fraction_denominator
    allowed_limits: list[Fraction] = []
    if absolute_limit is not None:
        allowed_limits.append(Fraction(absolute_limit))
    if fraction_numerator is not None and fraction_denominator is not None:
        allowed_limits.append(
            Fraction(min(span, pad_span) * fraction_numerator, fraction_denominator)
        )
    allowed = min(allowed_limits)
    worst_overhang = measured + deduction
    overhang_passes = Fraction(worst_overhang) <= allowed
    post = _post_gap(witness, deduction)
    required_gap = max(rule.minimum_post_tolerance_copper_gap_um, clearance.clearance_um)
    required_measured = required_gap + deduction
    gap_passes = Fraction(
        witness.squared_distance_um2_numerator,
        witness.squared_distance_um2_denominator,
    ) >= required_measured * required_measured
    advisory = authority_reasons == ("advisory_authority",)
    disposition_overhang = (
        SemanticDisposition.ADVISORY
        if advisory
        else SemanticDisposition.PASS if overhang_passes else SemanticDisposition.FAIL
    )
    disposition_gap = (
        SemanticDisposition.ADVISORY
        if advisory
        else SemanticDisposition.PASS if gap_passes else SemanticDisposition.FAIL
    )
    verdict_overhang = (
        NeighborRuleVerdict.PROCESS_REVIEW_REQUIRED
        if advisory
        else NeighborRuleVerdict.PASS if overhang_passes else NeighborRuleVerdict.FAIL
    )
    verdict_gap = (
        NeighborRuleVerdict.PROCESS_REVIEW_REQUIRED
        if advisory
        else NeighborRuleVerdict.PASS if gap_passes else NeighborRuleVerdict.FAIL
    )
    reason_ids = ("advisory_authority_cannot_hard_decide",) if advisory else ()
    overhang = NeighborOverhangFinding(
        requirement_id=rule.requirement_id,
        acceptance_class=declaration.selected_acceptance_class,
        package_geometry_kind=declaration.package_geometry_kind,
        component_reference=declaration.component_reference,
        direction=rule.allowed_overhang_direction,
        measured_terminal_overhang_um=measured,
        terminal_span_um=span,
        pad_span_um=pad_span,
        fraction_reference_span_um=min(span, pad_span),
        allowed_terminal_overhang_numerator_um=allowed.numerator,
        allowed_terminal_overhang_denominator=allowed.denominator,
        placement_tolerance_um=tolerance.placement_tolerance_um,
        fabrication_tolerance_um=tolerance.fabrication_tolerance_um,
        total_tolerance_deduction_um=deduction,
        worst_case_terminal_overhang_um=worst_overhang,
        verdict=verdict_overhang,
        disposition=disposition_overhang,
        verification=SemanticVerification.EXACT,
        reason_ids=reason_ids,
    )
    gap = NeighborCopperGapFinding(
        requirement_id=rule.requirement_id,
        acceptance_class=declaration.selected_acceptance_class,
        package_geometry_kind=declaration.package_geometry_kind,
        component_reference=declaration.component_reference,
        witness=witness,
        placement_tolerance_um=tolerance.placement_tolerance_um,
        fabrication_tolerance_um=tolerance.fabrication_tolerance_um,
        total_tolerance_deduction_um=deduction,
        post_tolerance_gap=post,
        minimum_rule_gap_um=rule.minimum_post_tolerance_copper_gap_um,
        active_electrical_clearance_um=clearance.clearance_um,
        verdict=verdict_gap,
        disposition=disposition_gap,
        verification=SemanticVerification.EXACT,
        reason_ids=reason_ids,
    )
    return overhang, gap


def rederive_neighbor_overhang(declaration: NeighborOverhangDeclaration) -> dict[str, Any]:
    overhang, gap = _derive_findings(declaration)
    return {
        "overhang_finding": overhang,
        "copper_gap_finding": gap,
        "excluded_claims": _EXCLUDED_CLAIMS,
        "findings_fingerprint": fingerprint(
            [overhang.model_dump(mode="json"), gap.model_dump(mode="json")]
        ),
    }


def evaluate_neighbor_overhang(
    layout: BoardLayout,
    netlist: BoardNetlist,
    declaration: NeighborOverhangDeclaration,
) -> NeighborOverhangResult:
    """Evaluate exact retained facts without board mutation or package inference."""

    layout_before = canonical_board_layout_snapshot_json(layout)
    netlist_before = canonical_board_netlist_snapshot_json(netlist)
    if layout_before != declaration.board_layout_snapshot_json:
        raise ValueError("caller BoardLayout differs from the declaration snapshot")
    if netlist_before != declaration.board_netlist_snapshot_json:
        raise ValueError("caller BoardNetlist differs from the declaration snapshot")
    derived = rederive_neighbor_overhang(declaration)
    if canonical_board_layout_snapshot_json(layout) != layout_before:
        raise RuntimeError("neighbor evaluator mutated caller BoardLayout")
    if canonical_board_netlist_snapshot_json(netlist) != netlist_before:
        raise RuntimeError("neighbor evaluator mutated caller BoardNetlist")
    fields: dict[str, Any] = {"declaration": declaration, **derived}
    provisional = NeighborOverhangResult.model_construct(**fields, result_fingerprint="0" * 64)
    result_fp = fingerprint(provisional.model_dump(mode="json", exclude={"result_fingerprint"}))
    return NeighborOverhangResult(**fields, result_fingerprint=result_fp)
