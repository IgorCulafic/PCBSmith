from __future__ import annotations

import pytest

from pcbsmith.revision import revision_for_authority_failure, should_stop_revision_loop


def test_revision_for_kicad_failure_targets_existing_schematic() -> None:
    revision = revision_for_authority_failure(
        revision_id="rev-2",
        parent_revision_id="rev-1",
        failure_code="kicad_failed",
        findings=("ERC reports unconnected HP_OUT.",),
    )

    assert revision.changed_artifacts == ("KiCad schematic or symbol mapping",)
    assert revision.authority_checks == ("kicad_erc", "kicad_spice_export")
    assert revision.next_action == "Patch the existing KiCad schematic or symbol mapping."


def test_revision_loop_stops_after_repeated_same_failure() -> None:
    assert should_stop_revision_loop(("simulation_failed", "simulation_failed"), limit=2)
    assert not should_stop_revision_loop(("simulation_failed", "kicad_failed"), limit=2)


def test_revision_for_unknown_failure_code_fails_closed() -> None:
    with pytest.raises(ValueError, match="Unknown authority failure code: not_a_route"):
        revision_for_authority_failure(
            revision_id="rev-2",
            parent_revision_id="rev-1",
            failure_code="not_a_route",
            findings=("No route exists.",),
        )
