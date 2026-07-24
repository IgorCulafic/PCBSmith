from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcbsmith.failure_corpus import (
    REQUIRED_FAILURE_CATEGORIES,
    Phase17FailureCorpus,
    RetainedFailureCase,
    build_phase17_failure_corpus,
)

SHA = "1" * 64


def _cases() -> tuple[RetainedFailureCase, ...]:
    return tuple(
        RetainedFailureCase.build(
            case_id=f"{category}-case",
            category=category,
            trigger=f"{category} trigger",
            expected_outcome=f"{category} expected outcome",
            observed_outcome=f"{category} observed outcome",
            evidence_locator=f"tests/{category}.py",
            evidence_sha256=SHA,
            prevented_claims=(f"{category} unsupported claim",),
        )
        for category in sorted(REQUIRED_FAILURE_CATEGORIES)
    )


def test_failure_corpus_round_trips_with_all_required_categories() -> None:
    corpus = build_phase17_failure_corpus(_cases())

    reconstructed = Phase17FailureCorpus.model_validate(
        corpus.model_dump(mode="json")
    )

    assert reconstructed == corpus
    assert {case.category for case in corpus.cases} == REQUIRED_FAILURE_CATEGORIES


def test_failure_corpus_rejects_missing_required_category() -> None:
    cases = tuple(
        case for case in _cases() if case.category != "transaction_rollback"
    )

    with pytest.raises(ValidationError, match="at least 6 items"):
        build_phase17_failure_corpus(cases)


def test_failure_case_rejects_tampered_evidence_binding() -> None:
    case = _cases()[0]
    payload = case.model_dump(mode="json")
    payload["evidence_sha256"] = "2" * 64

    with pytest.raises(ValidationError, match="fingerprint is stale"):
        RetainedFailureCase.model_validate(payload)


def test_failure_corpus_rejects_tampered_case_set() -> None:
    corpus = build_phase17_failure_corpus(_cases())
    payload = corpus.model_dump(mode="json")
    payload["cases"][0]["observed_outcome"] = "tampered outcome"

    with pytest.raises(ValidationError, match="fingerprint is stale"):
        Phase17FailureCorpus.model_validate(payload)
