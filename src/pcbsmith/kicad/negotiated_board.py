"""Board-wide deterministic negotiated-congestion routing orchestration."""

from __future__ import annotations

import copy
import hashlib
import json
import math
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass

from pcbsmith.corridor_guidance import (
    CorridorGuidanceDisposition,
    CorridorGuidanceReport,
    build_corridor_route_guide,
)
from pcbsmith.corridor_ir import CorridorGraph, CorridorPlanResult
from pcbsmith.kicad.astar_router import (
    DEFAULT_MAX_BOARD_EXPANSIONS,
    DEFAULT_MAX_EXPANSIONS_PER_NET,
    GRID_MM,
    RouteResult,
    RoutingError,
    _routable_nets,
)
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.clearance_domains import (
    ClearanceGroupInput,
    build_route_pairwise_clearance_domains,
)
from pcbsmith.kicad.corridor_guidance import project_corridor_route_guide
from pcbsmith.kicad.corridor_planner import build_corridor_graph
from pcbsmith.kicad.negotiated_graph import (
    DEFAULT_NEGOTIATED_COST_POLICY,
    NegotiatedCostPolicy,
)
from pcbsmith.kicad.negotiated_grid import (
    GridSoftGuide,
    NegotiatedGridRoute,
    route_net_negotiated_candidate,
)
from pcbsmith.kicad.negotiated_resources import (
    OccupancyLedger,
    PairwiseClearanceDomain,
    RoutingResourceKey,
)
from pcbsmith.kicad.placement_routability import board_layout_fingerprint
from pcbsmith.kicad.route_prefix import GridRoutePrefix
from pcbsmith.routing_ir import (
    NetRoutingTelemetry,
    ResourceOveruseSummary,
    RoutingBudget,
    RoutingFailureReason,
    RoutingPassTelemetry,
    RoutingRunResult,
)
from pcbsmith.rule_profiles import (
    DEFAULT_PCB_RULE_PROFILE,
    PcbRuleProfile,
)


@dataclass(frozen=True)
class ExactRouteCheckResult:
    """Board-level exact checker verdict kept separate from search success."""

    accepted: bool
    checker_id: str
    finding_fingerprints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, bool):
            raise TypeError("accepted must be a boolean")
        if not self.checker_id:
            raise ValueError("checker_id must be non-empty")
        canonical = tuple(sorted(set(self.finding_fingerprints)))
        if any(not item for item in canonical):
            raise ValueError("finding fingerprints must be non-empty")
        object.__setattr__(self, "finding_fingerprints", canonical)


ExactRouteChecker = Callable[[BoardLayout, BoardNetlist], ExactRouteCheckResult]


