"""Replay-bound immutable records for corridor-exchange preparation.

This module owns serialization only.  The KiCad adapter in
``corridor_exchange_preparation`` owns the deterministic preparation decision.
"""

from __future__ import annotations

import hashlib
import json
import math
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, StrictInt, field_serializer, field_validator, model_validator

from pcbsmith.corridor_exchange import CorridorExchangePlanResult
from pcbsmith.corridor_guidance import CorridorGuidanceDisposition
from pcbsmith.corridor_ir import CorridorGraph, CorridorIrModel
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.kicad.negotiated_grid import GridSoftGuide
from pcbsmith.kicad.route_prefix import GridRoutePrefix
from pcbsmith.rule_profiles import PcbRuleProfile


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def semantic_fingerprint(payload: Any) -> str:
    """Return the common canonical SHA-256 used by the replay envelope."""

    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _require_sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
    return value


class CorridorExchangePreparationReason(StrEnum):
    """Exactly classified reasons why exchange preparation was rejected."""

    PLAN_GRAPH_MISMATCH = "plan_graph_mismatch"
    NO_EXCHANGE_ALLOCATION = "no_exchange_allocation"
    CURRENT_GRAPH_BUILD_FAILURE = "current_graph_build_failure"
    CURRENT_GRAPH_UNSUPPORTED = "current_graph_unsupported"
    CURRENT_GRAPH_MISMATCH = "current_graph_mismatch"
    GUIDE_UNAVAILABLE = "guide_unavailable"
    GUIDE_PROJECTION_FAILURE = "guide_projection_failure"
    DUPLICATE_SELECTED_ALTERNATIVE = "duplicate_selected_alternative"
    MISSING_SUPPLIED_PREFIX = "missing_supplied_prefix"
    EXTRA_SUPPLIED_PREFIX = "extra_supplied_prefix"
    PREFIX_ALTERNATIVE_MISMATCH = "prefix_alternative_mismatch"
    PREFIX_NET_MISMATCH = "prefix_net_mismatch"
    PREFIX_FINGERPRINT_MISMATCH = "prefix_fingerprint_mismatch"
    PREFIX_ANCHOR_MISMATCH = "prefix_anchor_mismatch"
    PREFIX_LAYER_MISMATCH = "prefix_layer_mismatch"
    ENTRY_CELL_MISSING = "entry_cell_missing"
    ENTRY_CELL_WRONG_LAYER = "entry_cell_wrong_layer"
    PREFIX_EXIT_OUTSIDE_ENTRY = "prefix_exit_outside_entry"
    DUPLICATE_PREFIX_NET = "duplicate_prefix_net"
    MISSING_PROJECTED_GUIDE = "missing_projected_guide"


class CorridorExchangeNetWidth(CorridorIrModel):
    net_name: str = Field(min_length=1)
    width_mm: float = Field(gt=0)

    @field_validator("width_mm")
    @classmethod
    def width_is_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("net width must be finite")
        return value


class CorridorExchangeClearanceGroup(CorridorIrModel):
    """Canonical typed form of one caller clearance-group tuple."""

    nets_a: tuple[str, ...] = Field(min_length=1)
    nets_b: tuple[str, ...] = Field(min_length=1)
    minimum_clearance_mm: float = Field(ge=0)
    exempt_component_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def group_is_canonical(self) -> Self:
        side_a = tuple(sorted(set(self.nets_a)))
        side_b = tuple(sorted(set(self.nets_b)))
        exempt = tuple(sorted(set(self.exempt_component_refs)))
        if any(not item for item in (*side_a, *side_b, *exempt)):
            raise ValueError("clearance identities must be non-empty")
        if not math.isfinite(self.minimum_clearance_mm):
            raise ValueError("minimum clearance must be finite")
        low, high = sorted((side_a, side_b))
        object.__setattr__(self, "nets_a", low)
        object.__setattr__(self, "nets_b", high)
        object.__setattr__(self, "exempt_component_refs", exempt)
        return self

    def as_legacy_tuple(
        self,
    ) -> tuple[tuple[str, ...], tuple[str, ...], float, tuple[str, ...]]:
        return (
            self.nets_a,
            self.nets_b,
            self.minimum_clearance_mm,
            self.exempt_component_refs,
        )


class CorridorExchangeSuppliedPrefix(CorridorIrModel):
    alternative_id: str = Field(min_length=1)
    prefix: GridRoutePrefix


class CorridorExchangeSelectedPrefix(CorridorIrModel):
    demand_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    alternative_id: str = Field(min_length=1)
    prefix_fingerprint: str

    @field_validator("prefix_fingerprint")
    @classmethod
    def fingerprint_is_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)


class CorridorExchangePreparedPrefix(CorridorIrModel):
    net_name: str = Field(min_length=1)
    prefix: GridRoutePrefix

    @model_validator(mode="after")
    def key_matches_value(self) -> Self:
        if self.net_name != self.prefix.net_name:
            raise ValueError("prepared prefix key must equal its net identity")
        return self


class CorridorExchangePreparedGuide(CorridorIrModel):
    net_name: str = Field(min_length=1)
    guide: GridSoftGuide

    @field_serializer("guide")
    def serialize_guide_canonically(self, guide: GridSoftGuide) -> dict[str, Any]:
        """Serialize set-like R2 guide geometry in stable semantic order."""

        return {
            "grid_mm": guide.grid_mm,
            "allowed_track_nodes": sorted(guide.allowed_track_nodes),
            "allowed_track_transitions": sorted(guide.allowed_track_transitions),
            "allowed_via_cells": sorted(guide.allowed_via_cells),
            "off_guide_transition_cost_units": guide.off_guide_transition_cost_units,
        }


