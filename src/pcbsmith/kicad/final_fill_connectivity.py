"""Exact KiCad island evidence and conservative W3 source reachability."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.final_fill_adapter import (
    FillReachability,
    KiCadFilledCopperRegion,
    KiCadFinalFillSnapshot,
)
from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel


class KiCadPadZoneContact(SemanticIrModel):
    """One intended physical pad/zone/layer contact, including zero-spoke pads."""

    contact_id: str
    pad_id: str
    logical_pad_id: str
    zone_id: str
    layer: str
    mode: Literal["thermal", "solid", "none", "unverified"]
    flashed: bool
    contacting_region_ids: tuple[str, ...]

    @model_validator(mode="after")
    def exact_physical_identity(self) -> Self:
        for name in ("contact_id", "pad_id", "logical_pad_id", "zone_id", "layer"):
            require_identity(getattr(self, name), name)
        if not self.pad_id.startswith("pad:") or len(self.pad_id) <= 4:
            raise ValueError("pad/zone contacts require a physical pad identity")
        if len(set(self.contacting_region_ids)) != len(self.contacting_region_ids):
            raise ValueError("pad contact region identities must be unique")
        if not self.flashed and self.contacting_region_ids:
            raise ValueError("unflashed pad cannot claim a native plane contact")
        return self


def thermal_contact_inventory(
    observation: KiCadFinalFillConnectivityObservation,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if observation.pad_zone_contacts is not None:
        return tuple(
            sorted(c.contact_id for c in observation.pad_zone_contacts if c.mode == "thermal")
        ), tuple(
            sorted(c.contact_id for c in observation.pad_zone_contacts if c.mode == "unverified")
        )
    return tuple(
        sorted({p for r in observation.records for p in r.thermal_applicable_pad_ids})
    ), tuple(
        sorted({p for r in observation.records for p in r.thermal_resolution_unverified_pad_ids})
    )


class KiCadFilledRegionContactObservation(SemanticIrModel):
    region_id: str
    zone_id: str
    zone_index: int = Field(ge=0)
    region_index: int = Field(ge=0)
    net_name: str
    layer: str
    is_island: bool
    direct_contact_ids: tuple[str, ...] = ()
    connected_pad_ids: tuple[str, ...]
    reachable_pad_ids: tuple[str, ...] = ()
    thermal_applicable_pad_ids: tuple[str, ...] = ()
    thermal_resolution_unverified_pad_ids: tuple[str, ...] = ()
    pad_mapping_exact: bool
    pad_mapping_scope: Literal[
        "single_filled_region_zone",
        "isolated_region_exact",
        "integer_effective_shape_contact_graph",
        "fragmented_zone_pad_mapping_unresolved",
    ]
    thermal_spoke_status: Literal["unverified"] = "unverified"
    outline_nm: tuple[tuple[int, int], ...] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    holes_nm: tuple[tuple[tuple[int, int], ...], ...] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )

    @model_validator(mode="after")
    def contact_is_truthful(self) -> Self:
        for name in ("region_id", "zone_id", "net_name", "layer"):
            require_identity(getattr(self, name), name)
        if (self.outline_nm is None) != (self.holes_nm is None):
            raise ValueError("native region contours require both outline and hole inventory")
        if self.outline_nm is not None and (
            len(self.outline_nm) < 3 or any(len(h) < 3 for h in self.holes_nm or ())
        ):
            raise ValueError("native contours require at least three integer points")
        contacts = tuple(sorted(self.direct_contact_ids))
        pads = tuple(sorted(self.connected_pad_ids))
        reachable = tuple(sorted(self.reachable_pad_ids))
        thermal = tuple(sorted(self.thermal_applicable_pad_ids))
        unresolved_thermal = tuple(sorted(self.thermal_resolution_unverified_pad_ids))
        for label, identities in (
            ("direct contact", contacts),
            ("connected pad", pads),
            ("reachable pad", reachable),
            ("thermal-applicable pad", thermal),
            ("thermal-resolution-unverified pad", unresolved_thermal),
        ):
            if len(identities) != len(set(identities)):
                raise ValueError(f"{label} identities must be unique")
        if self.pad_mapping_scope == "single_filled_region_zone":
            if not self.pad_mapping_exact:
                raise ValueError("single-region zone pad mapping must be exact")
        elif self.pad_mapping_scope == "isolated_region_exact":
            if (
                not self.pad_mapping_exact
                or not self.is_island
                or contacts
                or pads
                or reachable
                or thermal
                or unresolved_thermal
            ):
                raise ValueError("isolated region must be exact and have no contacts")
        elif self.pad_mapping_scope == "integer_effective_shape_contact_graph":
            if not self.pad_mapping_exact:
                raise ValueError("integer-shape contact graph must be exact")
        elif self.pad_mapping_exact or contacts or pads or reachable:
            raise ValueError("unresolved fragmented mapping cannot invent contacts")
        object.__setattr__(self, "direct_contact_ids", contacts)
        object.__setattr__(self, "connected_pad_ids", pads)
        object.__setattr__(self, "reachable_pad_ids", reachable)
        object.__setattr__(self, "thermal_applicable_pad_ids", thermal)
        object.__setattr__(self, "thermal_resolution_unverified_pad_ids", unresolved_thermal)
        return self


class KiCadCopperItemComponent(SemanticIrModel):
    """A native same-net component queried with EXCLUDE_ZONES, using physical IDs."""

    net_name: str
    item_ids: tuple[str, ...]
    pad_ids: tuple[str, ...]

    @model_validator(mode="after")
    def physical_items_are_unique(self) -> Self:
        require_identity(self.net_name, "net_name")
        if not self.item_ids or len(set(self.item_ids)) != len(self.item_ids):
            raise ValueError("native item component must contain unique physical items")
        if any(
            not i.startswith(("pad:", "PCB_TRACK:", "PCB_ARC:", "PCB_VIA:")) for i in self.item_ids
        ):
            raise ValueError("native item component contains unsupported copper")
        if set(self.pad_ids) != {i for i in self.item_ids if i.startswith("pad:")} or len(
            self.pad_ids
        ) != len(set(self.pad_ids)):
            raise ValueError("native item component pad inventory is incomplete")
        return self


class KiCadRegionContactGraph(SemanticIrModel):
    """Complete contacts in the bridge's supported scope; no geometric path metrics."""

    authority: Literal["native-copper-items-and-filled-regions-v1"]
    item_components: tuple[KiCadCopperItemComponent, ...]
    region_contacts: tuple[tuple[str, str], ...]


