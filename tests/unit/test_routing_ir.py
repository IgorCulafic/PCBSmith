from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from pcbsmith.routing_ir import (
    NetRoutingTelemetry,
    ResourceOveruseSummary,
    RoutingBudget,
    RoutingFailureReason,
    RoutingIrModel,
    RoutingPassTelemetry,
    RoutingRunResult,
)


def budget(**changes: int) -> RoutingBudget:
    values = {
        "max_passes": 4,
        "max_expansions": 1_000,
        "max_expansions_per_net": 500,
        "max_stagnant_passes": 2,
        "max_exact_check_rejections": 1,
    }
    values.update(changes)
    return RoutingBudget(**values)


def zero_overuse() -> ResourceOveruseSummary:
    return ResourceOveruseSummary(
        resource_id="channel:main",
        resource_kind="channel",
        capacity_units=2,
        demand_units=2,
        overuse_units=0,
        net_names=("/A",),
    )


def routed_net() -> NetRoutingTelemetry:
    return NetRoutingTelemetry(
        net_name="/A",
        pass_index=0,
        attempt_index=0,
        expansion_count=17,
        segment_count=3,
        via_count=1,
        length_mm=12.5,
        routed=True,
        exact_check_accepted=True,
    )


def successful_run(**changes: object) -> RoutingRunResult:
    route_pass = RoutingPassTelemetry(
        pass_index=0,
        net_telemetry=(routed_net(),),
        unresolved_net_names=(),
        resource_overuse=(zero_overuse(),),
        expansion_count=17,
    )
    values: dict[str, object] = {
        "producer": "fixture-router/1",
        "budget": budget(),
        "success": True,
        "exact_check_accepted": True,
        "route_order": ("/A",),
        "passes": (route_pass,),
        "resource_overuse": (zero_overuse(),),
    }
    values.update(changes)
    return RoutingRunResult.model_validate(values)


@pytest.mark.parametrize(
    "field",
    [
        "max_passes",
        "max_expansions",
        "max_expansions_per_net",
        "max_stagnant_passes",
        "max_exact_check_rejections",
    ],
)
def test_negative_fixed_budgets_are_rejected(field: str) -> None:
    with pytest.raises(ValidationError):
        budget(**{field: -1})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pass_index", -1),
        ("attempt_index", -1),
        ("expansion_count", -1),
        ("segment_count", -1),
        ("via_count", -1),
        ("length_mm", -0.1),
    ],
)
def test_negative_net_telemetry_is_rejected(field: str, value: object) -> None:
    values = routed_net().model_dump()
    values[field] = value
    with pytest.raises(ValidationError):
        NetRoutingTelemetry.model_validate(values)


def test_resource_overuse_must_match_capacity_accounting() -> None:
    with pytest.raises(ValidationError, match="overuse_units must equal"):
        ResourceOveruseSummary(
            resource_id="edge:1",
            resource_kind="edge",
            capacity_units=2,
            demand_units=5,
            overuse_units=2,
        )


def test_net_attempt_outcome_and_exact_check_are_typed() -> None:
    with pytest.raises(ValidationError, match="requires a failure reason"):
        NetRoutingTelemetry(
            net_name="/A",
            pass_index=0,
            attempt_index=0,
            expansion_count=1,
            routed=False,
        )
    rejected = NetRoutingTelemetry(
        net_name="/A",
        pass_index=0,
        attempt_index=0,
        expansion_count=1,
        routed=False,
        failure_reason=RoutingFailureReason.EXACT_CHECK_REJECTION,
        exact_check_accepted=False,
    )
    assert rejected.failure_reason.value == "exact_check_rejection"


def test_pass_summaries_must_match_per_net_telemetry() -> None:
    with pytest.raises(ValidationError, match="expansion_count must equal"):
        RoutingPassTelemetry(
            pass_index=0,
            net_telemetry=(routed_net(),),
            expansion_count=16,
        )


def test_exactly_checked_success_is_zero_overuse_acceptance() -> None:
    result = successful_run()
    assert result.accepted
    assert result.success
    assert sum(item.overuse_units for item in result.resource_overuse) == 0


def test_algorithmic_success_without_exact_check_is_not_accepted() -> None:
    result = successful_run(exact_check_accepted=None)
    assert result.success
    assert result.exact_check_accepted is None
    assert not result.accepted


