"""R6.5 process-scoped dual-side component-retention firing matrix."""

from __future__ import annotations

from copy import deepcopy
from datetime import date

import pytest
from pydantic import ValidationError

from pcbsmith.assembly_retention_ir import (
    AdvisoryRetentionModel,
    AssemblerRetentionRule,
    AssemblerRetentionVerdict,
    AssemblyProcessProfile,
    AssemblyRetentionDeclaration,
    AssemblyRetentionResult,
    ComponentSide,
    PackageRetentionEvidence,
    QualifiedAssemblerReview,
    RetentionApplicabilityConditions,
    RetentionModelApplicability,
    RetentionValueStatus,
    fingerprint,
)
from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.kicad.assembly_retention import evaluate_assembly_retention
from pcbsmith.kicad.board import BoardComponent, BoardLayout, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.semantic_ir import (
    EvidenceApplicabilityBinding,
    SemanticAuthorityClass,
    SemanticDisposition,
)


def _board() -> tuple[BoardLayout, BoardNetlist]:
    u1 = BoardComponent(
        reference="U1",
        value="fixture",
        footprint="Fixture:QFN",
        uuid_path="uuid:U1",
    )
    u2 = BoardComponent(
        reference="U2",
        value="fixture",
        footprint="Fixture:Chip",
        uuid_path="uuid:U2",
    )
    return (
        BoardLayout(
            placements=((u1, 5.0), (u2, 15.0)),
            segments=(),
            vias=(),
            width_mm=20.0,
            height_mm=10.0,
            part_flip=("U1",),
        ),
        BoardNetlist(components=(u1, u2), nets=()),
    )


def _binding(
    *,
    binding_id: str = "binding:retention",
    claim_id: str = "claim:retention",
    object_fingerprint: str | None = None,
    condition_ids: tuple[str, ...] = ("exact-retention-fixture",),
    source_sha256: str | None = "a" * 64,
    complete: bool = True,
) -> EvidenceApplicabilityBinding:
    return EvidenceApplicabilityBinding(
        binding_id=binding_id,
        evidence=(
            EvidenceRef(
                kind="assembler_process_record",
                title="Retention fixture",
                locator="record:1",
                source_id="source:retention",
                organization_or_author="Fixture Assembler",
                revision="1",
                local_sha256=source_sha256 if complete else None,
                source_status="pinned" if complete else "unpinned",
                locator_status="text_verified" if complete else "unverified",
                applicability_status="confirmed" if complete else "unknown",
                required_conditions=condition_ids,
            ),
        ),
        claim_id=claim_id,
        applicability_record_id=f"applicability:{binding_id}",
        required_conditions=condition_ids,
        excluded_conditions=(),
        matched_conditions=condition_ids,
        unmatched_conditions=(),
        geometry_source_fingerprint=object_fingerprint,
        reviewer_record_id="reviewer:fixture" if complete else None,
    )


def _profile(
    *,
    sequence: str = "double_reflow",
    evidence_binding_ids: tuple[str, ...] = ("binding:retention",),
) -> AssemblyProcessProfile:
    if sequence == "double_reflow":
        first, second, inverted = "back", "front", "back"
    else:
        first, second, inverted = "not_applicable", "not_applicable", "none"
    return AssemblyProcessProfile(
        profile_id="process:fixture",
        assembler_id="assembler:fixture",
        process_revision="r1",
        sequence=sequence,
        first_reflow_side=first,
        second_reflow_side=second,
        inverted_during_second_reflow_side=inverted,
        alloy_id="SAC305",
        paste_id="paste:fixture",
        surface_finish_id="finish:enig",
        stencil_thickness_um=125,
        aperture_process_id="aperture:laser",
        oven_id="oven:1",
        peak_temperature_millic=245_000,
        time_above_liquidus_ms=60_000,
        conveyor_orientation="parallel",
        turbulence_class="low",
        board_carrier_id="carrier:none",
        adhesive_policy_id="adhesive:none",
        handling_policy_id="handling:fixture",
        process_condition_ids=(
            "exact-alloy-paste-finish-stencil-oven-profile",
            "exact-package-pad-aperture-void-orientation",
            "nitrogen",
        ),
        evidence_binding_ids=evidence_binding_ids,
    )


