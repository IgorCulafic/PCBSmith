"""Firing fixtures for bounded opt-in R6.1a thermal semantics."""

from __future__ import annotations

from datetime import date
from fractions import Fraction

import pytest
from pydantic import ValidationError

from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.kicad.board import BoardComponent, BoardLayout
from pcbsmith.kicad.thermal_semantics import evaluate_thermal_semantics
from pcbsmith.placement_geometry import (
    ExactPlanarCompound,
    ExactPlanarPolygon,
    PlanarRelation,
)
from pcbsmith.semantic_ir import (
    EnclosureEnvironmentProfile,
    EvidenceApplicabilityBinding,
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticEvaluationContext,
    SemanticLayoutProfile,
    SemanticRegion,
    SemanticResultOutcome,
    SemanticRuleDeclaration,
    SemanticVerification,
)
from pcbsmith.thermal_ir import (
    ThermalDeclarationCatalog,
    ThermalEvaluationResult,
    ThermalOperatingPoint,
    ThermalPredictionModel,
    ThermalRationalPoint,
    ThermalSensitiveDeclaration,
    ThermalSeparationRequirement,
    ThermalSourceDeclaration,
)


def _rect(x1: float, y1: float, x2: float, y2: float) -> ExactPlanarCompound:
    return ExactPlanarCompound(
        polygons=(ExactPlanarPolygon(outer=((x1, y1), (x2, y1), (x2, y2), (x1, y2))),)
    )


def _evidence() -> EvidenceRef:
    return EvidenceRef(
        kind="datasheet",
        title="Thermal fixture source",
        locator="section:thermal",
        source_id="source:thermal-fixture",
        organization_or_author="Fixture Vendor",
        revision="1",
        local_sha256="a" * 64,
        source_status="pinned",
        locator_status="figure_bound",
        applicability_status="confirmed",
        required_conditions=("board=fixture",),
    )


def _binding() -> EvidenceApplicabilityBinding:
    return EvidenceApplicabilityBinding(
        binding_id="binding:thermal",
        evidence=(_evidence(),),
        claim_id="claim:thermal",
        applicability_record_id="applicability:thermal",
        required_conditions=("board=fixture",),
        excluded_conditions=(),
        matched_conditions=("board=fixture",),
        unmatched_conditions=(),
        geometry_source_fingerprint="b" * 64,
        reviewer_record_id="review:thermal",
    )


def _enclosure(
    *,
    conditions: tuple[str, ...] = ("air=still", "enclosure=open"),
) -> EnclosureEnvironmentProfile:
    return EnclosureEnvironmentProfile(
        profile_id="enclosure:thermal-fixture",
        revision="1",
        enclosure_geometry_fingerprint="e" * 64,
        environment_condition_ids=conditions,
        evidence_binding_ids=("binding:thermal",),
    )


def _region(
    region_id: str,
    compound: ExactPlanarCompound,
    *,
    owner_reference: str | None,
) -> SemanticRegion:
    return SemanticRegion(
        region_id=region_id,
        coordinate_space="board" if owner_reference is None else "component_local",
        owner_reference=owner_reference,
        compound=compound,
        layers=("F.Fab",),
        verification=SemanticVerification.EXACT,
        maximum_error_mm=None,
        source_binding_ids=("binding:thermal",),
    )


def _component(reference: str) -> BoardComponent:
    return BoardComponent(
        reference=reference,
        value=f"value:{reference}",
        footprint=f"fixture:{reference}",
        uuid_path=f"uuid:{reference}",
        fields=(("identity", reference.lower()),),
    )


def _layout(
    *,
    source_x: float = 5.0,
    sensitive_x: float = 10.0,
    source_y: float = 5.0,
    sensitive_y: float = 5.0,
    source_rotation: float = 0.0,
    sensitive_rotation: float = 0.0,
    sensitive_back: bool = False,
) -> BoardLayout:
    return BoardLayout(
        placements=(
            (_component("U1"), source_x),
            (_component("U2"), sensitive_x),
        ),
        segments=(),
        vias=(),
        width_mm=20.0,
        height_mm=20.0,
        parts_row_y_mm=source_y,
        part_y_mm=(("U2", sensitive_y),),
        part_rotation=tuple(
            item
            for item in (
                ("U1", source_rotation),
                ("U2", sensitive_rotation),
            )
            if item[1] != 0
        ),
        part_flip=("U2",) if sensitive_back else (),
    )


