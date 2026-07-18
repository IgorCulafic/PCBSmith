from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.rule_models import (
    RuleApplicability,
    RuleImplementation,
    RulePolicy,
    RuleRecord,
)


def evidence(**changes: object) -> EvidenceRef:
    values: dict[str, object] = {
        "kind": "standard",
        "title": "Verified source",
        "locator": "section 4.2",
        "source_status": "pinned",
        "locator_status": "text_verified",
        "local_sha256": "a" * 64,
    }
    values.update(changes)
    return EvidenceRef.model_validate(values)


def record(**changes: object) -> RuleRecord:
    values: dict[str, object] = {
        "rule_id": "spacing.example",
        "source_statement": "A scoped source requirement.",
        "source": evidence(),
        "applicability": RuleApplicability(status="confirmed"),
        "project_policy": RulePolicy(check="Check the condition.", severity="blocker"),
    }
    values.update(changes)
    return RuleRecord.model_validate(values)


def test_advisory_may_retain_conditional_unpinned_evidence() -> None:
    result = record(
        source=evidence(source_status="unpinned", locator_status="unverified", local_sha256=None),
        applicability=RuleApplicability(status="conditional"),
        project_policy=RulePolicy(check="Request review.", severity="advisory"),
    )
    assert result.project_policy.severity == "advisory"


@pytest.mark.parametrize(
    ("source", "applicability", "message"),
    [
        (
            evidence(source_status="unpinned", local_sha256=None),
            RuleApplicability(status="confirmed"),
            "pinned source",
        ),
        (
            evidence(locator_status="unverified"),
            RuleApplicability(status="confirmed"),
            "verified source locator",
        ),
        (evidence(), RuleApplicability(status="conditional"), "confirmed applicability"),
    ],
)
def test_blocker_rejects_open_evidence_gates(
    source: EvidenceRef, applicability: RuleApplicability, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        record(source=source, applicability=applicability)


def test_pinned_rule_rejects_invalid_sha256() -> None:
    with pytest.raises(ValidationError, match="64-character SHA-256"):
        record(
            source=evidence(local_sha256="not-a-digest"),
            project_policy=RulePolicy(check="Request review.", severity="review"),
        )


def test_tested_implementation_requires_named_fixture() -> None:
    with pytest.raises(ValidationError, match="name at least one fixture test"):
        RuleImplementation(status="tested")


def test_semantic_hash_ignores_implementation_progress() -> None:
    candidate = record(implementation=RuleImplementation(status="candidate"))
    tested = record(implementation=RuleImplementation(status="tested", tests=("fixture_name",)))
    assert len(candidate.semantic_hash()) == 64
    assert candidate.semantic_hash() == tested.semantic_hash()


def test_semantic_hash_changes_with_policy() -> None:
    blocker = record()
    advisory = record(project_policy=RulePolicy(check="Check the condition.", severity="advisory"))
    assert blocker.semantic_hash() != advisory.semantic_hash()
