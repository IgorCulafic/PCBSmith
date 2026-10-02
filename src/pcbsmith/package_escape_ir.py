"""Source-preserving package escape certificates for W5."""

from __future__ import annotations

import math
from collections import defaultdict, deque
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.power_topology_ir import NeckdownAllowance
from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.routing_ir import (
    RouteMutationKind,
    RoutePoint,
    RouteSegmentDelta,
    RouteSegmentGeometry,
    RouteViaDelta,
    RouteViaGeometry,
)
from pcbsmith.semantic_ir import SemanticIrModel


class EscapePadAnchor(SemanticIrModel):
    pad_id: str
    net_name: str
    layer: str
    center: RoutePoint
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)


class EscapeNetWidth(SemanticIrModel):
    net_name: str
    bulk_width_mm: float = Field(gt=0)


class ReservedEscapeCorridor(SemanticIrModel):
    corridor_id: str
    role: Literal["power", "return"]
    layer: str
    x_min_mm: float
    y_min_mm: float
    x_max_mm: float
    y_max_mm: float
    permitted_net_names: tuple[str, ...] = ()

    @model_validator(mode="after")
    def bounds_are_ordered(self) -> Self:
        require_identity(self.corridor_id, "corridor_id")
        if self.x_min_mm >= self.x_max_mm or self.y_min_mm >= self.y_max_mm:
            raise ValueError("reserved corridor bounds must have positive area")
        nets = tuple(sorted(self.permitted_net_names))
        if len(nets) != len(set(nets)):
            raise ValueError("permitted corridor nets must be unique")
        object.__setattr__(self, "permitted_net_names", nets)
        return self