class CorridorExchangePreparationInput(CorridorIrModel):
    """Complete immutable authority needed to rerun pure preparation."""

    schema_id: Literal["pcbsmith-corridor-exchange-preparation-input"] = (
        "pcbsmith-corridor-exchange-preparation-input"
    )
    schema_version: Literal[1] = 1
    algorithm_id: Literal["pcbsmith-corridor-exchange-preparation-v1"] = (
        "pcbsmith-corridor-exchange-preparation-v1"
    )
    layout_snapshot_json: str = Field(min_length=2)
    netlist_snapshot_json: str = Field(min_length=2)
    corridor_graph: CorridorGraph
    exchange_plan: CorridorExchangePlanResult
    supplied_prefixes: tuple[CorridorExchangeSuppliedPrefix, ...] = ()
    target_nets: tuple[str, ...] | None = None
    net_widths: tuple[CorridorExchangeNetWidth, ...] = ()
    profile: PcbRuleProfile
    clearance_groups: tuple[CorridorExchangeClearanceGroup, ...] = ()
    default_width_mm: float = Field(gt=0)
    grid_mm: float = Field(gt=0)
    off_corridor_penalty_units: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def authority_is_canonical_and_parseable(self) -> Self:
        parse_canonical_board_layout_snapshot(self.layout_snapshot_json)
        parse_canonical_board_netlist_snapshot(self.netlist_snapshot_json)
        if not math.isfinite(self.default_width_mm) or not math.isfinite(self.grid_mm):
            raise ValueError("routing widths and grids must be finite")
        target_nets = None if self.target_nets is None else tuple(sorted(set(self.target_nets)))
        if target_nets is not None and any(not item for item in target_nets):
            raise ValueError("target net identities must be non-empty")
        widths_by_name: dict[str, CorridorExchangeNetWidth] = {}
        for width in self.net_widths:
            previous_width = widths_by_name.get(width.net_name)
            if previous_width is not None and previous_width != width:
                raise ValueError(f"conflicting width for net {width.net_name!r}")
            widths_by_name[width.net_name] = width
        prefixes_by_id: dict[str, CorridorExchangeSuppliedPrefix] = {}
        for supplied in self.supplied_prefixes:
            previous_prefix = prefixes_by_id.get(supplied.alternative_id)
            if previous_prefix is not None and previous_prefix != supplied:
                raise ValueError(f"conflicting supplied prefix for {supplied.alternative_id!r}")
            prefixes_by_id[supplied.alternative_id] = supplied
        groups_by_json = {group.semantic_json(): group for group in self.clearance_groups}
        object.__setattr__(self, "target_nets", target_nets)
        object.__setattr__(
            self,
            "net_widths",
            tuple(widths_by_name[name] for name in sorted(widths_by_name)),
        )
        object.__setattr__(
            self,
            "supplied_prefixes",
            tuple(prefixes_by_id[name] for name in sorted(prefixes_by_id)),
        )
        object.__setattr__(
            self,
            "clearance_groups",
            tuple(groups_by_json[key] for key in sorted(groups_by_json)),
        )
        return self

    @property
    def layout(self) -> BoardLayout:
        return parse_canonical_board_layout_snapshot(self.layout_snapshot_json)

    @property
    def netlist(self) -> BoardNetlist:
        return parse_canonical_board_netlist_snapshot(self.netlist_snapshot_json)

    @property
    def layout_fingerprint(self) -> str:
        return board_layout_snapshot_fingerprint(self.layout_snapshot_json)

    @property
    def netlist_fingerprint(self) -> str:
        return board_netlist_snapshot_fingerprint(self.netlist_snapshot_json)


class CorridorExchangePreparationResult(CorridorIrModel):
    """Replay-checked output of pure exchange preparation."""

    schema_id: Literal["pcbsmith-corridor-exchange-preparation-result"] = (
        "pcbsmith-corridor-exchange-preparation-result"
    )
    schema_version: Literal[1] = 1
    preparation_input: CorridorExchangePreparationInput
    disposition: CorridorGuidanceDisposition
    incompatibility_reason: CorridorExchangePreparationReason | None = None
    selected_prefixes: tuple[CorridorExchangeSelectedPrefix, ...] = ()
    route_prefixes: tuple[CorridorExchangePreparedPrefix, ...] = ()
    soft_guides: tuple[CorridorExchangePreparedGuide, ...] = ()
    graph_fingerprint: str
    exchange_plan_fingerprint: str
    supplied_prefixes_fingerprint: str
    selected_prefixes_fingerprint: str | None = None
    guide_fingerprint: str | None = None
    preparation_input_fingerprint: str

    @field_validator(
        "graph_fingerprint",
        "exchange_plan_fingerprint",
        "supplied_prefixes_fingerprint",
        "selected_prefixes_fingerprint",
        "guide_fingerprint",
        "preparation_input_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def replay_matches_retained_authority(self) -> Self:
        # Local import avoids a serialization/adapter import cycle.
        from pcbsmith.kicad.corridor_exchange_preparation import (
            _evaluate_corridor_exchange_preparation,
        )

        expected = _evaluate_corridor_exchange_preparation(self.preparation_input)
        expected_result = self.__class__.model_construct(
            schema_id=self.schema_id,
            schema_version=self.schema_version,
            **expected,
        )
        # Compare typed values rather than JSON-mode dumps. GridSoftGuide owns
        # frozensets, whose JSON list order is deliberately not authoritative.
        if self != expected_result:
            raise ValueError("corridor exchange preparation does not replay exactly")
        return self
