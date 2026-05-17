from __future__ import annotations

from collections.abc import Callable

from pydantic import BaseModel, ConfigDict, Field

from pcbsmith.core.circuit import CircuitDesign

CircuitTemplateParam = str | int | float | bool


class TemplateParameter(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    type: str
    default: CircuitTemplateParam
    description: str


class TemplateNetPort(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    default_net: str
    role: str
    description: str


class CircuitTemplateUse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    template_id: str
    instance: str = ""
    net_bindings: dict[str, str] = Field(default_factory=dict)
    params: dict[str, CircuitTemplateParam] = Field(default_factory=dict)


class CircuitTemplate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    title: str
    description: str
    category: str
    parameters: dict[str, TemplateParameter] = Field(default_factory=dict)
    net_ports: dict[str, TemplateNetPort] = Field(default_factory=dict)
    tags: tuple[str, ...] = ()


class ReferenceAllocator:
    def __init__(self) -> None:
        self._next_by_prefix: dict[str, int] = {}

    def next(self, prefix: str) -> str:
        next_number = self._next_by_prefix.get(prefix, 0) + 1
        self._next_by_prefix[prefix] = next_number
        return f"{prefix}{next_number}"


CircuitTemplateBuilder = Callable[[CircuitTemplateUse, ReferenceAllocator], CircuitDesign]


__all__ = [
    "CircuitTemplate",
    "CircuitTemplateBuilder",
    "CircuitTemplateParam",
    "CircuitTemplateUse",
    "ReferenceAllocator",
    "TemplateNetPort",
    "TemplateParameter",
]
