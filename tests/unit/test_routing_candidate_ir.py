from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from pcbsmith.routing_ir import (
    ConstraintConsumption,
    DeterministicRoutingConfiguration,
    PartialCandidateStatus,
    ProtectedRouteObjectPolicy,
    RouteCandidateResult,
    RouteClearanceConstraint,
    RouteConstraintDisposition,
    RouteFailureEvidence,
    RouteFailureKind,
    RouteGuide,
    RouteMutationKind,
    RouteObjectKind,
    RoutePoint,
    RouteRequest,
    RouteSegmentDelta,
    RouteSegmentGeometry,
    RouteTerminationEvidence,
    RouteTerminationState,
    RouteTopologyConstraint,
    RouteViaTechnology,
    RouteWidthConstraint,
    RoutingBudget,
    RoutingEngineIdentity,
    RoutingInputIdentity,
    StableRouteObjectIdentity,
    TargetRouteDomain,
    TargetRouteNet,
    validate_route_candidate_result,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64
SHA_0 = "0" * 64
SHA_1 = "1" * 64
SHA_2 = "2" * 64


def _budget() -> RoutingBudget:
    return RoutingBudget(
        max_passes=4,
        max_expansions=10_000,
        max_expansions_per_net=5_000,
        max_stagnant_passes=2,
        max_exact_check_rejections=0,
    )


def _source_segment(*, protected: bool = False) -> StableRouteObjectIdentity:
    return StableRouteObjectIdentity(
        object_id="route:segment:source-1",
        object_kind=RouteObjectKind.SEGMENT,
        source_board_sha256=SHA_B,
        source_object_fingerprint=SHA_C,
    )


def _request(
    *,
    protected: bool = False,
    additional_constraint_ids: tuple[str, ...] = (),
) -> RouteRequest:
    source = _source_segment(protected=protected)
    return RouteRequest(
        request_id="request:fixture",
        inputs=RoutingInputIdentity(
            project_sha256=SHA_A,
            board_sha256=SHA_B,
            schematic_sha256=SHA_C,
            netlist_sha256=SHA_D,
            placement_sha256=SHA_E,
            outline_sha256=SHA_F,
            holes_sha256=SHA_0,
            rules_sha256=SHA_1,
            protected_copper_sha256=SHA_2,
        ),
        target_domains=(
            TargetRouteDomain(
                domain_id="domain:ordinary",
                nets=(
                    TargetRouteNet(
                        net_name="/SIG",
                        terminal_object_ids=("terminal:U2:1", "terminal:U1:1"),
                    ),
                ),
                priority=10,
            ),
        ),
        source_route_objects=(source,),
        protected_policy=ProtectedRouteObjectPolicy(
            protected_objects=(source,) if protected else (),
        ),
        allowed_layers=("F.Cu", "B.Cu"),
        width_constraints=(
            RouteWidthConstraint(
                constraint_id="constraint:width:signal",
                net_names=("/SIG",),
                minimum_width_mm=0.2,
                preferred_width_mm=0.25,
                maximum_width_mm=0.4,
            ),
        ),
        clearance_constraints=(
            RouteClearanceConstraint(
                constraint_id="constraint:clearance:signal",
                net_names=("/SIG",),
                minimum_clearance_mm=0.2,
            ),
        ),
        via_technologies=(
            RouteViaTechnology(
                constraint_id="constraint:via:through",
                technology_id="via:through-default",
                start_layer="F.Cu",
                end_layer="B.Cu",
                diameter_mm=0.8,
                drill_mm=0.4,
            ),
        ),
        route_guides=(
            RouteGuide(
                constraint_id="constraint:guide:signal",
                guide_id="guide:signal",
                guide_kind="reserved_corridor",
                domain_ids=("domain:ordinary",),
                layers=("F.Cu",),
                points=(RoutePoint(x_mm=1, y_mm=1), RoutePoint(x_mm=5, y_mm=1)),
                half_width_mm=1,
                hard=False,
            ),
        ),
        topology_constraints=(
            RouteTopologyConstraint(
                constraint_id="constraint:topology:signal",
                domain_id="domain:ordinary",
                net_name="/SIG",
                topology_kind="ordered_path",
                ordered_terminal_object_ids=("terminal:U1:1", "terminal:U2:1"),
            ),
        ),
        budget=_budget(),
        deterministic=DeterministicRoutingConfiguration(
            seed=0,
            route_order=("/SIG",),
            tie_break_policy="pcbsmith-lexical-v1",
            adapter_options=(("grid_mm", "0.25"),),
        ),
        additional_constraint_ids=additional_constraint_ids,
    )


def _consumption(
    request: RouteRequest,
    *,
    overrides: dict[str, RouteConstraintDisposition] | None = None,
) -> tuple[ConstraintConsumption, ...]:
    changed = overrides or {}
    return tuple(
        ConstraintConsumption(
            constraint_id=constraint_id,
            disposition=changed.get(
                constraint_id,
                RouteConstraintDisposition.CONSUMED,
            ),
            detail=f"fixture classification for {constraint_id}",
        )
        for constraint_id in request.constraint_ids
    )


def _engine() -> RoutingEngineIdentity:
    return RoutingEngineIdentity(
        engine_id="pcbsmith-native-astar",
        engine_version="1",
        adapter_id="pcbsmith.routing.native",
        adapter_version="1",
        source_commit="fixture",
    )


def _termination(
    state: RouteTerminationState = RouteTerminationState.COMPLETED,
) -> RouteTerminationEvidence:
    return RouteTerminationEvidence(
        state=state,
        reason="fixture termination",
        exit_code=0,
        stdout_sha256=SHA_A,
        stderr_sha256=SHA_B,
        elapsed_seconds=1.25,
        exhausted_budget_fields=(
            ("max_expansions",)
            if state is RouteTerminationState.BUDGET_EXHAUSTED
            else ()
        ),
    )


def _added_segment() -> RouteSegmentDelta:
    return RouteSegmentDelta(
        mutation_id="mutation:segment:add:1",
        operation=RouteMutationKind.ADD,
        object_id="route:segment:candidate-1",
        after=RouteSegmentGeometry(
            net_name="/SIG",
            start=RoutePoint(x_mm=1, y_mm=1),
            end=RoutePoint(x_mm=5, y_mm=1),
            layer="F.Cu",
            width_mm=0.25,
        ),
    )


def _complete_candidate(request: RouteRequest) -> RouteCandidateResult:
    return RouteCandidateResult(
        request_fingerprint=request.semantic_fingerprint(),
        source_board_sha256=request.inputs.board_sha256,
        engine=_engine(),
        termination=_termination(),
        partial_status=PartialCandidateStatus.COMPLETE,
        segment_deltas=(_added_segment(),),
        constraint_consumption=_consumption(request),
    )


def test_route_request_is_frozen_extra_forbid_and_deterministic() -> None:
    first = _request()
    second = RouteRequest.model_validate_json(first.semantic_json())

    assert first == second
    assert first.target_domains[0].net_names == ("/SIG",)
    assert first.target_domains[0].nets[0].terminal_object_ids == (
        "terminal:U1:1",
        "terminal:U2:1",
    )
    assert first.semantic_json() == second.semantic_json()
    assert first.semantic_fingerprint() == second.semantic_fingerprint()
    assert json.loads(first.semantic_json())["schema_version"] == 1
    with pytest.raises(ValidationError, match="frozen"):
        first.request_id = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="Extra inputs"):
        RouteRequest.model_validate({**first.model_dump(), "unexpected": True})


