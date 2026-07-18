"""Replay-bound sequence-only planning for members outside a bus LCS.

This module classifies active members as stationary or LCS outliers.  It does
not assign layers, authorize vias or transition carriers, allocate capacity,
or claim physical route feasibility.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.bus_lcs import (
    BusLcsBoundaryMember,
    BusLcsSelectionInput,
    BusLcsSelectionResult,
    BusLcsSelectionState,
    BusLcsStayMember,
    select_bus_lcs,
)
from pcbsmith.routing_ir import RoutingIrModel


class BusLcsOutlierPlanInput(RoutingIrModel):
    """Complete ordered input for deterministic LCS outlier classification."""

    schema_id: Literal["pcbsmith-bus-lcs-outlier-plan-input"] = (
        "pcbsmith-bus-lcs-outlier-plan-input"
    )
    schema_version: Literal[1] = 1
    source_member_order: tuple[str, ...]
    target_member_order: tuple[str, ...]
    max_dp_cells: int = Field(ge=0)

    @field_validator("source_member_order", "target_member_order")
    @classmethod
    def member_order_is_unique_and_nonblank(
        cls,
        value: tuple[str, ...],
    ) -> tuple[str, ...]:
        if any(not member_id.strip() for member_id in value):
            raise ValueError("member orders must not contain blank member IDs")
        if len(value) != len(set(value)):
            raise ValueError("member orders must contain unique member IDs")
        return value


class BusLcsOutlierMember(RoutingIrModel):
    """One non-stationary member, retained in exact target-boundary order."""

    member_id: str = Field(min_length=1)
    source_index: int = Field(ge=0)
    target_index: int = Field(ge=0)


def _to_selection_input(plan_input: BusLcsOutlierPlanInput) -> BusLcsSelectionInput:
    return BusLcsSelectionInput(
        source_boundary=tuple(
            BusLcsBoundaryMember(member_id=member_id, active=True)
            for member_id in plan_input.source_member_order
        ),
        target_boundary=tuple(
            BusLcsBoundaryMember(member_id=member_id, active=True)
            for member_id in plan_input.target_member_order
        ),
        max_dp_cells=plan_input.max_dp_cells,
    )


def _derive_outliers(
    plan_input: BusLcsOutlierPlanInput,
    lcs_result: BusLcsSelectionResult,
) -> tuple[BusLcsOutlierMember, ...]:
    if lcs_result.state is not BusLcsSelectionState.SELECTED:
        return ()

    stationary_ids = {member.member_id for member in lcs_result.stay_layer_members}
    source_indices = {
        member_id: source_index
        for source_index, member_id in enumerate(plan_input.source_member_order)
    }
    return tuple(
        BusLcsOutlierMember(
            member_id=member_id,
            source_index=source_indices[member_id],
            target_index=target_index,
        )
        for target_index, member_id in enumerate(plan_input.target_member_order)
        if member_id not in stationary_ids
    )


class BusLcsOutlierPlanResult(RoutingIrModel):
    """Exact LCS replay plus its deterministic sequence-only complement.

    A selected result is classification telemetry only.  It supplies no layer,
    via, transition, capacity, geometry, or route-feasibility authority.
    """

    schema_id: Literal["pcbsmith-bus-lcs-outlier-plan-result"] = (
        "pcbsmith-bus-lcs-outlier-plan-result"
    )
    schema_version: Literal[1] = 1
    algorithm_id: Literal["pcbsmith-bus-lcs-outlier-target-order-v1"] = (
        "pcbsmith-bus-lcs-outlier-target-order-v1"
    )
    authority_scope: Literal["sequence-telemetry-only"] = "sequence-telemetry-only"
    plan_input: BusLcsOutlierPlanInput
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    lcs_result: BusLcsSelectionResult
    stationary_members: tuple[BusLcsStayMember, ...] = ()
    outlier_members: tuple[BusLcsOutlierMember, ...] = ()

    @model_validator(mode="after")
    def retained_plan_matches_complete_replay(self) -> Self:
        if self.input_fingerprint != self.plan_input.semantic_fingerprint():
            raise ValueError("input_fingerprint does not match the complete plan input")

        replayed_lcs = select_bus_lcs(_to_selection_input(self.plan_input))
        if self.lcs_result != replayed_lcs:
            raise ValueError("lcs_result does not match exact LCS replay")
        if self.stationary_members != replayed_lcs.stay_layer_members:
            raise ValueError("stationary_members do not match exact LCS replay")

        replayed_outliers = _derive_outliers(self.plan_input, replayed_lcs)
        if self.outlier_members != replayed_outliers:
            raise ValueError("outlier_members do not match the target-ordered LCS complement")
        return self


def plan_bus_lcs_outliers(plan_input: BusLcsOutlierPlanInput) -> BusLcsOutlierPlanResult:
    """Classify stationary and outlier members without physical authority."""
    lcs_result = select_bus_lcs(_to_selection_input(plan_input))
    return BusLcsOutlierPlanResult(
        plan_input=plan_input,
        input_fingerprint=plan_input.semantic_fingerprint(),
        lcs_result=lcs_result,
        stationary_members=lcs_result.stay_layer_members,
        outlier_members=_derive_outliers(plan_input, lcs_result),
    )
