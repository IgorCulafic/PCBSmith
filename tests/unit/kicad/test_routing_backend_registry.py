from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

import pcbsmith.kicad.routing_backend_registry as registry
from pcbsmith.kicad.board import BoardLayout
from pcbsmith.kicad.routing_backend_registry import (
    ROUTING_BACKEND_REGISTRY,
    RetainedRoutingRun,
    RoutingBackendScope,
    RoutingBackendStatus,
    compare_repeated_routing_runs,
    registered_routing_backend,
    run_registered_freerouting_candidate,
)
from pcbsmith.kicad.routing_external_adapters import ExternalToolBinding
from pcbsmith.routing_ir import (
    PartialCandidateStatus,
    RouteCandidateResult,
    RouteFailureEvidence,
    RouteFailureKind,
    RouteRequest,
    RouteTerminationEvidence,
    RouteTerminationState,
    RoutingEngineIdentity,
)


def _failed_result(*, detail: str = "failed") -> RouteCandidateResult:
    return RouteCandidateResult(
        request_fingerprint="a" * 64,
        source_board_sha256="b" * 64,
        engine=RoutingEngineIdentity(
            engine_id="freerouting-v2.3.0",
            engine_version="2.3.0",
            adapter_id="fixture",
            adapter_version="1",
        ),
        termination=RouteTerminationEvidence(
            state=RouteTerminationState.FAILED,
            reason="fixture_failed",
            stdout_sha256="c" * 64,
            stderr_sha256="d" * 64,
            elapsed_seconds=1.0,
        ),
        partial_status=PartialCandidateStatus.FAILED_NO_DELTA,
        constraint_consumption=(),
        failures=(
            RouteFailureEvidence(
                failure_id="failure:fixture",
                kind=RouteFailureKind.ENGINE_FAILURE,
                message=detail,
            ),
        ),
    )


def _retained(run_id: str, result: RouteCandidateResult) -> RetainedRoutingRun:
    return RetainedRoutingRun(
        run_id=run_id,
        retained_directory=f"runs/{run_id}",
        artifact_manifest_sha256=(run_id[-1] * 64),
        result=result,
    )


def test_registry_exposes_the_w6_matrix_and_never_publishes_directly() -> None:
    assert len(ROUTING_BACKEND_REGISTRY) == 6
    assert all(not item.publish_authorized for item in ROUTING_BACKEND_REGISTRY)
    freerouting = registered_routing_backend("router:freerouting-v2.3.0")
    assert freerouting.status is RoutingBackendStatus.PRODUCTION_CANDIDATE
    assert freerouting.scope is RoutingBackendScope.GLOBAL
    assert registered_routing_backend("router:kicad-routing-tools-v0.19.0").scope is (
        RoutingBackendScope.SELECTED_NET_LOCAL
    )
    blocked = registered_routing_backend("router:freerouting-v2.2.4")
    assert blocked.status is RoutingBackendStatus.BLOCKED and blocked.blocker_reason


def test_registered_caller_rejects_oracle_blocked_and_research_backends() -> None:
    dummy = cast(Any, object())
    for registration_id in (
        "router:freerouting-v1.9.0-oracle",
        "router:freerouting-v2.2.4",
        "router:freerouting-master-4514092",
    ):
        with pytest.raises(ValueError, match="not a production candidate"):
            run_registered_freerouting_candidate(
                registration_id=registration_id,
                request=dummy,
                source_layout=dummy,
                candidate_directory=Path("candidate"),
                binding=dummy,
                dsn_payload=b"",
                ses_importer=dummy,
            )


def test_registered_caller_dispatches_only_the_pinned_production_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}
    sentinel = _failed_result()

    def fake(**kwargs: Any) -> RouteCandidateResult:
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(registry, "run_freerouting_dsn_ses_candidate", fake)
    dummy_request = cast(RouteRequest, object())
    dummy_layout = cast(BoardLayout, object())
    dummy_binding = cast(ExternalToolBinding, object())
    result = run_registered_freerouting_candidate(
        registration_id="router:freerouting-v2.3.0",
        request=dummy_request,
        source_layout=dummy_layout,
        candidate_directory=Path("candidate"),
        binding=dummy_binding,
        dsn_payload=b"dsn",
        ses_importer=cast(Any, object()),
    )
    assert result is sentinel
    assert captured["spec"].version == "2.3.0"


def test_same_input_repeats_are_retained_and_compared_without_blending() -> None:
    result = _failed_result()
    equal = compare_repeated_routing_runs((_retained("run-1", result), _retained("run-2", result)))
    assert equal.exact_result_equal and equal.exact_delta_equal
    assert len(equal.runs) == 2

    different = compare_repeated_routing_runs(
        (_retained("run-1", result), _retained("run-2", _failed_result(detail="other")))
    )
    assert not different.exact_result_equal
    assert different.exact_delta_equal


def test_different_inputs_cannot_be_compared_as_repeats() -> None:
    first = _failed_result()
    second = first.model_copy(update={"source_board_sha256": "e" * 64})
    with pytest.raises(ValueError, match="not directly comparable"):
        compare_repeated_routing_runs((_retained("run-1", first), _retained("run-2", second)))