def _evidence(
    layout: BoardLayout,
    netlist: BoardNetlist,
    *,
    reference: str = "U1",
    mass_ug: int | None = 4_300,
    perimeter_um: int | None = 200,
    source_binding_ids: tuple[str, ...] = ("binding:retention",),
) -> PackageRetentionEvidence:
    component = next(item for item in netlist.components if item.reference == reference)
    return PackageRetentionEvidence(
        evidence_id=f"package:{reference}",
        component_reference=reference,
        footprint=component.footprint,
        side=ComponentSide.BACK if reference in layout.part_flip else ComponentSide.FRONT,
        board_layout_snapshot_fingerprint=board_layout_snapshot_fingerprint(
            canonical_board_layout_snapshot_json(layout)
        ),
        board_netlist_snapshot_fingerprint=board_netlist_snapshot_fingerprint(
            canonical_board_netlist_snapshot_json(netlist)
        ),
        package_family="QFN" if reference == "U1" else "CHIP",
        component_mass_ug=mass_ug,
        mass_source="manufacturer" if mass_ug is not None else "unknown",
        joint_ids=(f"{reference}.1", f"{reference}.2"),
        total_wetted_perimeter_um=perimeter_um,
        perimeter_geometry_kind="wetted_joint_interface" if perimeter_um is not None else "unknown",
        wetted_perimeter_method_id="method:joint-interface-r1"
        if perimeter_um is not None
        else None,
        pad_pattern_fingerprint="b" * 64 if reference == "U1" else "d" * 64,
        paste_aperture_fingerprint="c" * 64,
        void_fraction_basis_points=0,
        orientation_to_conveyor_millideg=0,
        source_binding_ids=source_binding_ids,
    )


def _model() -> AdvisoryRetentionModel:
    return AdvisoryRetentionModel(
        model_id="model:smta-sac305-narrow-fixture",
        model_revision="r1",
        model_kind="narrow_sac305_experiment",
        authority=SemanticAuthorityClass.ADVISORY_HYPOTHESIS,
        calculation_kind="mass_per_wetted_perimeter",
        advisory_limit_numerator_ug_per_um=43,
        advisory_limit_denominator=2,
        conditions=RetentionApplicabilityConditions(
            sequence="double_reflow",
            inverted_side=ComponentSide.BACK,
            alloy_id="SAC305",
            paste_id="paste:fixture",
            surface_finish_id="finish:enig",
            stencil_thickness_um=125,
            aperture_process_id="aperture:laser",
            oven_id="oven:1",
            peak_temperature_millic=245_000,
            time_above_liquidus_ms=60_000,
            conveyor_orientation="parallel",
            turbulence_class="low",
            board_carrier_id="carrier:none",
            adhesive_policy_id="adhesive:none",
            handling_policy_id="handling:fixture",
            package_families=("QFN",),
            pad_pattern_fingerprints=("b" * 64,),
            paste_aperture_fingerprints=("c" * 64,),
            void_fraction_basis_points=0,
            component_orientation_millideg=0,
            required_condition_ids=(
                "exact-alloy-paste-finish-stencil-oven-profile",
                "exact-package-pad-aperture-void-orientation",
            ),
            excluded_process_condition_ids=("adhesive-used", "wave-solder"),
        ),
        source_binding_ids=("binding:retention",),
    )


