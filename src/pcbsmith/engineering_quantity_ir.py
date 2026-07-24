"""Source-aware bounded engineering quantities shared by analysis authorities."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import model_validator

from pcbsmith.semantic_ir import SemanticIrModel


def require_engineering_identity(value: str, field_name: str) -> str:
    if not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a non-empty trimmed identity")
    return value


def canonical_engineering_identities(
    values: tuple[str, ...],
    field_name: str,
) -> tuple[str, ...]:
    canonical = tuple(sorted(require_engineering_identity(value, field_name) for value in values))
    if len(canonical) != len(set(canonical)):
        raise ValueError(f"{field_name} must contain unique identities")
    return canonical


class QuantityKnowledge(StrEnum):
    MEASURED = "measured"
    DATASHEET_BOUND = "datasheet_bound"
    DESIGN_TARGET = "design_target"
    ASSUMPTION = "assumption"
    DERIVED_BOUNDED = "derived_bounded"
    UNRESOLVED = "unresolved"


class BoundedQuantity(SemanticIrModel):
    """One interval with explicit knowledge state and no implicit unit conversion."""

    schema_id: Literal["pcbsmith-bounded-engineering-quantity"] = (
        "pcbsmith-bounded-engineering-quantity"
    )
    schema_version: Literal[1] = 1
    quantity_id: str
    unit: str
    knowledge: QuantityKnowledge
    lower: Decimal | None = None
    nominal: Decimal | None = None
    upper: Decimal | None = None
    evidence_binding_ids: tuple[str, ...] = ()
    rationale: str | None = None

    @model_validator(mode="after")
    def quantity_is_coherent(self) -> Self:
        require_engineering_identity(self.quantity_id, "quantity_id")
        require_engineering_identity(self.unit, "unit")
        evidence = canonical_engineering_identities(
            self.evidence_binding_ids,
            "evidence_binding_ids",
        )
        values = (self.lower, self.nominal, self.upper)
        if self.knowledge is QuantityKnowledge.UNRESOLVED:
            if any(value is not None for value in values):
                raise ValueError("unresolved quantities cannot carry numeric bounds")
            if self.rationale is None:
                raise ValueError("unresolved quantities require a missing-input rationale")
        else:
            if any(value is None for value in values):
                raise ValueError("known quantities require lower, nominal, and upper values")
            lower, nominal, upper = values
            assert lower is not None and nominal is not None and upper is not None
            if not all(value.is_finite() for value in (lower, nominal, upper)):
                raise ValueError("engineering quantity bounds must be finite")
            if not lower <= nominal <= upper:
                raise ValueError(
                    "engineering quantity bounds must satisfy lower <= nominal <= upper"
                )
            if self.knowledge in {
                QuantityKnowledge.MEASURED,
                QuantityKnowledge.DATASHEET_BOUND,
                QuantityKnowledge.DESIGN_TARGET,
                QuantityKnowledge.DERIVED_BOUNDED,
            } and not evidence:
                raise ValueError(f"{self.knowledge.value} quantities require evidence bindings")
            if self.knowledge is QuantityKnowledge.ASSUMPTION and self.rationale is None:
                raise ValueError("assumed quantities require an explicit rationale")
        if self.rationale is not None:
            require_engineering_identity(self.rationale, "rationale")
        object.__setattr__(self, "evidence_binding_ids", evidence)
        return self

    @property
    def is_known(self) -> bool:
        return self.knowledge is not QuantityKnowledge.UNRESOLVED
