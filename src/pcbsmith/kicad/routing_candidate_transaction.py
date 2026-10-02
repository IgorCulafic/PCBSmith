"""Isolated, fail-closed transactions for immutable routing candidates.

The routing transaction owns candidate retention and validation. The existing
generation transaction remains the sole authority that may publish a canonical
board or change ``CURRENT.json``.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import asdict, is_dataclass, replace
from enum import Enum, StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator

from pcbsmith.applicability_execution import (
    ProjectApplicabilityExecutionManifest,
    ProjectExecutionAuthority,
)
from pcbsmith.kicad.board import (
    BoardLayout,
    BoardNetlist,
    TrackSegment,
    ViaSpec,
    render_board_from_layout,
)
from pcbsmith.kicad.placement_readback import (
    KiCadBoardReadbackSnapshot,
    extract_kicad_board_readback,
)
from pcbsmith.kicad.retained_native_repair import RetainedNativeRepair
from pcbsmith.kicad.routing_candidate_adapter import (
    native_routing_netlist_fingerprint,
    native_routing_profile_fingerprint,
    native_source_route_object_bindings,
)
from pcbsmith.kicad.routing_evidence import (
    KiCadDrcEvidence,
    RoutingArtifactState,
    SavedBoardRoutingEvidence,
)
from pcbsmith.production_workflow import (
    ArtifactRole,
    GenerationTransactionResult,
    RoutedBoardVerificationEvidence,
    RoutedVerificationKind,
    commit_generation_transaction,
    prepare_generation_transaction,
)
from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.routing_ir import (
    PartialCandidateStatus,
    RouteCandidateResult,
    RouteFailureEvidence,
    RouteFailureKind,
    RouteObjectKind,
    RoutePoint,
    RouteRequest,
    RouteSegmentGeometry,
    RouteTerminationEvidence,
    RouteTerminationState,
    RouteViaGeometry,
    RouteZoneGeometry,
    RoutingEngineIdentity,
    RoutingInputIdentity,
    StableRouteObjectIdentity,
    validate_route_candidate_result,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile
from pcbsmith.semantic_ir import SemanticIrModel
from pcbsmith.workflow_authority import WorkflowStage


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    def json_default(item: Any) -> Any:
        if isinstance(item, BaseModel):
            return item.model_dump(mode="json")
        if is_dataclass(item) and not isinstance(item, type):
            return asdict(item)
        if isinstance(item, Enum):
            return item.value
        raise TypeError(f"unsupported canonical JSON value: {type(item).__name__}")

    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=json_default,
    ).encode("utf-8")


def _aggregate_payload_identity(
    payloads: Mapping[str, bytes],
    paths: tuple[str, ...],
    *,
    schema_id: str,
) -> str:
    return _sha256(
        _canonical_bytes(
            {
                "schema_id": schema_id,
                "schema_version": 1,
                "artifacts": [
                    {"relative_path": path, "content_sha256": _sha256(payloads[path])}
                    for path in sorted(paths)
                ],
            }
        )
    )


def _layout_identity(layout: BoardLayout, field: str, value: Any) -> str:
    return _sha256(
        _canonical_bytes(
            {
                "schema_id": f"pcbsmith-native-routing-{field}",
                "schema_version": 1,
                "value": value,
            }
        )
    )


def _safe_relative_path(value: str) -> str:
    require_identity(value, "relative_path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value:
        raise ValueError(f"unsafe routing artifact path: {value!r}")
    return value


class FrozenRoutingInputArtifact(SemanticIrModel):
    """One exact artifact frozen before a routing engine starts."""

    schema_id: Literal["pcbsmith-frozen-routing-input-artifact"] = (
        "pcbsmith-frozen-routing-input-artifact"
    )
    schema_version: Literal[1] = 1
    relative_path: str
    role: ArtifactRole
    content_sha256: str

    @model_validator(mode="after")
    def artifact_is_safe(self) -> Self:
        _safe_relative_path(self.relative_path)
        require_sha256(self.content_sha256, "content_sha256")
        return self


class RoutingCandidateInputSnapshot(SemanticIrModel):
    """Closed inventory behind one route request's non-routing identities."""

    schema_id: Literal["pcbsmith-routing-candidate-input-snapshot"] = (
        "pcbsmith-routing-candidate-input-snapshot"
    )
    schema_version: Literal[1] = 1
    identity: RoutingInputIdentity
    board_relative_path: str
    schematic_relative_paths: tuple[str, ...] = Field(min_length=1)
    artifacts: tuple[FrozenRoutingInputArtifact, ...] = Field(min_length=1)
    snapshot_fingerprint: str

    @model_validator(mode="after")
    def snapshot_is_closed(self) -> Self:
        _safe_relative_path(self.board_relative_path)
        schematic_paths = tuple(sorted(self.schematic_relative_paths))
        for path in schematic_paths:
            _safe_relative_path(path)
        artifacts = tuple(sorted(self.artifacts, key=lambda item: item.relative_path))
        paths = tuple(item.relative_path for item in artifacts)
        if len(paths) != len(set(paths)):
            raise ValueError("frozen routing artifact paths must be unique")
        if self.board_relative_path not in paths:
            raise ValueError("frozen routing snapshot is missing its board")
        if not set(schematic_paths).issubset(paths):
            raise ValueError("frozen routing snapshot is missing a schematic artifact")
        object.__setattr__(self, "schematic_relative_paths", schematic_paths)
        object.__setattr__(self, "artifacts", artifacts)
        require_sha256(self.snapshot_fingerprint, "snapshot_fingerprint")
        payload = self.model_dump(mode="json", exclude={"snapshot_fingerprint"})
        if self.snapshot_fingerprint != fingerprint(payload):
            raise ValueError("routing input snapshot fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        identity: RoutingInputIdentity,
        board_relative_path: str,
        schematic_relative_paths: tuple[str, ...],
        artifacts: tuple[FrozenRoutingInputArtifact, ...],
    ) -> RoutingCandidateInputSnapshot:
        fields: dict[str, Any] = {
            "identity": identity,
            "board_relative_path": board_relative_path,
            "schematic_relative_paths": tuple(sorted(schematic_relative_paths)),
            "artifacts": tuple(sorted(artifacts, key=lambda item: item.relative_path)),
        }
        provisional = cls.model_construct(**fields, snapshot_fingerprint="0" * 64)
        return cls(
            **fields,
            snapshot_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"snapshot_fingerprint"})
            ),
        )


