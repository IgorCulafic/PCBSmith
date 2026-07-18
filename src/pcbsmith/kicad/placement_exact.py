"""Opt-in R5.5 exact-check orchestration over immutable R5.4 detail results."""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass

from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.negotiated_board import (
    ExactRouteChecker,
    ExactRouteCheckResult,
)
from pcbsmith.kicad.placement_detail import PlacementDetailRun
from pcbsmith.kicad.placement_routability import board_layout_fingerprint
from pcbsmith.placement_exact_ir import (
    PlacementExactBudget,
    PlacementExactCandidateRecord,
    PlacementExactCheckEvidence,
    PlacementExactDisposition,
    PlacementExactPolicy,
    PlacementExactRunResult,
    PlacementFinalState,
    exact_candidate_input_fingerprint,
    exact_checker_report_fingerprint,
    exact_invocation_input_fingerprint,
)


def _fp(payload: object) -> str:
    text = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(text.encode()).hexdigest()


def placement_exact_netlist_fingerprint(netlist: BoardNetlist) -> str:
    """Canonical netlist identity used by R5.5 exact-candidate records."""
    components = tuple(
        {
            "reference": item.reference,
            "value": item.value,
            "footprint": item.footprint,
            "uuid_path": item.uuid_path,
            "fields": item.fields,
        }
        for item in sorted(netlist.components, key=lambda item: item.reference)
    )
    nets = tuple(
        {"name": item.name, "nodes": tuple(sorted(item.nodes))}
        for item in sorted(netlist.nets, key=lambda item: item.name)
    )
    return _fp(
        {
            "schema_id": "pcbsmith-board-netlist",
            "schema_version": 1,
            "components": components,
            "nets": nets,
        }
    )


def placement_route_geometry_fingerprint(
    layout: BoardLayout, target_nets: frozenset[str]
) -> str:
    """Canonical target-route identity used by R5.4/R5.5 evidence."""
    return _fp(
        {
            "schema_id": "pcbsmith-placement-detail-route-geometry",
            "schema_version": 1,
            "segments": [asdict(item) for item in layout.segments if item.net_name in target_nets],
            "vias": [asdict(item) for item in layout.vias if item.net_name in target_nets],
        }
    )


@dataclass(frozen=True)
class PlacementExactInput:
    candidate_fingerprint: str
    detail_record_fingerprint: str
    routing_run_fingerprint: str
    route_geometry_fingerprint: str
    materialized_layout_fingerprint: str
    netlist_fingerprint: str
    layout: BoardLayout
    netlist: BoardNetlist

    def __post_init__(self) -> None:
        values = (
            self.candidate_fingerprint,
            self.detail_record_fingerprint,
            self.routing_run_fingerprint,
            self.route_geometry_fingerprint,
            self.materialized_layout_fingerprint,
            self.netlist_fingerprint,
        )
        if any(
            len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
            for value in values
        ):
            raise ValueError("exact input fingerprints must be lowercase SHA-256")
        if board_layout_fingerprint(self.layout) != self.materialized_layout_fingerprint:
            raise ValueError("exact input materialized layout fingerprint is stale")
        if placement_exact_netlist_fingerprint(self.netlist) != self.netlist_fingerprint:
            raise ValueError("exact input netlist fingerprint is stale")

    def semantic_fingerprint(self) -> str:
        return exact_candidate_input_fingerprint(
            self.candidate_fingerprint,
            self.detail_record_fingerprint,
            self.routing_run_fingerprint,
            self.route_geometry_fingerprint,
            self.materialized_layout_fingerprint,
            self.netlist_fingerprint,
        )


@dataclass(frozen=True)
class PlacementExactRun:
    result: PlacementExactRunResult
    detail_run: PlacementDetailRun

    def __post_init__(self) -> None:
        if (
            self.result.detail_result_fingerprint != self.detail_run.result.semantic_fingerprint()
            or self.result.detail_result != self.detail_run.result
        ):
            raise ValueError("R5.5 result does not bind its immutable R5.4 source")