def _case(
    source_region: SemanticRegion,
    sensitive_region: SemanticRegion,
    *,
    authority: SemanticAuthorityClass = SemanticAuthorityClass.HARD_GEOMETRY,
    threshold_mm: float | None = 1.0,
    prediction_requested: bool = False,
    prediction_model_id: str | None = None,
    model_mode: str = "missing",
) -> tuple[ThermalDeclarationCatalog, SemanticEvaluationContext]:
    enclosure = _enclosure()
    separation_rule = SemanticRuleDeclaration(
        rule_id="rule:thermal-separation",
        authority=authority,
        object_ids=("source:U1", "sensitive:U2"),
        geometry_region_ids=(source_region.region_id, sensitive_region.region_id),
        evidence_binding_ids=("binding:thermal",),
    )
    rules = [separation_rule]
    if prediction_requested:
        rules.append(
            SemanticRuleDeclaration(
                rule_id="rule:thermal-prediction",
                authority=SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
                object_ids=("source:U1",),
                geometry_region_ids=(source_region.region_id,),
                evidence_binding_ids=("binding:thermal",),
            )
        )
    context = SemanticEvaluationContext(
        pcb_profile_fingerprint="1" * 64,
        evaluation_date=date(2026, 7, 16),
        semantic_profile=SemanticLayoutProfile(
            profile_id="semantic:thermal-fixture",
            revision="1",
            evidence_bindings=(_binding(),),
            regions=(source_region, sensitive_region),
            rules=tuple(rules),
        ),
        assembly_profile=None,
        enclosure_profile=enclosure,
        validation_profile=None,
    )
    operating_point = ThermalOperatingPoint(
        operating_point_id="operating-point:U1",
        ambient_temperature_c=25.0,
        dissipation_w=2.0,
        duty_cycle=0.5,
        pcb_profile_fingerprint=context.pcb_profile_fingerprint,
        enclosure_profile_fingerprint=(
            enclosure.semantic_fingerprint() if prediction_requested else None
        ),
        board_condition_ids=("copper=2-layer", "mounting=horizontal"),
        air_condition_ids=("air=still",),
        enclosure_condition_ids=(
            enclosure.environment_condition_ids if prediction_requested else ()
        ),
        evidence_binding_ids=("binding:thermal",),
    )
    models: tuple[ThermalPredictionModel, ...] = ()
    if model_mode in {"matching", "mismatch"}:
        assert operating_point.enclosure_profile_fingerprint is not None
        models = (
            ThermalPredictionModel(
                model_id="model:theta",
                theta_c_per_w=10.0,
                ambient_temperature_c=(
                    operating_point.ambient_temperature_c
                    if model_mode == "matching"
                    else operating_point.ambient_temperature_c + 1
                ),
                dissipation_w=operating_point.dissipation_w,
                duty_cycle=operating_point.duty_cycle,
                pcb_profile_fingerprint=operating_point.pcb_profile_fingerprint,
                enclosure_profile_fingerprint=(operating_point.enclosure_profile_fingerprint),
                board_condition_ids=operating_point.board_condition_ids,
                air_condition_ids=operating_point.air_condition_ids,
                enclosure_condition_ids=operating_point.enclosure_condition_ids,
                applicable_source_ids=("source:U1",),
                evidence_binding_ids=("binding:thermal",),
            ),
        )
    source = ThermalSourceDeclaration(
        source_id="source:U1",
        region_id=source_region.region_id,
        operating_point_id=operating_point.operating_point_id,
        component_refs=("U1",),
        net_refs=(),
        prediction_requested=prediction_requested,
        prediction_model_id=prediction_model_id,
        prediction_rule_id="rule:thermal-prediction" if prediction_requested else None,
        evidence_binding_ids=("binding:thermal",),
    )
    sensitive = ThermalSensitiveDeclaration(
        sensitive_id="sensitive:U2",
        region_id=sensitive_region.region_id,
        component_refs=("U2",),
        net_refs=(),
        evidence_binding_ids=("binding:thermal",),
    )
    catalog = ThermalDeclarationCatalog(
        catalog_id="thermal:fixture",
        revision="1",
        regions=(source_region, sensitive_region),
        operating_points=(operating_point,),
        sources=(source,),
        sensitive_regions=(sensitive,),
        separation_requirements=(
            ThermalSeparationRequirement(
                requirement_id="requirement:thermal-separation",
                rule_id=separation_rule.rule_id,
                source_id=source.source_id,
                sensitive_id=sensitive.sensitive_id,
                authority=authority,
                minimum_separation_mm=threshold_mm,
                evidence_binding_ids=("binding:thermal",),
            ),
        ),
        prediction_models=models,
    )
    return catalog, context


