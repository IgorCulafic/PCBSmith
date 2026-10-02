from __future__ import annotations

from pcbsmith.local_routing_repair import (
    RoutingCandidateMetrics,
    RoutingRepairRegion,
    SelectedRoutingDomain,
    run_local_routing_repair,
)


def _domain(expansions: int = 1) -> SelectedRoutingDomain:
    return SelectedRoutingDomain(
        domain_id="open-sig",
        net_names=("SIG",),
        mutable_object_ids=("seg-a",),
        protected_object_fingerprints=(("seg-b", "a" * 64),),
        initial_region=RoutingRepairRegion(
            x_min_mm=0, y_min_mm=0, x_max_mm=10, y_max_mm=10, expansion_index=0
        ),
        maximum_expansions=expansions,
    )


def _candidate(
    region: RoutingRepairRegion, candidate_id: str, **changes: int | float
) -> RoutingCandidateMetrics:
    values: dict[str, int | float | str | RoutingRepairRegion] = {
        "candidate_id": candidate_id,
        "engine_id": "fixture",
        "region": region,
        "drc_violation_count": 0,
        "open_count": 0,
        "width_failure_count": 0,
        "return_failure_count": 0,
        "protected_change_count": 0,
        "unrelated_net_change_count": 0,
        "craft_penalty": 1.0,
        "route_length_mm": 12.0,
        "via_count": 1,
        "retained_directory": "candidate",
    }
    values.update(changes)
    return RoutingCandidateMetrics.model_validate(values)


def test_protected_change_rejects_otherwise_clean_candidate() -> None:
    result = run_local_routing_repair(
        _domain(0),
        producer=lambda region: (_candidate(region, "bad", protected_change_count=1),),
        expansion_margin_mm=2,
    )
    assert not result.accepted
    assert result.terminal_reason == "bounded_expansions_exhausted"


def test_region_expands_monotonically_and_stops_on_first_clean_level() -> None:
    def produce(region: RoutingRepairRegion) -> tuple[RoutingCandidateMetrics, ...]:
        return (
            _candidate(
                region,
                f"candidate-{region.expansion_index}",
                open_count=0 if region.expansion_index == 1 else 1,
            ),
        )

    result = run_local_routing_repair(_domain(2), producer=produce, expansion_margin_mm=2)
    assert result.accepted
    assert [item.region.expansion_index for item in result.attempts] == [0, 1]
    assert result.selected_candidate_id == "candidate-1"


def test_craft_ranks_only_among_hard_clean_candidates() -> None:
    def produce(region: RoutingRepairRegion) -> tuple[RoutingCandidateMetrics, ...]:
        return (
            _candidate(region, "short-bad", open_count=1, route_length_mm=1),
            _candidate(region, "clean-rough", craft_penalty=5, route_length_mm=8),
            _candidate(region, "clean-neat", craft_penalty=1, route_length_mm=10),
        )

    result = run_local_routing_repair(_domain(0), producer=produce, expansion_margin_mm=2)
    assert result.selected_candidate_id == "clean-neat"


def test_geometry_preflight_cannot_substitute_for_qualified_routing():
    import pytest

    domain = _domain(0)
    geometry = _candidate(domain.initial_region, "scope-only").model_copy(
        update={
            "validation_scope": "geometry_envelope",
            "drc_violation_count": None,
            "open_count": None,
            "width_failure_count": None,
            "return_failure_count": None,
        }
    )
    assert geometry.hard_clean
    assert not geometry.model_copy(update={"validation_scope": "qualified_routing"}).hard_clean
    with pytest.raises(ValueError, match="validation scope"):
        run_local_routing_repair(domain, producer=lambda _: (geometry,), expansion_margin_mm=1)


def test_legacy_qualified_routing_receipt_remains_readable():
    import hashlib
    import json

    from pcbsmith.local_routing_repair import LocalRoutingRepairRun

    run = run_local_routing_repair(
        _domain(0), producer=lambda r: (_candidate(r, "good"),), expansion_margin_mm=1
    )
    old = run.model_dump(mode="json", exclude={"run_fingerprint"})
    old["domain"].pop("validation_scope")
    for attempt in old["attempts"]:
        attempt.pop("validation_scope")
    old["run_fingerprint"] = hashlib.sha256(
        json.dumps(old, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert LocalRoutingRepairRun.model_validate(old).accepted