def _replay_region_graph(
    records: tuple[KiCadFilledRegionContactObservation, ...], graph: KiCadRegionContactGraph
) -> dict[str, tuple[str, ...]]:
    """Replay region contacts without ever treating a whole zone as one conductor."""

    regions = {r.region_id: r for r in records}
    item_component: dict[str, int] = {}
    adjacency: dict[str | int, set[str | int]] = {r: set() for r in regions}
    for index, component in enumerate(graph.item_components):
        adjacency[index] = set()
        for item in component.item_ids:
            if item in item_component:
                raise ValueError("physical copper item belongs to multiple native components")
            item_component[item] = index
    for region in records:
        if (
            not region.pad_mapping_exact
            or region.pad_mapping_scope != "integer_effective_shape_contact_graph"
            or region.outline_nm is None
        ):
            raise ValueError("region graph requires exact per-outline contact geometry")
        if set(region.connected_pad_ids) != {
            i for i in region.direct_contact_ids if i.startswith("pad:")
        }:
            raise ValueError("region graph direct pad inventory is incomplete")
        for item in region.direct_contact_ids:
            component_index = item_component.get(item)
            if (
                component_index is None
                or graph.item_components[component_index].net_name != region.net_name
            ):
                raise ValueError("region contact has missing or foreign-net item component")
            adjacency[region.region_id].add(component_index)
            adjacency[component_index].add(region.region_id)
    seen_links: set[tuple[str, str]] = set()
    for a, b in graph.region_contacts:
        if a >= b or (a, b) in seen_links or a not in regions or b not in regions:
            raise ValueError("region contacts must be unique ordered pairs of known regions")
        seen_links.add((a, b))
        if (regions[a].net_name, regions[a].layer) != (regions[b].net_name, regions[b].layer):
            raise ValueError("region contact crosses a net or copper layer")
        adjacency[a].add(b)
        adjacency[b].add(a)
    reached: dict[str, tuple[str, ...]] = {}
    for identity in regions:
        if identity in reached:
            continue
        pending: list[str | int] = [identity]
        visited: set[str | int] = set()
        pads: set[str] = set()
        while pending:
            node = pending.pop()
            if node in visited:
                continue
            visited.add(node)
            if isinstance(node, int):
                pads.update(graph.item_components[node].pad_ids)
            pending.extend(adjacency[node] - visited)
        for node in visited:
            if isinstance(node, str):
                reached[node] = tuple(sorted(pads))
    for region in records:
        if region.reachable_pad_ids != reached[region.region_id]:
            raise ValueError("region reachability differs from replayed native contact graph")
    return reached