def _rule(
    layout: BoardLayout,
    netlist: BoardNetlist,
    process: AssemblyProcessProfile,
    evidence: PackageRetentionEvidence,
    *,
    numerator: int = 43,
    denominator: int = 2,
    status: str = "active",
    expiry: date | None = date(2027, 1, 1),
    layout_fingerprint: str | None = None,
    review_binding_ids: tuple[str, ...] = ("binding:review",),
    rule_binding_ids: tuple[str, ...] = ("binding:rule",),
    covered_condition_ids: tuple[str, ...] | None = None,
    deviation_ids: tuple[str, ...] = (),
) -> AssemblerRetentionRule:
    context = {
        "rule_id": "assembler-rule:maximum-retention-ratio",
        "calculation_kind": "mass_per_wetted_perimeter",
        "maximum_ratio_numerator_ug_per_um": numerator,
        "maximum_ratio_denominator": denominator,
    }
    review = QualifiedAssemblerReview(
        review_id="assembler-review:fixture",
        assembler_id="assembler:fixture",
        reviewer_identity="reviewer:fixture",
        qualification_record_id="qualification:fixture",
        qualification_source_sha256="a" * 64,
        status=status,
        effective_date=date(2026, 1, 1),
        expiry_date=expiry,
        board_layout_snapshot_fingerprint=(
            layout_fingerprint
            or board_layout_snapshot_fingerprint(canonical_board_layout_snapshot_json(layout))
        ),
        board_netlist_snapshot_fingerprint=board_netlist_snapshot_fingerprint(
            canonical_board_netlist_snapshot_json(netlist)
        ),
        process_profile_fingerprint=process.semantic_fingerprint(),
        component_evidence_fingerprint=evidence.semantic_fingerprint(),
        package_family=evidence.package_family,
        rule_context_fingerprint=fingerprint(context),
        covered_condition_ids=covered_condition_ids or process.process_condition_ids,
        required_restriction_ids=("assembler-rule:maximum-retention-ratio",),
        deviation_ids=deviation_ids,
        source_binding_ids=review_binding_ids,
    )
    return AssemblerRetentionRule(
        rule_id="assembler-rule:maximum-retention-ratio",
        authority=SemanticAuthorityClass.QUALIFIED_PROCESS_REQUIREMENT,
        calculation_kind="mass_per_wetted_perimeter",
        maximum_ratio_numerator_ug_per_um=numerator,
        maximum_ratio_denominator=denominator,
        review=review,
        source_binding_ids=rule_binding_ids,
    )


def _hard_bindings(
    process: AssemblyProcessProfile,
    evidence: PackageRetentionEvidence,
    rule: AssemblerRetentionRule,
    *,
    review_source_sha256: str = "a" * 64,
) -> tuple[EvidenceApplicabilityBinding, ...]:
    return (
        _binding(
            binding_id="binding:package",
            claim_id=evidence.evidence_id,
            object_fingerprint=evidence.semantic_fingerprint(),
            condition_ids=("exact-package-context",),
        ),
        _binding(
            binding_id="binding:process",
            claim_id=process.profile_id,
            object_fingerprint=process.semantic_fingerprint(),
            condition_ids=("exact-process-context",),
        ),
        _binding(
            binding_id="binding:review",
            claim_id=rule.review.review_id,
            object_fingerprint=rule.review.semantic_fingerprint(),
            condition_ids=("exact-review-context",),
            source_sha256=review_source_sha256,
        ),
        _binding(
            binding_id="binding:rule",
            claim_id=rule.rule_id,
            object_fingerprint=rule.semantic_fingerprint(),
            condition_ids=("exact-rule-threshold-context",),
        ),
    )


def _declaration(
    layout: BoardLayout,
    netlist: BoardNetlist,
    *,
    process: AssemblyProcessProfile | None = None,
    evidence: tuple[PackageRetentionEvidence, ...] | None = None,
    models: tuple[AdvisoryRetentionModel, ...] = (),
    rules: tuple[AssemblerRetentionRule, ...] = (),
    binding: EvidenceApplicabilityBinding | None = None,
    bindings: tuple[EvidenceApplicabilityBinding, ...] | None = None,
) -> AssemblyRetentionDeclaration:
    actual_evidence = evidence or (_evidence(layout, netlist),)
    layout_json = canonical_board_layout_snapshot_json(layout)
    netlist_json = canonical_board_netlist_snapshot_json(netlist)
    return AssemblyRetentionDeclaration(
        declaration_id="retention:fixture",
        evaluation_date=date(2026, 7, 18),
        board_layout_snapshot_json=layout_json,
        board_netlist_snapshot_json=netlist_json,
        board_layout_snapshot_fingerprint=board_layout_snapshot_fingerprint(layout_json),
        board_netlist_snapshot_fingerprint=board_netlist_snapshot_fingerprint(netlist_json),
        process_profile=process or _profile(),
        scoped_component_references=tuple(item.component_reference for item in actual_evidence),
        whole_board_component_inventory_declared=False,
        package_evidence=actual_evidence,
        advisory_models=models,
        assembler_rules=rules,
        evidence_bindings=bindings or (binding or _binding(),),
    )