def freeze_native_routing_inputs(
    *,
    payloads: Mapping[str, bytes],
    roles: Mapping[str, ArtifactRole],
    board_relative_path: str,
    schematic_relative_paths: tuple[str, ...],
    layout: BoardLayout,
    netlist: BoardNetlist,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    protected_objects: tuple[StableRouteObjectIdentity, ...] = (),
) -> RoutingCandidateInputSnapshot:
    """Freeze every native non-routing authority into one replay-bound snapshot."""

    if set(payloads) != set(roles):
        raise ValueError("routing input payload and role paths must match exactly")
    for path in payloads:
        _safe_relative_path(path)
    if board_relative_path not in payloads:
        raise ValueError("routing input payloads are missing the source board")
    if not schematic_relative_paths or not set(schematic_relative_paths).issubset(payloads):
        raise ValueError("routing input payloads are missing schematic inputs")
    board_sha256 = _sha256(payloads[board_relative_path])
    protected = tuple(
        sorted(
            protected_objects,
            key=lambda item: (item.object_kind.value, item.object_id),
        )
    )
    if any(item.source_board_sha256 != board_sha256 for item in protected):
        raise ValueError("protected routing input belongs to a different board")
    placement_value = {
        "placements": [
            {
                "reference": component.reference,
                "uuid_path": component.uuid_path,
                "x_mm": x_mm,
            }
            for component, x_mm in layout.placements
        ],
        "parts_row_y_mm": layout.parts_row_y_mm,
        "part_y_mm": layout.part_y_mm,
        "part_rotation": layout.part_rotation,
        "part_flip": layout.part_flip,
    }
    outline_value = {
        "width_mm": layout.width_mm,
        "height_mm": layout.height_mm,
        "outline": layout.outline,
        "cutouts": layout.cutouts,
    }
    holes_value = {
        "footprints": [
            {
                "reference": component.reference,
                "footprint": component.footprint,
                "uuid_path": component.uuid_path,
            }
            for component, _x_mm in layout.placements
        ],
        "mask_apertures": layout.mask_apertures,
    }
    identity = RoutingInputIdentity(
        project_sha256=_aggregate_payload_identity(
            payloads,
            tuple(payloads),
            schema_id="pcbsmith-routing-project-inputs",
        ),
        board_sha256=board_sha256,
        schematic_sha256=_aggregate_payload_identity(
            payloads,
            schematic_relative_paths,
            schema_id="pcbsmith-routing-schematic-inputs",
        ),
        netlist_sha256=native_routing_netlist_fingerprint(netlist),
        placement_sha256=_layout_identity(layout, "placement", placement_value),
        outline_sha256=_layout_identity(layout, "outline", outline_value),
        holes_sha256=_layout_identity(layout, "holes", holes_value),
        rules_sha256=native_routing_profile_fingerprint(profile),
        protected_copper_sha256=_sha256(
            _canonical_bytes(
                {
                    "schema_id": "pcbsmith-routing-protected-copper",
                    "schema_version": 1,
                    "objects": [item.model_dump(mode="json") for item in protected],
                }
            )
        ),
    )
    artifacts = tuple(
        FrozenRoutingInputArtifact(
            relative_path=path,
            role=roles[path],
            content_sha256=_sha256(payload),
        )
        for path, payload in sorted(payloads.items())
    )
    return RoutingCandidateInputSnapshot.build(
        identity=identity,
        board_relative_path=board_relative_path,
        schematic_relative_paths=schematic_relative_paths,
        artifacts=artifacts,
    )