class KiCadFinalFillConnectivityObservation(SemanticIrModel):
    schema_id: Literal["pcbsmith-kicad-final-fill-connectivity-observation-v1"] = (
        "pcbsmith-kicad-final-fill-connectivity-observation-v1"
    )
    board_file: str
    board_sha256: str
    kicad_version: str
    island_authority: Literal["ZONE.IsIsland(layer, filled_outline_index)"]
    records: tuple[KiCadFilledRegionContactObservation, ...]
    qualification_boundary: str
    pad_zone_contacts: tuple[KiCadPadZoneContact, ...] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    region_contact_graph: KiCadRegionContactGraph | None = Field(
        default=None, exclude_if=lambda v: v is None
    )

    @model_validator(mode="after")
    def observation_is_closed(self) -> Self:
        require_identity(self.board_file, "board_file")
        require_sha256(self.board_sha256, "board_sha256")
        require_identity(self.kicad_version, "kicad_version")
        require_identity(self.qualification_boundary, "qualification_boundary")
        records = tuple(sorted(self.records, key=lambda item: item.region_id))
        ids = tuple(item.region_id for item in records)
        if len(ids) != len(set(ids)):
            raise ValueError("filled-region contact identities must be unique")
        if self.region_contact_graph is not None:
            _replay_region_graph(records, self.region_contact_graph)
        if self.pad_zone_contacts is not None:
            contact_ids = [c.contact_id for c in self.pad_zone_contacts]
            if len(contact_ids) != len(set(contact_ids)):
                raise ValueError("pad/zone/layer contacts must be unique")
            by_id = {r.region_id: r for r in records}
            for contact in self.pad_zone_contacts:
                if contact.contact_id != f"{contact.zone_id}:{contact.layer}:{contact.pad_id}":
                    raise ValueError("pad/zone/layer contact identity is stale")
                for identity in contact.contacting_region_ids:
                    region = by_id.get(identity)
                    if region is None or (region.zone_id, region.layer) != (
                        contact.zone_id,
                        contact.layer,
                    ):
                        raise ValueError("pad contact targets another region or layer")
                    if contact.pad_id not in region.connected_pad_ids:
                        raise ValueError("pad contact is absent from native region inventory")
            for region in records:
                observed = {
                    c.pad_id
                    for c in self.pad_zone_contacts
                    if region.region_id in c.contacting_region_ids
                }
                if observed != set(region.connected_pad_ids):
                    raise ValueError("pad/zone inventory does not cover every observed pad contact")
        object.__setattr__(self, "records", records)
        return self


