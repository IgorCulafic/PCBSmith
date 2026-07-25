from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from pcbsmith.applicability_execution import (
    ApplicableCheckRequirement,
    CheckExecutionRecord,
    ProjectApplicabilityExecutionManifest,
    ProjectCheckApplicability,
    ProjectCheckDisposition,
    ProjectExecutionAuthority,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _requirement(
    check_id: str,
    design_sha256: str,
    *,
    applicability: ProjectCheckApplicability = ProjectCheckApplicability.APPLICABLE,
    minimum: int = 1,
) -> ApplicableCheckRequirement:
    return ApplicableCheckRequirement.build(
        check_id=check_id,
        rule_ids=(f"rule.{check_id}",),
        applicability=applicability,
        applicability_authority_id=f"authority.{check_id}",
        exact_input_sha256s=(design_sha256, _sha(f"context.{check_id}")),
        minimum_evaluated_objects=minimum,
        rationale=f"Applicability decision for {check_id}.",
    )


def _execution(
    requirement: ApplicableCheckRequirement,
    *,
    count: int = 1,
    disposition: ProjectCheckDisposition = ProjectCheckDisposition.PASS,
) -> CheckExecutionRecord:
    return CheckExecutionRecord.build(
        check_id=requirement.check_id,
        exact_input_sha256s=requirement.exact_input_sha256s,
        producer_id=f"pcbsmith.{requirement.check_id}",
        tool_version="1.0.0",
        evaluated_object_count=count,
        disposition=disposition,
        result_sha256=_sha(f"result.{requirement.check_id}.{disposition.value}"),
    )


def test_manifest_proves_exact_applicable_execution_and_justified_na() -> None:
    design = _sha("saved-board")
    geometry = _requirement("geometry", design, minimum=3)
    rf = _requirement(
        "rf",
        design,
        applicability=ProjectCheckApplicability.NOT_APPLICABLE,
        minimum=0,
    )

    manifest = ProjectApplicabilityExecutionManifest.build(
        project_id="project.example",
        saved_design_sha256=design,
        requirements=(rf, geometry),
        executions=(_execution(geometry, count=3),),
    )

    assert manifest.authority is ProjectExecutionAuthority.READY
    assert manifest.blockers == ()
    assert tuple(item.check_id for item in manifest.requirements) == ("geometry", "rf")


@pytest.mark.parametrize(
    ("executions", "expected"),
    (
        ((), "applicable check execution is missing"),
        (
            ("too-few",),
            "evaluated-object count is 0, expected at least 1",
        ),
        (("failed",), "production execution is fail"),
    ),
)
def test_manifest_fails_closed_for_missing_zero_or_failed_execution(
    executions: tuple[str, ...],
    expected: str,
) -> None:
    design = _sha("saved-board")
    requirement = _requirement("geometry", design)
    records: tuple[CheckExecutionRecord, ...]
    if executions == ("too-few",):
        records = (_execution(requirement, count=0),)
    elif executions == ("failed",):
        records = (
            _execution(
                requirement,
                disposition=ProjectCheckDisposition.FAIL,
            ),
        )
    else:
        records = ()

    manifest = ProjectApplicabilityExecutionManifest.build(
        project_id="project.example",
        saved_design_sha256=design,
        requirements=(requirement,),
        executions=records,
    )

    assert manifest.authority is ProjectExecutionAuthority.BLOCKED
    assert any(expected in blocker for blocker in manifest.blockers)


def test_manifest_rejects_stale_conflicting_and_undeclared_execution() -> None:
    design = _sha("saved-board")
    other_design = _sha("other-board")
    geometry = _requirement("geometry", design)
    stale = CheckExecutionRecord.build(
        check_id="geometry",
        exact_input_sha256s=(other_design, _sha("context.geometry")),
        producer_id="pcbsmith.geometry",
        tool_version="1.0.0",
        evaluated_object_count=1,
        disposition=ProjectCheckDisposition.PASS,
        result_sha256=_sha("stale-result"),
    )
    extra_requirement = _requirement("extra", design)
    extra = _execution(extra_requirement)

    manifest = ProjectApplicabilityExecutionManifest.build(
        project_id="project.example",
        saved_design_sha256=design,
        requirements=(geometry,),
        executions=(stale, extra),
    )

    assert "geometry: execution inputs are stale or conflicting" in manifest.blockers
    assert "extra: execution has no applicability declaration" in manifest.blockers


def test_unresolved_and_not_applicable_checks_cannot_hide_executions() -> None:
    design = _sha("saved-board")
    unresolved = _requirement(
        "thermal",
        design,
        applicability=ProjectCheckApplicability.UNRESOLVED,
        minimum=0,
    )
    not_applicable = _requirement(
        "rf",
        design,
        applicability=ProjectCheckApplicability.NOT_APPLICABLE,
        minimum=0,
    )

    manifest = ProjectApplicabilityExecutionManifest.build(
        project_id="project.example",
        saved_design_sha256=design,
        requirements=(unresolved, not_applicable),
        executions=(_execution(unresolved), _execution(not_applicable)),
    )

    assert "thermal: applicability is unresolved" in manifest.blockers
    assert "thermal: unresolved check has conflicting execution" in manifest.blockers
    assert "rf: not-applicable check has conflicting execution" in manifest.blockers


def test_manifest_detects_tampered_authority_or_fingerprint() -> None:
    design = _sha("saved-board")
    requirement = _requirement("geometry", design)
    manifest = ProjectApplicabilityExecutionManifest.build(
        project_id="project.example",
        saved_design_sha256=design,
        requirements=(requirement,),
        executions=(_execution(requirement),),
    )
    payload = manifest.model_dump(mode="json")
    payload["authority"] = "blocked"

    with pytest.raises(ValidationError, match="authority is stale"):
        ProjectApplicabilityExecutionManifest.model_validate(payload)

    payload = manifest.model_dump(mode="json")
    payload["manifest_fingerprint"] = "0" * 64
    with pytest.raises(ValidationError, match="fingerprint is stale"):
        ProjectApplicabilityExecutionManifest.model_validate(payload)