class PackageEscapeRequest(SemanticIrModel):
    schema_id: Literal["pcbsmith-package-escape-request"] = "pcbsmith-package-escape-request"
    schema_version: Literal[1] = 1
    source_board_sha256: str
    exact_footprint_geometry_fingerprint: str
    fabrication_profile_fingerprint: str
    minimum_via_diameter_mm: float = Field(gt=0)
    minimum_via_drill_mm: float = Field(gt=0)
    pads: tuple[EscapePadAnchor, ...] = Field(min_length=1)
    net_widths: tuple[EscapeNetWidth, ...] = Field(min_length=1)
    neckdown_allowances: tuple[NeckdownAllowance, ...] = ()
    reserved_corridors: tuple[ReservedEscapeCorridor, ...] = ()
    via_in_pad_authority_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def request_is_canonical(self) -> Self:
        for name in (
            "source_board_sha256",
            "exact_footprint_geometry_fingerprint",
            "fabrication_profile_fingerprint",
        ):
            require_sha256(getattr(self, name), name)
        if self.minimum_via_drill_mm >= self.minimum_via_diameter_mm:
            raise ValueError("minimum via drill must be smaller than diameter")
        pads = tuple(sorted(self.pads, key=lambda item: item.pad_id))
        widths = tuple(sorted(self.net_widths, key=lambda item: item.net_name))
        neckdowns = tuple(sorted(self.neckdown_allowances, key=lambda item: item.neckdown_id))
        corridors = tuple(sorted(self.reserved_corridors, key=lambda item: item.corridor_id))
        authorities = tuple(sorted(self.via_in_pad_authority_ids))
        for values, name in (
            (tuple(item.pad_id for item in pads), "pad"),
            (tuple(item.net_name for item in widths), "net width"),
            (tuple(item.neckdown_id for item in neckdowns), "neckdown"),
            (tuple(item.corridor_id for item in corridors), "corridor"),
            (authorities, "via-in-pad authority"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{name} identities must be unique")
        object.__setattr__(self, "pads", pads)
        object.__setattr__(self, "net_widths", widths)
        object.__setattr__(self, "neckdown_allowances", neckdowns)
        object.__setattr__(self, "reserved_corridors", corridors)
        object.__setattr__(self, "via_in_pad_authority_ids", authorities)
        return self


class EscapeSegmentProposal(SemanticIrModel):
    segment_id: str
    pad_id: str
    geometry: RouteSegmentGeometry
    neckdown_id: str | None = None


class EscapeViaProposal(SemanticIrModel):
    via_id: str
    pad_id: str
    geometry: RouteViaGeometry
    via_in_pad_authority_id: str | None = None


class PackageEscapeCertificate(SemanticIrModel):
    schema_id: Literal["pcbsmith-package-escape-certificate"] = (
        "pcbsmith-package-escape-certificate"
    )
    schema_version: Literal[1] = 1
    source_board_sha256: str
    request_fingerprint: str
    qualified: bool
    blocker_ids: tuple[str, ...]
    segment_proposals: tuple[EscapeSegmentProposal, ...]
    via_proposals: tuple[EscapeViaProposal, ...]
    segment_deltas: tuple[RouteSegmentDelta, ...]
    via_deltas: tuple[RouteViaDelta, ...]
    automatic_apply_authorized: Literal[False] = False
    certificate_fingerprint: str

    @model_validator(mode="after")
    def certificate_is_coherent(self) -> Self:
        require_sha256(self.source_board_sha256, "source_board_sha256")
        require_sha256(self.request_fingerprint, "request_fingerprint")
        blockers = tuple(sorted(set(self.blocker_ids)))
        if self.qualified != (not blockers):
            raise ValueError("escape certificate disposition is stale")
        if blockers and (self.segment_deltas or self.via_deltas):
            raise ValueError("failed escape certificate must not expose a mutation delta")
        object.__setattr__(self, "blocker_ids", blockers)
        require_sha256(self.certificate_fingerprint, "certificate_fingerprint")
        expected = fingerprint(self.model_dump(mode="json", exclude={"certificate_fingerprint"}))
        if self.certificate_fingerprint != expected:
            raise ValueError("escape certificate fingerprint is stale")
        return self


def _length(segment: RouteSegmentGeometry) -> float:
    return math.hypot(segment.end.x_mm - segment.start.x_mm, segment.end.y_mm - segment.start.y_mm)


def _point_key(point: RoutePoint) -> tuple[float, float, str]:
    return (point.x_mm, point.y_mm, "")


def _distance_to_pad(segment: RouteSegmentGeometry, pad: EscapePadAnchor) -> float:
    return min(
        math.hypot(point.x_mm - pad.center.x_mm, point.y_mm - pad.center.y_mm)
        for point in (segment.start, segment.end)
    )


def _segment_hits_expanded_corridor(
    segment: RouteSegmentGeometry, corridor: ReservedEscapeCorridor
) -> bool:
    """Liang-Barsky intersection with the trace-radius-expanded rectangle."""

    radius = segment.width_mm / 2
    x_min, x_max = corridor.x_min_mm - radius, corridor.x_max_mm + radius
    y_min, y_max = corridor.y_min_mm - radius, corridor.y_max_mm + radius
    x0, y0 = segment.start.x_mm, segment.start.y_mm
    dx, dy = segment.end.x_mm - x0, segment.end.y_mm - y0
    lower, upper = 0.0, 1.0
    for p, q in ((-dx, x0 - x_min), (dx, x_max - x0), (-dy, y0 - y_min), (dy, y_max - y0)):
        if p == 0:
            if q < 0:
                return False
            continue
        ratio = q / p
        if p < 0:
            lower = max(lower, ratio)
        else:
            upper = min(upper, ratio)
        if lower > upper:
            return False
    return True


def _via_inside_pad(via: RouteViaGeometry, pad: EscapePadAnchor) -> bool:
    return (
        abs(via.position.x_mm - pad.center.x_mm) <= pad.width_mm / 2
        and abs(via.position.y_mm - pad.center.y_mm) <= pad.height_mm / 2
    )


def _pad_reaches_bulk(
    pad: EscapePadAnchor,
    segments: tuple[EscapeSegmentProposal, ...],
    bulk_width: float,
) -> bool:
    by_point: dict[tuple[float, float, str], list[EscapeSegmentProposal]] = defaultdict(list)
    for proposal in segments:
        if proposal.geometry.net_name != pad.net_name or proposal.geometry.layer != pad.layer:
            continue
        by_point[_point_key(proposal.geometry.start)].append(proposal)
        by_point[_point_key(proposal.geometry.end)].append(proposal)
    initial = (pad.center.x_mm, pad.center.y_mm, "")
    queue = deque([initial])
    seen_points = {initial}
    seen_segments: set[str] = set()
    while queue:
        point = queue.popleft()
        for proposal in by_point.get(point, []):
            if proposal.segment_id in seen_segments:
                continue
            seen_segments.add(proposal.segment_id)
            if proposal.geometry.width_mm >= bulk_width:
                return True
            for endpoint in (proposal.geometry.start, proposal.geometry.end):
                key = _point_key(endpoint)
                if key not in seen_points:
                    seen_points.add(key)
                    queue.append(key)
    return False


def build_package_escape_certificate(
    request: PackageEscapeRequest,
    *,
    segment_proposals: tuple[EscapeSegmentProposal, ...],
    via_proposals: tuple[EscapeViaProposal, ...],
) -> PackageEscapeCertificate:
    pads = {item.pad_id: item for item in request.pads}
    widths = {item.net_name: item.bulk_width_mm for item in request.net_widths}
    allowances = {item.neckdown_id: item for item in request.neckdown_allowances}
    blockers: set[str] = set()
    segment_ids = tuple(item.segment_id for item in segment_proposals)
    via_ids = tuple(item.via_id for item in via_proposals)
    if len(segment_ids) != len(set(segment_ids)):
        blockers.add("duplicate_segment_identity")
    if len(via_ids) != len(set(via_ids)):
        blockers.add("duplicate_via_identity")

    for proposal in segment_proposals:
        pad = pads.get(proposal.pad_id)
        bulk_width = widths.get(proposal.geometry.net_name)
        if pad is None or proposal.geometry.net_name != pad.net_name:
            blockers.add(f"{proposal.segment_id}:pad_or_net_mismatch")
            continue
        if bulk_width is None:
            blockers.add(f"{proposal.segment_id}:bulk_width_undeclared")
            continue
        if proposal.geometry.width_mm < bulk_width:
            allowance = allowances.get(proposal.neckdown_id or "")
            if allowance is None or proposal.pad_id not in allowance.pad_ids:
                blockers.add(f"{proposal.segment_id}:neckdown_undeclared")
            elif (
                proposal.geometry.width_mm < allowance.minimum_width_mm
                or _length(proposal.geometry) > allowance.maximum_length_mm
                or _distance_to_pad(proposal.geometry, pad) > allowance.maximum_length_mm
            ):
                blockers.add(f"{proposal.segment_id}:neckdown_envelope_exceeded")
        elif proposal.neckdown_id is not None:
            blockers.add(f"{proposal.segment_id}:spurious_neckdown_assignment")
        for corridor in request.reserved_corridors:
            if (
                proposal.geometry.layer == corridor.layer
                and proposal.geometry.net_name not in corridor.permitted_net_names
                and _segment_hits_expanded_corridor(proposal.geometry, corridor)
            ):
                blockers.add(f"{proposal.segment_id}:reserved_{corridor.role}_corridor")

    for pad in request.pads:
        if not _pad_reaches_bulk(pad, segment_proposals, widths.get(pad.net_name, math.inf)):
            blockers.add(f"{pad.pad_id}:bulk_width_not_restored")

    for via_proposal in via_proposals:
        pad = pads.get(via_proposal.pad_id)
        if pad is None or via_proposal.geometry.net_name != pad.net_name:
            blockers.add(f"{via_proposal.via_id}:pad_or_net_mismatch")
            continue
        if (
            via_proposal.geometry.diameter_mm < request.minimum_via_diameter_mm
            or via_proposal.geometry.drill_mm < request.minimum_via_drill_mm
        ):
            blockers.add(f"{via_proposal.via_id}:via_below_profile_minimum")
        if _via_inside_pad(via_proposal.geometry, pad):
            authority = via_proposal.via_in_pad_authority_id
            if authority is None or authority not in request.via_in_pad_authority_ids:
                blockers.add(f"{via_proposal.via_id}:via_in_pad_unsupported")
        for corridor in request.reserved_corridors:
            point = via_proposal.geometry.position
            if (
                via_proposal.geometry.start_layer == corridor.layer
                and via_proposal.geometry.net_name not in corridor.permitted_net_names
                and corridor.x_min_mm <= point.x_mm <= corridor.x_max_mm
                and corridor.y_min_mm <= point.y_mm <= corridor.y_max_mm
            ):
                blockers.add(f"{via_proposal.via_id}:reserved_{corridor.role}_corridor")

    canonical_segments = tuple(sorted(segment_proposals, key=lambda item: item.segment_id))
    canonical_vias = tuple(sorted(via_proposals, key=lambda item: item.via_id))
    segment_deltas: tuple[RouteSegmentDelta, ...] = ()
    via_deltas: tuple[RouteViaDelta, ...] = ()
    if not blockers:
        segment_deltas = tuple(
            RouteSegmentDelta(
                mutation_id=f"escape-add:{item.segment_id}",
                operation=RouteMutationKind.ADD,
                object_id=item.segment_id,
                after=item.geometry,
            )
            for item in canonical_segments
        )
        via_deltas = tuple(
            RouteViaDelta(
                mutation_id=f"escape-add:{item.via_id}",
                operation=RouteMutationKind.ADD,
                object_id=item.via_id,
                after=item.geometry,
            )
            for item in canonical_vias
        )
    values: dict[str, Any] = {
        "source_board_sha256": request.source_board_sha256,
        "request_fingerprint": request.semantic_fingerprint(),
        "qualified": not blockers,
        "blocker_ids": tuple(sorted(blockers)),
        "segment_proposals": canonical_segments,
        "via_proposals": canonical_vias,
        "segment_deltas": segment_deltas,
        "via_deltas": via_deltas,
    }
    provisional = PackageEscapeCertificate.model_construct(
        **values, certificate_fingerprint="0" * 64
    )
    return PackageEscapeCertificate(
        **values,
        certificate_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"certificate_fingerprint"})
        ),
    )


__all__ = [
    "EscapeNetWidth",
    "EscapePadAnchor",
    "EscapeSegmentProposal",
    "EscapeViaProposal",
    "PackageEscapeCertificate",
    "PackageEscapeRequest",
    "ReservedEscapeCorridor",
    "build_package_escape_certificate",
]
