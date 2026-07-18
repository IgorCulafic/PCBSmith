"""One-shot exact-checked atomic commit for a complete certified bus bundle.

R4.2c3 deliberately performs no retries or scheduling.  It snapshots the full
coordinator state, invokes one pure R4.2c2 candidate build, provisionally
installs a zero-overuse complete bundle, materializes once, and invokes at most
one exact checker.  Only an accepting exact report retains provisional state.
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import replace
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.bus_allocator import BusLaneAllocationResult
from pcbsmith.bus_ir import BusGroup
from pcbsmith.kicad.board import BoardLayout, BoardNetlist
from pcbsmith.kicad.board_serialization import (
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.kicad.bus_candidate import BusCandidateResult
from pcbsmith.kicad.bus_transaction import (
    BusRouteBundle,
    bus_route_map_fingerprint,
)
from pcbsmith.kicad.negotiated_board import (
    ExactRouteChecker,
    ExactRouteCheckEvidence,
    ExactRouteCheckResult,
)
from pcbsmith.kicad.negotiated_grid import NegotiatedGridRoute
from pcbsmith.kicad.negotiated_resources import NetResourceClaims, OccupancyLedger
from pcbsmith.routing_ir import RoutingIrModel

BusCandidateBuilder = Callable[[OccupancyLedger], BusCandidateResult]
BusRouteMapMaterializer = Callable[
    [BoardLayout, Mapping[str, NegotiatedGridRoute]],
    BoardLayout,
]


def _fingerprint(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
    return value


def exact_route_check_fingerprint(report: ExactRouteCheckResult | None) -> str | None:
    """Canonical exact-report identity shared by result and telemetry."""

    if report is None:
        return None
    return _fingerprint(
        {
            "accepted": report.accepted,
            "checker_id": report.checker_id,
            "finding_fingerprints": report.finding_fingerprints,
        }
    )


class BusExactDisposition(StrEnum):
    """Why provisional state was retained or rolled back."""

    CANDIDATE_FAILED = "candidate_failed"
    CANDIDATE_INVALID = "candidate_invalid"
    CHECKER_MISSING = "checker_missing"
    REJECTED = "rejected"
    ACCEPTED = "accepted"


class BusCheckedCommitTelemetry(RoutingIrModel):
    """Full-state fingerprints and bounded callback counts for one attempt."""

    schema_id: Literal["pcbsmith-bus-checked-commit-telemetry"] = (
        "pcbsmith-bus-checked-commit-telemetry"
    )
    schema_version: Literal[1] = 1
    bus_id: str = Field(min_length=1)
    bus_fingerprint: str
    allocation_fingerprint: str
    exact_disposition: BusExactDisposition
    candidate_call_count: Literal[1] = 1
    materialization_call_count: Literal[0, 1]
    exact_check_call_count: Literal[0, 1]
    candidate_result_fingerprint: str
    exact_report_fingerprint: str | None = None
    ledger_before_fingerprint: str
    ledger_after_fingerprint: str
    route_map_before_fingerprint: str
    route_map_after_fingerprint: str

    @field_validator(
        "bus_fingerprint",
        "allocation_fingerprint",
        "candidate_result_fingerprint",
        "exact_report_fingerprint",
        "ledger_before_fingerprint",
        "ledger_after_fingerprint",
        "route_map_before_fingerprint",
        "route_map_after_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str | None, info: Any) -> str | None:
        return None if value is None else _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def telemetry_is_coherent(self) -> Self:
        checked = self.exact_disposition in {
            BusExactDisposition.ACCEPTED,
            BusExactDisposition.REJECTED,
        }
        if self.materialization_call_count != int(checked):
            raise ValueError("materialization count must match the exact disposition")
        if self.exact_check_call_count != int(checked):
            raise ValueError("exact-check count must match the exact disposition")
        if (self.exact_report_fingerprint is not None) != checked:
            raise ValueError("exact report fingerprint must be present exactly when checked")
        if self.exact_disposition is not BusExactDisposition.ACCEPTED:
            if self.ledger_before_fingerprint != self.ledger_after_fingerprint:
                raise ValueError("uncommitted checked attempt must restore the full ledger")
            if self.route_map_before_fingerprint != self.route_map_after_fingerprint:
                raise ValueError("uncommitted checked attempt must restore the full route map")
        return self


class BusCheckedCommitResult(RoutingIrModel):
    """Checked commit outcome with algorithmic and exact authority separated."""

    schema_id: Literal["pcbsmith-bus-checked-commit-result"] = "pcbsmith-bus-checked-commit-result"
    schema_version: Literal[2] = 2
    algorithmic_success: bool
    exact_disposition: BusExactDisposition
    exact_report: ExactRouteCheckResult | None = None
    materialized_layout: BoardLayout | None = None
    checked_netlist: BoardNetlist | None = None
    exact_check_evidence: ExactRouteCheckEvidence | None = None
    committed: bool
    candidate_result: BusCandidateResult
    telemetry: BusCheckedCommitTelemetry

    @property
    def accepted(self) -> bool:
        """True only for a zero-overuse candidate retained after exact acceptance."""

        return (
            self.algorithmic_success
            and self.exact_disposition is BusExactDisposition.ACCEPTED
            and self.exact_report is not None
            and self.exact_report.accepted
            and self.committed
        )

    @model_validator(mode="after")
    def outcome_is_coherent(self) -> Self:
        if self.telemetry.exact_disposition is not self.exact_disposition:
            raise ValueError("result and telemetry exact dispositions must match")
        if self.telemetry.candidate_result_fingerprint != (
            self.candidate_result.semantic_fingerprint()
        ):
            raise ValueError("telemetry candidate fingerprint is stale")
        if self.telemetry.exact_report_fingerprint != exact_route_check_fingerprint(
            self.exact_report
        ):
            raise ValueError("telemetry exact report fingerprint is stale")
        if self.committed != (self.exact_disposition is BusExactDisposition.ACCEPTED):
            raise ValueError("only an exact-accepted attempt may remain committed")
        checked = self.exact_disposition in {
            BusExactDisposition.ACCEPTED,
            BusExactDisposition.REJECTED,
        }
        retained = (
            self.materialized_layout,
            self.checked_netlist,
            self.exact_check_evidence,
        )
        if checked != all(item is not None for item in retained):
            raise ValueError(
                "materialized layout, checked netlist, and exact evidence "
                "must be retained exactly when checked"
            )
        if any(item is not None for item in retained) and not checked:
            raise ValueError("unchecked outcomes cannot retain exact-check inputs or evidence")
        if self.exact_disposition is BusExactDisposition.ACCEPTED:
            if self.exact_report is None or not self.exact_report.accepted:
                raise ValueError("accepted disposition requires an accepting exact report")
        elif self.exact_disposition is BusExactDisposition.REJECTED:
            if self.exact_report is None or self.exact_report.accepted:
                raise ValueError("rejected disposition requires a rejecting exact report")
        elif self.exact_report is not None:
            raise ValueError("an exact report is valid only when the checker ran")
        if self.exact_disposition in {
            BusExactDisposition.ACCEPTED,
            BusExactDisposition.REJECTED,
            BusExactDisposition.CHECKER_MISSING,
        }:
            if not self.algorithmic_success:
                raise ValueError("post-candidate exact dispositions require algorithmic success")
        elif self.algorithmic_success:
            raise ValueError("failed or invalid candidates cannot claim algorithmic success")
        if checked:
            assert self.exact_report is not None
            assert self.materialized_layout is not None
            assert self.checked_netlist is not None
            assert self.exact_check_evidence is not None
            try:
                canonical_report = ExactRouteCheckResult(
                    accepted=self.exact_report.accepted,
                    checker_id=self.exact_report.checker_id,
                    finding_fingerprints=tuple(self.exact_report.finding_fingerprints),
                )
                canonical_evidence = ExactRouteCheckEvidence(
                    materialized_layout_fingerprint=(
                        self.exact_check_evidence.materialized_layout_fingerprint
                    ),
                    checked_netlist_fingerprint=(
                        self.exact_check_evidence.checked_netlist_fingerprint
                    ),
                    checker_id=self.exact_check_evidence.checker_id,
                    finding_identities=tuple(self.exact_check_evidence.finding_identities),
                    finding_identities_fingerprint=(
                        self.exact_check_evidence.finding_identities_fingerprint
                    ),
                    report_fingerprint=self.exact_check_evidence.report_fingerprint,
                    call_input_fingerprint=self.exact_check_evidence.call_input_fingerprint,
                    accepted=self.exact_check_evidence.accepted,
                    schema_id=self.exact_check_evidence.schema_id,
                    schema_version=self.exact_check_evidence.schema_version,
                )
            except (AttributeError, TypeError, ValueError) as error:
                raise ValueError("retained exact-check authority is invalid") from error
            if canonical_report != self.exact_report:
                raise ValueError("retained exact report is not canonical")
            if canonical_evidence != self.exact_check_evidence:
                raise ValueError("retained exact evidence is not canonical")
            expected_evidence = ExactRouteCheckEvidence.from_exact_check(
                self.materialized_layout,
                self.checked_netlist,
                canonical_report,
            )
            if canonical_evidence != expected_evidence:
                raise ValueError(
                    "retained exact evidence does not bind the report, layout, and netlist"
                )
        return self

    def semantic_json(self) -> str:
        """Serialize the nested c2 result by its canonical semantic fingerprint."""

        payload = self.model_dump(mode="json", exclude={"candidate_result"})
        payload["candidate_result_fingerprint"] = self.candidate_result.semantic_fingerprint()
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )


class BusCheckedCallbackMutationError(RuntimeError):
    """A supposedly read-only callback changed coordinator-owned state."""


class BusCheckedMaterializationMismatchError(RuntimeError):
    """The supplied materializer omitted or altered canonical mixed copper."""


class BusCheckedRollbackError(RuntimeError):
    """Rollback itself failed; preserve both errors and any exact report."""

    def __init__(
        self,
        original_error: Exception,
        rollback_error: Exception,
        exact_report: ExactRouteCheckResult | None,
    ) -> None:
        super().__init__(f"checked bus rollback failed after {type(original_error).__name__}")
        self.original_error = original_error
        self.rollback_error = rollback_error
        self.exact_report = exact_report


def _require_unchanged_board_inputs(
    *,
    callback_name: str,
    layouts: tuple[tuple[str, BoardLayout, str], ...],
    netlists: tuple[tuple[str, BoardNetlist, str], ...],
) -> None:
    """Compare complete neutral-schema snapshots after an untrusted callback."""

    mutations: list[str] = []
    snapshot_errors: list[Exception] = []
    for label, layout, before in layouts:
        try:
            after = canonical_board_layout_snapshot_json(layout)
        except Exception as error:
            mutations.append(label)
            snapshot_errors.append(error)
        else:
            if after != before:
                mutations.append(label)
    for label, netlist, before in netlists:
        try:
            after = canonical_board_netlist_snapshot_json(netlist)
        except Exception as error:
            mutations.append(label)
            snapshot_errors.append(error)
        else:
            if after != before:
                mutations.append(label)
    if mutations:
        cause = snapshot_errors[0] if snapshot_errors else None
        raise BusCheckedCallbackMutationError(
            f"{callback_name} mutated bound board input(s): {tuple(mutations)!r}"
        ) from cause


def _invoke_detached_exact_checker(
    checker: ExactRouteChecker,
    materialized_layout: BoardLayout,
    netlist: BoardNetlist,
    *,
    caller_layout: BoardLayout,
    caller_layout_before: str,
    caller_netlist_before: str,
) -> tuple[
    ExactRouteCheckResult,
    ExactRouteCheckEvidence,
    BoardLayout,
    BoardNetlist,
]:
    """Invoke one exact checker on detached inputs and bind its complete authority."""

    checker_layout = copy.deepcopy(materialized_layout)
    checker_netlist = copy.deepcopy(netlist)
    checker_layout_before = canonical_board_layout_snapshot_json(checker_layout)
    checker_netlist_before = canonical_board_netlist_snapshot_json(checker_netlist)
    if checker_layout_before != canonical_board_layout_snapshot_json(materialized_layout):
        raise ValueError("exact checker layout copy does not match the materialized input")
    if checker_netlist_before != caller_netlist_before:
        raise ValueError("exact checker netlist copy does not match the caller input")

    raw_report: object | None = None
    checker_error: Exception | None = None
    try:
        raw_report = checker(checker_layout, checker_netlist)
    except Exception as error:
        checker_error = error

    _require_unchanged_board_inputs(
        callback_name="exact checker",
        layouts=(
            ("detached checker layout", checker_layout, checker_layout_before),
            ("caller layout", caller_layout, caller_layout_before),
        ),
        netlists=(
            ("detached checker netlist", checker_netlist, checker_netlist_before),
            ("caller netlist", netlist, caller_netlist_before),
        ),
    )
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
    retained_layout = copy.deepcopy(checker_layout)
    retained_netlist = copy.deepcopy(checker_netlist)
    evidence = ExactRouteCheckEvidence.from_exact_check(
        retained_layout,
        retained_netlist,
        report,
    )
    return report, evidence, retained_layout, retained_netlist


def materialize_complete_route_map(
    static_layout: BoardLayout,
    routes_by_net: Mapping[str, NegotiatedGridRoute],
) -> BoardLayout:
    """Losslessly append one complete mixed route map to a static layout."""

    route_nets = frozenset(routes_by_net)
    if any(segment.net_name in route_nets for segment in static_layout.segments) or any(
        via.net_name in route_nets for via in static_layout.vias
    ):
        raise ValueError("static layout already contains materialized route-map copper")
    ordered_routes: list[NegotiatedGridRoute] = []
    for net_name in sorted(routes_by_net):
        route = routes_by_net[net_name]
        if route.result.net_name != net_name or route.claims.net_name != net_name:
            raise ValueError("route-map keys must match route and claim ownership")
        ordered_routes.append(route)
    return replace(
        static_layout,
        segments=(
            *static_layout.segments,
            *(segment for route in ordered_routes for segment in route.result.segments),
        ),
        vias=(
            *static_layout.vias,
            *(via for route in ordered_routes for via in route.result.vias),
        ),
    )


class BusCheckedCommitCoordinator:
    """Replace and exact-check one bus as a full ledger/map transaction.

    R4.2c3 is replacement-only: the coordinator must already own exactly one
    complete route for every bus member. Initial installation remains outside
    this bounded slice.
    """

    def __init__(
        self,
        ledger: OccupancyLedger,
        routes_by_net: MutableMapping[str, NegotiatedGridRoute],
    ) -> None:
        self.ledger = ledger
        self.routes_by_net = routes_by_net
        self.last_result: BusCheckedCommitResult | None = None

    def commit(
        self,
        static_layout: BoardLayout,
        netlist: BoardNetlist,
        bus: BusGroup,
        allocation: BusLaneAllocationResult,
        candidate_builder: BusCandidateBuilder,
        *,
        exact_checker: ExactRouteChecker | None,
        materializer: BusRouteMapMaterializer = materialize_complete_route_map,
    ) -> BusCheckedCommitResult:
        """Replace an existing complete bus with one checked candidate once."""

        self.last_result = None
        caller_layout_before = canonical_board_layout_snapshot_json(static_layout)
        caller_netlist_before = canonical_board_netlist_snapshot_json(netlist)
        old_bundle = self._current_bundle(bus, allocation)
        for net_name, route in old_bundle.by_net().items():
            if self.ledger.claims_for(net_name) != route.claims:
                raise ValueError("ledger claims must equal every current bus member route claim")

        snapshot_claims = self.ledger.committed_claims()
        snapshot_routes = dict(self.routes_by_net)
        ledger_before = self.ledger.semantic_fingerprint()
        route_map_before = bus_route_map_fingerprint(self.routes_by_net)
        member_nets = tuple(sorted(member.net_name for member in bus.members))
        for net_name in member_nets:
            self.ledger.rip_up(net_name)
            del self.routes_by_net[net_name]
        stripped_ledger = self.ledger.semantic_fingerprint()
        stripped_route_map = bus_route_map_fingerprint(self.routes_by_net)

        exact_report: ExactRouteCheckResult | None = None
        exact_evidence: ExactRouteCheckEvidence | None = None
        retained_layout: BoardLayout | None = None
        retained_netlist: BoardNetlist | None = None
        try:
            candidate = candidate_builder(self.ledger)
            self._require_callback_state(stripped_ledger, stripped_route_map, "candidate builder")
        except Exception as error:
            self._restore_or_raise(error, snapshot_claims, snapshot_routes, exact_report)

        if not isinstance(candidate, BusCandidateResult):
            error = TypeError("candidate builder must return BusCandidateResult")
            self._restore_or_raise(error, snapshot_claims, snapshot_routes, exact_report)
        try:
            candidate = BusCandidateResult.model_validate_json(candidate.model_dump_json())
        except (TypeError, ValueError) as error:
            self._restore_or_raise(error, snapshot_claims, snapshot_routes, exact_report)
        candidate_fingerprint = candidate.semantic_fingerprint()

        if not self._candidate_binding_is_valid(candidate, bus, allocation):
            self._restore_for_result(snapshot_claims, snapshot_routes, exact_report)
            return self._record_result(
                bus,
                allocation,
                candidate,
                algorithmic_success=False,
                disposition=BusExactDisposition.CANDIDATE_INVALID,
                exact_report=None,
                committed=False,
                materialization_calls=0,
                exact_check_calls=0,
                candidate_fingerprint=candidate_fingerprint,
                ledger_before=ledger_before,
                route_map_before=route_map_before,
            )

        if not candidate.success or not candidate.zero_overuse or candidate.bundle is None:
            self._restore_for_result(snapshot_claims, snapshot_routes, exact_report)
            return self._record_result(
                bus,
                allocation,
                candidate,
                algorithmic_success=False,
                disposition=BusExactDisposition.CANDIDATE_FAILED,
                exact_report=None,
                committed=False,
                materialization_calls=0,
                exact_check_calls=0,
                candidate_fingerprint=candidate_fingerprint,
                ledger_before=ledger_before,
                route_map_before=route_map_before,
            )

        for route in candidate.bundle.member_routes:
            self.ledger.commit(route.claims)
            self.routes_by_net[route.result.net_name] = route
        if self.ledger.overuse():
            self._restore_for_result(snapshot_claims, snapshot_routes, exact_report)
            return self._record_result(
                bus,
                allocation,
                candidate,
                algorithmic_success=False,
                disposition=BusExactDisposition.CANDIDATE_INVALID,
                exact_report=None,
                committed=False,
                materialization_calls=0,
                exact_check_calls=0,
                candidate_fingerprint=candidate_fingerprint,
                ledger_before=ledger_before,
                route_map_before=route_map_before,
            )

        provisional_ledger = self.ledger.semantic_fingerprint()
        provisional_route_map = bus_route_map_fingerprint(self.routes_by_net)
        if exact_checker is None:
            self._restore_for_result(snapshot_claims, snapshot_routes, exact_report)
            return self._record_result(
                bus,
                allocation,
                candidate,
                algorithmic_success=True,
                disposition=BusExactDisposition.CHECKER_MISSING,
                exact_report=None,
                committed=False,
                materialization_calls=0,
                exact_check_calls=0,
                candidate_fingerprint=candidate_fingerprint,
                ledger_before=ledger_before,
                route_map_before=route_map_before,
            )

        try:
            materializer_layout = copy.deepcopy(static_layout)
            materializer_routes = copy.deepcopy(dict(self.routes_by_net))
            materializer_layout_before = canonical_board_layout_snapshot_json(
                materializer_layout
            )
            materializer_routes_before = bus_route_map_fingerprint(materializer_routes)
            if materializer_layout_before != caller_layout_before:
                raise ValueError("materializer layout copy does not match the caller input")
            if materializer_routes_before != provisional_route_map:
                raise ValueError("materializer route-map copy does not match provisional state")
            raw_mixed_layout: object | None = None
            materializer_error: Exception | None = None
            try:
                raw_mixed_layout = materializer(
                    materializer_layout,
                    MappingProxyType(materializer_routes),
                )
            except Exception as error:
                materializer_error = error
            _require_unchanged_board_inputs(
                callback_name="route-map materializer",
                layouts=(
                    (
                        "detached materializer layout",
                        materializer_layout,
                        materializer_layout_before,
                    ),
                    ("caller layout", static_layout, caller_layout_before),
                ),
                netlists=(("caller netlist", netlist, caller_netlist_before),),
            )
            try:
                materializer_routes_after = bus_route_map_fingerprint(materializer_routes)
            except Exception as error:
                raise BusCheckedCallbackMutationError(
                    "route-map materializer mutated its detached route-map input"
                ) from error
            if materializer_routes_after != materializer_routes_before:
                raise BusCheckedCallbackMutationError(
                    "route-map materializer mutated its detached route-map input"
                )
            self._require_callback_state(
                provisional_ledger,
                provisional_route_map,
                "route-map materializer",
            )
            if materializer_error is not None:
                raise materializer_error
            if not isinstance(raw_mixed_layout, BoardLayout):
                raise TypeError("route-map materializer must return BoardLayout")
            mixed_layout = raw_mixed_layout
            canonical_layout = materialize_complete_route_map(
                static_layout,
                MappingProxyType(dict(self.routes_by_net)),
            )
            mixed_snapshot = canonical_board_layout_snapshot_json(mixed_layout)
            canonical_snapshot = canonical_board_layout_snapshot_json(canonical_layout)
            if mixed_snapshot != canonical_snapshot:
                raise BusCheckedMaterializationMismatchError(
                    "route-map materializer did not return the exact complete mixed layout"
                )
            (
                exact_report,
                exact_evidence,
                retained_layout,
                retained_netlist,
            ) = _invoke_detached_exact_checker(
                exact_checker,
                mixed_layout,
                netlist,
                caller_layout=static_layout,
                caller_layout_before=caller_layout_before,
                caller_netlist_before=caller_netlist_before,
            )
            self._require_callback_state(
                provisional_ledger,
                provisional_route_map,
                "exact checker",
            )
        except Exception as error:
            self._restore_or_raise(error, snapshot_claims, snapshot_routes, exact_report)

        assert exact_report is not None
        if not exact_report.accepted:
            self._restore_for_result(snapshot_claims, snapshot_routes, exact_report)
            return self._record_result(
                bus,
                allocation,
                candidate,
                algorithmic_success=True,
                disposition=BusExactDisposition.REJECTED,
                exact_report=exact_report,
                materialized_layout=retained_layout,
                checked_netlist=retained_netlist,
                exact_check_evidence=exact_evidence,
                committed=False,
                materialization_calls=1,
                exact_check_calls=1,
                candidate_fingerprint=candidate_fingerprint,
                ledger_before=ledger_before,
                route_map_before=route_map_before,
            )

        return self._record_result(
            bus,
            allocation,
            candidate,
            algorithmic_success=True,
            disposition=BusExactDisposition.ACCEPTED,
            exact_report=exact_report,
            materialized_layout=retained_layout,
            checked_netlist=retained_netlist,
            exact_check_evidence=exact_evidence,
            committed=True,
            materialization_calls=1,
            exact_check_calls=1,
            candidate_fingerprint=candidate_fingerprint,
            ledger_before=ledger_before,
            route_map_before=route_map_before,
        )

    def _current_bundle(
        self,
        bus: BusGroup,
        allocation: BusLaneAllocationResult,
    ) -> BusRouteBundle:
        routes: list[NegotiatedGridRoute] = []
        missing: list[str] = []
        for member in bus.members:
            route = self.routes_by_net.get(member.net_name)
            if route is None:
                missing.append(member.net_name)
            else:
                routes.append(route)
        if missing:
            raise ValueError(f"current route map is incomplete for bus nets {tuple(missing)!r}")
        return BusRouteBundle(bus=bus, allocation=allocation, member_routes=tuple(routes))

    @staticmethod
    def _candidate_binding_is_valid(
        candidate: BusCandidateResult,
        bus: BusGroup,
        allocation: BusLaneAllocationResult,
    ) -> bool:
        bundle = candidate.bundle
        if candidate.bus_id != bus.bus_id:
            return False
        if candidate.bus_fingerprint != bus.semantic_fingerprint():
            return False
        if candidate.allocation_fingerprint != allocation.allocation_fingerprint:
            return False
        if candidate.success != (candidate.complete and candidate.zero_overuse):
            return False
        if candidate.success and bundle is None:
            return False
        if bundle is None:
            return True
        return (
            bundle.bus.semantic_fingerprint() == bus.semantic_fingerprint()
            and bundle.allocation.semantic_fingerprint() == allocation.semantic_fingerprint()
        )

    def _require_callback_state(
        self,
        expected_ledger: str,
        expected_route_map: str,
        callback_name: str,
    ) -> None:
        if self.ledger.semantic_fingerprint() != expected_ledger:
            raise BusCheckedCallbackMutationError(
                f"{callback_name} mutated the coordinator occupancy ledger"
            )
        if bus_route_map_fingerprint(self.routes_by_net) != expected_route_map:
            raise BusCheckedCallbackMutationError(
                f"{callback_name} mutated the coordinator route map"
            )

    def _restore_state(
        self,
        claims: tuple[NetResourceClaims, ...],
        routes: Mapping[str, NegotiatedGridRoute],
    ) -> None:
        for current in self.ledger.committed_claims():
            self.ledger.rip_up(current.net_name)
        for claim in claims:
            self.ledger.restore(claim)
        self.routes_by_net.clear()
        self.routes_by_net.update(routes)

    def _restore_or_raise(
        self,
        original_error: Exception,
        claims: tuple[NetResourceClaims, ...],
        routes: Mapping[str, NegotiatedGridRoute],
        exact_report: ExactRouteCheckResult | None,
    ) -> None:
        try:
            self._restore_state(claims, routes)
        except Exception as rollback_error:
            raise BusCheckedRollbackError(
                original_error,
                rollback_error,
                exact_report,
            ) from original_error
        raise original_error

    def _restore_for_result(
        self,
        claims: tuple[NetResourceClaims, ...],
        routes: Mapping[str, NegotiatedGridRoute],
        exact_report: ExactRouteCheckResult | None,
    ) -> None:
        normal_outcome = RuntimeError("checked bus attempt requires rollback")
        try:
            self._restore_state(claims, routes)
        except Exception as rollback_error:
            raise BusCheckedRollbackError(
                normal_outcome,
                rollback_error,
                exact_report,
            ) from normal_outcome

    def _record_result(
        self,
        bus: BusGroup,
        allocation: BusLaneAllocationResult,
        candidate: BusCandidateResult,
        *,
        algorithmic_success: bool,
        disposition: BusExactDisposition,
        exact_report: ExactRouteCheckResult | None,
        materialized_layout: BoardLayout | None = None,
        checked_netlist: BoardNetlist | None = None,
        exact_check_evidence: ExactRouteCheckEvidence | None = None,
        committed: bool,
        materialization_calls: Literal[0, 1],
        exact_check_calls: Literal[0, 1],
        candidate_fingerprint: str,
        ledger_before: str,
        route_map_before: str,
    ) -> BusCheckedCommitResult:
        telemetry = BusCheckedCommitTelemetry(
            bus_id=bus.bus_id,
            bus_fingerprint=bus.semantic_fingerprint(),
            allocation_fingerprint=allocation.allocation_fingerprint,
            exact_disposition=disposition,
            materialization_call_count=materialization_calls,
            exact_check_call_count=exact_check_calls,
            candidate_result_fingerprint=candidate_fingerprint,
            exact_report_fingerprint=exact_route_check_fingerprint(exact_report),
            ledger_before_fingerprint=ledger_before,
            ledger_after_fingerprint=self.ledger.semantic_fingerprint(),
            route_map_before_fingerprint=route_map_before,
            route_map_after_fingerprint=bus_route_map_fingerprint(self.routes_by_net),
        )
        result = BusCheckedCommitResult(
            algorithmic_success=algorithmic_success,
            exact_disposition=disposition,
            exact_report=exact_report,
            materialized_layout=materialized_layout,
            checked_netlist=checked_netlist,
            exact_check_evidence=exact_check_evidence,
            committed=committed,
            candidate_result=candidate,
            telemetry=telemetry,
        )
        self.last_result = result
        return result
