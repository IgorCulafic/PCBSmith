"""Engine-neutral, deterministic routing-run interchange models.

The current KiCad A* result types can be adapted into this schema later. This
module deliberately contains no router behavior or KiCad geometry types.
"""

from __future__ import annotations

import hashlib
import json
import math
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RoutingFailureReason(StrEnum):
    """Terminal reasons understood by routing orchestration."""

    UNROUTABLE = "unroutable"
    EXPANSION_BUDGET = "expansion_budget"
    PASS_BUDGET = "pass_budget"
    STAGNATION = "stagnation"
    EXACT_CHECK_REJECTION = "exact_check_rejection"
    OVERUSE_REMAINING = "overuse_remaining"


class RoutingIrModel(BaseModel):
    """Frozen base with canonical semantic serialization."""

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        allow_inf_nan=False,
    )

    def semantic_json(self) -> str:
        """Return deterministic JSON suitable for cache and audit keys."""
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )

    def semantic_fingerprint(self) -> str:
        """SHA-256 of the complete versioned semantic representation."""
        return hashlib.sha256(self.semantic_json().encode("utf-8")).hexdigest()


def _require_identity(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a canonical non-empty identity")
    return value


def _require_sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")
    return value


def _canonical_identities(
    values: tuple[str, ...],
    field_name: str,
    *,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    canonical = tuple(sorted(_require_identity(value, field_name) for value in values))
    if len(canonical) != len(set(canonical)):
        raise ValueError(f"{field_name} must contain unique identities")
    if not allow_empty and not canonical:
        raise ValueError(f"{field_name} must not be empty")
    return canonical


def _finite_non_negative(value: float, field_name: str) -> float:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{field_name} must be finite and non-negative")
    return 0.0 if value == 0.0 else value


def _finite_positive(value: float, field_name: str) -> float:
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{field_name} must be finite and positive")
    return value


# Geometry requests and candidate deltas deliberately remain separate from the
# routing-run telemetry below. Telemetry describes search work; these models
# define what a backend was permitted to change and what it actually proposed.


class RouteObjectKind(StrEnum):
    SEGMENT = "segment"
    VIA = "via"
    ZONE = "zone"


class RouteMutationKind(StrEnum):
    ADD = "add"
    REMOVE = "remove"
    REPLACE = "replace"


class ProtectedObjectDisposition(StrEnum):
    REJECT_MUTATION = "reject_mutation"


class RouteConstraintDisposition(StrEnum):
    CONSUMED = "consumed"
    APPROXIMATED = "approximated"
    UNSUPPORTED = "unsupported"
    REJECTED = "rejected"


class RouteTerminationState(StrEnum):
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    BUDGET_EXHAUSTED = "budget_exhausted"
    TIMEOUT = "timeout"
    FAILED = "failed"


class PartialCandidateStatus(StrEnum):
    COMPLETE = "complete"
    BOUNDED_PARTIAL = "bounded_partial"
    FAILED_NO_DELTA = "failed_no_delta"
    REJECTED = "rejected"


class RouteFailureKind(StrEnum):
    UNSUPPORTED_CONSTRAINT = "unsupported_constraint"
    REJECTED_CONSTRAINT = "rejected_constraint"
    PROTECTED_OBJECT_MUTATION = "protected_object_mutation"
    SEMANTIC_DRIFT = "semantic_drift"
    STALE_INPUT = "stale_input"
    DUPLICATE_IDENTITY = "duplicate_identity"
    MISSING_IDENTITY = "missing_identity"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CANCELLED = "cancelled"
    ENGINE_FAILURE = "engine_failure"
    INVALID_DELTA = "invalid_delta"
    ROLLBACK_FAILED = "rollback_failed"
    VALIDATION_FAILED = "validation_failed"
    UNROUTABLE = "unroutable"


class RoutePoint(RoutingIrModel):
    """One finite point in the canonical board coordinate system."""

    x_mm: float
    y_mm: float

    @field_validator("x_mm", "y_mm")
    @classmethod
    def coordinates_are_finite(cls, value: float, info: Any) -> float:
        if not math.isfinite(value):
            raise ValueError(f"{info.field_name} must be finite")
        return 0.0 if value == 0.0 else value


class StableRouteObjectIdentity(RoutingIrModel):
    """Stable identity for one source-board route object."""

    object_id: str = Field(min_length=1)
    object_kind: RouteObjectKind
    source_board_sha256: str
    source_object_fingerprint: str

    @field_validator("object_id")
    @classmethod
    def object_id_is_canonical(cls, value: str) -> str:
        return _require_identity(value, "object_id")

    @field_validator("source_board_sha256", "source_object_fingerprint")
    @classmethod
    def digests_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)


class RoutingInputIdentity(RoutingIrModel):
    """Frozen identities for every non-routing input authority."""

    schema_id: Literal["pcbsmith-routing-input-identity"] = "pcbsmith-routing-input-identity"
    schema_version: Literal[1] = 1
    project_sha256: str
    board_sha256: str
    schematic_sha256: str
    netlist_sha256: str
    placement_sha256: str
    outline_sha256: str
    holes_sha256: str
    rules_sha256: str
    protected_copper_sha256: str

    @field_validator(
        "project_sha256",
        "board_sha256",
        "schematic_sha256",
        "netlist_sha256",
        "placement_sha256",
        "outline_sha256",
        "holes_sha256",
        "rules_sha256",
        "protected_copper_sha256",
    )
    @classmethod
    def identities_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)