def test_front_and_back_placement_alone_never_infers_double_reflow() -> None:
    layout, netlist = _board()
    declaration = _declaration(layout, netlist, process=_profile(sequence="other"))
    result = evaluate_assembly_retention(layout, netlist, declaration)
    finding = result.component_findings[0]
    assert finding.side is ComponentSide.BACK
    assert not finding.inverted_during_second_reflow
    assert finding.process_applicability is SemanticDisposition.NOT_APPLICABLE
    assert finding.mass_status is RetentionValueStatus.NOT_APPLICABLE
    assert finding.final_finding_kind == "not_applicable"


@pytest.mark.parametrize(("mass", "perimeter"), ((None, 200), (4_300, None), (None, None)))
def test_missing_mass_or_wetted_geometry_is_unverified(
    mass: int | None, perimeter: int | None
) -> None:
    layout, netlist = _board()
    declaration = _declaration(
        layout,
        netlist,
        evidence=(_evidence(layout, netlist, mass_ug=mass, perimeter_um=perimeter),),
        models=(_model(),),
    )
    finding = evaluate_assembly_retention(layout, netlist, declaration).component_findings[0]
    assert finding.ratio is None
    assert finding.final_disposition is SemanticDisposition.UNVERIFIED
    assert finding.final_finding_kind == "missing_package_measurement"
    assert finding.advisory_evidence[0].comparison is None


def test_body_perimeter_substitution_is_rejected_at_the_ir_boundary() -> None:
    layout, netlist = _board()
    payload = _evidence(layout, netlist).model_dump()
    payload["perimeter_geometry_kind"] = "body_outline"
    with pytest.raises(ValidationError, match="body outline"):
        PackageRetentionEvidence.model_validate(payload)


def test_narrow_sac305_ratio_is_exact_deterministic_and_only_advisory() -> None:
    layout, netlist = _board()
    declaration = _declaration(layout, netlist, models=(_model(),))
    first = evaluate_assembly_retention(layout, netlist, declaration)
    second = evaluate_assembly_retention(layout, netlist, declaration)
    finding = first.component_findings[0]
    assert first == second
    assert finding.ratio is not None
    assert finding.ratio.numerator_mass_ug == 4_300
    assert finding.ratio.denominator_wetted_perimeter_um == 200
    assert finding.ratio.diagnostic_ug_per_um == "21.5"
    assert finding.advisory_evidence[0].applicability is RetentionModelApplicability.MATCHED
    assert finding.advisory_evidence[0].comparison == "at_or_below_advisory_limit"
    assert finding.final_disposition is SemanticDisposition.ADVISORY
    assert finding.assembler_verdict is AssemblerRetentionVerdict.NOT_APPLICABLE


@pytest.mark.parametrize(
    ("target", "field", "value"),
    (
        ("process", "surface_finish_id", "finish:hasl"),
        ("process", "stencil_thickness_um", 100),
        ("process", "paste_id", "paste:other"),
        ("process", "alloy_id", "Sn63Pb37"),
        ("process", "peak_temperature_millic", 244_999),
        ("process", "time_above_liquidus_ms", 59_999),
        ("process", "oven_id", "oven:2"),
        ("process", "aperture_process_id", "aperture:etched"),
        ("process", "conveyor_orientation", "perpendicular"),
        ("process", "turbulence_class", "high"),
        ("process", "board_carrier_id", "carrier:fixture"),
        ("process", "adhesive_policy_id", "adhesive:used"),
        ("process", "handling_policy_id", "handling:other"),
        ("package", "package_family", "DFN"),
        ("package", "pad_pattern_fingerprint", "e" * 64),
        ("package", "void_fraction_basis_points", 1),
        ("package", "orientation_to_conveyor_millideg", 1),
        ("package", "paste_aperture_fingerprint", "f" * 64),
    ),
)
def test_each_relevant_process_or_package_change_breaks_advisory_applicability(
    target: str, field: str, value: object
) -> None:
    layout, netlist = _board()
    process = _profile()
    evidence = _evidence(layout, netlist)
    if target == "process":
        process = AssemblyProcessProfile.model_validate({**process.model_dump(), field: value})
    else:
        evidence = PackageRetentionEvidence.model_validate({**evidence.model_dump(), field: value})
    declaration = _declaration(
        layout, netlist, process=process, evidence=(evidence,), models=(_model(),)
    )
    model_evidence = (
        evaluate_assembly_retention(layout, netlist, declaration)
        .component_findings[0]
        .advisory_evidence[0]
    )
    assert model_evidence.applicability is RetentionModelApplicability.UNVERIFIED
    assert field in model_evidence.unmatched_condition_ids
    assert model_evidence.comparison is None