def _build_exact_inputs(
    detail_run: PlacementDetailRun,
    netlists_by_candidate_fingerprint: Mapping[str, BoardNetlist],
) -> dict[str, PlacementExactInput]:
    layouts = dict(detail_run.routed_layouts)
    eligible = {
        item.candidate_fingerprint
        for item in detail_run.result.candidate_records
        if item.routed_unchecked
    }
    if set(netlists_by_candidate_fingerprint) != eligible:
        raise ValueError("exact netlist mapping must exactly cover routed-unchecked candidates")
    target_nets = frozenset(detail_run.result.r2_policy.target_nets)
    out: dict[str, PlacementExactInput] = {}
    for record in detail_run.result.candidate_records:
        candidate = record.candidate_fingerprint
        if candidate not in eligible:
            continue
        layout = layouts.get(candidate)
        if layout is None:
            raise ValueError("eligible exact candidate lacks its R5.4 materialized layout")
        if (
            record.routing_run is None
            or record.route_geometry_fingerprint is None
            or record.materialized_layout_fingerprint is None
        ):
            raise ValueError("eligible exact candidate lacks bound R5.4 route evidence")
        route_geometry = placement_route_geometry_fingerprint(layout, target_nets)
        if route_geometry != record.route_geometry_fingerprint:
            raise ValueError("R5.4 route geometry fingerprint is stale for exact checking")
        netlist = netlists_by_candidate_fingerprint[candidate]
        out[candidate] = PlacementExactInput(
            candidate_fingerprint=candidate,
            detail_record_fingerprint=record.semantic_fingerprint(),
            routing_run_fingerprint=record.routing_run.semantic_fingerprint(),
            route_geometry_fingerprint=route_geometry,
            materialized_layout_fingerprint=record.materialized_layout_fingerprint,
            netlist_fingerprint=placement_exact_netlist_fingerprint(netlist),
            layout=layout,
            netlist=netlist,
        )
    return out