def test_algorithmic_success_rejected_by_exact_check_is_not_accepted() -> None:
    result = successful_run(exact_check_accepted=False)
    assert result.success
    assert not result.accepted


def test_exact_acceptance_requires_algorithmic_success() -> None:
    with pytest.raises(ValidationError, match="requires algorithmic success"):
        RoutingRunResult(
            producer="fixture-router/1",
            budget=budget(),
            success=False,
            exact_check_accepted=True,
            failure_reason=RoutingFailureReason.UNROUTABLE,
        )


def test_exact_check_rejection_reason_requires_rejected_status() -> None:
    with pytest.raises(
        ValidationError,
        match="exact_check_rejection requires exact_check_accepted=False",
    ):
        RoutingRunResult(
            producer="fixture-router/1",
            budget=budget(),
            success=False,
            failure_reason=RoutingFailureReason.EXACT_CHECK_REJECTION,
        )


def test_rejected_exact_check_has_coherent_run_status() -> None:
    rejected = NetRoutingTelemetry(
        net_name="/A",
        pass_index=0,
        attempt_index=0,
        expansion_count=1,
        routed=False,
        failure_reason=RoutingFailureReason.EXACT_CHECK_REJECTION,
        exact_check_accepted=False,
    )
    route_pass = RoutingPassTelemetry(
        pass_index=0,
        net_telemetry=(rejected,),
        unresolved_net_names=("/A",),
        expansion_count=1,
        exact_check_rejection_count=1,
    )
    result = RoutingRunResult(
        producer="fixture-router/1",
        budget=budget(),
        success=False,
        exact_check_accepted=False,
        failure_reason=RoutingFailureReason.EXACT_CHECK_REJECTION,
        route_order=("/A",),
        unresolved_net_names=("/A",),
        passes=(route_pass,),
    )
    assert not result.accepted
    assert result.exact_check_accepted is False


def test_success_rejects_unresolved_nets() -> None:
    with pytest.raises(ValidationError, match="unresolved nets"):
        successful_run(unresolved_net_names=("/A",), passes=())


def test_success_rejects_remaining_overuse() -> None:
    overuse = ResourceOveruseSummary(
        resource_id="channel:main",
        resource_kind="channel",
        capacity_units=1,
        demand_units=2,
        overuse_units=1,
        net_names=("/A", "/B"),
    )
    with pytest.raises(ValidationError, match="zero resource overuse"):
        successful_run(resource_overuse=(overuse,), passes=())


def test_failed_run_requires_typed_reason() -> None:
    with pytest.raises(ValidationError, match="typed failure reason"):
        RoutingRunResult(
            producer="fixture-router/1",
            budget=budget(),
            success=False,
        )


def test_overuse_remaining_requires_positive_overuse() -> None:
    with pytest.raises(ValidationError, match="positive resource overuse"):
        RoutingRunResult(
            producer="fixture-router/1",
            budget=budget(),
            success=False,
            failure_reason=RoutingFailureReason.OVERUSE_REMAINING,
        )


def test_run_rejects_work_beyond_fixed_budgets() -> None:
    route_pass = RoutingPassTelemetry(
        pass_index=0,
        net_telemetry=(routed_net(),),
        expansion_count=17,
    )
    with pytest.raises(ValidationError, match="fixed expansion budget"):
        RoutingRunResult(
            producer="fixture-router/1",
            budget=budget(max_expansions=16),
            success=False,
            failure_reason=RoutingFailureReason.EXPANSION_BUDGET,
            route_order=("/A",),
            passes=(route_pass,),
        )


def test_schema_round_trip_and_fingerprint_are_stable() -> None:
    first = successful_run()
    second = RoutingRunResult.model_validate_json(first.semantic_json())
    assert first == second
    assert first.schema_id == "pcbsmith-routing-run"
    assert first.schema_version == 2
    assert first.semantic_json() == second.semantic_json()
    assert len(first.semantic_fingerprint()) == 64
    assert first.semantic_fingerprint() == second.semantic_fingerprint()
    assert json.loads(first.semantic_json())["schema_version"] == 2


def test_fingerprint_changes_with_routing_semantics() -> None:
    first = successful_run()
    second = successful_run(restart_count=1)
    assert first.semantic_fingerprint() != second.semantic_fingerprint()


def test_failure_reason_values_are_stable_adapter_tokens() -> None:
    assert {item.value for item in RoutingFailureReason} == {
        "unroutable",
        "expansion_budget",
        "pass_budget",
        "stagnation",
        "exact_check_rejection",
        "overuse_remaining",
    }