def _sha256_json(payload: object) -> str:
    text = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _require_sha256(value: str, field_name: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")


def board_netlist_fingerprint(netlist: BoardNetlist) -> str:
    """Fingerprint the complete canonical BoardNetlist semantic value."""

    components = tuple(
        {
            "reference": component.reference,
            "value": component.value,
            "footprint": component.footprint,
            "uuid_path": component.uuid_path,
            "fields": tuple(sorted(component.fields)),
        }
        for component in sorted(
            netlist.components,
            key=lambda item: (
                item.reference,
                item.value,
                item.footprint,
                item.uuid_path,
                tuple(sorted(item.fields)),
            ),
        )
    )
    nets = tuple(
        {"name": net.name, "nodes": tuple(sorted(net.nodes))}
        for net in sorted(netlist.nets, key=lambda item: (item.name, tuple(sorted(item.nodes))))
    )
    return _sha256_json(
        {
            "schema_id": "pcbsmith-board-netlist-complete",
            "schema_version": 1,
            "components": components,
            "nets": nets,
        }
    )


def _finding_identities_fingerprint(finding_identities: tuple[str, ...]) -> str:
    return _sha256_json(
        {
            "schema_id": "pcbsmith-exact-route-finding-identities",
            "schema_version": 1,
            "finding_identities": finding_identities,
        }
    )


def exact_route_check_report_fingerprint(result: ExactRouteCheckResult) -> str:
    """Fingerprint one canonical exact-check report."""

    return _sha256_json(
        {
            "accepted": result.accepted,
            "checker_id": result.checker_id,
            "finding_fingerprints": result.finding_fingerprints,
        }
    )


def _exact_route_call_input_fingerprint(
    layout_fingerprint: str,
    netlist_fingerprint: str,
    checker_id: str,
) -> str:
    return _sha256_json(
        {
            "schema_id": "pcbsmith-exact-route-check-call-input",
            "schema_version": 1,
            "layout_fingerprint": layout_fingerprint,
            "netlist_fingerprint": netlist_fingerprint,
            "checker_id": checker_id,
        }
    )


@dataclass(frozen=True)
class ExactRouteCheckEvidence:
    """Replay-validated binding of an exact verdict to its complete inputs."""

    materialized_layout_fingerprint: str
    checked_netlist_fingerprint: str
    checker_id: str
    finding_identities: tuple[str, ...]
    finding_identities_fingerprint: str
    report_fingerprint: str
    call_input_fingerprint: str
    accepted: bool
    schema_id: str = "pcbsmith-exact-route-check-evidence"
    schema_version: int = 1

    def __post_init__(self) -> None:
        if self.schema_id != "pcbsmith-exact-route-check-evidence" or self.schema_version != 1:
            raise ValueError("unsupported exact route check evidence schema")
        if not isinstance(self.accepted, bool):
            raise TypeError("exact evidence accepted must be a boolean")
        if not self.checker_id:
            raise ValueError("exact evidence checker_id must be non-empty")
        canonical = tuple(sorted(set(self.finding_identities)))
        if canonical != self.finding_identities or any(not item for item in canonical):
            raise ValueError(
                "exact evidence finding identities must be sorted, unique, and non-empty"
            )
        for field_name, value in (
            ("materialized_layout_fingerprint", self.materialized_layout_fingerprint),
            ("checked_netlist_fingerprint", self.checked_netlist_fingerprint),
            ("finding_identities_fingerprint", self.finding_identities_fingerprint),
            ("report_fingerprint", self.report_fingerprint),
            ("call_input_fingerprint", self.call_input_fingerprint),
        ):
            _require_sha256(value, field_name)
        if self.finding_identities_fingerprint != _finding_identities_fingerprint(canonical):
            raise ValueError("exact evidence finding identity fingerprint is stale")
        report = ExactRouteCheckResult(self.accepted, self.checker_id, canonical)
        if self.report_fingerprint != exact_route_check_report_fingerprint(report):
            raise ValueError("exact evidence report fingerprint is stale")
        expected_call = _exact_route_call_input_fingerprint(
            self.materialized_layout_fingerprint,
            self.checked_netlist_fingerprint,
            self.checker_id,
        )
        if self.call_input_fingerprint != expected_call:
            raise ValueError("exact evidence call input fingerprint is stale")

    @classmethod
    def from_exact_check(
        cls,
        layout: BoardLayout,
        netlist: BoardNetlist,
        report: ExactRouteCheckResult,
    ) -> ExactRouteCheckEvidence:
        layout_fingerprint = board_layout_fingerprint(layout)
        netlist_fingerprint = board_netlist_fingerprint(netlist)
        findings = report.finding_fingerprints
        return cls(
            materialized_layout_fingerprint=layout_fingerprint,
            checked_netlist_fingerprint=netlist_fingerprint,
            checker_id=report.checker_id,
            finding_identities=findings,
            finding_identities_fingerprint=_finding_identities_fingerprint(findings),
            report_fingerprint=exact_route_check_report_fingerprint(report),
            call_input_fingerprint=_exact_route_call_input_fingerprint(
                layout_fingerprint,
                netlist_fingerprint,
                report.checker_id,
            ),
            accepted=report.accepted,
        )


@dataclass(frozen=True, order=True)
class AppliedRoutePrefixBinding:
    """Auditable identity of one prefix present in a materialized board route."""

    net_name: str
    alternative_id: str
    prefix_fingerprint: str

    def __post_init__(self) -> None:
        if not self.net_name or not self.alternative_id:
            raise ValueError("applied prefix identities must be non-empty")
        if len(self.prefix_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in self.prefix_fingerprint
        ):
            raise ValueError("applied prefix fingerprint must be a lowercase SHA-256")


@dataclass(frozen=True)
class NegotiatedBoardRouteResult:
    """Materialized board plus algorithmic and exact-check outcomes."""

    layout: BoardLayout
    results: tuple[RouteResult, ...]
    order: tuple[str, ...]
    run_result: RoutingRunResult
    exact_check: ExactRouteCheckResult | None
    prefix_bindings: tuple[AppliedRoutePrefixBinding, ...] = ()
    exact_check_evidence: ExactRouteCheckEvidence | None = None
    checked_netlist: BoardNetlist | None = None

    def __post_init__(self) -> None:
        if len(set(self.order)) != len(self.order):
            raise ValueError("board route order must contain unique nets")
        result_names = tuple(item.net_name for item in self.results)
        expected_names = tuple(name for name in self.order if name in set(result_names))
        if result_names != expected_names or len(set(result_names)) != len(result_names):
            raise ValueError("route results must be unique and follow board route order")
        if self.run_result.route_order != self.order:
            raise ValueError("run route_order must match board route order")
        if self.run_result.success and result_names != self.order:
            raise ValueError("successful board routing requires a result for every net")
        if self.exact_check is None:
            if self.run_result.exact_check_accepted is not None:
                raise ValueError("missing exact check requires an unknown run verdict")
            if self.exact_check_evidence is not None or self.checked_netlist is not None:
                raise ValueError("missing exact check cannot retain exact evidence or netlist")
        else:
            try:
                canonical_report = ExactRouteCheckResult(
                    accepted=self.exact_check.accepted,
                    checker_id=self.exact_check.checker_id,
                    finding_fingerprints=tuple(self.exact_check.finding_fingerprints),
                )
            except (AttributeError, TypeError, ValueError) as error:
                raise ValueError("exact check report is invalid") from error
            if canonical_report != self.exact_check:
                raise ValueError("exact check report is not canonical")
            if self.run_result.exact_check_accepted is not canonical_report.accepted:
                raise ValueError("exact check and run verdict must agree")
            if not self.run_result.success:
                raise ValueError("algorithmic failure cannot contain an exact check")
            if self.exact_check_evidence is None or self.checked_netlist is None:
                raise ValueError("exact check requires retained evidence and checked netlist")
            evidence = self.exact_check_evidence
            try:
                canonical_evidence = ExactRouteCheckEvidence(
                    materialized_layout_fingerprint=evidence.materialized_layout_fingerprint,
                    checked_netlist_fingerprint=evidence.checked_netlist_fingerprint,
                    checker_id=evidence.checker_id,
                    finding_identities=tuple(evidence.finding_identities),
                    finding_identities_fingerprint=evidence.finding_identities_fingerprint,
                    report_fingerprint=evidence.report_fingerprint,
                    call_input_fingerprint=evidence.call_input_fingerprint,
                    accepted=evidence.accepted,
                    schema_id=evidence.schema_id,
                    schema_version=evidence.schema_version,
                )
            except (AttributeError, TypeError, ValueError) as error:
                raise ValueError("exact check evidence is invalid") from error
            if canonical_evidence != evidence:
                raise ValueError("exact check evidence is not canonical")
            if evidence.accepted is not canonical_report.accepted:
                raise ValueError("exact evidence and report verdict must agree")
            if evidence.checker_id != canonical_report.checker_id:
                raise ValueError("exact evidence and report checker IDs must agree")
            if evidence.finding_identities != canonical_report.finding_fingerprints:
                raise ValueError("exact evidence and report findings must agree")
            if evidence.report_fingerprint != exact_route_check_report_fingerprint(
                canonical_report
            ):
                raise ValueError("exact evidence does not bind the retained report")
            if evidence.materialized_layout_fingerprint != board_layout_fingerprint(self.layout):
                raise ValueError("exact evidence does not bind the materialized layout")
            if evidence.checked_netlist_fingerprint != board_netlist_fingerprint(
                self.checked_netlist
            ):
                raise ValueError("exact evidence does not bind the retained checked netlist")
        canonical_bindings = tuple(sorted(set(self.prefix_bindings)))
        if canonical_bindings != self.prefix_bindings:
            raise ValueError("prefix bindings must be sorted and unique")
        if any(binding.net_name not in result_names for binding in canonical_bindings):
            raise ValueError("prefix bindings must belong to materialized route results")


@dataclass(frozen=True)
class CorridorGuidedBoardRouteResult:
    """Detailed routing plus a separately fingerprinted guidance disposition."""

    route_result: NegotiatedBoardRouteResult
    guidance: CorridorGuidanceReport

    def __post_init__(self) -> None:
        if (
            self.guidance.routing_run_fingerprint
            != self.route_result.run_result.semantic_fingerprint()
        ):
            raise ValueError("guidance report must bind the nested routing run")


def route_board_corridor_guided(
    layout: BoardLayout,
    netlist: BoardNetlist,
    *,
    corridor_graph: CorridorGraph | None = None,
    corridor_plan: CorridorPlanResult | None = None,
    off_corridor_penalty_units: int = 0,
    target_nets: Collection[str] | None = None,
    net_widths: Mapping[str, float] | None = None,
    default_width_mm: float = 0.4,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    net_order: Sequence[str] | None = None,
    grid_mm: float = GRID_MM,
    clearance_groups: Sequence[ClearanceGroupInput] = (),
    max_passes: int = 16,
    max_expansions: int = DEFAULT_MAX_BOARD_EXPANSIONS,
    max_expansions_per_net: int = DEFAULT_MAX_EXPANSIONS_PER_NET,
    max_stagnant_passes: int = 8,
    cost_policy: NegotiatedCostPolicy = DEFAULT_NEGOTIATED_COST_POLICY,
    exact_checker: ExactRouteChecker | None = None,
) -> CorridorGuidedBoardRouteResult:
    """Apply compatible corridor guidance, otherwise run ordinary negotiated R2."""
    _require_non_negative_int(off_corridor_penalty_units, "off_corridor_penalty_units")
    disposition = CorridorGuidanceDisposition.ABSENT
    plan_fingerprint: str | None = None
    graph_fingerprint: str | None = None
    plan_failure_reason = None
    projected_fingerprint: str | None = None
    soft_guides: Mapping[str, GridSoftGuide] = {}

    if corridor_plan is not None:
        plan_fingerprint = corridor_plan.semantic_fingerprint()
        plan_failure_reason = corridor_plan.failure_reason
    if corridor_graph is not None:
        graph_fingerprint = corridor_graph.semantic_fingerprint()
    if corridor_graph is None and corridor_plan is None:
        disposition = CorridorGuidanceDisposition.ABSENT
    elif corridor_graph is None or corridor_plan is None:
        disposition = CorridorGuidanceDisposition.INCOMPLETE_INPUT
    elif not corridor_plan.guidance_ready:
        disposition = CorridorGuidanceDisposition.PLAN_NOT_READY
    else:
        try:
            current_graph_build = build_corridor_graph(
                layout,
                netlist,
                target_nets=target_nets,
                net_widths=net_widths,
                default_width_mm=default_width_mm,
                profile=profile,
                clearance_groups=clearance_groups,
                coarse_grid_mm=corridor_graph.coarse_grid_mm,
                capacity_quantum_mm=corridor_graph.capacity_quantum_mm,
            )
            if (
                not current_graph_build.planning_supported
                or current_graph_build.graph.semantic_fingerprint()
                != corridor_graph.semantic_fingerprint()
            ):
                projected = None
            else:
                coarse_guide = build_corridor_route_guide(
                    corridor_graph,
                    corridor_plan,
                    off_corridor_penalty_units=off_corridor_penalty_units,
                )
                projected = (
                    project_corridor_route_guide(
                        coarse_guide,
                        corridor_graph,
                        layout,
                        grid_mm=grid_mm,
                    )
                    if coarse_guide is not None
                    else None
                )
        except ValueError:
            disposition = CorridorGuidanceDisposition.INCOMPATIBLE
        else:
            if projected is None:
                disposition = CorridorGuidanceDisposition.INCOMPATIBLE
            else:
                disposition = CorridorGuidanceDisposition.APPLIED
                projected_fingerprint = projected.semantic_fingerprint()
                soft_guides = projected.as_soft_guides()

    route_result = route_board_negotiated(
        layout,
        netlist,
        target_nets=target_nets,
        net_widths=net_widths,
        default_width_mm=default_width_mm,
        profile=profile,
        net_order=net_order,
        grid_mm=grid_mm,
        clearance_groups=clearance_groups,
        soft_guides=soft_guides,
        max_passes=max_passes,
        max_expansions=max_expansions,
        max_expansions_per_net=max_expansions_per_net,
        max_stagnant_passes=max_stagnant_passes,
        cost_policy=cost_policy,
        exact_checker=exact_checker,
    )
    guided_names = tuple(name for name in route_result.order if name in soft_guides)
    unguided_names = tuple(name for name in route_result.order if name not in soft_guides)
    if disposition is CorridorGuidanceDisposition.APPLIED and not guided_names:
        disposition = CorridorGuidanceDisposition.INCOMPATIBLE
        projected_fingerprint = None
        unguided_names = route_result.order
    report = CorridorGuidanceReport(
        disposition=disposition,
        plan_fingerprint=plan_fingerprint,
        graph_fingerprint=graph_fingerprint,
        guide_fingerprint=projected_fingerprint,
        plan_failure_reason=(
            plan_failure_reason
            if disposition is CorridorGuidanceDisposition.PLAN_NOT_READY
            else None
        ),
        guided_net_names=(
            guided_names if disposition is CorridorGuidanceDisposition.APPLIED else ()
        ),
        unguided_net_names=unguided_names,
        routing_run_fingerprint=route_result.run_result.semantic_fingerprint(),
        exact_check_fingerprint=_exact_check_fingerprint(route_result.exact_check),
    )
    return CorridorGuidedBoardRouteResult(route_result=route_result, guidance=report)


def _exact_check_fingerprint(result: ExactRouteCheckResult | None) -> str | None:
    if result is None:
        return None
    return exact_route_check_report_fingerprint(result)


def _invoke_exact_checker(
    checker: ExactRouteChecker,
    layout: BoardLayout,
    netlist: BoardNetlist,
) -> tuple[ExactRouteCheckResult, ExactRouteCheckEvidence, BoardNetlist]:
    """Invoke a checker on detached inputs and fail closed on any mutation."""

    caller_layout_before = board_layout_fingerprint(layout)
    caller_netlist_before = board_netlist_fingerprint(netlist)
    checker_layout = copy.deepcopy(layout)
    checker_netlist = copy.deepcopy(netlist)
    checker_layout_before = board_layout_fingerprint(checker_layout)
    checker_netlist_before = board_netlist_fingerprint(checker_netlist)
    if checker_layout_before != caller_layout_before:
        raise ValueError("exact checker layout copy does not match the caller input")
    if checker_netlist_before != caller_netlist_before:
        raise ValueError("exact checker netlist copy does not match the caller input")

    raw_report: object | None = None
    checker_error: Exception | None = None
    try:
        raw_report = checker(checker_layout, checker_netlist)
    except Exception as error:
        checker_error = error

    fingerprint_calls: tuple[tuple[str, str, Callable[[], str]], ...] = (
        ("checker layout", checker_layout_before, lambda: board_layout_fingerprint(checker_layout)),
        (
            "checker netlist",
            checker_netlist_before,
            lambda: board_netlist_fingerprint(checker_netlist),
        ),
        ("caller layout", caller_layout_before, lambda: board_layout_fingerprint(layout)),
        ("caller netlist", caller_netlist_before, lambda: board_netlist_fingerprint(netlist)),
    )
    mutations: list[str] = []
    fingerprint_errors: list[Exception] = []
    for label, before, fingerprint in fingerprint_calls:
        try:
            after = fingerprint()
        except Exception as error:
            mutations.append(label)
            fingerprint_errors.append(error)
        else:
            if after != before:
                mutations.append(label)
    if mutations:
        cause = fingerprint_errors[0] if fingerprint_errors else None
        raise ValueError(f"exact checker mutated bound input(s): {tuple(mutations)!r}") from cause
    if checker_error is not None:
        raise checker_error
    if not isinstance(raw_report, ExactRouteCheckResult):
        raise TypeError("exact checker must return ExactRouteCheckResult")
    try:
        report = ExactRouteCheckResult(
            accepted=raw_report.accepted,
            checker_id=raw_report.checker_id,
            finding_fingerprints=tuple(raw_report.finding_fingerprints),
        )
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError("exact checker returned an invalid report") from error
    if report != raw_report:
        raise ValueError("exact checker returned a non-canonical report")
    retained_netlist = copy.deepcopy(checker_netlist)
    evidence = ExactRouteCheckEvidence.from_exact_check(checker_layout, retained_netlist, report)
    return report, evidence, retained_netlist


def route_board_negotiated(
    layout: BoardLayout,
    netlist: BoardNetlist,
    *,
    target_nets: Collection[str] | None = None,
    net_widths: Mapping[str, float] | None = None,
    default_width_mm: float = 0.4,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    net_order: Sequence[str] | None = None,
    grid_mm: float = GRID_MM,
    clearance_groups: Sequence[ClearanceGroupInput] = (),
    soft_guides: Mapping[str, GridSoftGuide] | None = None,
    route_prefixes: Mapping[str, GridRoutePrefix] | None = None,
    max_passes: int = 16,
    max_expansions: int = DEFAULT_MAX_BOARD_EXPANSIONS,
    max_expansions_per_net: int = DEFAULT_MAX_EXPANSIONS_PER_NET,
    max_stagnant_passes: int = 8,
    cost_policy: NegotiatedCostPolicy = DEFAULT_NEGOTIATED_COST_POLICY,
    exact_checker: ExactRouteChecker | None = None,
) -> NegotiatedBoardRouteResult:
    """Route all selected nets with whole-net negotiated rip-up and replacement."""
    _require_non_negative_int(max_passes, "max_passes")
    _require_non_negative_int(max_expansions, "max_expansions")
    _require_non_negative_int(max_expansions_per_net, "max_expansions_per_net")
    _require_non_negative_int(max_stagnant_passes, "max_stagnant_passes")
    if not math.isfinite(default_width_mm) or default_width_mm <= 0:
        raise ValueError("default_width_mm must be finite and positive")
    if not math.isfinite(grid_mm) or grid_mm <= 0:
        raise ValueError("grid_mm must be finite and positive")

    widths = dict(net_widths or {})
    if any(not math.isfinite(value) or value <= 0 for value in widths.values()):
        raise ValueError("net widths must be finite and positive")
    guides = dict(soft_guides or {})
    if any(not net_name for net_name in guides):
        raise ValueError("soft guide net names must be non-empty")
    prefixes = dict(route_prefixes or {})
    for net_name, prefix in prefixes.items():
        if not net_name or prefix.net_name != net_name:
            raise ValueError("route prefix mapping keys must match their prefix nets")
    order = _baseline_order(layout, netlist, profile, target_nets, net_order)
    unknown_prefix_nets = tuple(sorted(set(prefixes) - set(order)))
    if unknown_prefix_nets:
        raise ValueError(
            f"route prefixes reference nets outside the computed route order: {unknown_prefix_nets}"
        )
    static_layout = _strip_target_routes(layout, frozenset(order))
    pairwise_domains = build_route_pairwise_clearance_domains(profile, clearance_groups)
    budget = RoutingBudget(
        max_passes=max_passes,
        max_expansions=max_expansions,
        max_expansions_per_net=max_expansions_per_net,
        max_stagnant_passes=max_stagnant_passes,
        max_exact_check_rejections=0,
    )
    ledger = OccupancyLedger()
    history: dict[RoutingResourceKey, int] = {}
    routes: dict[str, NegotiatedGridRoute] = {}
    passes: list[RoutingPassTelemetry] = []
    total_expansions = 0
    present_factor = cost_policy.present_factor_units

    def materialize() -> tuple[BoardLayout, tuple[RouteResult, ...]]:
        results = tuple(routes[name].result for name in order if name in routes)
        return _materialize_routes(static_layout, results), results

    def materialized_prefix_bindings() -> tuple[AppliedRoutePrefixBinding, ...]:
        return tuple(
            AppliedRoutePrefixBinding(
                net_name=name,
                alternative_id=route.prefix_alternative_id,
                prefix_fingerprint=route.prefix_fingerprint,
            )
            for name in sorted(routes)
            if (route := routes[name]).prefix_alternative_id is not None
            and route.prefix_fingerprint is not None
        )

    def finish(
        reason: RoutingFailureReason | None,
        unresolved: Sequence[str],
    ) -> NegotiatedBoardRouteResult:
        unresolved_names = tuple(dict.fromkeys(unresolved))
        overuse = ledger.overuse()
        algorithmic_success = reason is None and not unresolved_names and not overuse
        final_layout, final_results = materialize()
        exact_check: ExactRouteCheckResult | None = None
        exact_evidence: ExactRouteCheckEvidence | None = None
        checked_netlist: BoardNetlist | None = None
        if algorithmic_success and exact_checker is not None:
            exact_check, exact_evidence, checked_netlist = _invoke_exact_checker(
                exact_checker,
                final_layout,
                netlist,
            )
        run_result = RoutingRunResult(
            producer="pcbsmith.kicad.negotiated_board",
            budget=budget,
            success=algorithmic_success,
            exact_check_accepted=(exact_check.accepted if exact_check is not None else None),
            failure_reason=reason,
            route_order=order,
            unresolved_net_names=unresolved_names,
            restart_count=max(0, len(passes) - 1),
            passes=tuple(passes),
            resource_overuse=overuse,
        )
        return NegotiatedBoardRouteResult(
            layout=final_layout,
            results=final_results,
            order=order,
            run_result=run_result,
            exact_check=exact_check,
            prefix_bindings=materialized_prefix_bindings(),
            exact_check_evidence=exact_evidence,
            checked_netlist=checked_netlist,
        )

    if not order:
        return finish(None, ())
    if max_passes == 0:
        return finish(RoutingFailureReason.PASS_BUDGET, order)

    initial_telemetry: list[NetRoutingTelemetry] = []
    for attempt_index, net_name in enumerate(order):
        remaining = max_expansions - total_expansions
        try:
            route = _search_candidate(
                static_layout,
                netlist,
                net_name,
                ledger,
                history,
                present_factor,
                cost_policy,
                widths.get(net_name, default_width_mm),
                grid_mm,
                profile,
                clearance_groups,
                pairwise_domains,
                min(max_expansions_per_net, remaining),
                guides.get(net_name),
                prefixes.get(net_name),
            )
        except RoutingError as error:
            total_expansions += error.expansion_count
            initial_telemetry.append(_failed_net_telemetry(net_name, 0, attempt_index, error))
            unresolved = order[attempt_index:]
            passes.append(
                _pass_telemetry(
                    0,
                    initial_telemetry,
                    unresolved,
                    ledger.overuse(),
                    stagnant=False,
                )
            )
            return finish(error.reason, unresolved)
        total_expansions += route.result.expansion_count
        _require_candidate_owner(route, net_name)
        ledger.commit(route.claims)
        routes[net_name] = route
        initial_telemetry.append(
            _successful_net_telemetry(net_name, 0, attempt_index, route.result)
        )

    overuse = ledger.overuse()
    _update_history(history, overuse, ledger, cost_policy)
    passes.append(_pass_telemetry(0, initial_telemetry, (), overuse, stagnant=False))
    if not overuse:
        return finish(None, ())
    if max_stagnant_passes == 0:
        return finish(RoutingFailureReason.OVERUSE_REMAINING, ())
    if len(passes) >= max_passes:
        return finish(RoutingFailureReason.PASS_BUDGET, ())

    best_objective = _objective((), overuse)
    stagnant_count = 0
    baseline_rank = {net_name: index for index, net_name in enumerate(order)}
    while len(passes) < max_passes:
        present_factor = _grow_present_factor(present_factor, cost_policy)
        reroute_order = _reroute_order(overuse, order, baseline_rank)
        pass_index = len(passes)
        telemetry: list[NetRoutingTelemetry] = []
        for attempt_index, net_name in enumerate(reroute_order):
            old_claims = ledger.rip_up(net_name)
            old_route = routes[net_name]
            remaining = max_expansions - total_expansions
            try:
                route = _search_candidate(
                    static_layout,
                    netlist,
                    net_name,
                    ledger,
                    history,
                    present_factor,
                    cost_policy,
                    widths.get(net_name, default_width_mm),
                    grid_mm,
                    profile,
                    clearance_groups,
                    pairwise_domains,
                    min(max_expansions_per_net, remaining),
                    guides.get(net_name),
                    prefixes.get(net_name),
                )
                _require_candidate_owner(route, net_name)
            except RoutingError as error:
                ledger.restore(old_claims)
                routes[net_name] = old_route
                total_expansions += error.expansion_count
                telemetry.append(
                    _failed_net_telemetry(
                        net_name,
                        pass_index,
                        attempt_index,
                        error,
                    )
                )
                passes.append(
                    _pass_telemetry(
                        pass_index,
                        telemetry,
                        (),
                        ledger.overuse(),
                        stagnant=False,
                    )
                )
                return finish(error.reason, ())
            except Exception:
                ledger.restore(old_claims)
                routes[net_name] = old_route
                raise
            total_expansions += route.result.expansion_count
            ledger.commit(route.claims)
            routes[net_name] = route
            telemetry.append(
                _successful_net_telemetry(
                    net_name,
                    pass_index,
                    attempt_index,
                    route.result,
                )
            )

        overuse = ledger.overuse()
        objective = _objective((), overuse)
        stagnant = objective >= best_objective
        if stagnant:
            stagnant_count += 1
        else:
            best_objective = objective
            stagnant_count = 0
        _update_history(history, overuse, ledger, cost_policy)
        passes.append(_pass_telemetry(pass_index, telemetry, (), overuse, stagnant=stagnant))
        if not overuse:
            return finish(None, ())
        if stagnant and stagnant_count >= max_stagnant_passes:
            return finish(RoutingFailureReason.STAGNATION, ())

    return finish(RoutingFailureReason.PASS_BUDGET, ())


def _require_non_negative_int(value: int, field: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")


def _baseline_order(
    layout: BoardLayout,
    netlist: BoardNetlist,
    profile: PcbRuleProfile,
    target_nets: Collection[str] | None,
    net_order: Sequence[str] | None,
) -> tuple[str, ...]:
    estimates = _routable_nets(layout, netlist, profile)
    if target_nets is not None:
        selected = set(target_nets)
        estimates = {name: estimate for name, estimate in estimates.items() if name in selected}
    explicit = tuple(dict.fromkeys(net_order or ()))
    ordered = tuple(name for name in explicit if name in estimates)
    remaining = tuple(
        sorted(
            (name for name in estimates if name not in set(ordered)),
            key=lambda name: (estimates[name], name),
        )
    )
    return (*ordered, *remaining)


def _strip_target_routes(layout: BoardLayout, targets: frozenset[str]) -> BoardLayout:
    fields = {name: getattr(layout, name) for name in layout.__dataclass_fields__}
    fields["segments"] = tuple(item for item in layout.segments if item.net_name not in targets)
    fields["vias"] = tuple(item for item in layout.vias if item.net_name not in targets)
    return layout.__class__(**fields)


def _materialize_routes(
    static_layout: BoardLayout,
    results: Sequence[RouteResult],
) -> BoardLayout:
    fields = {name: getattr(static_layout, name) for name in static_layout.__dataclass_fields__}
    fields["segments"] = (
        *static_layout.segments,
        *(segment for result in results for segment in result.segments),
    )
    fields["vias"] = (
        *static_layout.vias,
        *(via for result in results for via in result.vias),
    )
    return static_layout.__class__(**fields)


def _search_candidate(
    static_layout: BoardLayout,
    netlist: BoardNetlist,
    net_name: str,
    ledger: OccupancyLedger,
    history: Mapping[RoutingResourceKey, int],
    present_factor: int,
    cost_policy: NegotiatedCostPolicy,
    width_mm: float,
    grid_mm: float,
    profile: PcbRuleProfile,
    clearance_groups: Sequence[ClearanceGroupInput],
    pairwise_domains: tuple[PairwiseClearanceDomain, ...],
    expansion_cap: int,
    soft_guide: GridSoftGuide | None,
    route_prefix: GridRoutePrefix | None,
) -> NegotiatedGridRoute:
    return route_net_negotiated_candidate(
        static_layout,
        netlist,
        net_name,
        ledger,
        history,
        present_factor,
        cost_policy,
        track_width_mm=width_mm,
        grid_mm=grid_mm,
        profile=profile,
        clearance_groups=clearance_groups,
        pairwise_domains=pairwise_domains,
        max_expansions=expansion_cap,
        soft_guide=soft_guide,
        route_prefix=route_prefix,
    )


def _require_candidate_owner(route: NegotiatedGridRoute, net_name: str) -> None:
    if route.result.net_name != net_name or route.claims.net_name != net_name:
        raise ValueError("negotiated candidate must belong to the requested net")


def _successful_net_telemetry(
    net_name: str,
    pass_index: int,
    attempt_index: int,
    result: RouteResult,
) -> NetRoutingTelemetry:
    return NetRoutingTelemetry(
        net_name=net_name,
        pass_index=pass_index,
        attempt_index=attempt_index,
        expansion_count=result.expansion_count,
        segment_count=len(result.segments),
        via_count=len(result.vias),
        length_mm=result.length_mm,
        routed=True,
        exact_check_accepted=None,
    )


def _failed_net_telemetry(
    net_name: str,
    pass_index: int,
    attempt_index: int,
    error: RoutingError,
) -> NetRoutingTelemetry:
    return NetRoutingTelemetry(
        net_name=net_name,
        pass_index=pass_index,
        attempt_index=attempt_index,
        expansion_count=error.expansion_count,
        routed=False,
        failure_reason=error.reason,
        exact_check_accepted=None,
    )


def _pass_telemetry(
    pass_index: int,
    telemetry: Sequence[NetRoutingTelemetry],
    unresolved: Sequence[str],
    overuse: tuple[ResourceOveruseSummary, ...],
    *,
    stagnant: bool,
) -> RoutingPassTelemetry:
    return RoutingPassTelemetry(
        pass_index=pass_index,
        net_telemetry=tuple(telemetry),
        unresolved_net_names=tuple(dict.fromkeys(unresolved)),
        resource_overuse=overuse,
        expansion_count=sum(item.expansion_count for item in telemetry),
        exact_check_rejection_count=0,
        stagnant=stagnant,
    )


def _objective(
    unresolved: Sequence[str],
    overuse: tuple[ResourceOveruseSummary, ...],
) -> tuple[int, int, int, int]:
    values = tuple(item.overuse_units for item in overuse)
    return (len(set(unresolved)), sum(values), len(values), max(values, default=0))


def _update_history(
    history: dict[RoutingResourceKey, int],
    overuse: tuple[ResourceOveruseSummary, ...],
    ledger: OccupancyLedger,
    policy: NegotiatedCostPolicy,
) -> None:
    resources = {
        resource.resource_id: resource
        for claims in ledger.committed_claims()
        for resource in claims.resources
    }
    for item in overuse:
        resource = resources[item.resource_id]
        history[resource] = history.get(resource, 0) + (
            policy.history_increment_units * item.overuse_units
        )


def _reroute_order(
    overuse: tuple[ResourceOveruseSummary, ...],
    baseline_order: tuple[str, ...],
    rank: Mapping[str, int],
) -> tuple[str, ...]:
    touched = {net_name: 0 for net_name in baseline_order}
    for item in overuse:
        for net_name in item.net_names:
            touched[net_name] += item.overuse_units
    return tuple(
        sorted(
            baseline_order,
            key=lambda net_name: (-touched[net_name], rank[net_name], net_name),
        )
    )


def _grow_present_factor(current: int, policy: NegotiatedCostPolicy) -> int:
    numerator = current * policy.present_growth_numerator
    return (numerator + policy.present_growth_denominator - 1) // (
        policy.present_growth_denominator
    )