def test_qfn_label_never_creates_a_hard_result() -> None:
    layout, netlist = _board()
    result = evaluate_assembly_retention(
        layout, netlist, _declaration(layout, netlist, models=(_model(),))
    )
    finding = result.component_findings[0]
    assert finding.final_disposition is SemanticDisposition.ADVISORY
    assert not finding.assembler_evidence


def test_narrow_sac305_model_cannot_be_relabelled_for_another_alloy() -> None:
    payload = _model().model_dump()
    payload["conditions"]["alloy_id"] = "Sn63Pb37"
    with pytest.raises(ValidationError, match="cannot be relabeled"):
        AdvisoryRetentionModel.model_validate(payload)


def test_excluded_process_condition_breaks_advisory_applicability() -> None:
    layout, netlist = _board()
    profile = AssemblyProcessProfile.model_validate(
        {**_profile().model_dump(), "process_condition_ids": ("adhesive-used", "nitrogen")}
    )
    evidence = (
        evaluate_assembly_retention(
            layout,
            netlist,
            _declaration(layout, netlist, process=profile, models=(_model(),)),
        )
        .component_findings[0]
        .advisory_evidence[0]
    )
    assert evidence.applicability is RetentionModelApplicability.UNVERIFIED
    assert "excluded_process_condition_ids" in evidence.unmatched_condition_ids


def test_unknown_process_fields_remain_none_and_prevent_model_applicability() -> None:
    layout, netlist = _board()
    profile = AssemblyProcessProfile.model_validate(
        {**_profile().model_dump(), "paste_id": None, "oven_id": None}
    )
    assert profile.paste_id is None and profile.oven_id is None
    evidence = (
        evaluate_assembly_retention(
            layout,
            netlist,
            _declaration(layout, netlist, process=profile, models=(_model(),)),
        )
        .component_findings[0]
        .advisory_evidence[0]
    )
    assert evidence.applicability is RetentionModelApplicability.UNVERIFIED
    assert set(evidence.unmatched_condition_ids) >= {"paste_id", "oven_id"}


def test_missing_required_advisory_condition_id_prevents_applicability() -> None:
    layout, netlist = _board()
    profile = AssemblyProcessProfile.model_validate(
        {
            **_profile().model_dump(),
            "process_condition_ids": (
                "exact-alloy-paste-finish-stencil-oven-profile",
                "nitrogen",
            ),
        }
    )
    evidence = (
        evaluate_assembly_retention(
            layout,
            netlist,
            _declaration(layout, netlist, process=profile, models=(_model(),)),
        )
        .component_findings[0]
        .advisory_evidence[0]
    )
    assert evidence.applicability is RetentionModelApplicability.UNVERIFIED
    assert (
        "required_condition:exact-package-pad-aperture-void-orientation"
        in evidence.unmatched_condition_ids
    )


def test_ratio_diagnostic_uses_deterministic_integer_long_division() -> None:
    layout, netlist = _board()
    evidence = _evidence(layout, netlist, mass_ug=1, perimeter_um=3)
    declaration = _declaration(layout, netlist, evidence=(evidence,), models=(_model(),))
    first = evaluate_assembly_retention(layout, netlist, declaration)
    second = evaluate_assembly_retention(layout, netlist, declaration)
    assert first.component_findings[0].ratio is not None
    assert first.component_findings[0].ratio.diagnostic_ug_per_um == "0.333333333333"
    assert first == second


def test_active_exact_assembler_rule_passes_at_equality_and_one_less_threshold_fails() -> None:
    layout, netlist = _board()
    process = _profile(evidence_binding_ids=("binding:process",))
    evidence = _evidence(layout, netlist, source_binding_ids=("binding:package",))
    equal_rule = _rule(layout, netlist, process, evidence)
    equal = evaluate_assembly_retention(
        layout,
        netlist,
        _declaration(
            layout,
            netlist,
            process=process,
            evidence=(evidence,),
            rules=(equal_rule,),
            bindings=_hard_bindings(process, evidence, equal_rule),
        ),
    ).component_findings[0]
    assert equal.assembler_verdict is AssemblerRetentionVerdict.PASS
    assert equal.final_disposition is SemanticDisposition.PASS
    lower_rule = _rule(layout, netlist, process, evidence, numerator=42, denominator=2)
    lower = evaluate_assembly_retention(
        layout,
        netlist,
        _declaration(
            layout,
            netlist,
            process=process,
            evidence=(evidence,),
            rules=(lower_rule,),
            bindings=_hard_bindings(process, evidence, lower_rule),
        ),
    ).component_findings[0]
    assert lower.assembler_verdict is AssemblerRetentionVerdict.FAIL
    assert lower.final_disposition is SemanticDisposition.FAIL


