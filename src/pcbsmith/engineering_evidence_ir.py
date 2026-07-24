"""Typed, page-located engineering facts extracted from retained evidence."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from pcbsmith.engineering_quantity_ir import (
    BoundedQuantity,
    canonical_engineering_identities,
    require_engineering_identity,
)
from pcbsmith.semantic_ir import SemanticIrModel


class EngineeringEvidenceFact(SemanticIrModel):
    """One source fact, including its test conditions and applicability limits."""

    schema_id: Literal["pcbsmith-engineering-evidence-fact"] = "pcbsmith-engineering-evidence-fact"
    schema_version: Literal[1] = 1
    fact_id: str
    subject_id: str
    parameter_id: str
    quantity: BoundedQuantity
    source_id: str
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: str
    test_condition_ids: tuple[str, ...]
    applicability_notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def fact_is_traceable(self) -> Self:
        for field_name in (
            "fact_id",
            "subject_id",
            "parameter_id",
            "source_id",
            "locator",
        ):
            require_engineering_identity(getattr(self, field_name), field_name)
        conditions = canonical_engineering_identities(
            self.test_condition_ids,
            "test_condition_ids",
        )
        if not conditions:
            raise ValueError("engineering facts require explicit test conditions")
        notes = tuple(
            require_engineering_identity(note, "applicability_notes")
            for note in self.applicability_notes
        )
        if len(notes) != len(set(notes)):
            raise ValueError("applicability notes must be unique")
        if self.source_id not in self.quantity.evidence_binding_ids:
            raise ValueError("fact quantity must bind to the retained source identity")
        object.__setattr__(self, "test_condition_ids", conditions)
        object.__setattr__(self, "applicability_notes", notes)
        return self


class EngineeringEvidenceRegister(SemanticIrModel):
    """Canonical retained set of engineering facts used by calculations."""

    schema_id: Literal["pcbsmith-engineering-evidence-register"] = (
        "pcbsmith-engineering-evidence-register"
    )
    schema_version: Literal[1] = 1
    register_id: str
    revision: str
    facts: tuple[EngineeringEvidenceFact, ...]
    source_context_ids: tuple[str, ...]

    @model_validator(mode="after")
    def register_is_canonical(self) -> Self:
        require_engineering_identity(self.register_id, "register_id")
        require_engineering_identity(self.revision, "revision")
        facts = tuple(sorted(self.facts, key=lambda item: item.fact_id))
        if len(facts) != len({item.fact_id for item in facts}):
            raise ValueError("engineering fact identities must be unique")
        contexts = canonical_engineering_identities(
            self.source_context_ids,
            "source_context_ids",
        )
        if not contexts:
            raise ValueError("engineering evidence registers require source context")
        object.__setattr__(self, "facts", facts)
        object.__setattr__(self, "source_context_ids", contexts)
        return self

    def fact(self, fact_id: str) -> EngineeringEvidenceFact:
        result = next((item for item in self.facts if item.fact_id == fact_id), None)
        if result is None:
            raise KeyError(fact_id)
        return result
