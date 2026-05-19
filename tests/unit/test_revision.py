from __future__ import annotations

import pytest

from pcbsmith.revision import revision_for_authority_failure, should_stop_revision_loop


@pytest.mark.parametrize(
    ("failure_code", "changed_artifacts", "authority_checks", "next_action"),
    (
        (
            "evidence_missing",
            ("Evidence cache or part selection",),
            ("evidence_lookup",),
            "Fetch or request the missing evidence before changing the schematic.",
        ),
        (
            "math_mismatch",
            ("Circuit object values or deterministic calculators",),
            ("math_gate",),
            "Recalculate values and update the existing circuit object.",
        ),
        (
            "kicad_failed",
            ("KiCad schematic or symbol mapping",),
            ("kicad_erc", "kicad_spice_export"),
            "Patch the existing KiCad schematic or symbol mapping.",
        ),
        (
            "simulation_failed",
            ("SPICE model, simulation setup, or circuit values",),
            ("ngspice",),
            "Patch the simulation setup or circuit values and rerun ngspice.",
        ),
        (
            "reconciliation_failed",
            ("Translation boundary between PCBSmith, KiCad, and ngspice",),
            ("reconciliation",),
            "Patch the mismatched translation layer.",
        ),
    ),
)
def test_revision_for_authority_failure_routes_to_existing_artifacts(
    failure_code: str,
    changed_artifacts: tuple[str, ...],
    authority_checks: tuple[str, ...],
    next_action: str,
) -> None:
    revision = revision_for_authority_failure(
        revision_id="rev-2",
        parent_revision_id="rev-1",
        failure_code=failure_code,
        findings=("ERC reports unconnected HP_OUT.",),
    )

    assert revision.revision_id == "rev-2"
    assert revision.parent_revision_id == "rev-1"
    assert revision.changed_artifacts == changed_artifacts
    assert revision.authority_checks == authority_checks
    assert revision.findings == ("ERC reports unconnected HP_OUT.",)
    assert revision.next_action == next_action


def test_revision_loop_stops_after_repeated_same_failure() -> None:
    assert should_stop_revision_loop(("simulation_failed", "simulation_failed"), limit=2)
    assert not should_stop_revision_loop(("simulation_failed", "kicad_failed"), limit=2)


def test_revision_loop_accepts_list_style_history() -> None:
    failure_codes = ["simulation_failed", "simulation_failed"]

    assert should_stop_revision_loop(failure_codes, limit=2)


def test_revision_loop_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="Revision loop limit must be positive."):
        should_stop_revision_loop(("simulation_failed",), limit=0)


def test_revision_for_unknown_failure_code_fails_closed() -> None:
    with pytest.raises(ValueError, match="Unknown authority failure code: not_a_route"):
        revision_for_authority_failure(
            revision_id="rev-2",
            parent_revision_id="rev-1",
            failure_code="not_a_route",
            findings=("No route exists.",),
        )