@pytest.mark.parametrize(
    ("status", "expiry", "layout_fingerprint", "reason"),
    (
        ("expired", date(2026, 7, 1), None, "review_status"),
        ("active", date(2026, 7, 1), None, "review_effective_dates"),
        ("active", date(2027, 1, 1), "9" * 64, "board_layout_snapshot_fingerprint"),
    ),
)
def test_expired_or_mismatched_assembler_review_requires_process_review(
    status: str, expiry: date, layout_fingerprint: str | None, reason: str
) -> None:
    layout, netlist = _board()
    process = _profile(evidence_binding_ids=("binding:process",))
    evidence = _evidence(layout, netlist, source_binding_ids=("binding:package",))
    rule = _rule(
        layout,
        netlist,
        process,
        evidence,
        status=status,
        expiry=expiry,
        layout_fingerprint=layout_fingerprint,
    )
    finding = evaluate_assembly_retention(
        layout,
        netlist,
        _declaration(
            layout,
            netlist,
            process=process,
            evidence=(evidence,),
            rules=(rule,),
            bindings=_hard_bindings(process, evidence, rule),
        ),
    ).component_findings[0]
    assert finding.assembler_verdict is AssemblerRetentionVerdict.PROCESS_REVIEW_REQUIRED
    assert finding.final_disposition is SemanticDisposition.UNVERIFIED
    assert reason in finding.assembler_evidence[0].reason_ids


def test_incomplete_assembler_source_binding_cannot_create_hard_authority() -> None:
    layout, netlist = _board()
    process = _profile(evidence_binding_ids=("binding:process",))
    evidence = _evidence(layout, netlist, source_binding_ids=("binding:package",))
    rule = _rule(layout, netlist, process, evidence)
    bindings = list(_hard_bindings(process, evidence, rule))
    bindings[1] = _binding(
        binding_id="binding:process",
        claim_id=process.profile_id,
        object_fingerprint=process.semantic_fingerprint(),
        condition_ids=("exact-process-context",),
        complete=False,
    )
    result = evaluate_assembly_retention(
        layout,
        netlist,
        _declaration(
            layout,
            netlist,
            process=process,
            evidence=(evidence,),
            rules=(rule,),
            bindings=tuple(bindings),
        ),
    )
    item = result.component_findings[0].assembler_evidence[0]
    assert item.verdict is AssemblerRetentionVerdict.PROCESS_REVIEW_REQUIRED
    assert "pinned_applicable_reviewer_evidence" in item.reason_ids


@pytest.mark.parametrize("tamper", ("fingerprint", "claim"))
def test_unrelated_complete_binding_cannot_authorize_a_hard_object_context(tamper: str) -> None:
    layout, netlist = _board()
    process = _profile(evidence_binding_ids=("binding:process",))
    evidence = _evidence(layout, netlist, source_binding_ids=("binding:package",))
    rule = _rule(layout, netlist, process, evidence)
    bindings = list(_hard_bindings(process, evidence, rule))
    bindings[0] = _binding(
        binding_id="binding:package",
        claim_id="unrelated:claim" if tamper == "claim" else evidence.evidence_id,
        object_fingerprint=(
            process.semantic_fingerprint()
            if tamper == "fingerprint"
            else evidence.semantic_fingerprint()
        ),
        condition_ids=("exact-package-context",),
    )
    item = (
        evaluate_assembly_retention(
            layout,
            netlist,
            _declaration(
                layout,
                netlist,
                process=process,
                evidence=(evidence,),
                rules=(rule,),
                bindings=tuple(bindings),
            ),
        )
        .component_findings[0]
        .assembler_evidence[0]
    )
    assert item.verdict is AssemblerRetentionVerdict.PROCESS_REVIEW_REQUIRED
    assert "package_object_context_binding" in item.reason_ids