def test_ir_models_are_frozen() -> None:
    result = successful_run()
    with pytest.raises(ValidationError, match="frozen"):
        result.restart_count = 1


def _resource(
    resource_id: str,
    *,
    net_names: tuple[str, ...] = ("/A", "/B"),
    overuse_units: int = 0,
) -> ResourceOveruseSummary:
    return ResourceOveruseSummary(
        resource_id=resource_id,
        resource_kind="channel",
        capacity_units=2,
        demand_units=2 + overuse_units,
        overuse_units=overuse_units,
        net_names=net_names,
    )


def _assert_identical_semantics(first: RoutingIrModel, second: RoutingIrModel) -> None:
    assert first == second
    assert first.semantic_json() == second.semantic_json()
    assert first.semantic_fingerprint() == second.semantic_fingerprint()


def test_resource_net_names_are_canonical_set_like_semantics() -> None:
    first = _resource("channel:a", net_names=("/B", "/A"))
    second = _resource("channel:a", net_names=("/A", "/B"))

    _assert_identical_semantics(first, second)
    assert first.net_names == ("/A", "/B")


def test_pass_unresolved_names_are_canonical_set_like_semantics() -> None:
    first = RoutingPassTelemetry(
        pass_index=0,
        unresolved_net_names=("/B", "/A"),
    )
    second = RoutingPassTelemetry(
        pass_index=0,
        unresolved_net_names=("/A", "/B"),
    )

    _assert_identical_semantics(first, second)
    assert first.unresolved_net_names == ("/A", "/B")


def test_pass_resource_overuse_is_canonical_set_like_semantics() -> None:
    resource_a = _resource("channel:a")
    resource_b = _resource("channel:b")
    first = RoutingPassTelemetry(
        pass_index=0,
        resource_overuse=(resource_b, resource_a),
    )
    second = RoutingPassTelemetry(
        pass_index=0,
        resource_overuse=(resource_a, resource_b),
    )

    _assert_identical_semantics(first, second)
    assert tuple(item.resource_id for item in first.resource_overuse) == (
        "channel:a",
        "channel:b",
    )


def test_run_unresolved_names_are_canonical_set_like_semantics() -> None:
    final_pass = RoutingPassTelemetry(
        pass_index=0,
        unresolved_net_names=("/A", "/B"),
    )
    common = {
        "producer": "canonical-test",
        "budget": budget(),
        "success": False,
        "failure_reason": RoutingFailureReason.UNROUTABLE,
        "route_order": ("/A", "/B"),
        "passes": (final_pass,),
    }
    first = RoutingRunResult(**common, unresolved_net_names=("/B", "/A"))
    second = RoutingRunResult(**common, unresolved_net_names=("/A", "/B"))

    _assert_identical_semantics(first, second)
    assert first.unresolved_net_names == ("/A", "/B")


def test_run_resource_overuse_is_canonical_set_like_semantics() -> None:
    resource_a = _resource("channel:a")
    resource_b = _resource("channel:b")
    final_pass = RoutingPassTelemetry(
        pass_index=0,
        resource_overuse=(resource_a, resource_b),
    )
    common = {
        "producer": "canonical-test",
        "budget": budget(),
        "success": False,
        "failure_reason": RoutingFailureReason.UNROUTABLE,
        "route_order": (),
        "passes": (final_pass,),
    }
    first = RoutingRunResult(**common, resource_overuse=(resource_b, resource_a))
    second = RoutingRunResult(**common, resource_overuse=(resource_a, resource_b))

    _assert_identical_semantics(first, second)
    assert tuple(item.resource_id for item in first.resource_overuse) == (
        "channel:a",
        "channel:b",
    )


def test_set_like_duplicates_are_rejected_before_canonicalization() -> None:
    resource = _resource("channel:a")
    with pytest.raises(ValidationError, match="net_names must be unique"):
        _resource("channel:a", net_names=("/A", "/A"))
    with pytest.raises(ValidationError, match="unresolved_net_names must be unique"):
        RoutingPassTelemetry(pass_index=0, unresolved_net_names=("/A", "/A"))
    with pytest.raises(ValidationError, match="resource_id values must be unique within a pass"):
        RoutingPassTelemetry(pass_index=0, resource_overuse=(resource, resource))
    with pytest.raises(ValidationError, match="unresolved_net_names must be unique"):
        RoutingRunResult(
            producer="canonical-test",
            budget=budget(),
            success=False,
            failure_reason=RoutingFailureReason.UNROUTABLE,
            route_order=("/A",),
            unresolved_net_names=("/A", "/A"),
        )
    with pytest.raises(ValidationError, match="final resource_id values must be unique"):
        RoutingRunResult(
            producer="canonical-test",
            budget=budget(),
            success=False,
            failure_reason=RoutingFailureReason.UNROUTABLE,
            resource_overuse=(resource, resource),
        )