def _finding(
    result: ThermalEvaluationResult,
    rule_id: str = "rule:thermal-separation",
):
    return next(item for item in result.findings if item.rule_id == rule_id)


def test_front_back_arbitrary_angle_regions_are_bounded_and_deterministic() -> None:
    source_region = _region(
        "region:source",
        _rect(-0.4, -0.2, 0.6, 0.3),
        owner_reference="U1",
    )
    sensitive_region = _region(
        "region:sensitive",
        _rect(-0.3, -0.4, 0.2, 0.5),
        owner_reference="U2",
    )
    catalog, context = _case(
        source_region,
        sensitive_region,
        threshold_mm=2.0,
    )
    layout = _layout(
        source_rotation=37.0,
        sensitive_rotation=37.0,
        sensitive_back=True,
    )

    first = evaluate_thermal_semantics(
        layout,
        catalog,
        context,
        placement_candidate_fingerprint="c" * 64,
    )
    reversed_catalog = ThermalDeclarationCatalog(
        **{
            **catalog.model_dump(),
            "regions": tuple(reversed(catalog.regions)),
            "operating_points": tuple(reversed(catalog.operating_points)),
            "sources": tuple(reversed(catalog.sources)),
            "sensitive_regions": tuple(reversed(catalog.sensitive_regions)),
            "separation_requirements": tuple(reversed(catalog.separation_requirements)),
        }
    )
    second = evaluate_thermal_semantics(
        layout,
        reversed_catalog,
        context,
        placement_candidate_fingerprint="c" * 64,
    )

    assert first == second
    assert first.input_fingerprint == second.input_fingerprint
    assert (
        first.semantic_fingerprint()
        == "f384435d5cf0419a65c57358453da0ce6df80c15a7facbba9a7d19b279ea9771"
    )
    assert (
        first.input_fingerprint
        == "693d861402fd644d2b8f2823e620c0f779dbd6722b36de138fb21a83ee156781"
    )
    assert (
        first.separation_evidence[0].semantic_fingerprint()
        == "ab383509d2ff8c2fce9d09a189c873a76578bab741c500da07d1dd60c0c40506"
    )
    assert {item.verification for item in first.resolved_regions} == {
        SemanticVerification.BOUNDED_APPROXIMATION
    }
    assert all(
        item.maximum_error_mm is not None and item.maximum_error_mm > 0
        for item in first.resolved_regions
    )
    assert _finding(first).disposition is SemanticDisposition.PASS
    assert _finding(first).verification is SemanticVerification.BOUNDED_APPROXIMATION
    assert first.semantic_result.outcome is SemanticResultOutcome.PASSED

    overlapping = evaluate_thermal_semantics(
        _layout(
            sensitive_x=5.0,
            source_rotation=37.0,
            sensitive_rotation=37.0,
            sensitive_back=True,
        ),
        catalog,
        context,
    )
    assert _finding(overlapping).disposition is SemanticDisposition.UNVERIFIED
    overlap_evidence = overlapping.separation_evidence[0]
    assert overlap_evidence.relation is PlanarRelation.INTERIOR_OVERLAP
    assert overlap_evidence.squared_distance() == Fraction(0)
    assert overlap_evidence.closest_source_point == (overlap_evidence.closest_sensitive_point)
    assert overlapping.semantic_result.outcome is SemanticResultOutcome.HARD_SCOPE_UNVERIFIED


