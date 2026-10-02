"""Registered production caller for native and pinned external routing candidates."""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.board import BoardLayout
from pcbsmith.kicad.routing_external_adapters import (
    FREEROUTING_MASTER_2026_07_09,
    FREEROUTING_V1_9_0,
    FREEROUTING_V2_2_4,
    FREEROUTING_V2_3_0,
    KRT_V0_19_0,
    ExternalLayoutImporter,
    ExternalProcessExecutor,
    ExternalRouterFamily,
    ExternalToolBinding,
    PinnedExternalRouterSpec,
    run_external_process,
    run_freerouting_dsn_ses_candidate,
    run_krt_board_candidate,
)
from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.routing_ir import RouteCandidateResult, RouteRequest
from pcbsmith.semantic_ir import SemanticIrModel


class RoutingBackendScope(StrEnum):
    GLOBAL = "global"
    SELECTED_NET_LOCAL = "selected_net_local"
    LEGACY_ORACLE = "legacy_oracle"
    ISOLATED_RESEARCH = "isolated_research"


class RoutingBackendStatus(StrEnum):
    PRODUCTION_CANDIDATE = "production_candidate"
    ORACLE_ONLY = "oracle_only"
    BLOCKED = "blocked"
    RESEARCH_ONLY = "research_only"


class RoutingBackendRegistration(SemanticIrModel):
    registration_id: str
    engine_id: str
    family: Literal["native", "freerouting", "kicad_routing_tools"]
    scope: RoutingBackendScope
    status: RoutingBackendStatus
    spec_fingerprint: str | None = None
    blocker_reason: str | None = None
    publish_authorized: Literal[False] = False

    @model_validator(mode="after")
    def registration_is_coherent(self) -> Self:
        require_identity(self.registration_id, "registration_id")
        require_identity(self.engine_id, "engine_id")
        if self.family == "native":
            if self.spec_fingerprint is not None:
                raise ValueError("native backend cannot bind an external spec")
        elif self.spec_fingerprint is None:
            raise ValueError("external backend requires a pinned spec fingerprint")
        else:
            require_sha256(self.spec_fingerprint, "spec_fingerprint")
        if self.status is RoutingBackendStatus.BLOCKED:
            if self.blocker_reason is None:
                raise ValueError("blocked backend requires a reason")
        elif self.blocker_reason is not None:
            raise ValueError("unblocked backend cannot retain a blocker reason")
        return self


def _external_registration(
    spec: PinnedExternalRouterSpec,
    *,
    scope: RoutingBackendScope,
    status: RoutingBackendStatus,
    blocker_reason: str | None = None,
) -> RoutingBackendRegistration:
    return RoutingBackendRegistration(
        registration_id=f"router:{spec.engine_id}",
        engine_id=spec.engine_id,
        family=spec.family.value,
        scope=scope,
        status=status,
        spec_fingerprint=spec.spec_fingerprint,
        blocker_reason=blocker_reason,
    )


ROUTING_BACKEND_REGISTRY = (
    RoutingBackendRegistration(
        registration_id="router:pcbsmith-native-negotiated",
        engine_id="pcbsmith-native-negotiated",
        family="native",
        scope=RoutingBackendScope.GLOBAL,
        status=RoutingBackendStatus.PRODUCTION_CANDIDATE,
    ),
    _external_registration(
        FREEROUTING_V2_3_0,
        scope=RoutingBackendScope.GLOBAL,
        status=RoutingBackendStatus.PRODUCTION_CANDIDATE,
    ),
    _external_registration(
        FREEROUTING_V1_9_0,
        scope=RoutingBackendScope.LEGACY_ORACLE,
        status=RoutingBackendStatus.ORACLE_ONLY,
    ),
    _external_registration(
        KRT_V0_19_0,
        scope=RoutingBackendScope.SELECTED_NET_LOCAL,
        status=RoutingBackendStatus.PRODUCTION_CANDIDATE,
    ),
    _external_registration(
        FREEROUTING_V2_2_4,
        scope=RoutingBackendScope.ISOLATED_RESEARCH,
        status=RoutingBackendStatus.BLOCKED,
        blocker_reason="retained wiring can trigger PolylineTrace.combine StackOverflowError",
    ),
    _external_registration(
        FREEROUTING_MASTER_2026_07_09,
        scope=RoutingBackendScope.ISOLATED_RESEARCH,
        status=RoutingBackendStatus.RESEARCH_ONLY,
    ),
)

_REGISTRY = {item.registration_id: item for item in ROUTING_BACKEND_REGISTRY}
_SPECS = {
    spec.engine_id: spec
    for spec in (
        FREEROUTING_V2_3_0,
        FREEROUTING_V1_9_0,
        KRT_V0_19_0,
        FREEROUTING_V2_2_4,
        FREEROUTING_MASTER_2026_07_09,
    )
}


def registered_routing_backend(registration_id: str) -> RoutingBackendRegistration:
    try:
        return _REGISTRY[registration_id]
    except KeyError as exc:
        raise ValueError(f"unregistered routing backend {registration_id!r}") from exc


def _production_external_spec(registration_id: str) -> PinnedExternalRouterSpec:
    registration = registered_routing_backend(registration_id)
    if registration.status is not RoutingBackendStatus.PRODUCTION_CANDIDATE:
        raise ValueError(
            f"routing backend {registration_id!r} is not a production candidate: "
            f"{registration.status.value}"
        )
    if registration.family == "native":
        raise ValueError("native routing uses the native candidate adapter")
    spec = _SPECS[registration.engine_id]
    if spec.spec_fingerprint != registration.spec_fingerprint:
        raise ValueError("routing backend registration is stale for its pinned spec")
    return spec