class RoutingCandidateValidationBundle(SemanticIrModel):
    """Independent KiCad and PCBSmith validation for one saved candidate."""

    schema_id: Literal["pcbsmith-routing-candidate-validation"] = (
        "pcbsmith-routing-candidate-validation"
    )
    schema_version: Literal[1] = 1
    board_sha256: str
    saved_board_routing: SavedBoardRoutingEvidence
    kicad_drc: KiCadDrcEvidence
    verification: RoutedBoardVerificationEvidence
    applicability_execution: ProjectApplicabilityExecutionManifest
    semantic_readback_accepted: bool
    blockers: tuple[str, ...]
    validation_fingerprint: str

    @model_validator(mode="after")
    def validation_is_replay_bound(self) -> Self:
        require_sha256(self.board_sha256, "board_sha256")
        bound_hashes = {
            self.saved_board_routing.board_sha256,
            self.verification.board_sha256,
            self.applicability_execution.saved_design_sha256,
        }
        if bound_hashes != {self.board_sha256}:
            raise ValueError("routing validation authorities target different boards")
        expected: list[str] = []
        if not self.semantic_readback_accepted:
            expected.append("saved candidate changed immutable board semantics")
        if self.saved_board_routing.state is not RoutingArtifactState.ROUTED_CANDIDATE:
            expected.append(f"saved board routing state is {self.saved_board_routing.state.value}")
        if not self.kicad_drc.clean:
            expected.append("KiCad DRC/connectivity/parity is not clean")
        for kind in RoutedVerificationKind:
            if not self.verification.record(kind).accepted:
                expected.append(f"{kind.value} verification rejected the candidate")
        if self.applicability_execution.authority is not ProjectExecutionAuthority.READY:
            expected.append("PCBSmith applicability/engineering execution is blocked")
        if self.blockers != tuple(expected):
            raise ValueError("routing validation blockers are stale")
        require_sha256(self.validation_fingerprint, "validation_fingerprint")
        payload = self.model_dump(mode="json", exclude={"validation_fingerprint"})
        if self.validation_fingerprint != fingerprint(payload):
            raise ValueError("routing validation fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        board_sha256: str,
        saved_board_routing: SavedBoardRoutingEvidence,
        kicad_drc: KiCadDrcEvidence,
        verification: RoutedBoardVerificationEvidence,
        applicability_execution: ProjectApplicabilityExecutionManifest,
        semantic_readback_accepted: bool,
    ) -> RoutingCandidateValidationBundle:
        blockers: list[str] = []
        if not semantic_readback_accepted:
            blockers.append("saved candidate changed immutable board semantics")
        if saved_board_routing.state is not RoutingArtifactState.ROUTED_CANDIDATE:
            blockers.append(f"saved board routing state is {saved_board_routing.state.value}")
        if not kicad_drc.clean:
            blockers.append("KiCad DRC/connectivity/parity is not clean")
        for kind in RoutedVerificationKind:
            if not verification.record(kind).accepted:
                blockers.append(f"{kind.value} verification rejected the candidate")
        if applicability_execution.authority is not ProjectExecutionAuthority.READY:
            blockers.append("PCBSmith applicability/engineering execution is blocked")
        fields: dict[str, Any] = {
            "board_sha256": board_sha256,
            "saved_board_routing": saved_board_routing,
            "kicad_drc": kicad_drc,
            "verification": verification,
            "applicability_execution": applicability_execution,
            "semantic_readback_accepted": semantic_readback_accepted,
            "blockers": tuple(blockers),
        }
        provisional = cls.model_construct(**fields, validation_fingerprint="0" * 64)
        return cls(
            **fields,
            validation_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"validation_fingerprint"})
            ),
        )

    @property
    def accepted(self) -> bool:
        return not self.blockers


class RoutingCandidateTransactionStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"


class RoutingCandidateTransactionResult(SemanticIrModel):
    """Retained outcome of one isolated routing-candidate transaction."""

    schema_id: Literal["pcbsmith-routing-candidate-transaction-result"] = (
        "pcbsmith-routing-candidate-transaction-result"
    )
    schema_version: Literal[1] = 1
    candidate_id: str
    request_fingerprint: str
    input_snapshot_fingerprint: str
    candidate: RouteCandidateResult | None
    validation: RoutingCandidateValidationBundle | None
    generation_transaction: GenerationTransactionResult | None
    status: RoutingCandidateTransactionStatus
    failures: tuple[RouteFailureEvidence, ...]
    canonical_pointer_sha256_before: str | None
    canonical_pointer_sha256_after: str | None
    retained_directory: str
    result_fingerprint: str

    @model_validator(mode="after")
    def result_is_coherent(self) -> Self:
        require_identity(self.candidate_id, "candidate_id")
        require_sha256(self.request_fingerprint, "request_fingerprint")
        require_sha256(self.input_snapshot_fingerprint, "input_snapshot_fingerprint")
        for digest in (
            self.canonical_pointer_sha256_before,
            self.canonical_pointer_sha256_after,
        ):
            if digest is not None:
                require_sha256(digest, "canonical_pointer_sha256")
        failures = tuple(sorted(self.failures, key=lambda item: item.failure_id))
        if len(failures) != len({item.failure_id for item in failures}):
            raise ValueError("routing transaction failure identities must be unique")
        if self.status is RoutingCandidateTransactionStatus.ACCEPTED:
            if failures or self.validation is None or not self.validation.accepted:
                raise ValueError("accepted routing transaction requires clean validation")
            if (
                self.generation_transaction is None
                or self.generation_transaction.manifest.status != "committed"
            ):
                raise ValueError("accepted routing transaction requires atomic publication")
        elif not failures:
            raise ValueError("non-accepted routing transaction requires failure evidence")
        object.__setattr__(self, "failures", failures)
        require_sha256(self.result_fingerprint, "result_fingerprint")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("routing transaction result fingerprint is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> RoutingCandidateTransactionResult:
        fields = dict(values)
        fields["failures"] = tuple(
            sorted(fields.get("failures", ()), key=lambda item: item.failure_id)
        )
        provisional = cls.model_construct(**fields, result_fingerprint="0" * 64)
        return cls(
            **fields,
            result_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"result_fingerprint"})
            ),
        )