def test_advisory_without_threshold_reports_metric_and_never_fails() -> None:
    catalog, context = _case(
        _region("region:source", _rect(0.0, 0.0, 1.0, 1.0), owner_reference=None),
        _region(
            "region:sensitive",
            _rect(2.0, 0.0, 3.0, 1.0),
            owner_reference=None,
        ),
        authority=SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
        threshold_mm=None,
    )

    result = evaluate_thermal_semantics(_layout(), catalog, context)

    finding = _finding(result)
    assert finding.disposition is SemanticDisposition.ADVISORY
    assert all(item.disposition is not SemanticDisposition.FAIL for item in result.findings)
    metric = next(
        item for item in result.metrics if item.metric_id.startswith("thermal:separation:")
    )
    assert metric.quantity is not None
    assert metric.quantity.value == pytest.approx(1.0, abs=3e-16)
    assert catalog.operating_points[0].enclosure_profile_fingerprint is None
    assert catalog.operating_points[0].enclosure_condition_ids == ()
    assert "without a hidden threshold" in finding.message
    with pytest.raises(ValidationError, match="explicit threshold"):
        ThermalSeparationRequirement.model_validate(
            {
                **catalog.separation_requirements[0].model_dump(),
                "authority": "hard_geometry",
            }
        )


def test_hard_exact_threshold_passes_at_equality_and_fails_one_micrometre_below() -> None:
    source = _region(
        "region:source",
        _rect(0.0, 0.0, 1.0, 1.0),
        owner_reference=None,
    )
    equal_sensitive = _region(
        "region:sensitive",
        _rect(2.0, 0.0, 3.0, 1.0),
        owner_reference=None,
    )
    equal_catalog, equal_context = _case(
        source,
        equal_sensitive,
        threshold_mm=1.0,
    )
    equal = evaluate_thermal_semantics(_layout(), equal_catalog, equal_context)

    below_sensitive = _region(
        "region:sensitive",
        _rect(1.999, 0.0, 2.999, 1.0),
        owner_reference=None,
    )
    below_catalog, below_context = _case(
        source,
        below_sensitive,
        threshold_mm=1.0,
    )
    below = evaluate_thermal_semantics(_layout(), below_catalog, below_context)

    assert _finding(equal).verification is SemanticVerification.EXACT
    assert _finding(equal).disposition is SemanticDisposition.PASS
    assert _finding(below).verification is SemanticVerification.EXACT
    assert _finding(below).disposition is SemanticDisposition.FAIL
    equal_evidence = equal.separation_evidence[0]
    below_evidence = below.separation_evidence[0]
    assert equal_evidence.squared_distance() == Fraction(1)
    assert equal_evidence.closest_source_point is not None
    assert equal_evidence.closest_sensitive_point is not None
    assert equal_evidence.closest_source_point.as_point() == (
        Fraction(1),
        Fraction(0),
    )
    assert equal_evidence.closest_sensitive_point.as_point() == (
        Fraction(2),
        Fraction(0),
    )
    assert below_evidence.squared_distance() == Fraction(998001, 1_000_000)
    assert below_evidence.closest_source_point is not None
    assert below_evidence.closest_sensitive_point is not None
    assert below_evidence.closest_source_point.as_point() == (
        Fraction(1),
        Fraction(0),
    )
    assert below_evidence.closest_sensitive_point.as_point() == (
        Fraction(1999, 1000),
        Fraction(0),
    )
    assert below.semantic_result.outcome is SemanticResultOutcome.HARD_REJECTED
    below_metric = next(
        item for item in below.metrics if item.metric_id.startswith("thermal:separation:")
    )
    assert below_metric.quantity is not None
    assert below_metric.quantity.value == pytest.approx(0.999, abs=1e-15)


