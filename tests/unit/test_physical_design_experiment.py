from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from pcbsmith.physical_design_experiment import (
    ExperimentComparisonScope,
    ExperimentTermination,
    GeometryComparison,
    PhysicalDesignAuthorityIdentity,
    PhysicalDesignExperimentIdentity,
    PhysicalDesignExperimentResult,
    SoftwareIdentity,
    compare_physical_design_results,
    summarize_physical_design_results,
)


def _digest(character: str) -> str:
    return character * 64


def _software(name: str) -> SoftwareIdentity:
    return SoftwareIdentity(software_id=name, version="fixture-1")


def _authority(*, board: str = "1", predicate: str = "a") -> PhysicalDesignAuthorityIdentity:
    return PhysicalDesignAuthorityIdentity(
        source_board_sha256=_digest(board),
        schematic_sha256=_digest("2"),
        netlist_sha256=_digest("3"),
        exact_part_authority_sha256=_digest("4"),
        footprint_library_sha256=_digest("5"),
        fabrication_profile_sha256=_digest("6"),
        translated_constraints_sha256=_digest("7"),
        zone_intent_sha256=_digest("8"),
        acceptance_predicate_id="phase17-whole-board",
        acceptance_predicate_version="v1",
        acceptance_predicate_sha256=_digest(predicate),
        active_copper_layers=("F.Cu", "B.Cu"),
    )


def _identity(
    experiment_id: str,
    *,
    cohort_id: str = "cohort-33-of-40",
    authority: PhysicalDesignAuthorityIdentity | None = None,
    final_board: str = "b",
) -> PhysicalDesignExperimentIdentity:
    started = datetime(2026, 8, 19, 8, tzinfo=UTC)
    return PhysicalDesignExperimentIdentity.build(
        experiment_id=experiment_id,
        cohort_id=cohort_id,
        case_id="RC01",
        authorities=authority or _authority(),
        generator=_software("pcbsmith"),
        kicad=_software("kicad-cli"),
        router=_software("freerouting"),
        adapter=_software("pcbsmith-freerouting-adapter"),
        java=_software("java"),
        python=_software("python"),
        router_seed=17,
        router_configuration_sha256=_digest("9"),
        final_filled_board_sha256=_digest(final_board),
        started_at_utc=started,
        ended_at_utc=started + timedelta(seconds=10),
        termination=ExperimentTermination.COMPLETED,
        time_budget_seconds=60.0,
        memory_budget_bytes=1_000_000,
        elapsed_seconds=10.0,
        peak_memory_bytes=100_000,
    )


def _result(
    experiment_id: str,
    *,
    cohort_id: str = "cohort-33-of-40",
    authority: PhysicalDesignAuthorityIdentity | None = None,
    final_board: str = "b",
    semantic_geometry: str = "c",
    accepted: bool = True,
    whole_board_gate_complete: bool = True,
) -> PhysicalDesignExperimentResult:
    return PhysicalDesignExperimentResult.build(
        identity=_identity(
            experiment_id,
            cohort_id=cohort_id,
            authority=authority,
            final_board=final_board,
        ),
        semantic_geometry_sha256=_digest(semantic_geometry),
        acceptance_result_sha256=_digest("d"),
        whole_board_accepted=accepted,
        local_check_pass_count=2500,
        local_check_fail_count=0,
        whole_board_gate_complete=whole_board_gate_complete,
    )


def test_historical_cohorts_have_distinct_complete_identities() -> None:
    identities = tuple(
        _identity(name, cohort_id=name)
        for name in ("cohort-33-of-40", "cohort-20-of-40", "hard-eight-v7", "hard-eight-v11")
    )

    assert len({item.identity_fingerprint for item in identities}) == 4
    assert {item.cohort_id for item in identities} == {
        "cohort-33-of-40",
        "cohort-20-of-40",
        "hard-eight-v7",
        "hard-eight-v11",
    }


@pytest.mark.parametrize(
    ("left_authority", "right_authority"),
    [
        (_authority(board="1"), _authority(board="e")),
        (_authority(predicate="a"), _authority(predicate="f")),
    ],
)
def test_comparison_refuses_different_board_or_gate_without_cross_cohort_label(
    left_authority: PhysicalDesignAuthorityIdentity,
    right_authority: PhysicalDesignAuthorityIdentity,
) -> None:
    left = _result("left", authority=left_authority)
    right = _result("right", authority=right_authority)

    with pytest.raises(ValueError, match="different input boards or gate definitions"):
        compare_physical_design_results(left, right)
    with pytest.raises(ValueError, match="explicit label"):
        compare_physical_design_results(left, right, cross_cohort=True)

    comparison = compare_physical_design_results(
        left,
        right,
        cross_cohort=True,
        cross_cohort_label="historical context only",
    )
    assert comparison.scope is ExperimentComparisonScope.CROSS_COHORT
    assert comparison.geometry_comparison is GeometryComparison.NOT_COMPARED
    assert not comparison.aggregate_success_rate_allowed


def test_repeat_reports_exact_then_semantic_geometry_equality() -> None:
    left = _result("repeat-1", final_board="b", semantic_geometry="c")
    exact = _result("repeat-2", final_board="b", semantic_geometry="c")
    semantic = _result("repeat-3", final_board="e", semantic_geometry="c")

    assert (
        compare_physical_design_results(left, exact).geometry_comparison
        is GeometryComparison.EXACT_EQUAL
    )
    assert (
        compare_physical_design_results(left, semantic).geometry_comparison
        is GeometryComparison.SEMANTIC_EQUAL
    )


def test_local_passes_cannot_claim_whole_board_acceptance() -> None:
    with pytest.raises(ValidationError, match="local checks cannot establish"):
        _result("local-only", whole_board_gate_complete=False)


def test_cross_cohort_summary_cannot_emit_a_blended_success_rate() -> None:
    results = (
        _result("old", authority=_authority(board="1")),
        _result("new", authority=_authority(board="e"), accepted=False),
    )
    with pytest.raises(ValueError, match="cannot aggregate"):
        summarize_physical_design_results(results)

    summary = summarize_physical_design_results(
        results,
        cross_cohort=True,
        cross_cohort_label="historical results under different gates",
    )
    assert summary.success_rate is None
    assert summary.accepted_count == 1
    assert len(summary.input_gate_fingerprints) == 2
