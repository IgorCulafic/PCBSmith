from __future__ import annotations

import hashlib

from pcbsmith.review_conventions import (
    ConventionApplicability,
    ConventionApplicabilityContext,
    ConventionCheckDisposition,
    ConventionCheckResult,
    ConventionClass,
    ConventionDomain,
    ReviewConvention,
    evaluate_review_conventions,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _convention(
    convention_id: str,
    convention_class: ConventionClass,
    applicability: ConventionApplicability,
    *,
    trigger_ids: tuple[str, ...] = (),
) -> ReviewConvention:
    return ReviewConvention(
        convention_id=convention_id,
        domain=ConventionDomain.PCB,
        convention_class=convention_class,
        applicability=applicability,
        summary=f"Typed convention {convention_id}.",
        trigger_ids=trigger_ids,
        authority_id=f"authority.{convention_id}",
        source_document_sha256=_sha("user supplied conventions"),
        source_start=10,
        source_end=20,
    )


def _result(
    convention_id: str,
    design: str,
    disposition: ConventionCheckDisposition,
) -> ConventionCheckResult:
    return ConventionCheckResult(
        convention_id=convention_id,
        saved_design_sha256=design,
        producer_id="test.convention-checker",
        tool_version="1",
        disposition=disposition,
        evaluated_object_count=1,
        evidence_sha256=_sha(f"{convention_id}.{disposition.value}"),
        findings=(f"{convention_id} finding",),
    )


def test_release_failure_blocks_but_presentation_failure_does_not() -> None:
    design = _sha("board")
    release = _convention(
        "orientation-markers",
        ConventionClass.RELEASE,
        ConventionApplicability.ALWAYS,
    )
    presentation = _convention(
        "helpful-silkscreen-text",
        ConventionClass.PRESENTATION,
        ConventionApplicability.SPACE_CONDITIONAL,
    )
    context = ConventionApplicabilityContext.build(
        saved_design_sha256=design,
        space_available=True,
    )

    report = evaluate_review_conventions(
        conventions=(presentation, release),
        context=context,
        results=(
            _result(release.convention_id, design, ConventionCheckDisposition.FAIL),
            _result(
                presentation.convention_id,
                design,
                ConventionCheckDisposition.FAIL,
            ),
        ),
    )

    assert not report.ready
    assert len(report.blockers) == 1
    assert report.blockers[0].startswith("orientation-markers:")


def test_dormant_board_trigger_cannot_be_promoted_to_universal_blocker() -> None:
    design = _sha("board")
    sensitive_routing = _convention(
        "no-routing-under-rf",
        ConventionClass.CONDITIONAL_ELECTRICAL_LAYOUT,
        ConventionApplicability.BOARD_TRIGGERED,
        trigger_ids=("rf", "antenna"),
    )
    context = ConventionApplicabilityContext.build(
        saved_design_sha256=design,
        board_trigger_ids=("usb2",),
    )

    report = evaluate_review_conventions(
        conventions=(sensitive_routing,),
        context=context,
        results=(),
    )

    assert report.ready
    assert report.evaluations[0].applicable is False
    assert report.evaluations[0].check_disposition is ConventionCheckDisposition.NOT_APPLICABLE


def test_unresolved_human_applicability_blocks_only_release_class() -> None:
    design = _sha("board")
    release = _convention(
        "mounting-authority",
        ConventionClass.RELEASE,
        ConventionApplicability.HUMAN_DECISION,
    )
    presentation = _convention(
        "privacy-name-removal",
        ConventionClass.PRESENTATION,
        ConventionApplicability.HUMAN_DECISION,
    )
    context = ConventionApplicabilityContext.build(saved_design_sha256=design)

    report = evaluate_review_conventions(
        conventions=(release, presentation),
        context=context,
        results=(),
    )

    assert not report.ready
    assert len(report.blockers) == 1
    assert report.blockers[0].startswith("mounting-authority:")
