from decimal import Decimal

import pytest
from pydantic import ValidationError

from pcbsmith.engineering_evidence_ir import (
    EngineeringEvidenceFact,
    EngineeringEvidenceRegister,
)
from pcbsmith.engineering_quantity_ir import BoundedQuantity, QuantityKnowledge

SOURCE = "part:example:datasheet"
SHA = "a" * 64


def _quantity() -> BoundedQuantity:
    return BoundedQuantity(
        quantity_id="resistance",
        unit="ohm",
        knowledge=QuantityKnowledge.DATASHEET_BOUND,
        lower=Decimal("0.9"),
        nominal=Decimal("1.0"),
        upper=Decimal("1.1"),
        evidence_binding_ids=(SOURCE,),
    )


def _fact(fact_id: str = "part.resistance") -> EngineeringEvidenceFact:
    return EngineeringEvidenceFact(
        fact_id=fact_id,
        subject_id="R1",
        parameter_id="resistance",
        quantity=_quantity(),
        source_id=SOURCE,
        source_sha256=SHA,
        locator="page 2, table 1",
        test_condition_ids=("temperature=25degC",),
    )


def test_fact_requires_quantity_to_bind_same_source() -> None:
    payload = _fact().model_dump()
    payload["source_id"] = "part:other:datasheet"
    with pytest.raises(ValidationError, match="must bind"):
        EngineeringEvidenceFact.model_validate(payload)


def test_register_is_canonical_and_addressable() -> None:
    register = EngineeringEvidenceRegister(
        register_id="facts",
        revision="1",
        facts=(_fact("z"), _fact("a")),
        source_context_ids=(SOURCE,),
    )
    assert tuple(item.fact_id for item in register.facts) == ("a", "z")
    assert register.fact("z").quantity.upper == Decimal("1.1")
    with pytest.raises(KeyError):
        register.fact("missing")