class TargetRouteNet(RoutingIrModel):
    """One target net with its complete stable terminal inventory."""

    net_name: str = Field(min_length=1)
    terminal_object_ids: tuple[str, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def target_net_is_canonical(self) -> Self:
        _require_identity(self.net_name, "net_name")
        terminals = _canonical_identities(
            self.terminal_object_ids,
            "terminal_object_ids",
            allow_empty=False,
        )
        object.__setattr__(self, "terminal_object_ids", terminals)
        return self


class TargetRouteDomain(RoutingIrModel):
    """One ordered routing domain and its exact net/terminal membership."""

    domain_id: str = Field(min_length=1)
    nets: tuple[TargetRouteNet, ...] = Field(min_length=1)
    priority: int = Field(ge=0)
    dependency_domain_ids: tuple[str, ...] = ()
    allow_partial: bool = False

    @model_validator(mode="after")
    def domain_is_canonical(self) -> Self:
        _require_identity(self.domain_id, "domain_id")
        nets = tuple(sorted(self.nets, key=lambda item: item.net_name))
        if len(nets) != len({item.net_name for item in nets}):
            raise ValueError("target route net identities must be unique within a domain")
        terminals = tuple(terminal for net in nets for terminal in net.terminal_object_ids)
        if len(terminals) != len(set(terminals)):
            raise ValueError("terminal object identities must belong to exactly one target net")
        dependencies = _canonical_identities(
            self.dependency_domain_ids,
            "dependency_domain_ids",
        )
        if self.domain_id in dependencies:
            raise ValueError("route domain cannot depend on itself")
        object.__setattr__(self, "nets", nets)
        object.__setattr__(self, "dependency_domain_ids", dependencies)
        return self

    @property
    def net_names(self) -> tuple[str, ...]:
        return tuple(item.net_name for item in self.nets)


class ProtectedRouteObjectPolicy(RoutingIrModel):
    """Closed fail-closed policy for source objects a backend cannot mutate."""

    disposition: Literal[ProtectedObjectDisposition.REJECT_MUTATION] = (
        ProtectedObjectDisposition.REJECT_MUTATION
    )
    protected_objects: tuple[StableRouteObjectIdentity, ...] = ()

    @model_validator(mode="after")
    def protected_identities_are_unique(self) -> Self:
        canonical = tuple(
            sorted(self.protected_objects, key=lambda item: (item.object_kind, item.object_id))
        )
        keys = tuple((item.object_kind, item.object_id) for item in canonical)
        if len(keys) != len(set(keys)):
            raise ValueError("protected route object identities must be unique")
        object.__setattr__(self, "protected_objects", canonical)
        return self


class RouteWidthConstraint(RoutingIrModel):
    constraint_id: str = Field(min_length=1)
    net_names: tuple[str, ...] = Field(min_length=1)
    minimum_width_mm: float
    preferred_width_mm: float
    maximum_width_mm: float

    @model_validator(mode="after")
    def width_range_is_canonical(self) -> Self:
        _require_identity(self.constraint_id, "constraint_id")
        nets = _canonical_identities(self.net_names, "net_names", allow_empty=False)
        minimum = _finite_positive(self.minimum_width_mm, "minimum_width_mm")
        preferred = _finite_positive(self.preferred_width_mm, "preferred_width_mm")
        maximum = _finite_positive(self.maximum_width_mm, "maximum_width_mm")
        if not minimum <= preferred <= maximum:
            raise ValueError("route widths must satisfy minimum <= preferred <= maximum")
        object.__setattr__(self, "net_names", nets)
        return self


class RouteClearanceConstraint(RoutingIrModel):
    constraint_id: str = Field(min_length=1)
    net_names: tuple[str, ...] = Field(min_length=1)
    other_net_names: tuple[str, ...] = ()
    minimum_clearance_mm: float

    @model_validator(mode="after")
    def clearance_is_canonical(self) -> Self:
        _require_identity(self.constraint_id, "constraint_id")
        nets = _canonical_identities(self.net_names, "net_names", allow_empty=False)
        others = _canonical_identities(self.other_net_names, "other_net_names")
        if set(nets) & set(others):
            raise ValueError("clearance constraint net sets must be disjoint")
        object.__setattr__(self, "net_names", nets)
        object.__setattr__(self, "other_net_names", others)
        object.__setattr__(
            self,
            "minimum_clearance_mm",
            _finite_non_negative(self.minimum_clearance_mm, "minimum_clearance_mm"),
        )
        return self


class RouteViaTechnology(RoutingIrModel):
    constraint_id: str = Field(min_length=1)
    technology_id: str = Field(min_length=1)
    start_layer: str = Field(min_length=1)
    end_layer: str = Field(min_length=1)
    diameter_mm: float
    drill_mm: float

    @model_validator(mode="after")
    def via_technology_is_physical(self) -> Self:
        for field_name in ("constraint_id", "technology_id", "start_layer", "end_layer"):
            _require_identity(getattr(self, field_name), field_name)
        if self.start_layer == self.end_layer:
            raise ValueError("via technology must connect distinct layers")
        diameter = _finite_positive(self.diameter_mm, "diameter_mm")
        drill = _finite_positive(self.drill_mm, "drill_mm")
        if drill >= diameter:
            raise ValueError("via drill must be smaller than via diameter")
        return self


class RouteGuide(RoutingIrModel):
    """A hard reservation or soft preference in board coordinates."""

    constraint_id: str = Field(min_length=1)
    guide_id: str = Field(min_length=1)
    guide_kind: Literal["centerline", "reserved_corridor", "forbidden_corridor"]
    domain_ids: tuple[str, ...] = ()
    net_names: tuple[str, ...] = ()
    layers: tuple[str, ...] = Field(min_length=1)
    points: tuple[RoutePoint, ...] = Field(min_length=2)
    half_width_mm: float
    hard: bool

    @model_validator(mode="after")
    def guide_is_canonical(self) -> Self:
        _require_identity(self.constraint_id, "constraint_id")
        _require_identity(self.guide_id, "guide_id")
        domains = _canonical_identities(self.domain_ids, "domain_ids")
        nets = _canonical_identities(self.net_names, "net_names")
        layers = _canonical_identities(self.layers, "layers", allow_empty=False)
        if not domains and not nets:
            raise ValueError("route guide must target a domain or net")
        if self.guide_kind == "forbidden_corridor" and not self.hard:
            raise ValueError("forbidden corridors must be hard constraints")
        object.__setattr__(self, "domain_ids", domains)
        object.__setattr__(self, "net_names", nets)
        object.__setattr__(self, "layers", layers)
        object.__setattr__(
            self,
            "half_width_mm",
            _finite_positive(self.half_width_mm, "half_width_mm"),
        )
        return self


class RouteTopologyConstraint(RoutingIrModel):
    """Explicit connection intent for a multi-terminal net."""

    constraint_id: str = Field(min_length=1)
    domain_id: str = Field(min_length=1)
    net_name: str = Field(min_length=1)
    topology_kind: Literal[
        "any_tree",
        "ordered_path",
        "star",
        "source_to_sinks",
        "paired_bundle",
    ]
    ordered_terminal_object_ids: tuple[str, ...] = Field(min_length=2)
    paired_net_names: tuple[str, ...] = ()

    @model_validator(mode="after")
    def topology_is_canonical(self) -> Self:
        for field_name in ("constraint_id", "domain_id", "net_name"):
            _require_identity(getattr(self, field_name), field_name)
        ordered = tuple(
            _require_identity(item, "ordered_terminal_object_ids")
            for item in self.ordered_terminal_object_ids
        )
        if len(ordered) != len(set(ordered)):
            raise ValueError("ordered topology terminals must be unique")
        paired = _canonical_identities(self.paired_net_names, "paired_net_names")
        if self.topology_kind == "paired_bundle":
            if not paired or self.net_name in paired:
                raise ValueError("paired-bundle topology requires distinct paired net identities")
        elif paired:
            raise ValueError("only paired-bundle topology may name paired nets")
        object.__setattr__(self, "ordered_terminal_object_ids", ordered)
        object.__setattr__(self, "paired_net_names", paired)
        return self


class DeterministicRoutingConfiguration(RoutingIrModel):
    """Backend-independent deterministic controls and explicit adapter options."""

    seed: int = Field(ge=0)
    route_order: tuple[str, ...]
    tie_break_policy: str = Field(min_length=1)
    worker_count: Literal[1] = 1
    adapter_options: tuple[tuple[str, str], ...] = ()

    @model_validator(mode="after")
    def configuration_is_canonical(self) -> Self:
        _require_identity(self.tie_break_policy, "tie_break_policy")
        order = tuple(_require_identity(item, "route_order") for item in self.route_order)
        if len(order) != len(set(order)):
            raise ValueError("route_order must contain unique net identities")
        options = tuple(sorted(self.adapter_options))
        if len(options) != len({key for key, _value in options}):
            raise ValueError("adapter option keys must be unique")
        for key, value in options:
            _require_identity(key, "adapter option key")
            _require_identity(value, "adapter option value")
        object.__setattr__(self, "route_order", order)
        object.__setattr__(self, "adapter_options", options)
        return self


class RouteRequest(RoutingIrModel):
    """Versioned immutable routing authority supplied to every engine."""

    schema_id: Literal["pcbsmith-route-request"] = "pcbsmith-route-request"
    schema_version: Literal[1] = 1
    request_id: str = Field(min_length=1)
    inputs: RoutingInputIdentity
    target_domains: tuple[TargetRouteDomain, ...] = Field(min_length=1)
    source_route_objects: tuple[StableRouteObjectIdentity, ...] = ()
    protected_policy: ProtectedRouteObjectPolicy
    allowed_layers: tuple[str, ...] = Field(min_length=1)
    width_constraints: tuple[RouteWidthConstraint, ...] = Field(min_length=1)
    clearance_constraints: tuple[RouteClearanceConstraint, ...] = Field(min_length=1)
    via_technologies: tuple[RouteViaTechnology, ...] = ()
    route_guides: tuple[RouteGuide, ...] = ()
    topology_constraints: tuple[RouteTopologyConstraint, ...] = Field(min_length=1)
    budget: RoutingBudget
    deterministic: DeterministicRoutingConfiguration
    additional_constraint_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def request_is_closed_and_canonical(self) -> Self:
        _require_identity(self.request_id, "request_id")
        layers = _canonical_identities(self.allowed_layers, "allowed_layers", allow_empty=False)
        domains = tuple(sorted(self.target_domains, key=lambda item: item.domain_id))
        domain_ids = tuple(item.domain_id for item in domains)
        if len(domain_ids) != len(set(domain_ids)):
            raise ValueError("target route domain identities must be unique")
        known_domains = set(domain_ids)
        if any(not set(domain.dependency_domain_ids).issubset(known_domains) for domain in domains):
            raise ValueError("route domain references an unknown dependency")
        all_nets = tuple(net for domain in domains for net in domain.net_names)
        if len(all_nets) != len(set(all_nets)):
            raise ValueError("target nets must belong to exactly one route domain")
        source_objects = tuple(
            sorted(
                self.source_route_objects,
                key=lambda item: (item.object_kind, item.object_id),
            )
        )
        source_keys = tuple((item.object_kind, item.object_id) for item in source_objects)
        if len(source_keys) != len(set(source_keys)):
            raise ValueError("source route object identities must be unique")
        if any(item.source_board_sha256 != self.inputs.board_sha256 for item in source_objects):
            raise ValueError("source route object belongs to a different board")
        source_by_key = {(item.object_kind, item.object_id): item for item in source_objects}
        for protected in self.protected_policy.protected_objects:
            key = (protected.object_kind, protected.object_id)
            if source_by_key.get(key) != protected:
                raise ValueError("protected route object is absent or stale in source inventory")
        widths = tuple(sorted(self.width_constraints, key=lambda item: item.constraint_id))
        clearances = tuple(sorted(self.clearance_constraints, key=lambda item: item.constraint_id))
        vias = tuple(sorted(self.via_technologies, key=lambda item: item.constraint_id))
        guides = tuple(sorted(self.route_guides, key=lambda item: item.constraint_id))
        topologies = tuple(sorted(self.topology_constraints, key=lambda item: item.constraint_id))
        additional = _canonical_identities(
            self.additional_constraint_ids,
            "additional_constraint_ids",
        )
        constraints = (
            tuple(item.constraint_id for item in widths)
            + tuple(item.constraint_id for item in clearances)
            + tuple(item.constraint_id for item in vias)
            + tuple(item.constraint_id for item in guides)
            + tuple(item.constraint_id for item in topologies)
            + additional
        )
        if len(constraints) != len(set(constraints)):
            raise ValueError("route constraint identities must be globally unique")
        target_nets = set(all_nets)
        if any(not set(item.net_names).issubset(target_nets) for item in widths):
            raise ValueError("width constraint references a non-target net")
        if any(not set(item.net_names).issubset(target_nets) for item in clearances):
            raise ValueError("clearance constraint references a non-target subject net")
        if any(
            not set(item.domain_ids).issubset(known_domains)
            or not set(item.net_names).issubset(target_nets)
            or not set(item.layers).issubset(layers)
            for item in guides
        ):
            raise ValueError("route guide references an unknown target or disallowed layer")
        if any(item.start_layer not in layers or item.end_layer not in layers for item in vias):
            raise ValueError("via technology references a disallowed layer")
        target_by_name = {
            net.net_name: (domain.domain_id, net) for domain in domains for net in domain.nets
        }
        topology_nets = tuple(item.net_name for item in topologies)
        if set(topology_nets) != target_nets or len(topology_nets) != len(target_nets):
            raise ValueError("each target net requires exactly one topology constraint")
        for topology in topologies:
            domain_id, target = target_by_name[topology.net_name]
            if topology.domain_id != domain_id:
                raise ValueError("topology constraint targets the wrong route domain")
            if set(topology.ordered_terminal_object_ids) != set(target.terminal_object_ids):
                raise ValueError("topology constraint must classify every target terminal")
            if not set(topology.paired_net_names).issubset(target_nets):
                raise ValueError("topology constraint references an unknown paired net")
        if set(self.deterministic.route_order) != target_nets:
            raise ValueError("deterministic route_order must cover every target net exactly")
        object.__setattr__(self, "allowed_layers", layers)
        object.__setattr__(self, "target_domains", domains)
        object.__setattr__(self, "source_route_objects", source_objects)
        object.__setattr__(self, "width_constraints", widths)
        object.__setattr__(self, "clearance_constraints", clearances)
        object.__setattr__(self, "via_technologies", vias)
        object.__setattr__(self, "route_guides", guides)
        object.__setattr__(self, "topology_constraints", topologies)
        object.__setattr__(self, "additional_constraint_ids", additional)
        return self

    @property
    def constraint_ids(self) -> tuple[str, ...]:
        """Every declared constraint identity in canonical order."""

        return tuple(
            sorted(
                (
                    *(item.constraint_id for item in self.width_constraints),
                    *(item.constraint_id for item in self.clearance_constraints),
                    *(item.constraint_id for item in self.via_technologies),
                    *(item.constraint_id for item in self.route_guides),
                    *(item.constraint_id for item in self.topology_constraints),
                    *self.additional_constraint_ids,
                )
            )
        )


class RouteSegmentGeometry(RoutingIrModel):
    net_name: str = Field(min_length=1)
    start: RoutePoint
    end: RoutePoint
    layer: str = Field(min_length=1)
    width_mm: float

    @model_validator(mode="after")
    def segment_is_physical(self) -> Self:
        _require_identity(self.net_name, "net_name")
        _require_identity(self.layer, "layer")
        if self.start == self.end:
            raise ValueError("route segment endpoints must differ")
        object.__setattr__(self, "width_mm", _finite_positive(self.width_mm, "width_mm"))
        return self


class RouteViaGeometry(RoutingIrModel):
    net_name: str = Field(min_length=1)
    position: RoutePoint
    technology_id: str = Field(min_length=1)
    start_layer: str = Field(min_length=1)
    end_layer: str = Field(min_length=1)
    diameter_mm: float
    drill_mm: float

    @model_validator(mode="after")
    def via_is_physical(self) -> Self:
        for field_name in ("net_name", "technology_id", "start_layer", "end_layer"):
            _require_identity(getattr(self, field_name), field_name)
        if self.start_layer == self.end_layer:
            raise ValueError("route via must connect distinct layers")
        diameter = _finite_positive(self.diameter_mm, "diameter_mm")
        drill = _finite_positive(self.drill_mm, "drill_mm")
        if drill >= diameter:
            raise ValueError("route via drill must be smaller than its diameter")
        return self


class RouteZoneGeometry(RoutingIrModel):
    net_name: str = Field(min_length=1)
    layer: str = Field(min_length=1)
    boundary: tuple[RoutePoint, ...] = Field(min_length=3)
    clearance_mm: float

    @model_validator(mode="after")
    def zone_is_physical(self) -> Self:
        _require_identity(self.net_name, "net_name")
        _require_identity(self.layer, "layer")
        if len(set(self.boundary)) < 3:
            raise ValueError("route zone boundary requires three distinct points")
        object.__setattr__(
            self,
            "clearance_mm",
            _finite_non_negative(self.clearance_mm, "clearance_mm"),
        )
        return self


def _validate_route_mutation(
    *,
    operation: RouteMutationKind,
    object_id: str,
    source_object_id: str | None,
    source_object_fingerprint: str | None,
    before: RoutingIrModel | None,
    after: RoutingIrModel | None,
) -> None:
    _require_identity(object_id, "object_id")
    if operation is RouteMutationKind.ADD:
        if (
            source_object_id is not None
            or source_object_fingerprint is not None
            or before is not None
        ):
            raise ValueError("add mutation cannot claim a source object")
        if after is None:
            raise ValueError("add mutation requires after geometry")
        return
    if source_object_id is None or source_object_fingerprint is None or before is None:
        raise ValueError("remove/replace mutation requires stable source identity and geometry")
    _require_identity(source_object_id, "source_object_id")
    _require_sha256(source_object_fingerprint, "source_object_fingerprint")
    if operation is RouteMutationKind.REMOVE:
        if after is not None or object_id != source_object_id:
            raise ValueError("remove mutation retains its source ID and has no after geometry")
        return
    if after is None:
        raise ValueError("replace mutation requires after geometry")


class RouteSegmentDelta(RoutingIrModel):
    mutation_id: str = Field(min_length=1)
    operation: RouteMutationKind
    object_id: str = Field(min_length=1)
    source_object_id: str | None = None
    source_object_fingerprint: str | None = None
    before: RouteSegmentGeometry | None = None
    after: RouteSegmentGeometry | None = None

    @model_validator(mode="after")
    def mutation_is_coherent(self) -> Self:
        _require_identity(self.mutation_id, "mutation_id")
        _validate_route_mutation(
            operation=self.operation,
            object_id=self.object_id,
            source_object_id=self.source_object_id,
            source_object_fingerprint=self.source_object_fingerprint,
            before=self.before,
            after=self.after,
        )
        if self.before is not None and self.after is not None:
            if self.before.net_name != self.after.net_name:
                raise ValueError("segment replacement cannot change net identity")
        return self


class RouteViaDelta(RoutingIrModel):
    mutation_id: str = Field(min_length=1)
    operation: RouteMutationKind
    object_id: str = Field(min_length=1)
    source_object_id: str | None = None
    source_object_fingerprint: str | None = None
    before: RouteViaGeometry | None = None
    after: RouteViaGeometry | None = None

    @model_validator(mode="after")
    def mutation_is_coherent(self) -> Self:
        _require_identity(self.mutation_id, "mutation_id")
        _validate_route_mutation(
            operation=self.operation,
            object_id=self.object_id,
            source_object_id=self.source_object_id,
            source_object_fingerprint=self.source_object_fingerprint,
            before=self.before,
            after=self.after,
        )
        if self.before is not None and self.after is not None:
            if self.before.net_name != self.after.net_name:
                raise ValueError("via replacement cannot change net identity")
        return self


class RouteZoneDelta(RoutingIrModel):
    mutation_id: str = Field(min_length=1)
    operation: RouteMutationKind
    object_id: str = Field(min_length=1)
    source_object_id: str | None = None
    source_object_fingerprint: str | None = None
    before: RouteZoneGeometry | None = None
    after: RouteZoneGeometry | None = None

    @model_validator(mode="after")
    def mutation_is_coherent(self) -> Self:
        _require_identity(self.mutation_id, "mutation_id")
        _validate_route_mutation(
            operation=self.operation,
            object_id=self.object_id,
            source_object_id=self.source_object_id,
            source_object_fingerprint=self.source_object_fingerprint,
            before=self.before,
            after=self.after,
        )
        if self.before is not None and self.after is not None:
            if self.before.net_name != self.after.net_name:
                raise ValueError("zone replacement cannot change net identity")
        return self


class ConstraintConsumption(RoutingIrModel):
    constraint_id: str = Field(min_length=1)
    disposition: RouteConstraintDisposition
    backend_constraint_id: str | None = None
    maximum_error_mm: float | None = None
    detail: str = Field(min_length=1)

    @model_validator(mode="after")
    def consumption_is_truthful(self) -> Self:
        _require_identity(self.constraint_id, "constraint_id")
        _require_identity(self.detail, "detail")
        if self.backend_constraint_id is not None:
            _require_identity(self.backend_constraint_id, "backend_constraint_id")
        if self.disposition is RouteConstraintDisposition.APPROXIMATED:
            if self.maximum_error_mm is None:
                raise ValueError("approximated constraint requires a maximum error")
            object.__setattr__(
                self,
                "maximum_error_mm",
                _finite_positive(self.maximum_error_mm, "maximum_error_mm"),
            )
        elif self.maximum_error_mm is not None:
            raise ValueError("only an approximated constraint may carry maximum_error_mm")
        return self


class RouteFailureEvidence(RoutingIrModel):
    failure_id: str = Field(min_length=1)
    kind: RouteFailureKind
    message: str = Field(min_length=1)
    domain_ids: tuple[str, ...] = ()
    net_names: tuple[str, ...] = ()
    object_ids: tuple[str, ...] = ()
    constraint_ids: tuple[str, ...] = ()
    resource_ids: tuple[str, ...] = ()
    retryable: bool = False

    @model_validator(mode="after")
    def evidence_is_canonical(self) -> Self:
        _require_identity(self.failure_id, "failure_id")
        _require_identity(self.message, "message")
        for field_name in (
            "domain_ids",
            "net_names",
            "object_ids",
            "constraint_ids",
            "resource_ids",
        ):
            object.__setattr__(
                self,
                field_name,
                _canonical_identities(getattr(self, field_name), field_name),
            )
        return self


class RoutingEngineIdentity(RoutingIrModel):
    engine_id: str = Field(min_length=1)
    engine_version: str = Field(min_length=1)
    adapter_id: str = Field(min_length=1)
    adapter_version: str = Field(min_length=1)
    source_commit: str | None = None
    executable_sha256: str | None = None

    @model_validator(mode="after")
    def engine_identity_is_complete(self) -> Self:
        for field_name in ("engine_id", "engine_version", "adapter_id", "adapter_version"):
            _require_identity(getattr(self, field_name), field_name)
        if self.source_commit is not None:
            _require_identity(self.source_commit, "source_commit")
        if self.executable_sha256 is not None:
            _require_sha256(self.executable_sha256, "executable_sha256")
        return self


class RouteTerminationEvidence(RoutingIrModel):
    state: RouteTerminationState
    reason: str = Field(min_length=1)
    exit_code: int | None = None
    stdout_sha256: str
    stderr_sha256: str
    elapsed_seconds: float
    exhausted_budget_fields: tuple[str, ...] = ()

    @model_validator(mode="after")
    def termination_is_canonical(self) -> Self:
        _require_identity(self.reason, "reason")
        _require_sha256(self.stdout_sha256, "stdout_sha256")
        _require_sha256(self.stderr_sha256, "stderr_sha256")
        exhausted = _canonical_identities(
            self.exhausted_budget_fields,
            "exhausted_budget_fields",
        )
        if self.state is RouteTerminationState.BUDGET_EXHAUSTED and not exhausted:
            raise ValueError("budget exhaustion requires exhausted budget identities")
        if self.state is not RouteTerminationState.BUDGET_EXHAUSTED and exhausted:
            raise ValueError("only budget exhaustion may list exhausted budgets")
        object.__setattr__(
            self,
            "elapsed_seconds",
            _finite_non_negative(self.elapsed_seconds, "elapsed_seconds"),
        )
        object.__setattr__(self, "exhausted_budget_fields", exhausted)
        return self


class RouteCandidateResult(RoutingIrModel):
    """Complete immutable result envelope returned by a routing adapter."""

    schema_id: Literal["pcbsmith-route-candidate-result"] = "pcbsmith-route-candidate-result"
    schema_version: Literal[1] = 1
    request_fingerprint: str
    source_board_sha256: str
    engine: RoutingEngineIdentity
    termination: RouteTerminationEvidence
    partial_status: PartialCandidateStatus
    segment_deltas: tuple[RouteSegmentDelta, ...] = ()
    via_deltas: tuple[RouteViaDelta, ...] = ()
    zone_deltas: tuple[RouteZoneDelta, ...] = ()
    constraint_consumption: tuple[ConstraintConsumption, ...]
    failures: tuple[RouteFailureEvidence, ...] = ()
    run_telemetry: RoutingRunResult | None = None

    @model_validator(mode="after")
    def result_is_canonical_and_coherent(self) -> Self:
        _require_sha256(self.request_fingerprint, "request_fingerprint")
        _require_sha256(self.source_board_sha256, "source_board_sha256")
        segments = tuple(sorted(self.segment_deltas, key=lambda item: item.mutation_id))
        vias = tuple(sorted(self.via_deltas, key=lambda item: item.mutation_id))
        zones = tuple(sorted(self.zone_deltas, key=lambda item: item.mutation_id))
        mutations = (
            tuple(item.mutation_id for item in segments)
            + tuple(item.mutation_id for item in vias)
            + tuple(item.mutation_id for item in zones)
        )
        if len(mutations) != len(set(mutations)):
            raise ValueError("route mutation identities must be globally unique")
        result_object_ids = (
            tuple(item.object_id for item in segments)
            + tuple(item.object_id for item in vias)
            + tuple(item.object_id for item in zones)
        )
        if len(result_object_ids) != len(set(result_object_ids)):
            raise ValueError("route result object identities must be globally unique")
        consumption = tuple(
            sorted(self.constraint_consumption, key=lambda item: item.constraint_id)
        )
        if len(consumption) != len({item.constraint_id for item in consumption}):
            raise ValueError("each route constraint must have one consumption result")
        failures = tuple(sorted(self.failures, key=lambda item: item.failure_id))
        if len(failures) != len({item.failure_id for item in failures}):
            raise ValueError("route failure identities must be unique")
        has_delta = bool(segments or vias or zones)
        if self.partial_status is PartialCandidateStatus.COMPLETE:
            if self.termination.state is not RouteTerminationState.COMPLETED or failures:
                raise ValueError("complete candidate requires clean completed termination")
        elif self.partial_status is PartialCandidateStatus.BOUNDED_PARTIAL:
            if not has_delta or not failures:
                raise ValueError("bounded partial candidate requires delta and failure evidence")
        elif self.partial_status is PartialCandidateStatus.FAILED_NO_DELTA:
            if has_delta or not failures:
                raise ValueError("failed-no-delta candidate requires failures and no mutations")
        elif not failures:
            raise ValueError("rejected candidate requires failure evidence")
        object.__setattr__(self, "segment_deltas", segments)
        object.__setattr__(self, "via_deltas", vias)
        object.__setattr__(self, "zone_deltas", zones)
        object.__setattr__(self, "constraint_consumption", consumption)
        object.__setattr__(self, "failures", failures)
        return self


def validate_route_candidate_result(
    request: RouteRequest,
    result: RouteCandidateResult,
) -> None:
    """Fail closed when an adapter result exceeds its immutable request."""

    if result.request_fingerprint != request.semantic_fingerprint():
        raise ValueError("route candidate targets a stale or different request")
    if result.source_board_sha256 != request.inputs.board_sha256:
        raise ValueError("route candidate targets a stale or different source board")
    consumed = tuple(item.constraint_id for item in result.constraint_consumption)
    if consumed != request.constraint_ids:
        unknown = tuple(sorted(set(consumed) - set(request.constraint_ids)))
        missing = tuple(sorted(set(request.constraint_ids) - set(consumed)))
        raise ValueError(
            f"constraint-consumption ledger is not exact: unknown={unknown!r}, missing={missing!r}"
        )
    unsupported = {
        item.constraint_id
        for item in result.constraint_consumption
        if item.disposition
        in {
            RouteConstraintDisposition.UNSUPPORTED,
            RouteConstraintDisposition.REJECTED,
        }
    }
    evidenced = {
        constraint_id
        for failure in result.failures
        if failure.kind
        in {
            RouteFailureKind.UNSUPPORTED_CONSTRAINT,
            RouteFailureKind.REJECTED_CONSTRAINT,
        }
        for constraint_id in failure.constraint_ids
    }
    if unsupported != evidenced:
        raise ValueError("unsupported/rejected constraints lack exact blocker evidence")

    target_nets = {net.net_name for domain in request.target_domains for net in domain.nets}
    protected = {
        (item.object_kind, item.object_id) for item in request.protected_policy.protected_objects
    }
    source_by_key = {
        (item.object_kind, item.object_id): item for item in request.source_route_objects
    }
    widths_by_net = {
        net_name: constraint
        for constraint in request.width_constraints
        for net_name in constraint.net_names
    }
    via_by_id = {item.technology_id: item for item in request.via_technologies}

    typed_deltas: tuple[
        tuple[RouteObjectKind, RouteSegmentDelta | RouteViaDelta | RouteZoneDelta], ...
    ] = (
        *((RouteObjectKind.SEGMENT, item) for item in result.segment_deltas),
        *((RouteObjectKind.VIA, item) for item in result.via_deltas),
        *((RouteObjectKind.ZONE, item) for item in result.zone_deltas),
    )
    for kind, delta in typed_deltas:
        result_key = (kind, delta.object_id)
        if delta.operation is RouteMutationKind.ADD and result_key in source_by_key:
            raise ValueError("route add mutation reuses an existing source object identity")
        if (
            delta.operation is RouteMutationKind.REPLACE
            and delta.object_id != delta.source_object_id
            and result_key in source_by_key
        ):
            raise ValueError("route replacement reuses another source object identity")
        if delta.source_object_id is not None:
            key = (kind, delta.source_object_id)
            source = source_by_key.get(key)
            if source is None:
                raise ValueError("route mutation references a missing source object identity")
            if source.source_object_fingerprint != delta.source_object_fingerprint:
                raise ValueError("route mutation references a stale source object fingerprint")
            if key in protected:
                raise ValueError("route mutation attempts to change protected copper")
        geometry = delta.after
        if geometry is None:
            continue
        if geometry.net_name not in target_nets:
            raise ValueError("route mutation targets a net outside the request")
        if isinstance(geometry, RouteSegmentGeometry):
            if geometry.layer not in request.allowed_layers:
                raise ValueError("route segment uses a disallowed layer")
            width = widths_by_net.get(geometry.net_name)
            if width is None or not (
                width.minimum_width_mm <= geometry.width_mm <= width.maximum_width_mm
            ):
                raise ValueError("route segment width is outside its declared constraint")
        elif isinstance(geometry, RouteViaGeometry):
            if (
                geometry.start_layer not in request.allowed_layers
                or geometry.end_layer not in request.allowed_layers
            ):
                raise ValueError("route via uses a disallowed layer")
            technology = via_by_id.get(geometry.technology_id)
            if technology is None:
                raise ValueError("route via uses an undeclared technology")
            if (
                geometry.start_layer != technology.start_layer
                or geometry.end_layer != technology.end_layer
                or geometry.diameter_mm != technology.diameter_mm
                or geometry.drill_mm != technology.drill_mm
            ):
                raise ValueError("route via geometry differs from its declared technology")
        elif geometry.layer not in request.allowed_layers:
            raise ValueError("route zone uses a disallowed layer")


class RoutingBudget(RoutingIrModel):
    """Fixed deterministic work limits for one routing run."""

    max_passes: int = Field(ge=0)
    max_expansions: int = Field(ge=0)
    max_expansions_per_net: int = Field(ge=0)
    max_stagnant_passes: int = Field(ge=0)
    max_exact_check_rejections: int = Field(ge=0)
    external_process_seconds: int | None = Field(
        default=None, gt=0, le=900, exclude_if=lambda v: v is None
    )

    @model_validator(mode="after")
    def external_budget_is_explicit(self) -> Self:
        if self.external_process_seconds is not None and (
            self.max_passes <= 0 or self.max_expansions or self.max_expansions_per_net
        ):
            raise ValueError(
                "external process budget requires finite passes and no expansion claim"
            )
        return self


class ResourceOveruseSummary(RoutingIrModel):
    """Capacity accounting for one engine-neutral routing resource."""

    resource_id: str = Field(min_length=1)
    resource_kind: Literal["edge", "via_site", "channel", "region", "other"]
    capacity_units: int = Field(ge=0)
    demand_units: int = Field(ge=0)
    overuse_units: int = Field(ge=0)
    net_names: tuple[str, ...] = ()

    @model_validator(mode="after")
    def overuse_matches_capacity_accounting(self) -> Self:
        expected = max(0, self.demand_units - self.capacity_units)
        if self.overuse_units != expected:
            raise ValueError("overuse_units must equal max(0, demand_units - capacity_units)")
        if len(set(self.net_names)) != len(self.net_names):
            raise ValueError("resource overuse net_names must be unique")
        object.__setattr__(self, "net_names", tuple(sorted(self.net_names)))
        return self


class NetRoutingTelemetry(RoutingIrModel):
    """One deterministic route attempt for one net in one pass."""

    net_name: str = Field(min_length=1)
    pass_index: int = Field(ge=0)
    attempt_index: int = Field(ge=0)
    expansion_count: int = Field(ge=0)
    segment_count: int = Field(default=0, ge=0)
    via_count: int = Field(default=0, ge=0)
    length_mm: float = Field(default=0.0, ge=0)
    routed: bool
    failure_reason: RoutingFailureReason | None = None
    exact_check_accepted: bool | None = None

    @model_validator(mode="after")
    def outcome_fields_are_coherent(self) -> Self:
        if self.routed and self.failure_reason is not None:
            raise ValueError("a routed net attempt cannot report a failure reason")
        if not self.routed and self.failure_reason is None:
            raise ValueError("an unresolved net attempt requires a failure reason")
        if self.exact_check_accepted is False and (
            self.failure_reason is not RoutingFailureReason.EXACT_CHECK_REJECTION
        ):
            raise ValueError("an exact-check rejection requires exact_check_rejection")
        if (
            self.failure_reason is RoutingFailureReason.EXACT_CHECK_REJECTION
            and self.exact_check_accepted is not False
        ):
            raise ValueError("exact_check_rejection requires exact_check_accepted=False")
        return self


class RoutingPassTelemetry(RoutingIrModel):
    """Per-pass net attempts, work counts, and resource state."""

    pass_index: int = Field(ge=0)
    net_telemetry: tuple[NetRoutingTelemetry, ...] = ()
    unresolved_net_names: tuple[str, ...] = ()
    resource_overuse: tuple[ResourceOveruseSummary, ...] = ()
    expansion_count: int = Field(default=0, ge=0)
    exact_check_rejection_count: int = Field(default=0, ge=0)
    stagnant: bool = False

    @model_validator(mode="after")
    def summaries_match_attempts(self) -> Self:
        attempt_keys = [(item.net_name, item.attempt_index) for item in self.net_telemetry]
        if len(set(attempt_keys)) != len(attempt_keys):
            raise ValueError("net attempts must be unique within a routing pass")
        if any(item.pass_index != self.pass_index for item in self.net_telemetry):
            raise ValueError("net telemetry pass_index must match its parent pass")
        if len(set(self.unresolved_net_names)) != len(self.unresolved_net_names):
            raise ValueError("unresolved_net_names must be unique")
        object.__setattr__(self, "unresolved_net_names", tuple(sorted(self.unresolved_net_names)))
        resource_ids = [item.resource_id for item in self.resource_overuse]
        if len(set(resource_ids)) != len(resource_ids):
            raise ValueError("resource_id values must be unique within a pass")
        object.__setattr__(
            self,
            "resource_overuse",
            tuple(sorted(self.resource_overuse, key=lambda item: item.resource_id)),
        )
        expected_expansions = sum(item.expansion_count for item in self.net_telemetry)
        if self.expansion_count != expected_expansions:
            raise ValueError("pass expansion_count must equal net telemetry total")
        expected_rejections = sum(
            item.failure_reason is RoutingFailureReason.EXACT_CHECK_REJECTION
            for item in self.net_telemetry
        )
        if self.exact_check_rejection_count != expected_rejections:
            raise ValueError("pass exact_check_rejection_count must equal net telemetry total")
        return self


class RoutingRunResult(RoutingIrModel):
    """Versioned routing-run result suitable for engine adapters.

    `success` means the routing algorithm completed with no unresolved nets or
    capacity overuse. It is not an exact-geometry acceptance decision.
    """

    schema_id: Literal["pcbsmith-routing-run"] = "pcbsmith-routing-run"
    schema_version: Literal[2] = 2
    producer: str = Field(min_length=1)
    budget: RoutingBudget
    success: bool
    exact_check_accepted: bool | None = None
    failure_reason: RoutingFailureReason | None = None
    route_order: tuple[str, ...] = ()
    unresolved_net_names: tuple[str, ...] = ()
    restart_count: int = Field(default=0, ge=0)
    passes: tuple[RoutingPassTelemetry, ...] = ()
    resource_overuse: tuple[ResourceOveruseSummary, ...] = ()

    @property
    def accepted(self) -> bool:
        """Whether routing completed and an exact checker accepted it."""
        return self.success and self.exact_check_accepted is True

    @model_validator(mode="after")
    def result_is_coherent_and_within_budget(self) -> Self:
        if len(set(self.route_order)) != len(self.route_order):
            raise ValueError("route_order must contain unique net names")
        if len(set(self.unresolved_net_names)) != len(self.unresolved_net_names):
            raise ValueError("unresolved_net_names must be unique")
        if not set(self.unresolved_net_names).issubset(self.route_order):
            raise ValueError("unresolved nets must be present in route_order")
        object.__setattr__(self, "unresolved_net_names", tuple(sorted(self.unresolved_net_names)))
        resource_ids = [item.resource_id for item in self.resource_overuse]
        if len(set(resource_ids)) != len(resource_ids):
            raise ValueError("final resource_id values must be unique")
        object.__setattr__(
            self,
            "resource_overuse",
            tuple(sorted(self.resource_overuse, key=lambda item: item.resource_id)),
        )

        expected_pass_indices = tuple(range(len(self.passes)))
        if tuple(item.pass_index for item in self.passes) != expected_pass_indices:
            raise ValueError("routing pass indices must be consecutive from zero")
        if len(self.passes) > self.budget.max_passes:
            raise ValueError("routing passes exceed the fixed pass budget")
        total_expansions = sum(item.expansion_count for item in self.passes)
        if total_expansions > self.budget.max_expansions:
            raise ValueError("routing expansions exceed the fixed expansion budget")
        if any(
            net.expansion_count > self.budget.max_expansions_per_net
            for route_pass in self.passes
            for net in route_pass.net_telemetry
        ):
            raise ValueError("net expansions exceed the fixed per-net budget")
        total_rejections = sum(item.exact_check_rejection_count for item in self.passes)
        if total_rejections > self.budget.max_exact_check_rejections:
            raise ValueError("exact-check rejections exceed the fixed budget")
        longest_stagnation = 0
        current_stagnation = 0
        for route_pass in self.passes:
            current_stagnation = current_stagnation + 1 if route_pass.stagnant else 0
            longest_stagnation = max(longest_stagnation, current_stagnation)
        if longest_stagnation > self.budget.max_stagnant_passes:
            raise ValueError("stagnant passes exceed the fixed stagnation budget")

        if self.passes:
            final_pass = self.passes[-1]
            if final_pass.unresolved_net_names != self.unresolved_net_names:
                raise ValueError("final pass unresolved nets must match the run result")
            if final_pass.resource_overuse != self.resource_overuse:
                raise ValueError("final pass overuse must match the run result")

        total_overuse = sum(item.overuse_units for item in self.resource_overuse)
        if self.exact_check_accepted is True and not self.success:
            raise ValueError("exact-check acceptance requires algorithmic success")
        if (
            self.failure_reason is RoutingFailureReason.EXACT_CHECK_REJECTION
            and self.exact_check_accepted is not False
        ):
            raise ValueError("exact_check_rejection requires exact_check_accepted=False")
        if self.success:
            if self.failure_reason is not None:
                raise ValueError("a successful run cannot report a failure reason")
            if self.unresolved_net_names:
                raise ValueError("a successful run cannot contain unresolved nets")
            if total_overuse:
                raise ValueError("a successful run requires zero resource overuse")
        elif self.failure_reason is None:
            raise ValueError("a failed run requires a typed failure reason")
        if self.failure_reason is RoutingFailureReason.OVERUSE_REMAINING and total_overuse == 0:
            raise ValueError("overuse_remaining requires positive resource overuse")
        if (
            self.failure_reason is RoutingFailureReason.EXACT_CHECK_REJECTION
            and total_rejections == 0
        ):
            raise ValueError("exact_check_rejection requires a rejected exact check")
        return self