def run_registered_freerouting_candidate(
    *,
    registration_id: str,
    request: RouteRequest,
    source_layout: BoardLayout,
    candidate_directory: Path,
    binding: ExternalToolBinding,
    dsn_payload: bytes,
    ses_importer: ExternalLayoutImporter,
    java_executable: str = "java",
    executor: ExternalProcessExecutor = run_external_process,
    completion_verifier: Callable[[], bool] | None = None,
) -> RouteCandidateResult:
    spec = _production_external_spec(registration_id)
    if spec.family is not ExternalRouterFamily.FREEROUTING:
        raise ValueError("registered backend is not Freerouting")
    return run_freerouting_dsn_ses_candidate(
        request=request,
        source_layout=source_layout,
        candidate_directory=candidate_directory,
        spec=spec,
        binding=binding,
        dsn_payload=dsn_payload,
        ses_importer=ses_importer,
        java_executable=java_executable,
        executor=executor,
        completion_verifier=completion_verifier,
    )


def run_registered_krt_candidate(
    *,
    registration_id: str,
    request: RouteRequest,
    source_layout: BoardLayout,
    candidate_directory: Path,
    binding: ExternalToolBinding,
    source_board_payload: bytes,
    board_importer: ExternalLayoutImporter,
    python_executable: str = "python",
    executor: ExternalProcessExecutor = run_external_process,
) -> RouteCandidateResult:
    spec = _production_external_spec(registration_id)
    if spec.family is not ExternalRouterFamily.KICAD_ROUTING_TOOLS:
        raise ValueError("registered backend is not KiCadRoutingTools")
    return run_krt_board_candidate(
        request=request,
        source_layout=source_layout,
        candidate_directory=candidate_directory,
        spec=spec,
        binding=binding,
        source_board_payload=source_board_payload,
        board_importer=board_importer,
        python_executable=python_executable,
        executor=executor,
    )


class RetainedRoutingRun(SemanticIrModel):
    run_id: str
    retained_directory: str
    artifact_manifest_sha256: str
    result: RouteCandidateResult

    @model_validator(mode="after")
    def run_is_retained(self) -> Self:
        require_identity(self.run_id, "run_id")
        require_identity(self.retained_directory, "retained_directory")
        require_sha256(self.artifact_manifest_sha256, "artifact_manifest_sha256")
        return self


class RepeatedRoutingComparison(SemanticIrModel):
    schema_id: Literal["pcbsmith-repeated-routing-comparison"] = (
        "pcbsmith-repeated-routing-comparison"
    )
    schema_version: Literal[1] = 1
    request_fingerprint: str
    source_board_sha256: str
    engine_id: str
    runs: tuple[RetainedRoutingRun, ...] = Field(min_length=2)
    exact_result_equal: bool
    exact_delta_equal: bool
    comparison_fingerprint: str

    @model_validator(mode="after")
    def comparison_is_replay_bound(self) -> Self:
        require_sha256(self.request_fingerprint, "request_fingerprint")
        require_sha256(self.source_board_sha256, "source_board_sha256")
        if len(self.runs) < 2:
            raise ValueError("repeat comparison requires at least two retained runs")
        if len({item.run_id for item in self.runs}) != len(self.runs):
            raise ValueError("retained repeat run identities must be unique")
        require_sha256(self.comparison_fingerprint, "comparison_fingerprint")
        expected = fingerprint(self.model_dump(mode="json", exclude={"comparison_fingerprint"}))
        if self.comparison_fingerprint != expected:
            raise ValueError("repeat comparison fingerprint is stale")
        return self


def compare_repeated_routing_runs(
    runs: tuple[RetainedRoutingRun, ...],
) -> RepeatedRoutingComparison:
    if len(runs) < 2:
        raise ValueError("repeat comparison requires at least two retained runs")
    canonical = tuple(sorted(runs, key=lambda item: item.run_id))
    requests = {item.result.request_fingerprint for item in canonical}
    boards = {item.result.source_board_sha256 for item in canonical}
    engines = {item.result.engine.engine_id for item in canonical}
    if len(requests) != 1 or len(boards) != 1 or len(engines) != 1:
        raise ValueError("routing repeats are not directly comparable")
    results = tuple(item.result.semantic_fingerprint() for item in canonical)
    deltas = tuple(
        fingerprint(
            {
                "segments": [value.model_dump(mode="json") for value in item.result.segment_deltas],
                "vias": [value.model_dump(mode="json") for value in item.result.via_deltas],
                "zones": [value.model_dump(mode="json") for value in item.result.zone_deltas],
            }
        )
        for item in canonical
    )
    values: dict[str, Any] = {
        "request_fingerprint": next(iter(requests)),
        "source_board_sha256": next(iter(boards)),
        "engine_id": next(iter(engines)),
        "runs": canonical,
        "exact_result_equal": len(set(results)) == 1,
        "exact_delta_equal": len(set(deltas)) == 1,
    }
    provisional = RepeatedRoutingComparison.model_construct(
        **values, comparison_fingerprint="0" * 64
    )
    return RepeatedRoutingComparison(
        **values,
        comparison_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"comparison_fingerprint"})
        ),
    )


__all__ = [
    "ROUTING_BACKEND_REGISTRY",
    "RepeatedRoutingComparison",
    "RetainedRoutingRun",
    "RoutingBackendRegistration",
    "RoutingBackendScope",
    "RoutingBackendStatus",
    "compare_repeated_routing_runs",
    "registered_routing_backend",
    "run_registered_freerouting_candidate",
    "run_registered_krt_candidate",
]