def evaluate_placement_exact(
    detail_run: PlacementDetailRun,
    *,
    netlists_by_candidate_fingerprint: Mapping[str, BoardNetlist],
    policy: PlacementExactPolicy,
    budget: PlacementExactBudget,
    checker: ExactRouteChecker | None,
) -> PlacementExactRun:
    """Run one exact checker at most once per eligible candidate, under a fixed budget."""

    exact_inputs = _build_exact_inputs(
        detail_run,
        netlists_by_candidate_fingerprint,
    )
    checker_available = checker is not None
    policy_fingerprint = policy.semantic_fingerprint()
    consumed = 0
    records: list[PlacementExactCandidateRecord] = []

    for detail in detail_run.result.candidate_records:
        candidate = detail.candidate_fingerprint
        common = {
            "candidate_fingerprint": candidate,
            "detail_record": detail,
            "detail_record_fingerprint": detail.semantic_fingerprint(),
        }
        if not detail.selected:
            records.append(
                PlacementExactCandidateRecord(
                    **common,
                    disposition=PlacementExactDisposition.NOT_ELIGIBLE,
                    final_state=PlacementFinalState.NOT_SELECTED,
                    exact_checks_consumed=0,
                )
            )
            continue
        if not detail.routed_unchecked:
            records.append(
                PlacementExactCandidateRecord(
                    **common,
                    disposition=PlacementExactDisposition.NOT_ELIGIBLE,
                    final_state=PlacementFinalState.ROUTING_FAILED,
                    exact_checks_consumed=0,
                )
            )
            continue
        source = exact_inputs[candidate]
        eligible_common = {**common, "netlist_fingerprint": source.netlist_fingerprint}
        if checker is None:
            records.append(
                PlacementExactCandidateRecord(
                    **eligible_common,
                    disposition=PlacementExactDisposition.CHECKER_UNAVAILABLE,
                    final_state=PlacementFinalState.ROUTED_UNCHECKED,
                    exact_checks_consumed=0,
                )
            )
            continue
        if consumed == budget.max_exact_checks:
            records.append(
                PlacementExactCandidateRecord(
                    **eligible_common,
                    disposition=PlacementExactDisposition.BUDGET_EXHAUSTED,
                    final_state=PlacementFinalState.ROUTED_UNCHECKED,
                    exact_checks_consumed=0,
                )
            )
            continue

        call_index = consumed
        consumed += 1
        exact_input_fingerprint = exact_invocation_input_fingerprint(
            source.semantic_fingerprint(),
            policy_fingerprint,
            policy.checker_id,
            call_index,
        )
        checker_layout = copy.deepcopy(source.layout)
        checker_netlist = copy.deepcopy(source.netlist)
        before_layout = board_layout_fingerprint(checker_layout)
        before_netlist = placement_exact_netlist_fingerprint(checker_netlist)
        if before_layout != source.materialized_layout_fingerprint:
            raise ValueError("exact checker input is not the bound R5.4 layout")
        if before_netlist != source.netlist_fingerprint:
            raise ValueError("exact checker input is not the bound R5.4 netlist")
        raw_report: object | None = None
        checker_error: Exception | None = None
        try:
            raw_report = checker(checker_layout, checker_netlist)
        except Exception as error:
            checker_error = error
        if board_layout_fingerprint(checker_layout) != before_layout:
            raise ValueError("exact checker mutated the materialized R5.4 layout")
        if placement_exact_netlist_fingerprint(checker_netlist) != before_netlist:
            raise ValueError("exact checker mutated the bound R5.4 netlist")
        if checker_error is not None:
            error_fingerprint = _fp(
                {
                    "schema_id": "pcbsmith-placement-exact-checker-error",
                    "schema_version": 1,
                    "error_type": (
                        f"{type(checker_error).__module__}.{type(checker_error).__qualname__}"
                    ),
                    "message": str(checker_error),
                }
            )
            records.append(
                PlacementExactCandidateRecord(
                    **eligible_common,
                    exact_input_fingerprint=exact_input_fingerprint,
                    exact_checks_consumed=1,
                    checker_call_index=call_index,
                    disposition=PlacementExactDisposition.CHECKER_ERROR,
                    final_state=PlacementFinalState.ROUTED_UNCHECKED,
                    checker_error_fingerprint=error_fingerprint,
                )
            )
            continue
        if not isinstance(raw_report, ExactRouteCheckResult):
            raise TypeError("exact checker must return ExactRouteCheckResult")
        if raw_report.checker_id != policy.checker_id:
            raise ValueError("exact checker report ID does not match the fixed policy")

        findings = tuple(raw_report.finding_fingerprints)
        evidence = PlacementExactCheckEvidence(
            candidate_fingerprint=candidate,
            detail_record_fingerprint=detail.semantic_fingerprint(),
            routing_run_fingerprint=source.routing_run_fingerprint,
            route_geometry_fingerprint=source.route_geometry_fingerprint,
            materialized_layout_fingerprint=source.materialized_layout_fingerprint,
            checker_id=raw_report.checker_id,
            checker_report_fingerprint=exact_checker_report_fingerprint(
                raw_report.accepted,
                raw_report.checker_id,
                tuple(sorted(set(findings))),
            ),
            accepted=raw_report.accepted,
            finding_fingerprints=findings,
            call_index=call_index,
        )
        accepted = detail.algorithmic_success and detail.zero_overuse and evidence.accepted
        records.append(
            PlacementExactCandidateRecord(
                **eligible_common,
                exact_input_fingerprint=exact_input_fingerprint,
                exact_checks_consumed=1,
                checker_call_index=call_index,
                disposition=(
                    PlacementExactDisposition.EXACT_ACCEPTED
                    if accepted
                    else PlacementExactDisposition.EXACT_REJECTED
                ),
                final_state=(
                    PlacementFinalState.ACCEPTED if accepted else PlacementFinalState.EXACT_REJECTED
                ),
                exact_report=evidence,
                accepted=accepted,
            )
        )

    detail_result_fingerprint = detail_run.result.semantic_fingerprint()
    budget_fingerprint = budget.semantic_fingerprint()
    input_catalog_fingerprint = _fp(
        {
            "schema_id": "pcbsmith-placement-exact-input-catalog",
            "schema_version": 1,
            "inputs": [
                exact_inputs[candidate].semantic_fingerprint() for candidate in sorted(exact_inputs)
            ],
        }
    )
    input_fields = {
        "detail_result_fingerprint": detail_result_fingerprint,
        "exact_policy_fingerprint": policy_fingerprint,
        "exact_budget_fingerprint": budget_fingerprint,
        "exact_input_catalog_fingerprint": input_catalog_fingerprint,
        "checker_available": checker_available,
    }
    result = PlacementExactRunResult(
        detail_result=detail_run.result,
        **input_fields,
        exact_policy=policy,
        exact_budget=budget,
        input_fingerprint=_fp(
            {
                "schema_id": "pcbsmith-placement-exact-input",
                "schema_version": 1,
                **input_fields,
            }
        ),
        candidate_records=tuple(records),
        exact_checks_consumed=consumed,
        accepted_candidate_fingerprints=tuple(
            item.candidate_fingerprint for item in records if item.accepted
        ),
    )
    return PlacementExactRun(result=result, detail_run=detail_run)