def test_request_rejects_duplicate_or_missing_stable_identities() -> None:
    request = _request()
    domain = request.target_domains[0]
    with pytest.raises(ValidationError, match="terminal object identities"):
        TargetRouteDomain(
            domain_id=domain.domain_id,
            nets=(
                TargetRouteNet(
                    net_name="/A",
                    terminal_object_ids=("terminal:U1:1", "terminal:U2:1"),
                ),
                TargetRouteNet(
                    net_name="/B",
                    terminal_object_ids=("terminal:U2:1", "terminal:U3:1"),
                ),
            ),
            priority=domain.priority,
        )
    with pytest.raises(ValidationError, match="protected route object is absent or stale"):
        RouteRequest.model_validate(
            {
                **request.model_dump(),
                "protected_policy": ProtectedRouteObjectPolicy(
                    protected_objects=(
                        _source_segment().model_copy(
                            update={"source_object_fingerprint": SHA_D}
                        ),
                    ),
                ),
            }
        )


def test_clean_internal_candidate_contract_is_accepted() -> None:
    request = _request()
    result = _complete_candidate(request)

    validate_route_candidate_result(request, result)

    assert result.partial_status is PartialCandidateStatus.COMPLETE
    assert result.segment_deltas[0].after is not None
    assert result.semantic_json() == RouteCandidateResult.model_validate_json(
        result.semantic_json()
    ).semantic_json()


