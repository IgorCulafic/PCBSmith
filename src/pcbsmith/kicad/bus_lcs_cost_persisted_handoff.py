"""Persisted KiCad/read-back consumer for the exact-accepted R4 handoff."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.board import BoardNetlist
from pcbsmith.kicad.board_serialization import (
    board_netlist_snapshot_fingerprint,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.kicad.bus_lcs_cost_board_handoff import (
    BusLcsCostAcceptedBoardLayoutHandoff,
)
from pcbsmith.kicad.placement_readback import (
    PlacementKiCadSaveRoundtripAuthority,
    verify_placement_kicad_save_roundtrip,
)
from pcbsmith.kicad.placement_serialization import (
    build_placement_serialization_authority,
)
from pcbsmith.placement_serialization_ir import PlacementSerializationAuthority
from pcbsmith.routed_copper_graph_ir import fingerprint
from pcbsmith.routing_ir import RoutingIrModel

RoundtripVerifier = Callable[
    [PlacementSerializationAuthority, Path],
    PlacementKiCadSaveRoundtripAuthority,
]


class PersistedBusLcsCostBoardHandoff(RoutingIrModel):
    schema_id: Literal["pcbsmith-persisted-bus-lcs-cost-board-handoff"] = (
        "pcbsmith-persisted-bus-lcs-cost-board-handoff"
    )
    schema_version: Literal[1] = 1
    neutral_handoff: BusLcsCostAcceptedBoardLayoutHandoff
    netlist_snapshot_json: str
    netlist_snapshot_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    serialization_authority: PlacementSerializationAuthority
    roundtrip_authority: PlacementKiCadSaveRoundtripAuthority
    persisted_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def persisted_result_is_replay_bound(self) -> Self:
        handoff = BusLcsCostAcceptedBoardLayoutHandoff.model_validate_json(
            self.neutral_handoff.model_dump_json()
        )
        serialization = PlacementSerializationAuthority.model_validate_json(
            self.serialization_authority.model_dump_json()
        )
        roundtrip = PlacementKiCadSaveRoundtripAuthority.model_validate_json(
            self.roundtrip_authority.model_dump_json()
        )
        if self.netlist_snapshot_fingerprint != board_netlist_snapshot_fingerprint(
            self.netlist_snapshot_json
        ):
            raise ValueError("persisted handoff netlist fingerprint is stale")
        if (
            serialization.source_layout_fingerprint
            != handoff.board_layout_snapshot_fingerprint
            or serialization.final_layout_fingerprint
            != handoff.board_layout_snapshot_fingerprint
        ):
            raise ValueError("persisted serialization substituted the accepted layout")
        if (
            serialization.source_netlist_snapshot_json
            != self.netlist_snapshot_json
            or not roundtrip.require_drc_pass
            or roundtrip.drc_status != "passed"
            or roundtrip.drc_findings
        ):
            raise ValueError("persisted handoff lacks a clean mandatory KiCad DRC roundtrip")
        if roundtrip.serialization_authority != serialization:
            raise ValueError("roundtrip authority belongs to another serialization")
        expected_fingerprint = _persisted_fingerprint(
            handoff=handoff,
            netlist_fingerprint=self.netlist_snapshot_fingerprint,
            serialization=serialization,
            roundtrip=roundtrip,
        )
        if self.persisted_fingerprint != expected_fingerprint:
            raise ValueError("persisted handoff fingerprint is stale")
        return self


def persist_accepted_bus_lcs_cost_board_layout(
    *,
    handoff: BusLcsCostAcceptedBoardLayoutHandoff,
    netlist: BoardNetlist,
    output_root: Path,
    verifier: RoundtripVerifier | None = None,
) -> PersistedBusLcsCostBoardHandoff:
    """Render, save/read back, and DRC the exact accepted neutral handoff."""

    validated = BusLcsCostAcceptedBoardLayoutHandoff.model_validate_json(
        handoff.model_dump_json()
    )
    layout = validated.layout
    serialization = build_placement_serialization_authority(
        layout,
        netlist,
        layout,
        tuple(net.name for net in netlist.nets),
        tuple(component.reference for component in netlist.components),
    )
    if verifier is None:
        roundtrip = verify_placement_kicad_save_roundtrip(
            serialization,
            output_root,
            require_drc_pass=True,
        )
    else:
        roundtrip = verifier(serialization, output_root)
    netlist_json = canonical_board_netlist_snapshot_json(netlist)
    netlist_fingerprint = board_netlist_snapshot_fingerprint(netlist_json)
    return PersistedBusLcsCostBoardHandoff(
        neutral_handoff=validated,
        netlist_snapshot_json=netlist_json,
        netlist_snapshot_fingerprint=netlist_fingerprint,
        serialization_authority=serialization,
        roundtrip_authority=roundtrip,
        persisted_fingerprint=_persisted_fingerprint(
            handoff=validated,
            netlist_fingerprint=netlist_fingerprint,
            serialization=serialization,
            roundtrip=roundtrip,
        ),
    )


def _persisted_fingerprint(
    *,
    handoff: BusLcsCostAcceptedBoardLayoutHandoff,
    netlist_fingerprint: str,
    serialization: PlacementSerializationAuthority,
    roundtrip: PlacementKiCadSaveRoundtripAuthority,
) -> str:
    """Bind stable retained identities, not incidental nested tuple ordering."""

    return fingerprint(
        {
            "schema_id": "pcbsmith-persisted-bus-lcs-cost-board-handoff",
            "schema_version": 1,
            "accepted_layout": handoff.board_layout_snapshot_fingerprint,
            "accepted_layout_value": handoff.board_layout_fingerprint,
            "netlist": netlist_fingerprint,
            "serialization": serialization.result_fingerprint,
            "rendered_board": serialization.rendered_board_sha256,
            "saved_board": roundtrip.saved_board_sha256,
            "drc_report": roundtrip.drc_report_sha256,
        }
    )
