"""Retained Phase 17 failure evidence and prohibited-claim boundaries."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel

FailureCategory = Literal[
    "ambiguity",
    "capacity",
    "missing_asset",
    "routing",
    "review_omission",
    "transaction_rollback",
]

REQUIRED_FAILURE_CATEGORIES: frozenset[FailureCategory] = frozenset(
    {
        "ambiguity",
        "capacity",
        "missing_asset",
        "routing",
        "review_omission",
        "transaction_rollback",
    }
)


class RetainedFailureCase(SemanticIrModel):
    schema_id: Literal["pcbsmith-retained-failure-case"] = (
        "pcbsmith-retained-failure-case"
    )
    schema_version: Literal[1] = 1
    case_id: str
    category: FailureCategory
    trigger: str
    expected_outcome: str
    observed_outcome: str
    evidence_locator: str
    evidence_sha256: str
    prevented_claims: tuple[str, ...] = Field(min_length=1)
    case_fingerprint: str

    @model_validator(mode="after")
    def case_is_canonical(self) -> Self:
        for field_name in (
            "case_id",
            "trigger",
            "expected_outcome",
            "observed_outcome",
            "evidence_locator",
        ):
            require_identity(getattr(self, field_name), field_name)
        require_sha256(self.evidence_sha256, "evidence_sha256")
        claims = tuple(sorted(self.prevented_claims))
        if len(claims) != len(set(claims)):
            raise ValueError("prevented failure claims must be unique")
        for claim in claims:
            require_identity(claim, "prevented_claim")
        object.__setattr__(self, "prevented_claims", claims)
        require_sha256(self.case_fingerprint, "case_fingerprint")
        if self.case_fingerprint != _failure_case_fingerprint(
            case_id=self.case_id,
            category=self.category,
            trigger=self.trigger,
            expected_outcome=self.expected_outcome,
            observed_outcome=self.observed_outcome,
            evidence_locator=self.evidence_locator,
            evidence_sha256=self.evidence_sha256,
            prevented_claims=claims,
        ):
            raise ValueError("retained failure-case fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        case_id: str,
        category: FailureCategory,
        trigger: str,
        expected_outcome: str,
        observed_outcome: str,
        evidence_locator: str,
        evidence_sha256: str,
        prevented_claims: tuple[str, ...],
    ) -> RetainedFailureCase:
        claims = tuple(sorted(prevented_claims))
        return cls(
            case_id=case_id,
            category=category,
            trigger=trigger,
            expected_outcome=expected_outcome,
            observed_outcome=observed_outcome,
            evidence_locator=evidence_locator,
            evidence_sha256=evidence_sha256,
            prevented_claims=claims,
            case_fingerprint=_failure_case_fingerprint(
                case_id=case_id,
                category=category,
                trigger=trigger,
                expected_outcome=expected_outcome,
                observed_outcome=observed_outcome,
                evidence_locator=evidence_locator,
                evidence_sha256=evidence_sha256,
                prevented_claims=claims,
            ),
        )


class Phase17FailureCorpus(SemanticIrModel):
    schema_id: Literal["pcbsmith-phase17-failure-corpus"] = (
        "pcbsmith-phase17-failure-corpus"
    )
    schema_version: Literal[1] = 1
    cases: tuple[RetainedFailureCase, ...] = Field(min_length=6)
    corpus_fingerprint: str

    @model_validator(mode="after")
    def corpus_is_complete(self) -> Self:
        cases = tuple(sorted(self.cases, key=lambda item: item.case_id))
        ids = tuple(item.case_id for item in cases)
        if len(ids) != len(set(ids)):
            raise ValueError("retained failure-case identities must be unique")
        categories = {item.category for item in cases}
        if categories != REQUIRED_FAILURE_CATEGORIES:
            raise ValueError(
                "failure corpus must cover ambiguity, capacity, missing assets, "
                "routing, review omission, and transaction rollback"
            )
        object.__setattr__(self, "cases", cases)
        require_sha256(self.corpus_fingerprint, "corpus_fingerprint")
        expected = fingerprint(
            {
                "schema_id": self.schema_id,
                "schema_version": self.schema_version,
                "case_fingerprints": tuple(
                    item.case_fingerprint for item in cases
                ),
            }
        )
        if self.corpus_fingerprint != expected:
            raise ValueError("failure corpus fingerprint is stale")
        return self


def build_phase17_failure_corpus(
    cases: tuple[RetainedFailureCase, ...],
) -> Phase17FailureCorpus:
    ordered = tuple(sorted(cases, key=lambda item: item.case_id))
    return Phase17FailureCorpus(
        cases=ordered,
        corpus_fingerprint=fingerprint(
            {
                "schema_id": "pcbsmith-phase17-failure-corpus",
                "schema_version": 1,
                "case_fingerprints": tuple(
                    item.case_fingerprint for item in ordered
                ),
            }
        ),
    )


def _failure_case_fingerprint(
    *,
    case_id: str,
    category: FailureCategory,
    trigger: str,
    expected_outcome: str,
    observed_outcome: str,
    evidence_locator: str,
    evidence_sha256: str,
    prevented_claims: tuple[str, ...],
) -> str:
    payload: dict[str, Any] = {
        "schema_id": "pcbsmith-retained-failure-case",
        "schema_version": 1,
        "case_id": case_id,
        "category": category,
        "trigger": trigger,
        "expected_outcome": expected_outcome,
        "observed_outcome": observed_outcome,
        "evidence_locator": evidence_locator,
        "evidence_sha256": evidence_sha256,
        "prevented_claims": prevented_claims,
    }
    return fingerprint(payload)
