from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from pcbsmith.core.circuit import CircuitDesign
from pcbsmith.templates import (
    CircuitTemplate,
    compose_templates,
    list_templates,
)
from pcbsmith.templates.models import CircuitTemplateParam, CircuitTemplateUse


class CircuitBlockUse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    instance: str = ""
    net_bindings: dict[str, str] = Field(default_factory=dict)
    params: dict[str, CircuitTemplateParam] = Field(default_factory=dict)


def compose_circuit_blocks(
    name: str,
    blocks: tuple[CircuitBlockUse, ...],
) -> CircuitDesign:
    uses = tuple(
        CircuitTemplateUse(
            template_id=block.name,
            instance=block.instance,
            net_bindings=block.net_bindings,
            params=block.params,
        )
        for block in blocks
    )
    try:
        return compose_templates(name, uses)
    except ValueError as exc:
        message = str(exc)
        if "Unknown circuit template" in message:
            raise ValueError(message.replace("template", "block")) from exc
        raise


def list_circuit_block_templates() -> tuple[CircuitTemplate, ...]:
    return list_templates()


__all__ = [
    "CircuitBlockUse",
    "compose_circuit_blocks",
    "list_circuit_block_templates",
]