class AcceptedRoutingExecution(SemanticIrModel):
    """Portable proof that an accepted routing transaction produced one board."""

    schema_id: Literal["pcbsmith-accepted-routing-execution"] = (
        "pcbsmith-accepted-routing-execution"
    )
    schema_version: Literal[1] = 1
    candidate_id: str
    board_sha256: str
    request_fingerprint: str
    input_snapshot_fingerprint: str
    candidate_result_fingerprint: str
    routing_transaction_fingerprint: str
    engine: RoutingEngineIdentity
    termination: RouteTerminationEvidence
    routing_generation_id: str
    routing_generation_sha256: str
    routing_generation_transaction_fingerprint: str
    receipt_fingerprint: str

    @model_validator(mode="after")
    def receipt_is_exact_and_completed(self) -> Self:
        require_identity(self.candidate_id, "candidate_id")
        require_identity(self.routing_generation_id, "routing_generation_id")
        for field_name in (
            "board_sha256",
            "request_fingerprint",
            "input_snapshot_fingerprint",
            "candidate_result_fingerprint",
            "routing_transaction_fingerprint",
            "routing_generation_sha256",
            "routing_generation_transaction_fingerprint",
            "receipt_fingerprint",
        ):
            require_sha256(getattr(self, field_name), field_name)
        if self.termination.state is not RouteTerminationState.COMPLETED:
            raise ValueError("accepted routing execution requires completed termination")
        payload = self.model_dump(mode="json", exclude={"receipt_fingerprint"})
        if self.receipt_fingerprint != fingerprint(payload):
            raise ValueError("accepted routing execution fingerprint is stale")
        return self

    @classmethod
    def from_transaction(
        cls,
        transaction: RoutingCandidateTransactionResult,
    ) -> AcceptedRoutingExecution:
        """Derive a publication receipt only from a fully accepted transaction."""

        if transaction.status is not RoutingCandidateTransactionStatus.ACCEPTED:
            raise ValueError("routing execution receipt requires an accepted transaction")
        candidate = transaction.candidate
        validation = transaction.validation
        generation = transaction.generation_transaction
        if candidate is None or candidate.partial_status is not PartialCandidateStatus.COMPLETE:
            raise ValueError("accepted routing execution requires a complete candidate result")
        if validation is None or not validation.accepted:
            raise ValueError("accepted routing execution requires accepted validation")
        if generation is None or generation.manifest.status != "committed":
            raise ValueError("accepted routing execution requires a committed generation")
        if generation.manifest.stage is not WorkflowStage.ROUTING:
            raise ValueError("accepted routing execution requires a routing-stage generation")
        board_artifacts = tuple(
            artifact for artifact in generation.manifest.artifacts if artifact.role == "board"
        )
        if len(board_artifacts) != 1:
            raise ValueError("routing generation must contain exactly one board artifact")
        if board_artifacts[0].content_sha256 != validation.board_sha256:
            raise ValueError("routing generation board does not match accepted validation")
        fields: dict[str, Any] = {
            "candidate_id": transaction.candidate_id,
            "board_sha256": validation.board_sha256,
            "request_fingerprint": transaction.request_fingerprint,
            "input_snapshot_fingerprint": transaction.input_snapshot_fingerprint,
            "candidate_result_fingerprint": candidate.semantic_fingerprint(),
            "routing_transaction_fingerprint": transaction.result_fingerprint,
            "engine": candidate.engine,
            "termination": candidate.termination,
            "routing_generation_id": generation.manifest.generation_id,
            "routing_generation_sha256": generation.manifest.generation_sha256,
            "routing_generation_transaction_fingerprint": (
                generation.manifest.transaction_fingerprint
            ),
        }
        provisional = cls.model_construct(**fields, receipt_fingerprint="0" * 64)
        return cls(
            **fields,
            receipt_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"receipt_fingerprint"})
            ),
        )


CandidateRunner = Callable[[RouteRequest, Path], RouteCandidateResult]
CandidateValidator = Callable[
    [Path, RouteRequest, KiCadBoardReadbackSnapshot, Path],
    RoutingCandidateValidationBundle,
]
GenerationCommitter = Callable[..., GenerationTransactionResult]


def _verify_frozen_snapshot(
    *,
    request: RouteRequest,
    snapshot: RoutingCandidateInputSnapshot,
    payloads: Mapping[str, bytes],
    source_layout: BoardLayout,
    netlist: BoardNetlist,
    profile: PcbRuleProfile,
) -> None:
    if request.inputs != snapshot.identity:
        raise ValueError("route request does not bind the frozen input snapshot")
    expected = {item.relative_path: item.content_sha256 for item in snapshot.artifacts}
    actual = {path: _sha256(payload) for path, payload in payloads.items()}
    if actual != expected:
        raise ValueError("frozen routing input artifacts are missing, added, or stale")
    if actual[snapshot.board_relative_path] != request.inputs.board_sha256:
        raise ValueError("route request board hash is stale")
    recomputed = freeze_native_routing_inputs(
        payloads=payloads,
        roles={item.relative_path: item.role for item in snapshot.artifacts},
        board_relative_path=snapshot.board_relative_path,
        schematic_relative_paths=snapshot.schematic_relative_paths,
        layout=source_layout,
        netlist=netlist,
        profile=profile,
        protected_objects=request.protected_policy.protected_objects,
    )
    if recomputed.identity != snapshot.identity:
        raise ValueError("routing input semantic identities are stale")
    if recomputed.snapshot_fingerprint != snapshot.snapshot_fingerprint:
        raise ValueError("routing input snapshot does not replay exactly")


def _point_tuple(point: RoutePoint) -> tuple[float, float]:
    return (point.x_mm, point.y_mm)


def _zone_rectangle(
    geometry: RouteZoneGeometry,
) -> tuple[str, str, tuple[float, float, float, float]]:
    points = {_point_tuple(point) for point in geometry.boundary}
    xs = sorted({point[0] for point in points})
    ys = sorted({point[1] for point in points})
    if len(points) != 4 or len(xs) != 2 or len(ys) != 2:
        raise ValueError("native board serialization only supports rectangular route zones")
    expected = {(x, y) for x in xs for y in ys}
    if points != expected:
        raise ValueError("native board serialization only supports rectangular route zones")
    return (geometry.net_name, geometry.layer, (xs[0], ys[0], xs[1], ys[1]))