def _attempt(net_name: str, *, pass_index: int, attempt_index: int) -> NetRoutingTelemetry:
    return NetRoutingTelemetry(
        net_name=net_name,
        pass_index=pass_index,
        attempt_index=attempt_index,
        expansion_count=1,
        routed=True,
    )


def test_route_order_remains_semantic_order() -> None:
    first = RoutingRunResult(
        producer="ordered-test",
        budget=budget(),
        success=True,
        route_order=("/A", "/B"),
    )
    second = RoutingRunResult(
        producer="ordered-test",
        budget=budget(),
        success=True,
        route_order=("/B", "/A"),
    )

    assert first != second
    assert first.semantic_json() != second.semantic_json()
    assert first.semantic_fingerprint() != second.semantic_fingerprint()


def test_net_telemetry_attempt_order_remains_semantic_order() -> None:
    attempt_a = _attempt("/A", pass_index=0, attempt_index=0)
    attempt_b = _attempt("/B", pass_index=0, attempt_index=1)
    first = RoutingPassTelemetry(
        pass_index=0,
        net_telemetry=(attempt_a, attempt_b),
        expansion_count=2,
    )
    second = RoutingPassTelemetry(
        pass_index=0,
        net_telemetry=(attempt_b, attempt_a),
        expansion_count=2,
    )

    assert first != second
    assert first.semantic_json() != second.semantic_json()
    assert first.semantic_fingerprint() != second.semantic_fingerprint()


def test_pass_sequence_remains_semantic_order() -> None:
    first_passes = (
        RoutingPassTelemetry(
            pass_index=0,
            net_telemetry=(_attempt("/A", pass_index=0, attempt_index=0),),
            expansion_count=1,
        ),
        RoutingPassTelemetry(
            pass_index=1,
            net_telemetry=(_attempt("/B", pass_index=1, attempt_index=0),),
            expansion_count=1,
        ),
    )
    second_passes = (
        RoutingPassTelemetry(
            pass_index=0,
            net_telemetry=(_attempt("/B", pass_index=0, attempt_index=0),),
            expansion_count=1,
        ),
        RoutingPassTelemetry(
            pass_index=1,
            net_telemetry=(_attempt("/A", pass_index=1, attempt_index=0),),
            expansion_count=1,
        ),
    )
    common = {
        "producer": "ordered-test",
        "budget": budget(),
        "success": True,
        "route_order": ("/A", "/B"),
    }
    first = RoutingRunResult(**common, passes=first_passes)
    second = RoutingRunResult(**common, passes=second_passes)

    assert first != second
    assert first.semantic_json() != second.semantic_json()
    assert first.semantic_fingerprint() != second.semantic_fingerprint()


def test_final_pass_and_run_match_after_independent_canonicalization() -> None:
    resource_a = _resource("channel:a")
    resource_b = _resource("channel:b")
    final_pass = RoutingPassTelemetry(
        pass_index=0,
        unresolved_net_names=("/B", "/A"),
        resource_overuse=(resource_b, resource_a),
    )
    result = RoutingRunResult(
        producer="canonical-test",
        budget=budget(),
        success=False,
        failure_reason=RoutingFailureReason.UNROUTABLE,
        route_order=("/A", "/B"),
        unresolved_net_names=("/A", "/B"),
        passes=(final_pass,),
        resource_overuse=(resource_a, resource_b),
    )

    assert result.unresolved_net_names == final_pass.unresolved_net_names
    assert result.resource_overuse == final_pass.resource_overuse
    with pytest.raises(ValidationError, match="final pass overuse"):
        RoutingRunResult(
            producer="canonical-test",
            budget=budget(),
            success=False,
            failure_reason=RoutingFailureReason.UNROUTABLE,
            route_order=("/A", "/B"),
            unresolved_net_names=("/A", "/B"),
            passes=(final_pass,),
            resource_overuse=(resource_a,),
        )
