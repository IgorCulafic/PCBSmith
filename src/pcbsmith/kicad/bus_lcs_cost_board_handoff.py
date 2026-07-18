"""Read-only board-layout handoff for an accepted cost-aware bus commit.

This opt-in consumer exposes only the neutral ``BoardLayout`` already retained
by a fully replay-bound, exact-accepted cost-aware checked commit.  It does not
generate, render, save, or mutate a KiCad board artifact.
"""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.board import BoardLayout
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    parse_canonical_board_layout_snapshot,
)
from pcbsmith.kicad.bus_checked_commit import BusExactDisposition
from pcbsmith.kicad.bus_lcs_cost_replay_checked_commit import (
    BusLcsCostReplayCheckedCommitResult,
)
from pcbsmith.kicad.placement_routability import board_layout_fingerprint
from pcbsmith.routing_ir import RoutingIrModel

BoardLayoutHandoffExcludedClaim = Literal[
    "saved_kicad_artifact",
    "rendered_kicad_board",
    "filesystem_write",
    "manufacturability",
    "verification_beyond_retained_exact_checker",
    "alternate_candidate_selection",
]

_EXCLUDED_CLAIMS: tuple[BoardLayoutHandoffExcludedClaim, ...] = (
    "saved_kicad_artifact",
    "rendered_kicad_board",
    "filesystem_write",
    "manufacturability",
    "verification_beyond_retained_exact_checker",
    "alternate_candidate_selection",
)


def _revalidate_checked_authority(
    value: BusLcsCostReplayCheckedCommitResult,
) -> BusLcsCostReplayCheckedCommitResult:
    reconstructed = BusLcsCostReplayCheckedCommitResult.model_validate_json(value.model_dump_json())
    if reconstructed != value:
        raise ValueError("cost-aware checked authority failed exact JSON reconstruction")
    return reconstructed


class BusLcsCostAcceptedBoardLayoutHandoff(RoutingIrModel):
    """Canonical snapshot of the layout from one exact-accepted transaction."""

    schema_id: Literal["pcbsmith-bus-lcs-cost-accepted-board-layout-handoff"] = (
        "pcbsmith-bus-lcs-cost-accepted-board-layout-handoff"
    )
    schema_version: Literal[1] = 1
    authority_scope: Literal["accepted-cost-aware-neutral-board-layout-only"] = (
        "accepted-cost-aware-neutral-board-layout-only"
    )
    excluded_claims: tuple[BoardLayoutHandoffExcludedClaim, ...] = _EXCLUDED_CLAIMS
    checked_authority: BusLcsCostReplayCheckedCommitResult
    board_layout_snapshot_json: str
    board_layout_snapshot_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    board_layout_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @property
    def layout(self) -> BoardLayout:
        """Return a freshly parsed frozen layout; no producer or writer runs."""

        return parse_canonical_board_layout_snapshot(self.board_layout_snapshot_json)

    @model_validator(mode="after")
    def exact_accepted_layout_is_replay_bound(self) -> Self:
        authority = _revalidate_checked_authority(self.checked_authority)
        checked = authority.checked_result.checked_result
        if (
            checked.accepted is not True
            or checked.exact_disposition is not BusExactDisposition.ACCEPTED
            or checked.committed is not True
            or checked.materialized_layout is None
        ):
            raise ValueError(
                "board-layout handoff requires an accepted committed transaction "
                "with a materialized layout"
            )
        if self.excluded_claims != _EXCLUDED_CLAIMS:
            raise ValueError("board-layout handoff excluded claims are not exact")

        nested_layout = checked.materialized_layout
        expected_snapshot = canonical_board_layout_snapshot_json(nested_layout)
        if self.board_layout_snapshot_json != expected_snapshot:
            raise ValueError("board-layout handoff snapshot differs from the checked layout")
        if self.board_layout_snapshot_fingerprint != board_layout_snapshot_fingerprint(
            expected_snapshot
        ):
            raise ValueError("board-layout handoff snapshot fingerprint is stale")
        if self.board_layout_fingerprint != board_layout_fingerprint(nested_layout):
            raise ValueError("board-layout handoff layout fingerprint is stale")
        if self.layout != nested_layout:
            raise ValueError("board-layout handoff does not replay the checked layout exactly")
        return self


def consume_accepted_bus_lcs_cost_board_layout(
    checked_authority: BusLcsCostReplayCheckedCommitResult,
) -> BusLcsCostAcceptedBoardLayoutHandoff:
    """Create a read-only handoff from an already accepted checked authority."""

    validated = _revalidate_checked_authority(checked_authority)
    checked = validated.checked_result.checked_result
    if (
        checked.accepted is not True
        or checked.exact_disposition is not BusExactDisposition.ACCEPTED
        or checked.committed is not True
        or checked.materialized_layout is None
    ):
        raise ValueError(
            "board-layout handoff requires an accepted committed transaction "
            "with a materialized layout"
        )
    snapshot = canonical_board_layout_snapshot_json(checked.materialized_layout)
    return BusLcsCostAcceptedBoardLayoutHandoff(
        checked_authority=validated,
        board_layout_snapshot_json=snapshot,
        board_layout_snapshot_fingerprint=board_layout_snapshot_fingerprint(snapshot),
        board_layout_fingerprint=board_layout_fingerprint(checked.materialized_layout),
    )