def apply_declared_route_deltas(
    *,
    request: RouteRequest,
    candidate: RouteCandidateResult,
    source_layout: BoardLayout,
) -> BoardLayout:
    """Apply exactly the declared geometry mutations to a detached layout."""

    validate_route_candidate_result(request, candidate)
    via_technology_id = (
        request.via_technologies[0].technology_id
        if request.via_technologies
        else "via:through-default"
    )
    bindings = native_source_route_object_bindings(
        source_layout,
        source_board_sha256=request.inputs.board_sha256,
        via_technology_id=via_technology_id,
    )
    binding_by_key = {
        (item.identity.object_kind, item.identity.object_id): item for item in bindings
    }
    removed: dict[RouteObjectKind, set[int]] = {
        RouteObjectKind.SEGMENT: set(),
        RouteObjectKind.VIA: set(),
        RouteObjectKind.ZONE: set(),
    }
    added_segments: list[TrackSegment] = []
    added_vias: list[ViaSpec] = []
    added_zones: list[tuple[str, str, tuple[float, float, float, float]]] = []

    for kind, deltas in (
        (RouteObjectKind.SEGMENT, candidate.segment_deltas),
        (RouteObjectKind.VIA, candidate.via_deltas),
        (RouteObjectKind.ZONE, candidate.zone_deltas),
    ):
        for delta in deltas:
            if delta.source_object_id is not None:
                binding = binding_by_key[(kind, delta.source_object_id)]
                removed[kind].add(binding.source_index)
            geometry = delta.after
            if geometry is None:
                continue
            if isinstance(geometry, RouteSegmentGeometry):
                added_segments.append(
                    TrackSegment(
                        x1=geometry.start.x_mm,
                        y1=geometry.start.y_mm,
                        x2=geometry.end.x_mm,
                        y2=geometry.end.y_mm,
                        layer=geometry.layer,
                        net_name=geometry.net_name,
                        width_mm=geometry.width_mm,
                    )
                )
            elif isinstance(geometry, RouteViaGeometry):
                added_vias.append(
                    ViaSpec(
                        x=geometry.position.x_mm,
                        y=geometry.position.y_mm,
                        net_name=geometry.net_name,
                        size_mm=geometry.diameter_mm,
                        drill_mm=geometry.drill_mm,
                    )
                )
            else:
                added_zones.append(_zone_rectangle(geometry))
    return replace(
        source_layout,
        segments=tuple(
            item
            for index, item in enumerate(source_layout.segments)
            if index not in removed[RouteObjectKind.SEGMENT]
        )
        + tuple(added_segments),
        vias=tuple(
            item
            for index, item in enumerate(source_layout.vias)
            if index not in removed[RouteObjectKind.VIA]
        )
        + tuple(added_vias),
        zones=tuple(
            item
            for index, item in enumerate(source_layout.zones)
            if index not in removed[RouteObjectKind.ZONE]
        )
        + tuple(added_zones),
    )


def require_saved_layout_matches(
    source_text: str, layout: BoardLayout, netlist: BoardNetlist, profile: PcbRuleProfile
) -> None:
    """Check detached geometry/electrics against native input, excluding object IDs.

    IDs are not represented in BoardLayout. They are preserved separately by
    render_native_routing_candidate, then compared without exclusions on output.
    """

    def without_ids(value: Any) -> Any:
        if isinstance(value, list):
            # Hidden custom properties have no rendered orientation. Native
            # footprint rotation updates these angles; the detached serializer
            # emits zero. Preserve their names, values, positions and visibility.
            # Exact native objects are still retained by the candidate adapter.
            if (
                len(value) >= 3
                and value[0] == {"atom": "property"}
                and value[1] not in ({"quoted": "Reference"}, {"quoted": "Value"})
                and [{"atom": "hide"}, {"atom": "yes"}] in value
            ):
                value = [
                    [*item[:3], {"atom": "0"}, *item[4:]]
                    if isinstance(item, list) and len(item) >= 4 and item[0] == {"atom": "at"}
                    else item
                    for item in value
                ]
            # KiCad's omitted rotation is exactly zero, including pads.
            if len(value) == 3 and value[0] == {"atom": "at"}:
                value = [*value, {"atom": "0"}]
            # Native KiCad saves equivalent 270-degree placements as -90.
            # Normalize only the angular field, preserving all geometry/nets.
            if len(value) >= 4 and value[0] == {"atom": "at"}:
                from decimal import Decimal

                angle = value[3]
                if isinstance(angle, dict) and set(angle) == {"atom"}:
                    wrapped = Decimal(angle["atom"]) % 360
                    if wrapped < 0:
                        wrapped += 360
                    value = [*value[:3], {"atom": str(wrapped.normalize())}, *value[4:]]
            return [
                without_ids(item)
                for item in value
                if not (
                    isinstance(item, list)
                    and item
                    and item[0] in ({"atom": "uuid"}, {"atom": "tstamp"})
                )
            ]
        return value

    def semantics(snapshot: KiCadBoardReadbackSnapshot) -> dict[str, list[str]]:
        return {
            key: sorted(json.dumps(without_ids(json.loads(item)), sort_keys=True) for item in items)
            for key, items in snapshot.model_dump().items()
            if key not in {"schema_id", "schema_version"}
        }

    native = extract_kicad_board_readback(source_text)
    detached = extract_kicad_board_readback(
        render_board_from_layout(netlist, layout, profile=profile)
    )
    if semantics(native) != semantics(detached):
        raise ValueError(
            "detached layout does not match saved board geometry and electrical semantics"
        )


def render_native_routing_candidate(
    source_text: str,
    source_layout: BoardLayout,
    routed_layout: BoardLayout,
    netlist: BoardNetlist,
    profile: PcbRuleProfile,
) -> str:
    """Serialize routed copper into the exact saved non-copper object tree.

    The detached source is checked first, preventing stale placement/rule data.
    This initial-routing adapter does not replace existing routes: those require
    the existing transaction path until a native route-ID binding is supported.
    """
    from pcbsmith.kicad.library import _atom, parse_sexpr, serialize_sexpr

    require_saved_layout_matches(source_text, source_layout, netlist, profile)
    source = parse_sexpr(source_text)
    route_heads = {"segment", "arc", "via", "zone"}
    if any(isinstance(n, list) and n and _atom(n[0]) in route_heads for n in source):
        # Preserve the existing adapter for copper revisions; its strict full
        # immutable readback check remains authoritative.
        return render_board_from_layout(netlist, routed_layout, profile=profile)
    generated = parse_sexpr(render_board_from_layout(netlist, routed_layout, profile=profile))
    copper = [n for n in generated if isinstance(n, list) and n and _atom(n[0]) in route_heads]
    result = serialize_sexpr([*source, *copper]) + "\n"
    if not immutable_readback_matches(
        extract_kicad_board_readback(source_text), extract_kicad_board_readback(result)
    ):
        raise ValueError("routing serialization changed saved non-copper objects")
    return result