def test_unknown_and_unsupported_constraints_fail_closed() -> None:
    request = _request(additional_constraint_ids=("constraint:unknown:1",))
    missing = _complete_candidate(_request()).model_copy(
        update={"request_fingerprint": request.semantic_fingerprint()}
    )
    with pytest.raises(ValueError, match="constraint-consumption ledger is not exact"):
        validate_route_candidate_result(request, missing)

    unsupported_id = "constraint:unknown:1"
    unsupported = RouteCandidateResult(
        request_fingerprint=request.semantic_fingerprint(),
        source_board_sha256=request.inputs.board_sha256,
        engine=_engine(),
        termination=_termination(RouteTerminationState.FAILED),
        partial_status=PartialCandidateStatus.FAILED_NO_DELTA,
        constraint_consumption=_consumption(
            request,
            overrides={
                unsupported_id: RouteConstraintDisposition.UNSUPPORTED,
            },
        ),
        failures=(
            RouteFailureEvidence(
                failure_id="failure:unsupported:1",
                kind=RouteFailureKind.UNSUPPORTED_CONSTRAINT,
                message="native adapter cannot represent this constraint",
                constraint_ids=(unsupported_id,),
            ),
        ),
    )
    validate_route_candidate_result(request, unsupported)

    forged = unsupported.model_copy(
        update={
            "constraint_consumption": (
                *unsupported.constraint_consumption,
                ConstraintConsumption(
                    constraint_id="constraint:foreign",
                    disposition=RouteConstraintDisposition.CONSUMED,
                    detail="not declared by request",
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="unknown=.*constraint:foreign"):
        validate_route_candidate_result(request, forged)


def test_protected_copper_mutation_is_rejected() -> None:
    request = _request(protected=True)
    before = RouteSegmentGeometry(
        net_name="/SIG",
        start=RoutePoint(x_mm=1, y_mm=1),
        end=RoutePoint(x_mm=2, y_mm=1),
        layer="F.Cu",
        width_mm=0.25,
    )
    result = _complete_candidate(request).model_copy(
        update={
            "segment_deltas": (
                RouteSegmentDelta(
                    mutation_id="mutation:segment:remove:1",
                    operation=RouteMutationKind.REMOVE,
                    object_id="route:segment:source-1",
                    source_object_id="route:segment:source-1",
                    source_object_fingerprint=SHA_C,
                    before=before,
                ),
            )
        }
    )

    with pytest.raises(ValueError, match="protected copper"):
        validate_route_candidate_result(request, result)


def test_stale_board_and_request_hashes_are_rejected() -> None:
    request = _request()
    result = _complete_candidate(request)

    with pytest.raises(ValueError, match="stale or different request"):
        validate_route_candidate_result(
            request,
            result.model_copy(update={"request_fingerprint": SHA_F}),
        )
    with pytest.raises(ValueError, match="stale or different source board"):
        validate_route_candidate_result(
            request,
            result.model_copy(update={"source_board_sha256": SHA_F}),
        )


def test_budget_exhaustion_can_retain_a_bounded_partial_delta() -> None:
    request = _request()
    result = RouteCandidateResult(
        request_fingerprint=request.semantic_fingerprint(),
        source_board_sha256=request.inputs.board_sha256,
        engine=_engine(),
        termination=_termination(RouteTerminationState.BUDGET_EXHAUSTED),
        partial_status=PartialCandidateStatus.BOUNDED_PARTIAL,
        segment_deltas=(_added_segment(),),
        constraint_consumption=_consumption(request),
        failures=(
            RouteFailureEvidence(
                failure_id="failure:budget:1",
                kind=RouteFailureKind.BUDGET_EXHAUSTED,
                message="maximum expansion budget reached",
                net_names=("/SIG",),
                resource_ids=("max_expansions",),
            ),
        ),
    )

    validate_route_candidate_result(request, result)
    assert result.termination.exhausted_budget_fields == ("max_expansions",)


@pytest.mark.parametrize(
    ("operation", "changes", "message"),
    [
        (
            RouteMutationKind.ADD,
            {"before": _added_segment().after},
            "add mutation cannot claim a source object",
        ),
        (
            RouteMutationKind.REMOVE,
            {"after": _added_segment().after},
            "requires stable source identity",
        ),
        (
            RouteMutationKind.REPLACE,
            {},
            "requires stable source identity",
        ),
    ],
)
def test_mutation_operations_require_exact_before_after_boundaries(
    operation: RouteMutationKind,
    changes: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "mutation_id": "mutation:invalid",
        "operation": operation,
        "object_id": "route:segment:invalid",
        "after": _added_segment().after if operation is RouteMutationKind.ADD else None,
    }
    values.update(changes)
    with pytest.raises(ValidationError, match=message):
        RouteSegmentDelta.model_validate(values)
