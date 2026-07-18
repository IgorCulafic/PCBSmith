"""Firing fixtures for R6.1b sensor-isolation fabrication slice 1."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.kicad.board import BoardLayout
from pcbsmith.kicad.board_region import BoardCutoutPolygon
from pcbsmith.kicad.sensor_isolation import evaluate_sensor_isolation_fabrication
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon
from pcbsmith.rule_profiles import (
    FabElectricalSpacingProfile,
    FabricationGeometryProfile,
    InsulationProfile,
    PcbRuleProfile,
)
from pcbsmith.semantic_ir import (
    AssemblyProcessProfile,
    EvidenceApplicabilityBinding,
    QualifiedProcessRecord,
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticEvaluationContext,
    SemanticLayoutProfile,
    SemanticQuantity,
    SemanticRegion,
    SemanticRuleDeclaration,
    SemanticVerification,
)
from pcbsmith.sensor_isolation_ir import (
    SensorIsolationCandidate,
    SensorIsolationCatalog,
    SensorIsolationEvaluationResult,
    SensorIsolationFeature,
    SensorIsolationFeatureKind,
    SensorIsolationLimitOrigin,
    SensorIsolationNumericLimit,
    SensorIsolationProcessProfile,
    SensorIsolationValidationDeclaration,
)

SLOT_POINTS = (
    (2.0, 2.1),
    (2.1, 2.0),
    (3.9, 2.0),
    (4.0, 2.1),
    (4.0, 2.5),
    (3.9, 2.6),
    (2.1, 2.6),
    (2.0, 2.5),
)


def _compound(points: tuple[tuple[float, float], ...]) -> ExactPlanarCompound:
    return ExactPlanarCompound(polygons=(ExactPlanarPolygon(outer=points),))


def _rect(x1: float, y1: float, x2: float, y2: float) -> ExactPlanarCompound:
    return _compound(((x1, y1), (x2, y1), (x2, y2), (x1, y2)))


def _evidence(binding_id: str) -> EvidenceRef:
    return EvidenceRef(
        kind="fabricator_process_guide",
        title=f"Qualified source {binding_id}",
        locator="section:slot-web-tab",
        source_id=f"source:{binding_id}",
        organization_or_author="Fixture Fabricator",
        revision="1",
        local_sha256="a" * 64,
        source_status="pinned",
        locator_status="text_verified",
        applicability_status="confirmed",
        required_conditions=("board=fixture",),
    )


def _binding(binding_id: str = "binding:fabrication", *, complete: bool = True):
    return EvidenceApplicabilityBinding(
        binding_id=binding_id,
        evidence=(_evidence(binding_id),),
        claim_id=f"claim:{binding_id}",
        applicability_record_id=f"applicability:{binding_id}",
        required_conditions=("board=fixture",),
        excluded_conditions=(),
        matched_conditions=("board=fixture",) if complete else (),
        unmatched_conditions=() if complete else ("board=fixture",),
        geometry_source_fingerprint="b" * 64,
        reviewer_record_id="review:fabrication" if complete else None,
    )


def _qualification() -> QualifiedProcessRecord:
    return QualifiedProcessRecord(
        record_id="qualification:sensor-isolation",
        assembler_id="assembler:fixture",
        process_revision="assembly-r1",
        qualification_record_id="signed:sensor-isolation",
        qualification_source_sha256="c" * 64,
        applicability_binding_ids=("binding:assembly",),
        covered_conditions=("board=fixture", "process=double-reflow"),
        ordered_process_steps=("print", "place", "reflow", "handle"),
        effective_date=date(2026, 1, 1),
        expiry_date=date(2027, 1, 1),
        reviewer_record_id="review:assembly",
        review_identity="reviewer@example.invalid",
        status="active",
    )


def _assembly() -> AssemblyProcessProfile:
    return AssemblyProcessProfile(
        profile_id="assembly:sensor-isolation",
        assembler_id="assembler:fixture",
        process_revision="assembly-r1",
        sequence="double_reflow",
        ordered_process_steps=("print", "place", "reflow", "handle"),
        evidence_bindings=(_binding("binding:assembly"),),
        qualification_records=(_qualification(),),
    )


def _region(
    region_id: str,
    compound: ExactPlanarCompound,
    layer: str,
    *,
    binding_id: str,
) -> SemanticRegion:
    return SemanticRegion(
        region_id=region_id,
        coordinate_space="board",
        owner_reference=None,
        compound=compound,
        layers=(layer,),
        verification=SemanticVerification.EXACT,
        maximum_error_mm=None,
        source_binding_ids=(binding_id,),
    )


def _rule(
    feature_id: str,
    binding_ids: tuple[str, ...],
    *,
    authority: SemanticAuthorityClass = SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT,
    region_id: str | None = None,
) -> SemanticRuleDeclaration:
    if authority is SemanticAuthorityClass.HARD_GEOMETRY:
        assert region_id is not None
        geometry_region_ids = (region_id,)
        process_profile_id = None
        qualified_process_record_id = None
    else:
        geometry_region_ids = ()
        process_profile_id = (
            "assembly:sensor-isolation"
            if authority is SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT
            else None
        )
        qualified_process_record_id = (
            "qualification:sensor-isolation"
            if authority is SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT
            else None
        )
    return SemanticRuleDeclaration(
        rule_id=f"rule:sensor-isolation:{feature_id}",
        authority=authority,
        object_ids=(feature_id,),
        geometry_region_ids=geometry_region_ids,
        evidence_binding_ids=binding_ids,
        process_profile_id=process_profile_id,
        qualified_process_record_id=qualified_process_record_id,
    )


def _case(
    *,
    web_width_mm: float = 0.5,
    web_bounds: tuple[float, float, float, float] | None = None,
    web_limit_binding_id: str = "binding:fabrication",
    web_feature_binding_id: str = "binding:fabrication",
    include_web_bindings_in_context: bool = True,
    web_limit_binding_complete: bool = True,
    web_limit_origin: SensorIsolationLimitOrigin = (
        SensorIsolationLimitOrigin.FABRICATOR_PROCESS_CAPABILITY
    ),
    web_limit_authority: SemanticAuthorityClass = (
        SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT
    ),
) -> tuple[SensorIsolationCatalog, SemanticEvaluationContext, BoardLayout, PcbRuleProfile]:
    binding_id = "binding:fabrication"
    if web_bounds is None:
        web_bounds = (5.0, 2.0, 5.0 + web_width_mm, 3.0)
    regions = (
        _region("region:slot", _compound(SLOT_POINTS), "Edge.Cuts", binding_id=binding_id),
        _region(
            "region:web",
            _rect(*web_bounds),
            "Board.Material",
            binding_id=binding_id,
        ),
        _region(
            "region:tab",
            _rect(6.0, 2.0, 7.0, 2.4),
            "Board.Material",
            binding_id=binding_id,
        ),
    )
    specs = (
        ("slot", SensorIsolationFeatureKind.SLOT, "region:slot", "y", 0.6),
        ("web", SensorIsolationFeatureKind.RETAINED_WEB, "region:web", "x", 0.5),
        ("tab", SensorIsolationFeatureKind.SUPPORT_TAB, "region:tab", "y", 0.4),
    )
    features = tuple(
        SensorIsolationFeature(
            feature_id=f"feature:{name}",
            feature_kind=kind,
            region_id=region_id,
            measurement_axis=axis,
            limit_id=f"limit:{name}",
            rule_id=f"rule:sensor-isolation:feature:{name}",
            source_binding_ids=(web_feature_binding_id if name == "web" else binding_id,),
        )
        for name, kind, region_id, axis, _minimum in specs
    )
    limits = tuple(
        SensorIsolationNumericLimit(
            limit_id=f"limit:{name}",
            feature_kind=kind,
            minimum=SemanticQuantity(
                quantity_id=f"quantity:minimum:{name}",
                value=minimum,
                unit="mm",
                source_binding_ids=(web_limit_binding_id if name == "web" else binding_id,),
            ),
            origin=(
                web_limit_origin
                if name == "web"
                else SensorIsolationLimitOrigin.FABRICATOR_PROCESS_CAPABILITY
            ),
            authority=(
                web_limit_authority
                if name == "web"
                else SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT
            ),
            applicability_binding_ids=(web_limit_binding_id if name == "web" else binding_id,),
        )
        for name, kind, _region_id, _axis, minimum in specs
    )
    candidate = SensorIsolationCandidate(
        candidate_id="candidate:sensor-isolation",
        sensor_reference="U1",
        features=features,
        validation=SensorIsolationValidationDeclaration(
            thermal_requirement_id="validation:sensor-thermal",
            humidity_requirement_id="validation:sensor-humidity",
        ),
        source_binding_ids=(binding_id,),
    )
    selected_binding_ids = tuple(sorted({binding_id, web_limit_binding_id, web_feature_binding_id}))
    catalog = SensorIsolationCatalog(
        catalog_id="sensor-isolation:fixture",
        revision="1",
        regions=regions,
        candidate=candidate,
        process_profile=SensorIsolationProcessProfile(
            profile_id="assembly:sensor-isolation",
            fabrication_profile_id="fab:sensor-isolation",
            qualified_process_record_id="qualification:sensor-isolation",
            limits=limits,
            evidence_binding_ids=selected_binding_ids,
        ),
    )
    context_bindings = [_binding(binding_id)]
    if include_web_bindings_in_context:
        for extra_binding_id in selected_binding_ids:
            if extra_binding_id == binding_id:
                continue
            context_bindings.append(
                _binding(
                    extra_binding_id,
                    complete=(
                        web_limit_binding_complete
                        if extra_binding_id == web_limit_binding_id
                        else True
                    ),
                )
            )
    limit_by_id = {item.limit_id: item for item in limits}
    region_by_id = {item.region_id: item for item in regions}
    context = SemanticEvaluationContext(
        pcb_profile_fingerprint="d" * 64,
        evaluation_date=date(2026, 7, 17),
        semantic_profile=SemanticLayoutProfile(
            profile_id="semantic:sensor-isolation",
            revision="1",
            evidence_bindings=tuple(context_bindings),
            regions=regions,
            rules=tuple(
                _rule(
                    feature.feature_id,
                    tuple(
                        sorted(
                            {
                                *candidate.source_binding_ids,
                                *feature.source_binding_ids,
                                *region_by_id[feature.region_id].source_binding_ids,
                                *limit_by_id[feature.limit_id].applicability_binding_ids,
                                *limit_by_id[feature.limit_id].minimum.source_binding_ids,
                            }
                        )
                    ),
                    authority=limit_by_id[feature.limit_id].authority,
                    region_id=feature.region_id,
                )
                for feature in features
            ),
        ),
        assembly_profile=_assembly(),
        enclosure_profile=None,
        validation_profile=None,
    )
    layout = BoardLayout(
        placements=(),
        segments=(),
        vias=(),
        width_mm=10.0,
        height_mm=8.0,
        cutouts=(BoardCutoutPolygon(SLOT_POINTS),),
    )
    rules = PcbRuleProfile(
        profile_id="pcb:sensor-isolation",
        geometry=FabricationGeometryProfile(profile_id="fab:sensor-isolation"),
        fab_spacing=FabElectricalSpacingProfile(profile_id="spacing:fixture"),
        insulation=InsulationProfile(profile_id="insulation:fixture", status="not_applicable"),
    )
    return catalog, context, layout, rules


def _evaluate(*, web_width_mm: float = 0.5):
    catalog, context, layout, rules = _case(web_width_mm=web_width_mm)
    return evaluate_sensor_isolation_fabrication(
        layout,
        catalog,
        context,
        rule_profile=rules,
    )


def test_exact_rounded_slot_web_tab_pass_at_selected_limit_equality() -> None:
    result = _evaluate()

    assert all(item.disposition is SemanticDisposition.PASS for item in result.findings)
    assert {
        item.feature_id: item.span_numerator_mm / item.span_denominator
        for item in result.feature_evidence
    } == {
        "feature:slot": pytest.approx(0.6),
        "feature:tab": pytest.approx(0.4),
        "feature:web": pytest.approx(0.5),
    }
    slot = next(item for item in result.feature_evidence if item.feature_id == "feature:slot")
    assert slot.live_cutout_match is True
    assert all(item.authority_complete for item in result.feature_evidence)
    assert result.catalog.process_profile.profile_id == "assembly:sensor-isolation"
    assert all(
        item.process_profile_id == result.catalog.process_profile.profile_id
        for item in result.findings
    )
    positive = {
        item.feature_id: item
        for item in result.feature_evidence
        if item.feature_id != "feature:slot"
    }
    assert all(item.board_material_contained is True for item in positive.values())
    assert all(not item.intersecting_cutout_fingerprints for item in positive.values())


def test_one_micrometre_below_web_limit_fires_only_web_constraint() -> None:
    result = _evaluate(web_width_mm=0.499)

    dispositions = {item.rule_id: item.disposition for item in result.findings}
    assert dispositions["rule:sensor-isolation:feature:web"] is SemanticDisposition.FAIL
    assert dispositions["rule:sensor-isolation:feature:slot"] is SemanticDisposition.PASS
    assert dispositions["rule:sensor-isolation:feature:tab"] is SemanticDisposition.PASS


def test_one_incomplete_limit_only_makes_its_feature_unverified() -> None:
    catalog, context, layout, rules = _case(
        web_limit_binding_id="binding:web-limit",
        web_limit_binding_complete=False,
    )

    result = evaluate_sensor_isolation_fabrication(
        layout,
        catalog,
        context,
        rule_profile=rules,
    )

    dispositions = {item.rule_id: item.disposition for item in result.findings}
    assert dispositions["rule:sensor-isolation:feature:web"] is SemanticDisposition.UNVERIFIED
    assert dispositions["rule:sensor-isolation:feature:slot"] is SemanticDisposition.PASS
    assert dispositions["rule:sensor-isolation:feature:tab"] is SemanticDisposition.PASS
    authority = {item.feature_id: item.authority_complete for item in result.feature_evidence}
    assert authority == {"feature:slot": True, "feature:tab": True, "feature:web": False}


def test_unknown_feature_source_is_rejected_before_a_qualified_finding() -> None:
    with pytest.raises(ValidationError, match="unknown evidence binding"):
        _case(
            web_feature_binding_id="binding:unknown",
            include_web_bindings_in_context=False,
        )


@pytest.mark.parametrize(
    ("web_bounds", "contained", "overlap"),
    (
        ((10.1, 2.0, 10.6, 3.0), False, False),
        ((2.5, 2.1, 3.0, 2.5), True, True),
    ),
)
def test_positive_web_must_be_live_board_material_not_cutout_void(
    web_bounds: tuple[float, float, float, float],
    contained: bool,
    overlap: bool,
) -> None:
    catalog, context, layout, rules = _case(web_bounds=web_bounds)
    result = evaluate_sensor_isolation_fabrication(
        layout,
        catalog,
        context,
        rule_profile=rules,
    )

    web = next(item for item in result.feature_evidence if item.feature_id == "feature:web")
    assert web.board_material_contained is contained
    assert bool(web.intersecting_cutout_fingerprints) is overlap
    assert web.disposition is SemanticDisposition.FAIL
    assert all(
        item.disposition is SemanticDisposition.PASS
        for item in result.findings
        if item.rule_id != "rule:sensor-isolation:feature:web"
    )


def test_absent_live_slot_is_a_hard_failure_with_complete_authority() -> None:
    catalog, context, layout, rules = _case()
    layout = BoardLayout(
        placements=layout.placements,
        segments=layout.segments,
        vias=layout.vias,
        width_mm=layout.width_mm,
        height_mm=layout.height_mm,
    )

    result = evaluate_sensor_isolation_fabrication(
        layout,
        catalog,
        context,
        rule_profile=rules,
    )

    slot = next(item for item in result.feature_evidence if item.feature_id == "feature:slot")
    assert slot.live_cutout_match is False
    assert slot.disposition is SemanticDisposition.FAIL


def test_generic_manufacturer_advice_cannot_become_a_numeric_hard_limit() -> None:
    catalog, _context, _layout, _rules = _case()
    limit = catalog.process_profile.limits[0]

    with pytest.raises(ValidationError, match="origin"):
        SensorIsolationNumericLimit.model_validate(
            {**limit.model_dump(), "origin": "generic_manufacturer_advice"}
        )


@pytest.mark.parametrize(
    "advisory_origin",
    (
        SensorIsolationLimitOrigin.MANUFACTURER_RECOMMENDED_LAYOUT,
        SensorIsolationLimitOrigin.APPLICATION_NOTE_EXAMPLE,
        SensorIsolationLimitOrigin.GENERIC_BOOK_OR_ADVICE,
    ),
)
def test_same_numeric_source_cannot_change_from_project_authority_to_advice(
    advisory_origin: SensorIsolationLimitOrigin,
) -> None:
    catalog, _context, _layout, _rules = _case()
    original = catalog.process_profile.limits[0]
    project_payload = {
        **original.model_dump(),
        "origin": SensorIsolationLimitOrigin.EXACT_PROJECT_DESIGN_AUTHORITY,
        "authority": SemanticAuthorityClass.HARD_GEOMETRY,
    }
    project_limit = SensorIsolationNumericLimit.model_validate(project_payload)
    substituted_payload = {**project_limit.model_dump(), "origin": advisory_origin}

    with pytest.raises(ValidationError, match="hard sensor-isolation numeric authority"):
        SensorIsolationNumericLimit.model_validate(substituted_payload)

    assert substituted_payload["minimum"] == project_limit.model_dump()["minimum"]
    assert (
        substituted_payload["applicability_binding_ids"]
        == project_limit.model_dump()["applicability_binding_ids"]
    )


def test_advisory_example_is_retained_but_cannot_hard_fail() -> None:
    catalog, context, layout, rules = _case(
        web_width_mm=0.1,
        web_limit_origin=SensorIsolationLimitOrigin.MANUFACTURER_RECOMMENDED_LAYOUT,
        web_limit_authority=SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
    )

    result = evaluate_sensor_isolation_fabrication(
        layout,
        catalog,
        context,
        rule_profile=rules,
    )

    web = next(item for item in result.findings if item.rule_id.endswith("feature:web"))
    assert web.authority is SemanticAuthorityClass.ADVISORY_HYPOTHESIS
    assert web.disposition is SemanticDisposition.ADVISORY
    assert web.process_profile_id is None
    assert web.qualified_process_record_id is None
    assert all(item.disposition is not SemanticDisposition.FAIL for item in result.findings)


@pytest.mark.parametrize(
    "width_mm, expected",
    (
        (0.5, SemanticDisposition.PASS),
        (0.499, SemanticDisposition.FAIL),
    ),
)
def test_exact_project_numeric_authority_passes_at_equality_and_fires_below(
    width_mm: float,
    expected: SemanticDisposition,
) -> None:
    catalog, context, layout, rules = _case(
        web_width_mm=width_mm,
        web_limit_origin=SensorIsolationLimitOrigin.VALIDATED_PROJECT_REQUIREMENT,
        web_limit_authority=SemanticAuthorityClass.HARD_GEOMETRY,
    )

    result = evaluate_sensor_isolation_fabrication(
        layout,
        catalog,
        context,
        rule_profile=rules,
    )

    web = next(item for item in result.findings if item.rule_id.endswith("feature:web"))
    assert web.authority is SemanticAuthorityClass.HARD_GEOMETRY
    assert web.disposition is expected
    assert web.region_ids == ("region:web",)
    assert web.process_profile_id is None


def test_complete_process_evidence_cannot_substitute_incomplete_project_geometry() -> None:
    catalog, context, layout, rules = _case(
        web_limit_binding_id="binding:web-project",
        web_limit_binding_complete=False,
        web_limit_origin=SensorIsolationLimitOrigin.EXACT_PROJECT_DESIGN_AUTHORITY,
        web_limit_authority=SemanticAuthorityClass.HARD_GEOMETRY,
    )
    assert context.assembly_profile is not None
    assembly = AssemblyProcessProfile.model_validate(
        {
            **context.assembly_profile.model_dump(),
            "evidence_bindings": (
                *context.assembly_profile.evidence_bindings,
                _binding("binding:web-project", complete=True),
            ),
        }
    )
    substituted_context = SemanticEvaluationContext.model_validate(
        {**context.model_dump(), "assembly_profile": assembly}
    )

    result = evaluate_sensor_isolation_fabrication(
        layout,
        catalog,
        substituted_context,
        rule_profile=rules,
    )

    web = next(item for item in result.findings if item.rule_id.endswith("feature:web"))
    assert web.authority is SemanticAuthorityClass.HARD_GEOMETRY
    assert web.disposition is SemanticDisposition.UNVERIFIED
    assert next(
        item for item in result.feature_evidence if item.feature_id == "feature:web"
    ).authority_complete is False


def test_limit_origin_authority_json_tamper_is_rejected() -> None:
    catalog, context, layout, rules = _case(
        web_limit_origin=SensorIsolationLimitOrigin.EXACT_PROJECT_DESIGN_AUTHORITY,
        web_limit_authority=SemanticAuthorityClass.HARD_GEOMETRY,
    )
    result = evaluate_sensor_isolation_fabrication(
        layout,
        catalog,
        context,
        rule_profile=rules,
    )
    limits = list(result.catalog.process_profile.limits)
    web_index = next(index for index, item in enumerate(limits) if item.limit_id == "limit:web")
    limits[web_index] = limits[web_index].model_copy(
        update={"origin": SensorIsolationLimitOrigin.APPLICATION_NOTE_EXAMPLE}
    )
    forged_profile = result.catalog.process_profile.model_copy(update={"limits": tuple(limits)})
    forged_catalog = result.catalog.model_copy(update={"process_profile": forged_profile})

    with pytest.raises(ValidationError, match="hard sensor-isolation numeric authority"):
        SensorIsolationEvaluationResult.model_validate_json(
            result.model_copy(update={"catalog": forged_catalog}).model_dump_json()
        )


def test_result_revalidates_tamper_and_order_repeat_serialization() -> None:
    catalog, context, layout, rules = _case()
    first = evaluate_sensor_isolation_fabrication(
        layout,
        catalog,
        context,
        rule_profile=rules,
    )
    reversed_catalog = SensorIsolationCatalog(
        **{
            **catalog.model_dump(),
            "regions": tuple(reversed(catalog.regions)),
            "candidate": {
                **catalog.candidate.model_dump(),
                "features": tuple(reversed(catalog.candidate.features)),
            },
            "process_profile": {
                **catalog.process_profile.model_dump(),
                "limits": tuple(reversed(catalog.process_profile.limits)),
            },
        }
    )
    second = evaluate_sensor_isolation_fabrication(
        layout,
        reversed_catalog,
        context,
        rule_profile=rules,
    )

    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    forged = first.feature_evidence[0].model_copy(
        update={"span_numerator_mm": first.feature_evidence[0].span_numerator_mm + 1}
    )
    with pytest.raises(ValidationError, match="not derived"):
        SensorIsolationEvaluationResult.model_validate_json(
            first.model_copy(
                update={"feature_evidence": (forged, *first.feature_evidence[1:])}
            ).model_dump_json()
        )
    forged_outline = _rect(-1.0, -1.0, 11.0, 9.0)
    with pytest.raises(ValidationError, match="geometry/source fingerprint is stale"):
        SensorIsolationEvaluationResult.model_validate_json(
            first.model_copy(update={"board_outline": forged_outline}).model_dump_json()
        )
