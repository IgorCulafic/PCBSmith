"""Deterministic resource accounting for negotiated PCB routing.

This module intentionally contains no search or pass orchestration.  It defines
the capacity-one resource ledger and exact raster claims used by the first R2
implementation slice.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, TypeAlias

from pcbsmith.routing_ir import ResourceOveruseSummary
from pcbsmith.rule_profiles import (
    CopperRole,
    OrdinaryClearanceRequirement,
    OuterCopperMaskState,
)

LayerName: TypeAlias = Literal["F.Cu", "B.Cu"]
ResourceLayer: TypeAlias = LayerName | Literal["through"]
ResourceKind: TypeAlias = Literal["cell", "edge", "crossing", "via_site"]
Cell: TypeAlias = tuple[int, int]

_COPPER_LAYERS = frozenset({"F.Cu", "B.Cu"})
_RESOURCE_KINDS = frozenset({"cell", "edge", "crossing", "via_site"})
_GEOMETRY_EPSILON = 1e-12
GRID_ALIGNMENT_EPSILON_GRID_UNITS = 1e-9


@dataclass(frozen=True, order=True)
class RoutingResourceKey:
    """Canonical identity of one capacity-one negotiated routing resource."""

    domain_id: str
    layer: ResourceLayer
    kind: ResourceKind
    ix0: int
    iy0: int
    ix1: int = 0
    iy1: int = 0

    def __post_init__(self) -> None:
        if not self.domain_id:
            raise ValueError("resource domain_id must be non-empty")
        if self.kind not in _RESOURCE_KINDS:
            raise ValueError(f"unsupported resource kind: {self.kind}")
        if self.layer not in {*_COPPER_LAYERS, "through"}:
            raise ValueError(f"unsupported resource layer: {self.layer}")
        if any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in (self.ix0, self.iy0, self.ix1, self.iy1)
        ):
            raise TypeError("resource coordinates must be integers")

        if self.kind == "via_site":
            if self.layer != "through":
                raise ValueError("via_site resources require the through layer")
            self._require_unused_endpoint()
            return
        if self.layer == "through":
            raise ValueError("only via_site resources may use the through layer")
        if self.kind in {"cell", "crossing"}:
            self._require_unused_endpoint()
            return

        first = (self.ix0, self.iy0)
        second = (self.ix1, self.iy1)
        if first == second or max(abs(first[0] - second[0]), abs(first[1] - second[1])) != 1:
            raise ValueError("edge resource endpoints must be adjacent 8-neighbor cells")
        if second < first:
            object.__setattr__(self, "ix0", second[0])
            object.__setattr__(self, "iy0", second[1])
            object.__setattr__(self, "ix1", first[0])
            object.__setattr__(self, "iy1", first[1])

    def _require_unused_endpoint(self) -> None:
        if self.ix1 != 0 or self.iy1 != 0:
            raise ValueError(f"{self.kind} resources do not use a second endpoint")

    @property
    def resource_id(self) -> str:
        payload = [
            self.domain_id,
            self.layer,
            self.kind,
            self.ix0,
            self.iy0,
            self.ix1,
            self.iy1,
        ]
        return "pcbsmith-routing-resource-v1:" + json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )


@dataclass(frozen=True)
class NetResourceClaims:
    """A complete set-valued resource claim for one routed net."""

    net_name: str
    resources: frozenset[RoutingResourceKey]

    def __post_init__(self) -> None:
        if not self.net_name:
            raise ValueError("claim net_name must be non-empty")
        canonical = frozenset(self.resources)
        if any(not isinstance(resource, RoutingResourceKey) for resource in canonical):
            raise TypeError("claims may contain only RoutingResourceKey values")
        object.__setattr__(self, "resources", canonical)


def union_net_resource_claims(
    net_name: str,
    *parts: NetResourceClaims,
) -> NetResourceClaims:
    """Union complete claim fragments without permitting cross-net ownership."""
    resources: set[RoutingResourceKey] = set()
    for part in parts:
        if part.net_name != net_name:
            raise ValueError(
                f"claim owner {part.net_name!r} does not match union owner {net_name!r}"
            )
        resources.update(part.resources)
    return NetResourceClaims(net_name, frozenset(resources))


class OccupancyLedger:
    """Capacity-one, whole-net transactional resource occupancy."""

    capacity = 1

    def __init__(self, claims: Iterable[NetResourceClaims] = ()) -> None:
        self._by_net: dict[str, frozenset[RoutingResourceKey]] = {}
        self._by_resource: dict[RoutingResourceKey, set[str]] = {}
        for item in claims:
            self.commit(item)

    def claims_for(self, net_name: str) -> NetResourceClaims:
        return NetResourceClaims(net_name, self._by_net.get(net_name, frozenset()))

    def committed_claims(self) -> tuple[NetResourceClaims, ...]:
        return tuple(self.claims_for(net_name) for net_name in sorted(self._by_net))

    def rip_up(self, net_name: str) -> NetResourceClaims:
        old = self.claims_for(net_name)
        self._remove_net(net_name)
        return old

    def restore(self, claims: NetResourceClaims) -> None:
        self._replace(claims)

    def commit(self, claims: NetResourceClaims) -> None:
        self._replace(claims)

    def demand_without(self, resource: RoutingResourceKey, net_name: str) -> int:
        return sum(owner != net_name for owner in self._by_resource.get(resource, ()))

    def overuse(self) -> tuple[ResourceOveruseSummary, ...]:
        summaries: list[ResourceOveruseSummary] = []
        for resource, owners in self._by_resource.items():
            demand = len(owners)
            if demand <= self.capacity:
                continue
            summaries.append(
                ResourceOveruseSummary(
                    resource_id=resource.resource_id,
                    resource_kind=_telemetry_kind(resource.kind),
                    capacity_units=self.capacity,
                    demand_units=demand,
                    overuse_units=demand - self.capacity,
                    net_names=tuple(sorted(owners)),
                )
            )
        return tuple(sorted(summaries, key=lambda item: item.resource_id))

    def semantic_fingerprint(self) -> str:
        payload = {
            "schema_id": "pcbsmith-negotiated-occupancy",
            "schema_version": 1,
            "capacity": self.capacity,
            "claims": [
                {
                    "net_name": claims.net_name,
                    "resource_ids": sorted(resource.resource_id for resource in claims.resources),
                }
                for claims in self.committed_claims()
            ],
        }
        semantic_json = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        return hashlib.sha256(semantic_json.encode("utf-8")).hexdigest()

    def _replace(self, claims: NetResourceClaims) -> None:
        self._remove_net(claims.net_name)
        self._by_net[claims.net_name] = claims.resources
        for resource in sorted(claims.resources):
            self._by_resource.setdefault(resource, set()).add(claims.net_name)

    def _remove_net(self, net_name: str) -> None:
        resources = self._by_net.pop(net_name, frozenset())
        for resource in sorted(resources):
            owners = self._by_resource[resource]
            owners.discard(net_name)
            if not owners:
                del self._by_resource[resource]


@dataclass(frozen=True, order=True)
class PairwiseClearanceDomain:
    """One special-clearance domain for exactly one unordered net pair."""

    domain_id: str
    profile_id: str
    requirement_id: str
    net_low: str
    net_high: str
    minimum_clearance_mm: float
    mask_states_low: tuple[OuterCopperMaskState, ...] = ()
    mask_states_high: tuple[OuterCopperMaskState, ...] = ()
    roles_low: tuple[CopperRole, ...] = ()
    roles_high: tuple[CopperRole, ...] = ()
    exempt_component_refs: tuple[str, ...] = ()
    rule_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.domain_id or not self.profile_id or not self.requirement_id:
            raise ValueError("pairwise domain identities must be non-empty")
        if not self.net_low or not self.net_high or self.net_low >= self.net_high:
            raise ValueError("pairwise domain nets must be a canonical distinct pair")
        if not math.isfinite(self.minimum_clearance_mm) or self.minimum_clearance_mm <= 0:
            raise ValueError("pairwise minimum clearance must be finite and positive")

    @property
    def net_names(self) -> tuple[str, str]:
        return self.net_low, self.net_high

    def applies_to(self, net_name: str) -> bool:
        return net_name in self.net_names

    def selectors_for(
        self, net_name: str
    ) -> tuple[tuple[OuterCopperMaskState, ...], tuple[CopperRole, ...]]:
        if net_name == self.net_low:
            return self.mask_states_low, self.roles_low
        if net_name == self.net_high:
            return self.mask_states_high, self.roles_high
        raise ValueError(f"net {net_name!r} is not in pairwise domain")


def build_pairwise_clearance_domains(
    profile_id: str,
    requirements: Iterable[OrdinaryClearanceRequirement],
) -> tuple[PairwiseClearanceDomain, ...]:
    """Expand group rules into stable domains for individual unordered net pairs."""
    if not profile_id:
        raise ValueError("profile_id must be non-empty")
    domains: dict[str, PairwiseClearanceDomain] = {}
    for requirement in requirements:
        for net_a in sorted(set(requirement.nets_a)):
            for net_b in sorted(set(requirement.nets_b)):
                low, high = sorted((net_a, net_b))
                a_is_low = net_a == low
                low_states = requirement.mask_states_a if a_is_low else requirement.mask_states_b
                high_states = requirement.mask_states_b if a_is_low else requirement.mask_states_a
                low_roles = requirement.roles_a if a_is_low else requirement.roles_b
                high_roles = requirement.roles_b if a_is_low else requirement.roles_a
                normalized_low_states = tuple(sorted(set(low_states)))
                normalized_high_states = tuple(sorted(set(high_states)))
                normalized_low_roles = tuple(sorted(set(low_roles)))
                normalized_high_roles = tuple(sorted(set(high_roles)))
                normalized_exemptions = tuple(sorted(set(requirement.exempt_component_refs)))
                normalized_rule_ids = tuple(sorted(set(requirement.rule_ids)))
                normalized = {
                    "profile_id": profile_id,
                    "requirement_id": requirement.requirement_id,
                    "net_low": low,
                    "net_high": high,
                    "minimum_clearance_mm": requirement.minimum_clearance_mm,
                    "mask_states_low": normalized_low_states,
                    "mask_states_high": normalized_high_states,
                    "roles_low": normalized_low_roles,
                    "roles_high": normalized_high_roles,
                    "exempt_component_refs": normalized_exemptions,
                    "rule_ids": normalized_rule_ids,
                }
                identity = json.dumps(
                    normalized,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                    allow_nan=False,
                )
                domain_id = (
                    "pairwise-clearance-v1:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
                )
                domain = PairwiseClearanceDomain(
                    domain_id=domain_id,
                    profile_id=profile_id,
                    requirement_id=requirement.requirement_id,
                    net_low=low,
                    net_high=high,
                    minimum_clearance_mm=requirement.minimum_clearance_mm,
                    mask_states_low=normalized_low_states,
                    mask_states_high=normalized_high_states,
                    roles_low=normalized_low_roles,
                    roles_high=normalized_high_roles,
                    exempt_component_refs=normalized_exemptions,
                    rule_ids=normalized_rule_ids,
                )
                domains[domain_id] = domain
    return tuple(sorted(domains.values()))


def clearance_domains_for_net(
    domains: Iterable[PairwiseClearanceDomain], net_name: str
) -> tuple[PairwiseClearanceDomain, ...]:
    return tuple(sorted(domain for domain in domains if domain.applies_to(net_name)))


def symmetric_halo_radius(copper_width_mm: float, clearance_mm: float) -> float:
    """Radius claimed by one net for symmetric pairwise spacing."""
    if not math.isfinite(copper_width_mm) or copper_width_mm <= 0:
        raise ValueError("copper_width_mm must be finite and positive")
    if not math.isfinite(clearance_mm) or clearance_mm < 0:
        raise ValueError("clearance_mm must be finite and non-negative")
    return copper_width_mm / 2.0 + clearance_mm / 2.0


def capsule_move_claims(
    domain_id: str,
    layer: LayerName,
    start: Cell,
    end: Cell,
    grid_mm: float,
    halo_radius_mm: float,
) -> frozenset[RoutingResourceKey]:
    """Exact cell-square supercover plus edge/crossing claims for one grid move."""
    _validate_grid_and_radius(grid_mm, halo_radius_mm)
    _validate_cell(start)
    _validate_cell(end)
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    if (dx == 0 and dy == 0) or max(abs(dx), abs(dy)) != 1:
        raise ValueError("capsule move endpoints must be adjacent 8-neighbor cells")
    if layer not in _COPPER_LAYERS:
        raise ValueError(f"unsupported copper layer: {layer}")

    return capsule_segment_claims(
        domain_id,
        layer,
        (start[0] * grid_mm, start[1] * grid_mm),
        (end[0] * grid_mm, end[1] * grid_mm),
        grid_mm,
        halo_radius_mm,
    )


def capsule_segment_claims(
    domain_id: str,
    layer: LayerName,
    start_mm: tuple[float, float],
    end_mm: tuple[float, float],
    grid_mm: float,
    halo_radius_mm: float,
) -> frozenset[RoutingResourceKey]:
    """Exact physical capsule supercover with provable lattice transitions.

    Arbitrary physical segments always claim intersected closed cell squares.
    Edge and crossing identities are added only for an on-grid horizontal,
    vertical, or 45-degree segment that has a unique adjacent-move expansion.
    """
    _validate_grid_and_radius(grid_mm, halo_radius_mm)
    _validate_physical_point(start_mm)
    _validate_physical_point(end_mm)
    if layer not in _COPPER_LAYERS:
        raise ValueError(f"unsupported copper layer: {layer}")

    resources = _capsule_cell_claims(domain_id, layer, start_mm, end_mm, grid_mm, halo_radius_mm)
    start_cell = _aligned_grid_cell(start_mm, grid_mm)
    end_cell = _aligned_grid_cell(end_mm, grid_mm)
    if start_cell is None or end_cell is None or start_cell == end_cell:
        return frozenset(resources)
    dx = end_cell[0] - start_cell[0]
    dy = end_cell[1] - start_cell[1]
    if dx != 0 and dy != 0 and abs(dx) != abs(dy):
        return frozenset(resources)
    steps = max(abs(dx), abs(dy))
    step = (_sign(dx), _sign(dy))
    current = start_cell
    for _ in range(steps):
        following = (current[0] + step[0], current[1] + step[1])
        resources.update(_lattice_transition_claims(domain_id, layer, current, following))
        current = following
    return frozenset(resources)


def _lattice_transition_claims(
    domain_id: str,
    layer: LayerName,
    start: Cell,
    end: Cell,
) -> set[RoutingResourceKey]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    resources = {
        RoutingResourceKey(
            domain_id=domain_id,
            layer=layer,
            kind="edge",
            ix0=start[0],
            iy0=start[1],
            ix1=end[0],
            iy1=end[1],
        )
    }
    if dx != 0 and dy != 0:
        resources.add(
            RoutingResourceKey(
                domain_id=domain_id,
                layer=layer,
                kind="crossing",
                ix0=min(start[0], end[0]),
                iy0=min(start[1], end[1]),
            )
        )
    return resources


def via_claims(
    domain_id: str,
    ix: int,
    iy: int,
    grid_mm: float,
    halo_radius_mm: float,
) -> frozenset[RoutingResourceKey]:
    """Front/back circular cell supercovers plus one through via-site claim."""
    _validate_grid_and_radius(grid_mm, halo_radius_mm)
    _validate_cell((ix, iy))
    center = (ix * grid_mm, iy * grid_mm)
    resources: set[RoutingResourceKey] = {
        RoutingResourceKey(domain_id, "through", "via_site", ix, iy)
    }
    for layer in ("F.Cu", "B.Cu"):
        resources.update(
            _capsule_cell_claims(
                domain_id,
                layer,
                center,
                center,
                grid_mm,
                halo_radius_mm,
            )
        )
    return frozenset(resources)


def _telemetry_kind(
    kind: ResourceKind,
) -> Literal["edge", "via_site", "region"]:
    if kind == "cell":
        return "region"
    if kind == "via_site":
        return "via_site"
    return "edge"


def _validate_cell(cell: Cell) -> None:
    if len(cell) != 2 or any(
        not isinstance(value, int) or isinstance(value, bool) for value in cell
    ):
        raise TypeError("grid cells must contain exactly two integer coordinates")


def _validate_grid_and_radius(grid_mm: float, radius_mm: float) -> None:
    if not math.isfinite(grid_mm) or grid_mm <= 0:
        raise ValueError("grid_mm must be finite and positive")
    if not math.isfinite(radius_mm) or radius_mm < 0:
        raise ValueError("halo_radius_mm must be finite and non-negative")


def _validate_physical_point(point: tuple[float, float]) -> None:
    if len(point) != 2 or any(
        not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
        for value in point
    ):
        raise ValueError("physical endpoints must contain two finite coordinates")


def _aligned_grid_cell(point_mm: tuple[float, float], grid_mm: float) -> Cell | None:
    coordinates: list[int] = []
    for value in point_mm:
        grid_coordinate = value / grid_mm
        nearest = round(grid_coordinate)
        if abs(grid_coordinate - nearest) > GRID_ALIGNMENT_EPSILON_GRID_UNITS:
            return None
        coordinates.append(nearest)
    return coordinates[0], coordinates[1]


def _sign(value: int) -> int:
    return (value > 0) - (value < 0)


def _capsule_cell_claims(
    domain_id: str,
    layer: LayerName,
    start: tuple[float, float],
    end: tuple[float, float],
    grid_mm: float,
    radius_mm: float,
) -> set[RoutingResourceKey]:
    half = grid_mm / 2.0
    min_ix = math.ceil((min(start[0], end[0]) - radius_mm) / grid_mm - 0.5)
    max_ix = math.floor((max(start[0], end[0]) + radius_mm) / grid_mm + 0.5)
    min_iy = math.ceil((min(start[1], end[1]) - radius_mm) / grid_mm - 0.5)
    max_iy = math.floor((max(start[1], end[1]) + radius_mm) / grid_mm + 0.5)
    radius_squared = radius_mm * radius_mm
    resources: set[RoutingResourceKey] = set()
    for ix in range(min_ix, max_ix + 1):
        for iy in range(min_iy, max_iy + 1):
            rect = (
                ix * grid_mm - half,
                iy * grid_mm - half,
                ix * grid_mm + half,
                iy * grid_mm + half,
            )
            distance_squared = _segment_rect_distance_squared(start, end, rect)
            if distance_squared <= radius_squared + _GEOMETRY_EPSILON:
                resources.add(RoutingResourceKey(domain_id, layer, "cell", ix, iy))
    return resources


def _segment_rect_distance_squared(
    start: tuple[float, float],
    end: tuple[float, float],
    rect: tuple[float, float, float, float],
) -> float:
    min_x, min_y, max_x, max_y = rect
    if _point_in_rect(start, rect) or _point_in_rect(end, rect):
        return 0.0
    corners = (
        (min_x, min_y),
        (max_x, min_y),
        (max_x, max_y),
        (min_x, max_y),
    )
    edges = tuple((corners[index], corners[(index + 1) % 4]) for index in range(4))
    return min(_segment_distance_squared(start, end, a, b) for a, b in edges)


def _point_in_rect(point: tuple[float, float], rect: tuple[float, float, float, float]) -> bool:
    return rect[0] <= point[0] <= rect[2] and rect[1] <= point[1] <= rect[3]


def _segment_distance_squared(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> float:
    if _segments_intersect(a, b, c, d):
        return 0.0
    return min(
        _point_segment_distance_squared(a, c, d),
        _point_segment_distance_squared(b, c, d),
        _point_segment_distance_squared(c, a, b),
        _point_segment_distance_squared(d, a, b),
    )


def _point_segment_distance_squared(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length_squared = dx * dx + dy * dy
    if length_squared == 0:
        return (point[0] - start[0]) ** 2 + (point[1] - start[1]) ** 2
    parameter = ((point[0] - start[0]) * dx + (point[1] - start[1]) * dy) / length_squared
    parameter = min(1.0, max(0.0, parameter))
    nearest = (start[0] + parameter * dx, start[1] + parameter * dy)
    return (point[0] - nearest[0]) ** 2 + (point[1] - nearest[1]) ** 2


def _segments_intersect(
    a: tuple[float, float],
    b: tuple[float, float],
    c: tuple[float, float],
    d: tuple[float, float],
) -> bool:
    first = _orientation(a, b, c)
    second = _orientation(a, b, d)
    third = _orientation(c, d, a)
    fourth = _orientation(c, d, b)
    if first * second < 0 and third * fourth < 0:
        return True
    return (
        (first == 0 and _on_segment(c, a, b))
        or (second == 0 and _on_segment(d, a, b))
        or (third == 0 and _on_segment(a, c, d))
        or (fourth == 0 and _on_segment(b, c, d))
    )


def _orientation(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> int:
    value = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    if abs(value) <= _GEOMETRY_EPSILON:
        return 0
    return 1 if value > 0 else -1


def _on_segment(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> bool:
    return (
        min(start[0], end[0]) - _GEOMETRY_EPSILON
        <= point[0]
        <= max(start[0], end[0]) + _GEOMETRY_EPSILON
        and min(start[1], end[1]) - _GEOMETRY_EPSILON
        <= point[1]
        <= max(start[1], end[1]) + _GEOMETRY_EPSILON
    )
