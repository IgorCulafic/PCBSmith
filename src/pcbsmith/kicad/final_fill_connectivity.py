"""Exact KiCad island evidence and conservative W3 source reachability."""

from __future__ import annotations

from typing import Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.final_fill_adapter import (
    FillReachability,
    KiCadFilledCopperRegion,
    KiCadFinalFillSnapshot,
)
from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel


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

    @model_validator(mode="after")
    def contact_is_truthful(self) -> Self:
        for name in ("region_id", "zone_id", "net_name", "layer"):
            require_identity(getattr(self, name), name)
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
        object.__setattr__(
            self, "thermal_resolution_unverified_pad_ids", unresolved_thermal
        )
        return self


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
    sources = tuple(sorted(declared_source_pad_ids))
    if len(sources) != len(set(sources)) or any(not item.strip() for item in sources):
        raise ValueError("declared source pad identities must be unique and non-empty")
    by_id = {item.region_id: item for item in observation.records}
    if set(by_id) != {item.region_id for item in snapshot.regions}:
        raise ValueError("fill-connectivity observation does not cover the exact region set")
    regions: list[KiCadFilledCopperRegion] = []
    for region in snapshot.regions:
        contact = by_id[region.region_id]
        if (
            contact.zone_id != region.zone_id
            or contact.region_index != region.region_index
            or contact.net_name != region.net_name
            or contact.layer != region.layer
        ):
            raise ValueError("fill-connectivity region identity differs from exact fill")
        evidence_id = fingerprint(contact.model_dump(mode="json"))
        evidence: tuple[str, ...]
        if contact.is_island:
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