@pytest.mark.parametrize("mode", ("missing", "mismatch", "context-mismatch"))
def test_temperature_prediction_is_withheld_when_model_or_context_mismatches(
    mode: str,
) -> None:
    catalog, context = _case(
        _region("region:source", _rect(0.0, 0.0, 1.0, 1.0), owner_reference=None),
        _region(
            "region:sensitive",
            _rect(3.0, 0.0, 4.0, 1.0),
            owner_reference=None,
        ),
        authority=SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
        threshold_mm=None,
        prediction_requested=True,
        prediction_model_id="model:theta",
        model_mode="matching" if mode == "context-mismatch" else mode,
    )
    if mode == "context-mismatch":
        context = SemanticEvaluationContext.model_validate(
            {
                **context.model_dump(),
                "enclosure_profile": _enclosure(
                    conditions=("air=forced", "enclosure=closed")
                ).model_dump(),
            }
        )

    result = evaluate_thermal_semantics(_layout(), catalog, context)

    prediction = _finding(result, "rule:thermal-prediction")
    assert prediction.disposition is SemanticDisposition.UNVERIFIED
    assert prediction.verification is SemanticVerification.UNSUPPORTED
    assert not any(item.metric_id.startswith("thermal:model-estimate:") for item in result.metrics)


def test_matching_theta_scope_emits_only_an_advisory_model_estimate() -> None:
    catalog, context = _case(
        _region("region:source", _rect(0.0, 0.0, 1.0, 1.0), owner_reference=None),
        _region(
            "region:sensitive",
            _rect(3.0, 0.0, 4.0, 1.0),
            owner_reference=None,
        ),
        authority=SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
        threshold_mm=None,
        prediction_requested=True,
        prediction_model_id="model:theta",
        model_mode="matching",
    )

    result = evaluate_thermal_semantics(_layout(), catalog, context)

    prediction = _finding(result, "rule:thermal-prediction")
    estimate = next(
        item for item in result.metrics if item.metric_id == "thermal:model-estimate:source:U1"
    )
    assert prediction.disposition is SemanticDisposition.ADVISORY
    assert prediction.verification is SemanticVerification.EXACT
    assert "not thermal simulation or product validation" in prediction.message
    assert estimate.quantity is not None
    assert estimate.quantity.unit == "degC"
    assert estimate.quantity.value == 35.0


def test_unsupported_separation_retains_and_revalidates_typed_causes() -> None:
    catalog, context = _case(
        _region(
            "region:source",
            _rect(-0.5, -0.5, 0.5, 0.5),
            owner_reference="U1",
        ),
        _region(
            "region:sensitive",
            _rect(-0.5, -0.5, 0.5, 0.5),
            owner_reference="U2",
        ),
    )
    missing_sensitive = BoardLayout(
        placements=((_component("U1"), 5.0),),
        segments=(),
        vias=(),
        width_mm=20.0,
        height_mm=20.0,
        parts_row_y_mm=5.0,
    )

    result = evaluate_thermal_semantics(missing_sensitive, catalog, context)

    evidence = result.separation_evidence[0]
    assert evidence.verification is SemanticVerification.UNSUPPORTED
    assert evidence.disposition is SemanticDisposition.UNVERIFIED
    assert evidence.relation is None
    assert evidence.squared_distance() is None
    assert evidence.closest_source_point is None
    assert evidence.closest_sensitive_point is None
    assert evidence.maximum_error_mm is None
    assert evidence.conservative_distance_mm is None
    assert {
        (item.role, item.kind.value, item.identity) for item in evidence.unsupported_causes
    } == {
        ("sensitive", "component_missing_layout", "U2"),
        ("sensitive", "region_geometry_unsupported", "region:sensitive"),
    }
    metric = next(item for item in result.metrics if item.metric_id in evidence.metric_ids)
    assert metric.verification is SemanticVerification.UNSUPPORTED
    assert metric.quantity is None

    forged_causes = evidence.model_copy(
        update={"unsupported_causes": evidence.unsupported_causes[:1]}
    )
    with pytest.raises(ValidationError, match="unsupported thermal evidence is not derived"):
        ThermalEvaluationResult.model_validate_json(
            result.model_copy(update={"separation_evidence": (forged_causes,)}).model_dump_json()
        )

    fabricated_geometry = evidence.model_copy(
        update={
            "closest_source_point": ThermalRationalPoint(
                x_numerator=0,
                x_denominator=1,
                y_numerator=0,
                y_denominator=1,
            )
        }
    )
    with pytest.raises(ValidationError, match="cannot fabricate geometry"):
        ThermalEvaluationResult.model_validate_json(
            result.model_copy(
                update={"separation_evidence": (fabricated_geometry,)}
            ).model_dump_json()
        )

    forged_metric = metric.model_copy(update={"object_ids": ("source:U1",)})
    with pytest.raises(ValidationError, match="unsupported thermal evidence is not derived"):
        ThermalEvaluationResult.model_validate_json(
            result.model_copy(update={"metrics": (forged_metric,)}).model_dump_json()
        )

    finding = result.findings[0]
    forged_message = finding.model_copy(update={"message": "unsupported for an invented reason"})
    with pytest.raises(ValidationError, match="finding explanation is stale"):
        ThermalEvaluationResult.model_validate_json(
            result.model_copy(update={"findings": (forged_message,)}).model_dump_json()
        )

    forged_pass = evidence.model_copy(update={"disposition": SemanticDisposition.PASS})
    with pytest.raises(ValidationError, match="cannot fabricate geometry"):
        ThermalEvaluationResult.model_validate_json(
            result.model_copy(update={"separation_evidence": (forged_pass,)}).model_dump_json()
        )


