from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError
from tests.unit.kicad import test_bus_lcs_cost_board_handoff as handoff_fixtures
from tests.unit.kicad.test_placement_measured_corpus import _fake_roundtrip

from pcbsmith.kicad.board import BoardNet, BoardNetlist
from pcbsmith.kicad.bus_lcs_cost_board_handoff import (
    consume_accepted_bus_lcs_cost_board_layout,
)
from pcbsmith.kicad.bus_lcs_cost_persisted_handoff import (
    PersistedBusLcsCostBoardHandoff,
    persist_accepted_bus_lcs_cost_board_layout,
)


def _handoff_and_netlist():
    handoff = consume_accepted_bus_lcs_cost_board_layout(
        handoff_fixtures._checked_result(True)
    )
    layout = handoff.layout
    components = tuple(component for component, _x in layout.placements)
    netlist = BoardNetlist(
        components=components,
        nets=(
            BoardNet("/A", (("R1", "2"), ("R2", "1"))),
            BoardNet("/B", (("R3", "2"), ("R4", "1"))),
        ),
    )
    return handoff, netlist


def test_accepted_r4_handoff_is_persisted_read_back_and_drc_bound(
    tmp_path: Path,
) -> None:
    handoff, netlist = _handoff_and_netlist()
    result = persist_accepted_bus_lcs_cost_board_layout(
        handoff=handoff,
        netlist=netlist,
        output_root=tmp_path,
        verifier=lambda authority, _output: _fake_roundtrip(authority),
    )

    assert result.roundtrip_authority.drc_status == "passed"
    assert result.roundtrip_authority.require_drc_pass
    assert (
        result.serialization_authority.final_layout_fingerprint
        == handoff.board_layout_snapshot_fingerprint
    )
    assert (
        PersistedBusLcsCostBoardHandoff.model_validate_json(
            result.model_dump_json()
        )
        == result
    )


def test_persisted_r4_handoff_rejects_saved_revision_substitution(
    tmp_path: Path,
) -> None:
    handoff, netlist = _handoff_and_netlist()
    result = persist_accepted_bus_lcs_cost_board_layout(
        handoff=handoff,
        netlist=netlist,
        output_root=tmp_path,
        verifier=lambda authority, _output: _fake_roundtrip(authority),
    )
    payload = result.model_dump(mode="json")
    payload["roundtrip_authority"]["saved_board_sha256"] = "0" * 64

    with pytest.raises(ValidationError):
        PersistedBusLcsCostBoardHandoff.model_validate(payload)


@pytest.mark.skipif(
    os.environ.get("PCBSMITH_R4_KICAD_GOLDEN") != "1",
    reason="set PCBSMITH_R4_KICAD_GOLDEN=1 to exercise the installed KiCad CLI",
)
def test_accepted_r4_handoff_passes_live_repeat_save_readback_and_drc(
    tmp_path: Path,
) -> None:
    handoff, netlist = _handoff_and_netlist()

    result = persist_accepted_bus_lcs_cost_board_layout(
        handoff=handoff,
        netlist=netlist,
        output_root=tmp_path,
    )

    assert result.roundtrip_authority.drc_status == "passed"
    assert result.roundtrip_authority.drc_findings == ()
    assert (
        result.roundtrip_authority.saved_board_sha256
        == result.roundtrip_authority.repeated_saved_board_sha256
    )