_IMMUTABLE_READBACK_FIELDS = (
    "footprints",
    "edge_cuts",
    "board_graphics",
    "nets",
    "layers",
    "setup",
)


def immutable_readback_matches(
    source: KiCadBoardReadbackSnapshot,
    candidate: KiCadBoardReadbackSnapshot,
) -> bool:
    """Return whether every non-route KiCad read-back category is unchanged."""

    return all(
        getattr(source, field) == getattr(candidate, field) for field in _IMMUTABLE_READBACK_FIELDS
    )


def _pointer_sha256(root: Path) -> str | None:
    pointer = root / "CURRENT.json"
    return _sha256(pointer.read_bytes()) if pointer.exists() else None


def _failure(kind: RouteFailureKind, message: str) -> RouteFailureEvidence:
    return RouteFailureEvidence(
        failure_id=f"failure:transaction:{kind.value}",
        kind=kind,
        message=message,
    )


def _write_json(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _retain_candidate(work_root: Path, retained_root: Path) -> Path:
    retained_root.parent.mkdir(parents=True, exist_ok=True)
    if retained_root.exists():
        raise ValueError(f"routing candidate path already exists: {retained_root}")
    os.replace(work_root, retained_root)
    return retained_root


def run_routing_candidate_transaction(
    *,
    transaction_root: Path,
    project_id: str,
    candidate_id: str,
    generation_id: str,
    request: RouteRequest,
    input_snapshot: RoutingCandidateInputSnapshot,
    input_payloads: Mapping[str, bytes],
    source_layout: BoardLayout,
    netlist: BoardNetlist,
    engine_runner: CandidateRunner,
    validator: CandidateValidator,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    generation_committer: GenerationCommitter = commit_generation_transaction,
    revalidate_result: Path | None = None,
    revalidate_sha256: str | None = None,
    repair_plane_clearance_mm: float | None = None,
    native_repair: RetainedNativeRepair | None = None,
) -> RoutingCandidateTransactionResult:
    """Run, validate, retain, and conditionally publish one route candidate."""

    if native_repair is not None and (
        revalidate_result is None or repair_plane_clearance_mm is None
    ):
        raise ValueError("native repair requires retained-candidate plane revalidation")
    if repair_plane_clearance_mm is not None:
        import math

        if (
            revalidate_result is None
            or not math.isfinite(repair_plane_clearance_mm)
            or repair_plane_clearance_mm < profile.fab_spacing.minimum_copper_clearance_mm
        ):
            raise ValueError(
                "plane repair requires a retained candidate and operative minimum clearance"
            )
    require_identity(project_id, "project_id")
    require_identity(candidate_id, "candidate_id")
    require_identity(generation_id, "generation_id")
    root = transaction_root.resolve()
    retained_root = root / "routing-candidates" / candidate_id
    pointer_before = _pointer_sha256(root)
    candidate: RouteCandidateResult | None = None
    validation: RoutingCandidateValidationBundle | None = None
    generation_transaction: GenerationTransactionResult | None = None
    failures: tuple[RouteFailureEvidence, ...] = ()
    status = RoutingCandidateTransactionStatus.REJECTED

    work_parent = root / ".routing-candidate-work"
    work_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"{candidate_id}-", dir=work_parent) as temporary:
        work_root = Path(temporary)
        try:
            _verify_frozen_snapshot(
                request=request,
                snapshot=input_snapshot,
                payloads=input_payloads,
                source_layout=source_layout,
                netlist=netlist,
                profile=profile,
            )
            source_board = input_payloads[input_snapshot.board_relative_path]
            comparison_source = (
                native_repair.apply(source_board, source_only=True)[0]
                if native_repair
                else source_board
            )
            source_readback = extract_kicad_board_readback(comparison_source.decode("utf-8"))
            _write_json(work_root / "request.json", request)
            _write_json(work_root / "input-snapshot.json", input_snapshot)
            for item in input_snapshot.artifacts:
                target = work_root / "inputs" / PurePosixPath(item.relative_path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(input_payloads[item.relative_path])
            stdout_file = work_root / "engine" / "stdout.log"
            stderr_file = work_root / "engine" / "stderr.log"
            stdout_file.parent.mkdir(parents=True, exist_ok=True)
            stdout_file.write_bytes(b"")
            stderr_file.write_bytes(b"")
            previous_board: bytes | None = None
            if revalidate_result is None:
                if revalidate_sha256 is not None:
                    raise ValueError("revalidation hash requires a retained result")
                candidate = engine_runner(request, work_root)
            else:
                prior_raw = revalidate_result.read_bytes()
                if _sha256(prior_raw) != revalidate_sha256:
                    raise ValueError("retained routing result changed")
                prior = RoutingCandidateTransactionResult.model_validate_json(prior_raw)
                prior_root = Path(prior.retained_directory)
                if prior.status is not RoutingCandidateTransactionStatus.REJECTED:
                    raise ValueError("revalidation requires a rejected retained transaction")
                if (
                    prior.request_fingerprint != request.semantic_fingerprint()
                    or prior.input_snapshot_fingerprint != input_snapshot.snapshot_fingerprint
                ):
                    raise ValueError("retained routing inputs differ from current request")
                if (
                    RouteRequest.model_validate_json((prior_root / "request.json").read_bytes())
                    != request
                ):
                    raise ValueError("retained routing request changed")
                if (
                    RoutingCandidateInputSnapshot.model_validate_json(
                        (prior_root / "input-snapshot.json").read_bytes()
                    )
                    != input_snapshot
                ):
                    raise ValueError("retained routing snapshot changed")
                for item in input_snapshot.artifacts:
                    if (
                        prior_root / "inputs" / PurePosixPath(item.relative_path)
                    ).read_bytes() != input_payloads[item.relative_path]:
                        raise ValueError("retained source payload changed")
                candidate = RouteCandidateResult.model_validate_json(
                    (prior_root / "candidate-result.json").read_bytes()
                )
                if (
                    candidate != prior.candidate
                    or candidate.partial_status is not PartialCandidateStatus.COMPLETE
                ):
                    raise ValueError("retained candidate changed or is incomplete")
                previous_file = (
                    prior_root / "candidate" / PurePosixPath(input_snapshot.board_relative_path)
                )
                log_root = prior_root / "engine"
                early_external_log_rejection = (
                    not previous_file.exists()
                    and candidate.engine.engine_id == "freerouting-v2.3.0"
                    and len(prior.failures) == 1
                    and prior.failures[0].message
                    == "ValueError: candidate stdout evidence hash is stale"
                    and prior.validation is None
                    and prior.generation_transaction is None
                )
                if early_external_log_rejection:
                    # Historical dispatch retained genuine logs one directory
                    # deeper and failed before materialization. Replay exact
                    # deltas; normal hash checks and native validation follow.
                    log_root = prior_root / "freerouting" / "engine"
                else:
                    previous_board = previous_file.read_bytes()
                stdout_file.write_bytes((log_root / "stdout.log").read_bytes())
                stderr_file.write_bytes((log_root / "stderr.log").read_bytes())
                (work_root / "revalidated-predecessor.json").write_bytes(prior_raw)

            _write_json(work_root / "candidate-result.json", candidate)
            validate_route_candidate_result(request, candidate)
            if candidate.termination.stdout_sha256 != _sha256(stdout_file.read_bytes()):
                raise ValueError("candidate stdout evidence hash is stale")
            if candidate.termination.stderr_sha256 != _sha256(stderr_file.read_bytes()):
                raise ValueError("candidate stderr evidence hash is stale")
            if candidate.partial_status is not PartialCandidateStatus.COMPLETE:
                failures = candidate.failures or (
                    _failure(
                        RouteFailureKind.VALIDATION_FAILED,
                        f"candidate status is {candidate.partial_status.value}",
                    ),
                )
            else:
                routed_layout = apply_declared_route_deltas(
                    request=request,
                    candidate=candidate,
                    source_layout=source_layout,
                )
                board_text = render_native_routing_candidate(
                    source_board.decode("utf-8"), source_layout, routed_layout, netlist, profile
                )
                board_file = (
                    work_root / "candidate" / PurePosixPath(input_snapshot.board_relative_path)
                )
                board_file.parent.mkdir(parents=True, exist_ok=True)
                board_file.write_bytes(board_text.encode("utf-8"))
                if routed_layout.zones:
                    from pcbsmith.kicad.library import parse_sexpr
                    from pcbsmith.kicad.native_edits import atom, child, children
                    from pcbsmith.kicad.native_zone_edits import refill_native_edit

                    prefix = str(PurePosixPath(input_snapshot.board_relative_path).parent) + "/"
                    for relative, data in input_payloads.items():
                        if (
                            relative.startswith(prefix)
                            and relative != input_snapshot.board_relative_path
                        ):
                            target = board_file.parent / PurePosixPath(relative[len(prefix) :])
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(data)
                    zone_ids = tuple(
                        atom(child(z, "uuid")[1]) for z in children(parse_sexpr(board_text), "zone")
                    )
                    filled_payload, _ = refill_native_edit(
                        board_file, work_root / "final-fill", zone_ids
                    )
                    board_text = filled_payload.decode("utf-8")
                    board_file.write_bytes(filled_payload)
                if previous_board is not None and board_text.encode("utf-8") != previous_board:
                    raise ValueError("revalidation would change retained board bytes")
                if repair_plane_clearance_mm is not None:
                    from pcbsmith.kicad.native_edits import NativeEdit, apply_native_edits

                    if previous_board is None or not routed_layout.zones:
                        raise ValueError("plane repair requires retained filled zones")
                    repair_input = previous_board
                    if native_repair is not None:
                        if _sha256(previous_board) != native_repair.predecessor_board_sha256:
                            raise ValueError("local repair predecessor board changed")
                        repair_input, native_delta = native_repair.apply(
                            previous_board, allowed_zone_ids=zone_ids
                        )
                        _write_json(work_root / "native-repair-request.json", native_repair)
                        (work_root / "native-repair-delta.json").write_text(
                            json.dumps(native_delta, indent=2), encoding="utf-8"
                        )
                    edits = tuple(
                        NativeEdit(
                            kind="zone_clearance",
                            target=identity,
                            clearance_mm=repair_plane_clearance_mm,
                        )
                        for identity in zone_ids
                    )
                    repaired, delta = apply_native_edits(
                        repair_input,
                        edits,
                        maximum_displacement_mm=1,
                        maximum_changed_objects=len(zone_ids),
                        allowed_zone_ids=zone_ids,
                    )
                    board_file.write_bytes(repaired)
                    repaired, repair_closure = refill_native_edit(
                        board_file, work_root / "plane-repair-fill", zone_ids
                    )
                    board_file.write_bytes(repaired)
                    board_text = repaired.decode("utf-8")
                    (work_root / "native-plane-repair.json").write_text(
                        json.dumps(
                            {
                                "kind": "retained-candidate-zone-clearance",
                                "predecessor_result_sha256": revalidate_sha256,
                                "predecessor_board_sha256": _sha256(previous_board),
                                "board_sha256": _sha256(repaired),
                                "clearance_mm": repair_plane_clearance_mm,
                                "minimum_clearance_mm": (
                                    profile.fab_spacing.minimum_copper_clearance_mm
                                ),
                                "delta": delta,
                                "fill_closure": repair_closure,
                                "router_executed": False,
                            },
                            indent=2,
                        ),
                        encoding="utf-8",
                    )
                candidate_readback = extract_kicad_board_readback(board_text)
                semantic_accepted = immutable_readback_matches(
                    source_readback,
                    candidate_readback,
                )
                produced_validation = validator(
                    board_file,
                    request,
                    candidate_readback,
                    work_root,
                )
                if produced_validation.semantic_readback_accepted != semantic_accepted:
                    raise ValueError("validator semantic read-back disposition is stale")
                if produced_validation.board_sha256 != _sha256(board_text.encode("utf-8")):
                    raise ValueError("validator targets a different candidate board")
                entry_payload = input_payloads.get("evidence/routing-entry.json")
                if entry_payload is not None:
                    from pcbsmith.production_workflow import (
                        RoutingEntryGateReport,
                        require_routed_engineering_closure,
                    )
                    from pcbsmith.project_engineering_gate_ir import ProjectEngineeringGateResult

                    entry = RoutingEntryGateReport.model_validate_json(entry_payload)
                    if not entry.allowed or entry.saved_board_sha256 != request.inputs.board_sha256:
                        raise ValueError(
                            "retained routing entry does not admit these source inputs"
                        )
                    if entry.deferred_routed_features:
                        closure = work_root / "verification/engineering-gate.json"
                        if not closure.is_file():
                            raise ValueError("deferred routed engineering closure is missing")
                        final_gate = ProjectEngineeringGateResult.model_validate_json(
                            closure.read_bytes()
                        )
                        require_routed_engineering_closure(entry, final_gate)
                        from pcbsmith.kicad.board_serialization import (
                            board_layout_snapshot_fingerprint,
                            canonical_board_layout_snapshot_json,
                            canonical_board_netlist_snapshot_json,
                        )

                        if (
                            final_gate.context.board_netlist_snapshot_json
                            != canonical_board_netlist_snapshot_json(netlist)
                        ):
                            raise ValueError(
                                "routed engineering closure targets a different netlist"
                            )
                        actual_layout = board_layout_snapshot_fingerprint(
                            canonical_board_layout_snapshot_json(routed_layout)
                        )
                        if final_gate.context.board_layout_snapshot_fingerprint != actual_layout:
                            raise ValueError(
                                "routed engineering closure targets a different layout"
                            )
                validation = produced_validation
                _write_json(work_root / "validation.json", validation)
                if not validation.accepted:
                    failures = (
                        _failure(
                            RouteFailureKind.VALIDATION_FAILED,
                            "; ".join(validation.blockers),
                        ),
                    )
                else:
                    payloads: dict[str, bytes] = {
                        f"routing-candidate/{path.relative_to(work_root).as_posix()}": (
                            path.read_bytes()
                        )
                        for path in sorted(work_root.rglob("*"))
                        if path.is_file()
                    }
                    board_relative_path = input_snapshot.board_relative_path
                    payloads[board_relative_path] = board_text.encode("utf-8")
                    roles: dict[str, ArtifactRole] = {
                        path: (
                            "board"
                            if path == board_relative_path
                            else "verification"
                            if path.endswith(".json")
                            else "evidence"
                        )
                        for path in payloads
                    }
                    generation_sha256 = _aggregate_payload_identity(
                        payloads,
                        tuple(payloads),
                        schema_id="pcbsmith-routing-generation",
                    )
                    staged = prepare_generation_transaction(
                        project_id=project_id,
                        generation_id=generation_id,
                        generation_sha256=generation_sha256,
                        stage=WorkflowStage.ROUTING,
                        payloads=payloads,
                        roles=roles,
                        previous_current_sha256=pointer_before,
                    )
                    try:
                        generation_transaction = generation_committer(
                            transaction_root=root,
                            manifest=staged,
                            payloads=payloads,
                        )
                    except Exception as exc:
                        status = RoutingCandidateTransactionStatus.ROLLBACK_FAILED
                        failures = (
                            _failure(
                                RouteFailureKind.ROLLBACK_FAILED,
                                f"{type(exc).__name__}: {exc}",
                            ),
                        )
                    else:
                        if generation_transaction.manifest.status == "committed":
                            status = RoutingCandidateTransactionStatus.ACCEPTED
                        else:
                            status = RoutingCandidateTransactionStatus.ROLLED_BACK
                            failures = (
                                _failure(
                                    RouteFailureKind.VALIDATION_FAILED,
                                    generation_transaction.manifest.reason
                                    or "generation transaction rolled back",
                                ),
                            )
        except Exception as exc:
            failures = (
                _failure(
                    RouteFailureKind.VALIDATION_FAILED,
                    f"{type(exc).__name__}: {exc}",
                ),
            )
        finally:
            _retain_candidate(work_root, retained_root)

    pointer_after = _pointer_sha256(root)
    if status is not RoutingCandidateTransactionStatus.ACCEPTED:
        if pointer_after != pointer_before:
            status = RoutingCandidateTransactionStatus.ROLLBACK_FAILED
            failures = (
                _failure(
                    RouteFailureKind.ROLLBACK_FAILED,
                    "canonical generation pointer changed after candidate rejection",
                ),
            )
    return RoutingCandidateTransactionResult.build(
        candidate_id=candidate_id,
        request_fingerprint=request.semantic_fingerprint(),
        input_snapshot_fingerprint=input_snapshot.snapshot_fingerprint,
        candidate=candidate,
        validation=validation,
        generation_transaction=generation_transaction,
        status=status,
        failures=failures,
        canonical_pointer_sha256_before=pointer_before,
        canonical_pointer_sha256_after=pointer_after,
        retained_directory=str(retained_root),
    )
