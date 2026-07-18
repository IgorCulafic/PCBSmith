"""Firing fixtures for the R6.0 semantic interchange contract."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from pydantic import ValidationError

from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.placement_geometry import ExactPlanarCompound, ExactPlanarPolygon
from pcbsmith.semantic_ir import (
    AssemblyProcessProfile,
    EnclosureEnvironmentProfile,
    EvidenceApplicabilityBinding,
    QualifiedProcessRecord,
    SemanticAuthorityClass,
    SemanticDisposition,
    SemanticEvaluationContext,
    SemanticFinding,
    SemanticLayoutProfile,
    SemanticLayoutResult,
    SemanticMetric,
    SemanticQuantity,
    SemanticRegion,
    SemanticResultOutcome,
    SemanticRuleDeclaration,
    SemanticVerification,
    ValidationCampaignProfile,
)


def _evidence(*, digest: str = "a" * 64, title: str = "Vendor rule") -> EvidenceRef:
    return EvidenceRef(
        kind="datasheet",
        title=title,
        locator="section:layout",
        source_id=f"source:{title.lower().replace(' ', '-')}",
        organization_or_author="Vendor",
        revision="1",
        local_sha256=digest,
        source_status="pinned",
        locator_status="figure_bound",
        applicability_status="confirmed",
        required_conditions=("board=fixture", "revision=1"),
        exclusions=("board=other",),
    )


def _binding(
    *,
    binding_id: str = "binding:layout",
    digest: str = "a" * 64,
    geometry_digest: str | None = "b" * 64,
    evidence: tuple[EvidenceRef, ...] | None = None,
) -> EvidenceApplicabilityBinding:
    return EvidenceApplicabilityBinding(
        binding_id=binding_id,
        evidence=evidence or (_evidence(digest=digest),),
        claim_id=f"claim:{binding_id}",
        applicability_record_id=f"applicability:{binding_id}",
        required_conditions=("revision=1", "board=fixture"),
        excluded_conditions=("board=other",),
        matched_conditions=("board=fixture", "revision=1"),
        unmatched_conditions=(),
        geometry_source_fingerprint=geometry_digest,
        reviewer_record_id="review:layout",
    )


def _compound(*, right: float = 2.0) -> ExactPlanarCompound:
    return ExactPlanarCompound(
        polygons=(ExactPlanarPolygon(outer=((0.0, 0.0), (right, 0.0), (right, 1.0), (0.0, 1.0))),)
    )


def _region(*, right: float = 2.0) -> SemanticRegion:
    return SemanticRegion(
        region_id="region:antenna",
        coordinate_space="component_local",
        owner_reference="U1",
        compound=_compound(right=right),
        layers=("F.Cu", "B.Cu"),
        verification=SemanticVerification.EXACT,
        maximum_error_mm=None,
        source_binding_ids=("binding:layout",),
    )


def _rules() -> tuple[SemanticRuleDeclaration, ...]:
    common = {"evidence_binding_ids": ("binding:layout",)}
    return (
        SemanticRuleDeclaration(
            rule_id="rule:hard",
            authority=SemanticAuthorityClass.HARD_GEOMETRY,
            object_ids=("U1",),
            geometry_region_ids=("region:antenna",),
            ordered_path_ids=("pad:1", "pad:2", "pad:3"),
            **common,
        ),
        SemanticRuleDeclaration(
            rule_id="rule:process",
            authority=SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT,
            object_ids=("U2",),
            process_profile_id="assembly:fixture",
            qualified_process_record_id="qualification:fixture",
            **common,
        ),
        SemanticRuleDeclaration(
            rule_id="rule:advisory",
            authority=SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
            object_ids=("U3",),
            **common,
        ),
        SemanticRuleDeclaration(
            rule_id="rule:validation",
            authority=SemanticAuthorityClass.VALIDATION_REQUIRED,
            object_ids=("U4",),
            validation_requirement_ids=("validation:rf",),
            **common,
        ),
    )


def _semantic_profile(
    *, source_digest: str = "a" * 64, right: float = 2.0
) -> SemanticLayoutProfile:
    return SemanticLayoutProfile(
        profile_id="semantic:fixture",
        revision="1",
        evidence_bindings=(_binding(digest=source_digest),),
        regions=(_region(right=right),),
        rules=_rules(),
    )


def _process_binding() -> EvidenceApplicabilityBinding:
    return _binding(
        binding_id="binding:process",
        digest="c" * 64,
        geometry_digest=None,
    )


def _qualification(*, revision: str = "process-r1") -> QualifiedProcessRecord:
    return QualifiedProcessRecord(
        record_id="qualification:fixture",
        assembler_id="assembler:fixture",
        process_revision=revision,
        qualification_record_id="signed:qualification-001",
        qualification_source_sha256="d" * 64,
        applicability_binding_ids=("binding:process",),
        covered_conditions=("alloy=SAC305", "board=fixture"),
        ordered_process_steps=("print-front", "reflow-front", "reflow-back"),
        restriction_ids=("restriction:heavy-part",),
        effective_date=date(2026, 1, 1),
        expiry_date=date(2027, 1, 1),
        reviewer_record_id="review:assembler",
        review_identity="reviewer@example.invalid",
        status="active",
    )


def _assembly(*, revision: str = "process-r1") -> AssemblyProcessProfile:
    return AssemblyProcessProfile(
        profile_id="assembly:fixture",
        assembler_id="assembler:fixture",
        process_revision=revision,
        sequence="double_reflow",
        ordered_process_steps=("print-front", "reflow-front", "reflow-back"),
        evidence_bindings=(_process_binding(),),
        qualification_records=(_qualification(revision=revision),),
    )


def _enclosure(*, digest: str = "e" * 64) -> EnclosureEnvironmentProfile:
    return EnclosureEnvironmentProfile(
        profile_id="enclosure:fixture",
        revision="1",
        enclosure_geometry_fingerprint=digest,
        environment_condition_ids=("orientation=vertical", "vent=open"),
        evidence_binding_ids=("binding:layout",),
    )


def _validation(*, extra_targets: tuple[str, ...] = ()) -> ValidationCampaignProfile:
    return ValidationCampaignProfile(
        profile_id="validation:fixture",
        revision="1",
        validation_target_ids=("validation:rf", *extra_targets),
        campaign_record_fingerprints=("f" * 64,),
        evidence_binding_ids=("binding:layout",),
    )


def _context(
    *,
    source_digest: str = "a" * 64,
    right: float = 2.0,
    process_revision: str = "process-r1",
    enclosure_digest: str = "e" * 64,
    extra_targets: tuple[str, ...] = (),
) -> SemanticEvaluationContext:
    return SemanticEvaluationContext(
        pcb_profile_fingerprint="1" * 64,
        evaluation_date=date(2026, 6, 1),
        semantic_profile=_semantic_profile(source_digest=source_digest, right=right),
        assembly_profile=_assembly(revision=process_revision),
        enclosure_profile=_enclosure(digest=enclosure_digest),
        validation_profile=_validation(extra_targets=extra_targets),
    )


def _finding(
    authority: SemanticAuthorityClass,
    disposition: SemanticDisposition,
    *,
    verification: SemanticVerification = SemanticVerification.EXACT,
    message: str = "Semantic check result",
    metric_ids: tuple[str, ...] = (),
) -> SemanticFinding:
    values: dict[str, Any] = {
        "rule_id": f"rule:{authority.value}",
        "authority": authority,
        "disposition": disposition,
        "verification": verification,
        "object_ids": ("U1",),
        "region_ids": (
            ("region:antenna",) if authority is SemanticAuthorityClass.HARD_GEOMETRY else ()
        ),
        "metric_ids": metric_ids,
        "evidence_binding_ids": ("binding:layout",),
        "message": message,
        "suggested_action": "Review the scoped declaration",
    }
    if authority is SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT:
        values["process_profile_id"] = "assembly:fixture"
        values["qualified_process_record_id"] = "qualification:fixture"
    if authority is SemanticAuthorityClass.VALIDATION_REQUIRED:
        values["validation_requirement_ids"] = ("validation:rf",)
        if disposition in {SemanticDisposition.PASS, SemanticDisposition.FAIL}:
            values["validation_profile_id"] = "validation:fixture"
    return SemanticFinding.model_validate(values)


def test_authority_classes_are_not_substitutable() -> None:
    rules = {item.authority: item for item in _rules()}
    assert set(rules) == set(SemanticAuthorityClass)

    invalid_updates = (
        (
            rules[SemanticAuthorityClass.HARD_GEOMETRY],
            {"geometry_region_ids": (), "process_profile_id": "assembly:fixture"},
            "hard-geometry authority",
        ),
        (
            rules[SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT],
            {"qualified_process_record_id": None},
            "qualified-process authority",
        ),
        (
            rules[SemanticAuthorityClass.ADVISORY_HYPOTHESIS],
            {"validation_requirement_ids": ("validation:rf",)},
            "advisory authority",
        ),
        (
            rules[SemanticAuthorityClass.VALIDATION_REQUIRED],
            {"validation_requirement_ids": (), "process_profile_id": "assembly:fixture"},
            "validation authority",
        ),
    )
    for rule, update, message in invalid_updates:
        with pytest.raises(ValidationError, match=message):
            SemanticRuleDeclaration.model_validate({**rule.model_dump(), **update})

    context = _context()
    with pytest.raises(ValidationError, match="active assembly qualification"):
        SemanticEvaluationContext.model_validate({**context.model_dump(), "assembly_profile": None})
    with pytest.raises(ValidationError, match="matching campaign targets"):
        SemanticEvaluationContext.model_validate(
            {**context.model_dump(), "validation_profile": None}
        )


def test_advisory_cannot_fail_and_unsupported_cannot_pass_or_fail() -> None:
    with pytest.raises(ValidationError, match="incompatible with its authority"):
        _finding(
            SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
            SemanticDisposition.FAIL,
        )
    for disposition in (SemanticDisposition.PASS, SemanticDisposition.FAIL):
        with pytest.raises(ValidationError, match="unsupported verification"):
            _finding(
                SemanticAuthorityClass.HARD_GEOMETRY,
                disposition,
                verification=SemanticVerification.UNSUPPORTED,
            )


def test_qualified_findings_require_process_identity() -> None:
    finding = _finding(
        SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT,
        SemanticDisposition.FAIL,
    )
    for field_name in ("process_profile_id", "qualified_process_record_id"):
        with pytest.raises(ValidationError, match="require process identity"):
            SemanticFinding.model_validate({**finding.model_dump(), field_name: None})


@pytest.mark.parametrize(
    "missing_field",
    (
        "assembler_id",
        "process_revision",
        "qualification_record_id",
        "qualification_source_sha256",
        "applicability_binding_ids",
        "covered_conditions",
        "effective_date",
        "reviewer_record_id",
        "review_identity",
    ),
)
def test_incomplete_qualified_process_record_is_rejected(missing_field: str) -> None:
    payload = _qualification().model_dump()
    payload.pop(missing_field)
    with pytest.raises(ValidationError):
        QualifiedProcessRecord.model_validate(payload)


@pytest.mark.parametrize(
    "evaluation_date",
    (date(2025, 12, 31), date(2027, 1, 2)),
)
def test_qualified_process_is_bound_to_explicit_evaluation_date(
    evaluation_date: date,
) -> None:
    context = _context()
    with pytest.raises(ValidationError, match="active assembly qualification"):
        SemanticEvaluationContext.model_validate(
            {**context.model_dump(), "evaluation_date": evaluation_date}
        )

    assert SemanticEvaluationContext.model_validate(
        {**context.model_dump(), "evaluation_date": date(2026, 1, 1)}
    )
    assert SemanticEvaluationContext.model_validate(
        {**context.model_dump(), "evaluation_date": date(2027, 1, 1)}
    )


def test_semantic_region_geometry_metadata_is_coherent() -> None:
    exact = _region()
    assert exact.verification is SemanticVerification.EXACT
    bounded = SemanticRegion.model_validate(
        {**exact.model_dump(), "verification": "bounded_approximation", "maximum_error_mm": 0.01}
    )
    unsupported = SemanticRegion.model_validate(
        {
            **exact.model_dump(),
            "verification": "unsupported",
            "compound": None,
            "maximum_error_mm": None,
        }
    )
    assert bounded.maximum_error_mm == 0.01
    assert unsupported.compound is None

    invalid = (
        {**exact.model_dump(), "compound": None},
        {**exact.model_dump(), "maximum_error_mm": 0.01},
        {**bounded.model_dump(), "maximum_error_mm": 0.0},
        {**unsupported.model_dump(), "compound": _compound()},
        {**exact.model_dump(), "coordinate_space": "board"},
        {**exact.model_dump(), "owner_reference": None},
    )
    for payload in invalid:
        with pytest.raises(ValidationError):
            SemanticRegion.model_validate(payload)


def test_number_requires_unit_evidence_and_finite_value() -> None:
    quantity = SemanticQuantity(
        quantity_id="quantity:distance",
        value=1.25,
        unit="mm",
        source_binding_ids=("binding:layout",),
    )
    assert quantity.value == 1.25
    for field_name in ("unit", "source_binding_ids"):
        payload = quantity.model_dump()
        payload.pop(field_name)
        with pytest.raises(ValidationError):
            SemanticQuantity.model_validate(payload)
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValidationError):
            SemanticQuantity.model_validate({**quantity.model_dump(), "value": value})


def test_set_like_construction_is_canonical_but_ordered_fields_are_semantic() -> None:
    first = _evidence(title="A source")
    second = _evidence(digest="9" * 64, title="B source")
    binding = _binding(evidence=(first, second))
    reversed_binding = EvidenceApplicabilityBinding(
        **{
            **binding.model_dump(),
            "evidence": tuple(reversed(binding.evidence)),
            "required_conditions": tuple(reversed(binding.required_conditions)),
            "matched_conditions": tuple(reversed(binding.matched_conditions)),
        }
    )
    assert reversed_binding == binding
    assert (
        binding.semantic_fingerprint()
        == "d605592c46d22c22980648636e8eab1c934ad57d0b86a005a84e93d449f0856b"
    )

    profile = _semantic_profile()
    reversed_profile = SemanticLayoutProfile(
        profile_id=profile.profile_id,
        revision=profile.revision,
        evidence_bindings=tuple(reversed(profile.evidence_bindings)),
        regions=tuple(reversed(profile.regions)),
        rules=tuple(reversed(profile.rules)),
    )
    assert reversed_profile.semantic_json() == profile.semantic_json()
    assert (
        profile.semantic_fingerprint()
        == "94543cb18585ababa6160b1f37ea190c323fde3000f3e83dcd064977db7d5f61"
    )

    hard = _rules()[0]
    reordered_set = SemanticRuleDeclaration.model_validate(
        {**hard.model_dump(), "object_ids": ("U2", "U1")}
    )
    repeated_set = SemanticRuleDeclaration.model_validate(
        {**hard.model_dump(), "object_ids": ("U1", "U2")}
    )
    reordered_path = SemanticRuleDeclaration.model_validate(
        {**hard.model_dump(), "ordered_path_ids": tuple(reversed(hard.ordered_path_ids))}
    )
    assert reordered_set == repeated_set
    assert reordered_path.semantic_fingerprint() != hard.semantic_fingerprint()

    qualification = _qualification()
    reversed_sets = QualifiedProcessRecord.model_validate(
        {
            **qualification.model_dump(),
            "covered_conditions": tuple(reversed(qualification.covered_conditions)),
            "restriction_ids": tuple(reversed(qualification.restriction_ids)),
        }
    )
    reversed_steps = QualifiedProcessRecord.model_validate(
        {
            **qualification.model_dump(),
            "ordered_process_steps": tuple(reversed(qualification.ordered_process_steps)),
        }
    )
    assert reversed_sets == qualification
    assert reversed_steps.semantic_fingerprint() != qualification.semantic_fingerprint()


def _fingerprint_scope(context: SemanticEvaluationContext) -> dict[str, str]:
    return {
        "binding": context.semantic_profile.evidence_bindings[0].semantic_fingerprint(),
        "region": context.semantic_profile.regions[0].semantic_fingerprint(),
        "semantic": context.semantic_profile.semantic_fingerprint(),
        "qualification": context.assembly_profile.qualification_records[0].semantic_fingerprint(),
        "assembly": context.assembly_profile.semantic_fingerprint(),
        "enclosure": context.enclosure_profile.semantic_fingerprint(),
        "validation": context.validation_profile.semantic_fingerprint(),
        "context": context.semantic_fingerprint(),
    }


def _changed_keys(before: dict[str, str], after: dict[str, str]) -> set[str]:
    return {key for key in before if before[key] != after[key]}


def test_profile_and_context_fingerprint_changes_are_scoped() -> None:
    baseline = _fingerprint_scope(_context())
    assert _changed_keys(baseline, _fingerprint_scope(_context(source_digest="8" * 64))) == {
        "binding",
        "semantic",
        "context",
    }
    assert _changed_keys(baseline, _fingerprint_scope(_context(right=3.0))) == {
        "region",
        "semantic",
        "context",
    }
    assert _changed_keys(baseline, _fingerprint_scope(_context(process_revision="process-r2"))) == {
        "qualification",
        "assembly",
        "context",
    }
    assert _changed_keys(baseline, _fingerprint_scope(_context(enclosure_digest="7" * 64))) == {
        "enclosure",
        "context",
    }
    assert _changed_keys(
        baseline,
        _fingerprint_scope(_context(extra_targets=("validation:thermal",))),
    ) == {"validation", "context"}
    assert (
        _context().semantic_fingerprint()
        == "505bbe91c05fc94b2cc6e1ec62ae46605d0dcc6d5a88c1b25e5b6cd316bcfc41"
    )


def test_finding_identity_excludes_wording_but_includes_semantics() -> None:
    first = _finding(
        SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
        SemanticDisposition.ADVISORY,
        message="First wording",
    )
    repeated = _finding(
        SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
        SemanticDisposition.ADVISORY,
        message="Different wording",
    )
    changed = _finding(
        SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
        SemanticDisposition.UNVERIFIED,
        message="First wording",
    )
    assert first.finding_id == repeated.finding_id
    assert first.finding_id != changed.finding_id


def test_aggregate_models_revalidate_forged_nested_values() -> None:
    profile = _semantic_profile()
    advisory = next(
        rule
        for rule in profile.rules
        if rule.authority is SemanticAuthorityClass.ADVISORY_HYPOTHESIS
    )
    forged_rule = advisory.model_copy(update={"validation_requirement_ids": ("validation:rf",)})
    with pytest.raises(ValidationError, match="advisory authority"):
        SemanticLayoutProfile(
            profile_id=profile.profile_id,
            revision=profile.revision,
            evidence_bindings=profile.evidence_bindings,
            regions=profile.regions,
            rules=tuple(
                forged_rule if item.rule_id == advisory.rule_id else item for item in profile.rules
            ),
        )

    assembly = _assembly()
    forged_record = assembly.qualification_records[0].model_copy(update={"review_identity": ""})
    with pytest.raises(ValidationError, match="review_identity"):
        AssemblyProcessProfile(
            profile_id=assembly.profile_id,
            assembler_id=assembly.assembler_id,
            process_revision=assembly.process_revision,
            sequence=assembly.sequence,
            ordered_process_steps=assembly.ordered_process_steps,
            evidence_bindings=assembly.evidence_bindings,
            qualification_records=(forged_record,),
        )

    quantity = SemanticQuantity(
        quantity_id="quantity:forged",
        value=1,
        unit="mm",
        source_binding_ids=("binding:layout",),
    )
    with pytest.raises(ValidationError, match="unit"):
        SemanticMetric(
            metric_id="metric:forged",
            verification=SemanticVerification.EXACT,
            quantity=quantity.model_copy(update={"unit": ""}),
        )


def test_result_revalidates_nested_model_copy_payloads() -> None:
    finding = _finding(
        SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
        SemanticDisposition.ADVISORY,
    )
    forged_finding = finding.model_copy(update={"disposition": SemanticDisposition.FAIL})
    with pytest.raises(ValidationError, match="incompatible with its authority"):
        SemanticLayoutResult.build(
            context_fingerprint=_context().semantic_fingerprint(),
            declarations_fingerprint=_semantic_profile().semantic_fingerprint(),
            geometry_fingerprint=_region().semantic_fingerprint(),
            findings=(forged_finding,),
        )

    metric = SemanticMetric(
        metric_id="metric:distance",
        verification=SemanticVerification.EXACT,
        quantity=SemanticQuantity(
            quantity_id="quantity:distance",
            value=1,
            unit="mm",
            source_binding_ids=("binding:layout",),
        ),
    )
    forged_metric = metric.model_copy(update={"quantity": None})
    with pytest.raises(ValidationError, match="supported metrics require one"):
        SemanticLayoutResult.build(
            context_fingerprint=_context().semantic_fingerprint(),
            declarations_fingerprint=_semantic_profile().semantic_fingerprint(),
            geometry_fingerprint=_region().semantic_fingerprint(),
            metrics=(forged_metric,),
        )


def test_result_outcomes_keep_route_and_release_authority_separate() -> None:
    metric = SemanticMetric(
        metric_id="metric:distance",
        verification=SemanticVerification.EXACT,
        quantity=SemanticQuantity(
            quantity_id="quantity:distance",
            value=1200,
            unit="um",
            source_binding_ids=("binding:layout",),
        ),
        object_ids=("U1",),
    )
    common = {
        "context_fingerprint": _context().semantic_fingerprint(),
        "declarations_fingerprint": _semantic_profile().semantic_fingerprint(),
        "geometry_fingerprint": _region().semantic_fingerprint(),
        "metrics": (metric,),
    }
    hard_failure = SemanticLayoutResult.build(
        **common,
        findings=(
            _finding(
                SemanticAuthorityClass.HARD_GEOMETRY,
                SemanticDisposition.FAIL,
                metric_ids=(metric.metric_id,),
            ),
        ),
    )
    hard_unverified = SemanticLayoutResult.build(
        **common,
        findings=(
            _finding(
                SemanticAuthorityClass.HARD_GEOMETRY,
                SemanticDisposition.UNVERIFIED,
                verification=SemanticVerification.UNSUPPORTED,
            ),
        ),
    )
    validation_failure = SemanticLayoutResult.build(
        **common,
        findings=(
            _finding(
                SemanticAuthorityClass.VALIDATION_REQUIRED,
                SemanticDisposition.FAIL,
            ),
        ),
    )
    validation_pending = SemanticLayoutResult.build(
        **common,
        findings=(
            _finding(
                SemanticAuthorityClass.VALIDATION_REQUIRED,
                SemanticDisposition.VALIDATION_PENDING,
            ),
        ),
    )
    advisory = SemanticLayoutResult.build(
        **common,
        findings=(
            _finding(
                SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
                SemanticDisposition.ADVISORY,
            ),
        ),
    )
    assert hard_failure.outcome is SemanticResultOutcome.HARD_REJECTED
    assert hard_unverified.outcome is SemanticResultOutcome.HARD_SCOPE_UNVERIFIED
    assert validation_failure.outcome is SemanticResultOutcome.VALIDATION_FAILED
    assert validation_pending.outcome is SemanticResultOutcome.VALIDATION_PENDING
    assert advisory.outcome is SemanticResultOutcome.ADVISORY_REVIEW
    assert hard_failure.summary.route_acceptance_blocked
    assert hard_unverified.summary.route_acceptance_blocked
    assert not validation_failure.summary.route_acceptance_blocked
    assert (
        hard_failure.semantic_fingerprint()
        == "c36f916bb264d2047c999322cd0e8f8692069ae2625ee1907c415e38a3d47265"
    )

    forged = hard_failure.model_copy(update={"outcome": SemanticResultOutcome.PASSED})
    with pytest.raises(ValidationError, match="outcome is not derived"):
        SemanticLayoutResult.model_validate_json(forged.model_dump_json())
