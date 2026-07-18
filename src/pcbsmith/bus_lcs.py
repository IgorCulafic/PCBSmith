"""Bounded ordered-bus LCS selection telemetry.

This module computes only a deterministic maximum-cardinality subsequence of
active members shared by two semantic boundary orders.  A selected subsequence
is planning telemetry: it does not assign outlier layers, prove transition
carriers, allocate lanes, authorize vias, or establish physical route success.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.routing_ir import RoutingIrModel


class BusLcsSelectionState(StrEnum):
    """Terminal state of the bounded sequence-only computation."""

    SELECTED = "selected"
    MEMBER_SET_MISMATCH = "member_set_mismatch"
    ACTIVITY_MISMATCH = "activity_mismatch"
    DP_BUDGET = "dp_budget"


class BusLcsBoundaryMember(RoutingIrModel):
    """One member at its exact position in a semantic boundary order."""

    member_id: str = Field(min_length=1)
    active: bool

    @field_validator("member_id")
    @classmethod
    def member_id_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("member_id must not be blank")
        return value


class BusLcsSelectionInput(RoutingIrModel):
    """Complete replay input for bounded LCS telemetry.

    Boundary tuples are semantic order and are never canonicalized or sorted.
    ``max_dp_cells`` is a fixed work limit checked before every DP cell.
    """

    schema_id: Literal["pcbsmith-bus-lcs-selection-input"] = "pcbsmith-bus-lcs-selection-input"
    schema_version: Literal[1] = 1
    source_boundary: tuple[BusLcsBoundaryMember, ...]
    target_boundary: tuple[BusLcsBoundaryMember, ...]
    max_dp_cells: int = Field(ge=0)

    @model_validator(mode="after")
    def boundary_member_ids_are_unique(self) -> Self:
        for name, boundary in (
            ("source_boundary", self.source_boundary),
            ("target_boundary", self.target_boundary),
        ):
            member_ids = tuple(member.member_id for member in boundary)
            if len(member_ids) != len(set(member_ids)):
                raise ValueError(f"{name} member_id values must be unique")
        return self


class BusLcsStayMember(RoutingIrModel):
    """One chosen active member and its exact full-boundary indices."""

    source_index: int = Field(ge=0)
    target_index: int = Field(ge=0)
    member_id: str = Field(min_length=1)

    @field_validator("member_id")
    @classmethod
    def member_id_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("member_id must not be blank")
        return value


@dataclass(frozen=True)
class _LcsComputation:
    state: BusLcsSelectionState
    stay_layer_members: tuple[BusLcsStayMember, ...]
    dp_cells_evaluated: int


def _better_sequence(
    left: tuple[tuple[int, int, str], ...],
    right: tuple[tuple[int, int, str], ...],
) -> tuple[tuple[int, int, str], ...]:
    """Return the maximum-cardinality candidate with the complete lexical tie-break."""
    if len(left) != len(right):
        return left if len(left) > len(right) else right
    return left if left <= right else right


def _compute_lcs(selection_input: BusLcsSelectionInput) -> _LcsComputation:
    source_ids = {member.member_id for member in selection_input.source_boundary}
    target_ids = {member.member_id for member in selection_input.target_boundary}
    if source_ids != target_ids:
        return _LcsComputation(BusLcsSelectionState.MEMBER_SET_MISMATCH, (), 0)

    source_activity = {
        member.member_id: member.active for member in selection_input.source_boundary
    }
    target_activity = {
        member.member_id: member.active for member in selection_input.target_boundary
    }
    if source_activity != target_activity:
        return _LcsComputation(BusLcsSelectionState.ACTIVITY_MISMATCH, (), 0)

    source = tuple(
        (index, member.member_id)
        for index, member in enumerate(selection_input.source_boundary)
        if member.active
    )
    target = tuple(
        (index, member.member_id)
        for index, member in enumerate(selection_input.target_boundary)
        if member.active
    )

    # Prefix DP in stable row-major order.  Each cell retains the exact tuple
    # sequence needed for the complete deterministic tie-break; no permutation
    # or subsequence candidate enumeration is performed.
    previous: list[tuple[tuple[int, int, str], ...]] = [()] * (len(target) + 1)
    cells = 0
    for source_index, source_member_id in source:
        current: list[tuple[tuple[int, int, str], ...]] = [()]
        for target_offset, (target_index, target_member_id) in enumerate(target, start=1):
            if cells >= selection_input.max_dp_cells:
                return _LcsComputation(BusLcsSelectionState.DP_BUDGET, (), cells)
            cells += 1
            candidate = _better_sequence(previous[target_offset], current[target_offset - 1])
            if source_member_id == target_member_id:
                matched = previous[target_offset - 1] + (
                    (source_index, target_index, source_member_id),
                )
                candidate = _better_sequence(candidate, matched)
            current.append(candidate)
        previous = current

    selected = tuple(
        BusLcsStayMember(
            source_index=source_index,
            target_index=target_index,
            member_id=member_id,
        )
        for source_index, target_index, member_id in previous[-1]
    )
    return _LcsComputation(BusLcsSelectionState.SELECTED, selected, cells)


class BusLcsSelectionResult(RoutingIrModel):
    """Replay-bound sequence telemetry with no physical-planning authority.

    ``state=selected`` means only that the bounded LCS computation completed.
    It is not an outlier-layer plan, transition or lane certificate, via
    authorization, or claim that any member or bus has been physically routed.
    """

    schema_id: Literal["pcbsmith-bus-lcs-selection-result"] = "pcbsmith-bus-lcs-selection-result"
    schema_version: Literal[1] = 1
    algorithm_id: Literal["pcbsmith-bus-lcs-prefix-dp-v1"] = "pcbsmith-bus-lcs-prefix-dp-v1"
    selection_input: BusLcsSelectionInput
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    state: BusLcsSelectionState
    stay_layer_members: tuple[BusLcsStayMember, ...] = ()
    dp_cells_evaluated: int = Field(ge=0)

    @model_validator(mode="after")
    def retained_result_matches_complete_replay(self) -> Self:
        if self.input_fingerprint != self.selection_input.semantic_fingerprint():
            raise ValueError("input_fingerprint does not match the complete selection input")
        replayed = _compute_lcs(self.selection_input)
        if self.state is not replayed.state:
            raise ValueError("state does not match bounded LCS replay")
        if self.stay_layer_members != replayed.stay_layer_members:
            raise ValueError("stay_layer_members do not match bounded LCS replay")
        if self.dp_cells_evaluated != replayed.dp_cells_evaluated:
            raise ValueError("dp_cells_evaluated does not match bounded LCS replay")
        return self


def select_bus_lcs(selection_input: BusLcsSelectionInput) -> BusLcsSelectionResult:
    """Compute replayable LCS telemetry without making any physical-route claim."""
    computation = _compute_lcs(selection_input)
    return BusLcsSelectionResult(
        selection_input=selection_input,
        input_fingerprint=selection_input.semantic_fingerprint(),
        state=computation.state,
        stay_layer_members=computation.stay_layer_members,
        dp_cells_evaluated=computation.dp_cells_evaluated,
    )