def test_result_revalidates_forged_nested_findings_and_geometry() -> None:
    catalog, context = _case(
        _region(
            "region:source",
            _rect(-0.5, -0.5, 0.5, 0.5),
            owner_reference="U1",
        ),
        _region(
            "region:sensitive",
            _rect(-0.5, -0.5, 0.5, 0.5),
            owner_reference="U2",
        ),
        authority=SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
        threshold_mm=None,
    )
    result = evaluate_thermal_semantics(
        _layout(source_rotation=37.0, sensitive_rotation=37.0),
        catalog,
        context,
    )

    original = result.findings[0]
    forged_finding = original.model_copy(update={"disposition": SemanticDisposition.FAIL})
    forged_result = result.model_copy(update={"findings": (forged_finding,)})
    with pytest.raises(ValidationError, match="incompatible with its authority"):
        ThermalEvaluationResult.model_validate_json(forged_result.model_dump_json())

    original_region = result.resolved_regions[0]
    forged_region = original_region.model_copy(update={"maximum_error_mm": None})
    forged_geometry = result.model_copy(
        update={
            "resolved_regions": (
                forged_region,
                *result.resolved_regions[1:],
            )
        }
    )
    with pytest.raises(ValidationError, match="bounded resolved region"):
        ThermalEvaluationResult.model_validate_json(forged_geometry.model_dump_json())

    original_evidence = result.separation_evidence[0]
    forged_fraction = original_evidence.model_copy(
        update={
            "nominal_squared_distance_numerator": (
                original_evidence.nominal_squared_distance_numerator or 0
            )
            + 1
        }
    )
    with pytest.raises(ValidationError, match="fraction|witness|coordinate"):
        ThermalEvaluationResult.model_validate_json(
            result.model_copy(update={"separation_evidence": (forged_fraction,)}).model_dump_json()
        )

    assert original_evidence.closest_source_point is not None
    forged_point = original_evidence.closest_source_point.model_copy(
        update={"x_numerator": original_evidence.closest_source_point.x_numerator + 1}
    )
    forged_witness = original_evidence.model_copy(update={"closest_source_point": forged_point})
    with pytest.raises(ValidationError, match="fraction|witness|coordinate"):
        ThermalEvaluationResult.model_validate_json(
            result.model_copy(update={"separation_evidence": (forged_witness,)}).model_dump_json()
        )

    forged_disposition = original_evidence.model_copy(
        update={"disposition": SemanticDisposition.FAIL}
    )
    with pytest.raises(ValidationError, match="advisory thermal evidence cannot fail"):
        ThermalEvaluationResult.model_validate_json(
            result.model_copy(
                update={"separation_evidence": (forged_disposition,)}
            ).model_dump_json()
        )
