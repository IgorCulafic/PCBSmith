"""Proven-module registry (Track 8.4 MVP).

Diode's Registry, atopile's packages, and tscircuit's registry all
converge on the same idea: compositions should be built from PROVEN,
reusable blocks, not per-topology monoliths. This module is the seed:
each block is a deterministic builder returning the ComponentRoles a
functional group needs, registered with a description and the roles it
provides. `pcbsmith modules` lists them; compositions call them.

A block here is exactly the code that already survived a terminal-clean
board plus its golden regeneration - that is what "proven" means in
this codebase.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

from pcbsmith.circuit.models import ComponentRole


@dataclass(frozen=True)
class ModuleEntry:
    name: str
    description: str
    provides_roles: tuple[str, ...]
    proven_by: str  # the topology whose golden run guards it
    builder: Callable[..., tuple[ComponentRole, ...]]


MODULE_REGISTRY: dict[str, ModuleEntry] = {}


def register_module(
    name: str,
    description: str,
    provides_roles: Sequence[str],
    proven_by: str,
) -> Callable[
    [Callable[..., tuple[ComponentRole, ...]]],
    Callable[..., tuple[ComponentRole, ...]],
]:
    def wrap(
        builder: Callable[..., tuple[ComponentRole, ...]]
    ) -> Callable[..., tuple[ComponentRole, ...]]:
        MODULE_REGISTRY[name] = ModuleEntry(
            name=name,
            description=description,
            provides_roles=tuple(provides_roles),
            proven_by=proven_by,
            builder=builder,
        )
        return builder

    return wrap


def list_modules() -> tuple[ModuleEntry, ...]:
    return tuple(
        MODULE_REGISTRY[name] for name in sorted(MODULE_REGISTRY)
    )