def classify_final_fill_reachability(
    snapshot: KiCadFinalFillSnapshot,
    observation: KiCadFinalFillConnectivityObservation,
    *,
    declared_source_pad_ids: tuple[str, ...],
) -> KiCadFinalFillSnapshot:
    """Classify only reachability that KiCad's exact saved-fill state proves."""

    if observation.board_sha256 != snapshot.filled_board_sha256:
        raise ValueError("fill-connectivity observation targets another board revision")
    if observation.kicad_version != snapshot.kicad_version:
        raise ValueError("fill-connectivity and refill producer versions differ")
    sources = tuple(sorted(declared_source_pad_ids))
    if len(sources) != len(set(sources)) or any(not item.strip() for item in sources):
        raise ValueError("declared source pad identities must be unique and non-empty")
    by_id = {item.region_id: item for item in observation.records}
    graph_reachability = (
        _replay_region_graph(observation.records, observation.region_contact_graph)
        if observation.region_contact_graph is not None
        else None
    )
    zone_indices = {zone.zone_id: zone.zone_index for zone in snapshot.zones}
    if set(by_id) != {item.region_id for item in snapshot.regions}:
        raise ValueError("fill-connectivity observation does not cover the exact region set")
    regions: list[KiCadFilledCopperRegion] = []
    for region in snapshot.regions:
        contact = by_id[region.region_id]
        if (
            contact.zone_id != region.zone_id
            or contact.zone_index != zone_indices[region.zone_id]
            or contact.region_index != region.region_index
            or contact.net_name != region.net_name
            or contact.layer != region.layer
        ):
            raise ValueError("fill-connectivity region identity differs from exact fill")
        # Graph-based evidence includes the other regions and native item components
        # traversed to reach this region, not just this region's local contacts.
        evidence_id = fingerprint(
            observation.model_dump(mode="json")
            if graph_reachability is not None
            else contact.model_dump(mode="json")
        )
        evidence: tuple[str, ...]
        if (graph_reachability is not None and not graph_reachability[region.region_id]) or (
            graph_reachability is None and contact.is_island
        ):
            reachability = FillReachability.FLOATING
            evidence = (evidence_id,)
        elif contact.pad_mapping_exact and set(contact.reachable_pad_ids) & set(sources):
            reachability = FillReachability.SOURCE_REACHABLE
            evidence = (evidence_id,)
        else:
            reachability = FillReachability.UNVERIFIED
            evidence = ()
        values = {
            name: getattr(region, name)
            for name in type(region).model_fields
            if name != "region_fingerprint"
        }
        values["reachability"] = reachability
        values["reachability_evidence_ids"] = evidence
        regions.append(KiCadFilledCopperRegion.build(**values))
    excluded = {
        "regions",
        "unverified_region_ids",
        "zone_intent_unchanged",
        "stale_fill",
        "snapshot_fingerprint",
    }
    values = {
        name: getattr(snapshot, name)
        for name in type(snapshot).model_fields
        if name not in excluded
    }
    return KiCadFinalFillSnapshot.build(**values, regions=tuple(regions))


__all__ = [
    "KiCadFilledRegionContactObservation",
    "KiCadFinalFillConnectivityObservation",
    "classify_final_fill_reachability",
]


def observe_final_fill_contacts(
    board: Path,
    output: Path,
    *,
    kicad_python: Path,
    timeout_seconds: float = 60,
) -> KiCadFinalFillConnectivityObservation:
    """Run the read-only native observer with exact input binding and a finite timeout."""
    import hashlib
    import subprocess

    if not 0 < timeout_seconds <= 180:
        raise ValueError("native fill observation requires a bounded timeout")
    if output.exists():
        raise ValueError("native contact output must be fresh")
    before = hashlib.sha256(board.read_bytes()).hexdigest()
    bridge = Path(__file__).resolve().parents[3] / "tools/kicad_final_fill_connectivity_bridge.py"
    result = subprocess.run(
        [str(kicad_python), str(bridge), str(board.resolve()), str(output.resolve())],
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix(".stdout.log").write_bytes(result.stdout)
    output.with_suffix(".stderr.log").write_bytes(result.stderr)
    if result.returncode or not output.is_file():
        raise RuntimeError("native fill-contact observation failed; inspect retained logs")
    observation = KiCadFinalFillConnectivityObservation.model_validate_json(output.read_bytes())
    if (
        observation.board_sha256 != before
        or hashlib.sha256(board.read_bytes()).hexdigest() != before
    ):
        raise ValueError("native contact observer changed or mismatched its input board")
    return observation