def test_binding_evidence_must_exactly_cover_fully_matched_required_conditions() -> None:
    layout, netlist = _board()
    process = _profile(evidence_binding_ids=("binding:process",))
    evidence = _evidence(layout, netlist, source_binding_ids=("binding:package",))
    rule = _rule(layout, netlist, process, evidence)
    bindings = list(_hard_bindings(process, evidence, rule))
    payload = bindings[0].model_dump()
    payload["required_conditions"] = ("condition:a", "condition:b")
    payload["matched_conditions"] = ("condition:a", "condition:b")
    payload["evidence"][0]["required_conditions"] = ("condition:a",)
    bindings[0] = EvidenceApplicabilityBinding.model_validate(payload)
    item = (
        evaluate_assembly_retention(
            layout,
            netlist,
            _declaration(
                layout,
                netlist,
                process=process,
                evidence=(evidence,),
                rules=(rule,),
                bindings=tuple(bindings),
            ),
        )
        .component_findings[0]
        .assembler_evidence[0]
    )
    assert item.verdict is AssemblerRetentionVerdict.PROCESS_REVIEW_REQUIRED
    assert "pinned_applicable_reviewer_evidence" in item.reason_ids


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    (
        ("no-process-binding", "process_profile_evidence_binding_ids"),
        ("conditions-not-covered", "covered_process_condition_ids"),
        ("deviation", "review_deviation_ids"),
        ("qualification-sha-not-in-review", "qualification_source_sha256"),
    ),
)
def test_hard_review_fails_closed_for_missing_process_or_review_authority(
    case: str, expected_reason: str
) -> None:
    layout, netlist = _board()
    process = _profile(
        evidence_binding_ids=() if case == "no-process-binding" else ("binding:process",)
    )
    evidence = _evidence(layout, netlist, source_binding_ids=("binding:package",))
    rule = _rule(
        layout,
        netlist,
        process,
        evidence,
        covered_condition_ids=("nitrogen",) if case == "conditions-not-covered" else None,
        deviation_ids=("deviation:1",) if case == "deviation" else (),
    )
    bindings = _hard_bindings(
        process,
        evidence,
        rule,
        review_source_sha256=("f" * 64 if case == "qualification-sha-not-in-review" else "a" * 64),
    )
    item = (
        evaluate_assembly_retention(
            layout,
            netlist,
            _declaration(
                layout,
                netlist,
                process=process,
                evidence=(evidence,),
                rules=(rule,),
                bindings=bindings,
            ),
        )
        .component_findings[0]
        .assembler_evidence[0]
    )
    assert item.verdict is AssemblerRetentionVerdict.PROCESS_REVIEW_REQUIRED
    assert expected_reason in item.reason_ids


def test_declared_inventory_is_exact_but_not_silently_whole_board() -> None:
    layout, netlist = _board()
    declaration = _declaration(layout, netlist)
    result = evaluate_assembly_retention(layout, netlist, declaration)
    assert result.inventory_scope == "declared_component_scope_only_not_whole_board"
    payload = declaration.model_dump()
    payload["whole_board_component_inventory_declared"] = True
    with pytest.raises(ValidationError, match="every BoardNetlist component"):
        AssemblyRetentionDeclaration.model_validate(payload)


def test_replay_tamper_order_and_input_immutability() -> None:
    layout, netlist = _board()
    evidence = (_evidence(layout, netlist, reference="U2"), _evidence(layout, netlist))
    declaration = _declaration(layout, netlist, evidence=evidence, models=(_model(),))
    assert tuple(item.component_reference for item in declaration.package_evidence) == ("U1", "U2")
    layout_before = deepcopy(layout)
    netlist_before = deepcopy(netlist)
    result = evaluate_assembly_retention(layout, netlist, declaration)
    assert layout == layout_before and netlist == netlist_before
    restored = AssemblyRetentionResult.model_validate_json(result.model_dump_json())
    assert restored == result
    tampered = result.model_dump()
    tampered["component_findings"][0]["final_disposition"] = "pass"
    with pytest.raises(ValidationError, match="stale or not replay-derived"):
        AssemblyRetentionResult.model_validate(tampered)
    changed_layout = BoardLayout(**{**layout.__dict__, "width_mm": 21.0})
    with pytest.raises(ValueError, match="differs from the declaration"):
        evaluate_assembly_retention(changed_layout, netlist, declaration)
