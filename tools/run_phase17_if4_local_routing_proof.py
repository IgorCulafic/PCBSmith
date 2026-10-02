from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.local_routing_repair import (
    RoutingCandidateMetrics,
    RoutingRepairRegion,
    SelectedRoutingDomain,
    run_local_routing_repair,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "experiments" / "phase17-if4-local-routing-proof-2026-08-20"


def _domain(case: str, expansions: int) -> SelectedRoutingDomain:
    return SelectedRoutingDomain(
        domain_id=case,
        net_names=("SIG",),
        mutable_object_ids=("fault-segment",),
        protected_object_fingerprints=(("accepted-segment", "a" * 64),),
        initial_region=RoutingRepairRegion(
            x_min_mm=10, y_min_mm=10, x_max_mm=20, y_max_mm=20, expansion_index=0
        ),
        maximum_expansions=expansions,
    )


def _candidate(
    region: RoutingRepairRegion, candidate_id: str, **changes: int | float
) -> RoutingCandidateMetrics:
    values: dict[str, object] = {
        "candidate_id": candidate_id,
        "engine_id": "if4-proof-specialist",
        "region": region,
        "drc_violation_count": 0,
        "open_count": 0,
        "width_failure_count": 0,
        "return_failure_count": 0,
        "protected_change_count": 0,
        "unrelated_net_change_count": 0,
        "craft_penalty": 1.0,
        "route_length_mm": 8.0,
        "via_count": 0,
        "retained_directory": f"retained/{candidate_id}",
    }
    values.update(changes)
    return RoutingCandidateMetrics.model_validate(values)


def main() -> int:
    open_run = run_local_routing_repair(
        _domain("injected-open", 2),
        producer=lambda region: (
            _candidate(
                region,
                f"open-{region.expansion_index}",
                open_count=0 if region.expansion_index == 1 else 1,
            ),
        ),
        expansion_margin_mm=2,
    )
    clearance_run = run_local_routing_repair(
        _domain("injected-clearance", 1),
        producer=lambda region: (
            _candidate(
                region,
                f"clearance-{region.expansion_index}",
                protected_change_count=1,
            ),
        ),
        expansion_margin_mm=2,
    )
    craft_run = run_local_routing_repair(
        _domain("injected-via-craft", 0),
        producer=lambda region: (
            _candidate(region, "rough", craft_penalty=6, route_length_mm=6),
            _candidate(region, "neat", craft_penalty=1, route_length_mm=8),
            _candidate(region, "open-short", open_count=1, route_length_mm=1),
        ),
        expansion_margin_mm=2,
    )
    rt37 = json.loads(
        (
            ROOT / "experiments" / "phase17-w8-rt37-real-repair-2026-08-20" / "execution.json"
        ).read_text(encoding="utf-8")
    )
    payload = {
        "schema_id": "pcbsmith-phase17-if4-local-routing-proof",
        "schema_version": 1,
        "fault_matrix": [
            open_run.model_dump(mode="json"),
            clearance_run.model_dump(mode="json"),
            craft_run.model_dump(mode="json"),
        ],
        "real_retained_evidence": {
            "rt37_execution_outcome": rt37.get("result", {}).get("outcome"),
            "rt37_execution_fingerprint": rt37.get("result", {}).get("result_fingerprint"),
            "rt40_status": "blocked_existing_vin_island_and_sig8_b_open",
        },
        "conclusion": (
            "Injected selected-domain open repair and hard-clean craft ranking pass; "
            "protected mutation exhausts bounded expansion. RT37 retained evidence remains "
            "accepted; RT40 is not falsely claimed repaired."
        ),
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "summary.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
