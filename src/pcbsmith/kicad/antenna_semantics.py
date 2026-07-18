"""Placement-only R6.2 evaluator for module-specific antenna geometry."""

from __future__ import annotations

from pcbsmith.antenna_ir import (
    AntennaLocalRegion,
    AntennaModuleDeclaration,
    AntennaPlacedRegion,
    AntennaPlacementResult,
    AntennaRegionRole,
    InstalledFootprintKeepoutProvenance,
    antenna_placement_result_fingerprint,
)
from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNetlist,
    placement_rotation,
    placement_y,
)
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.placement_geometry import (
    ExactPlanarCompound,
    PlacementTransform,
    PlacementTransformAuthority,
    transform_compound,
    transform_compound_bounded,
)
from pcbsmith.semantic_ir import SemanticVerification


def _component_matches(component: BoardComponent, declaration: AntennaModuleDeclaration) -> bool:
    revision_fields = [
        value
        for name, value in component.fields
        if name == declaration.component_revision_field_name
    ]
    return (
        component.reference == declaration.module_reference
        and component.footprint == declaration.selected_footprint_library_id
        and component.uuid_path == declaration.component_uuid_path
        and revision_fields == [declaration.component_revision]
    )


def _placed_region(
    *,
    region: AntennaLocalRegion | InstalledFootprintKeepoutProvenance,
    role: AntennaRegionRole,
    transform: PlacementTransform,
) -> AntennaPlacedRegion:
    bounded = transform_compound_bounded(region.compound, transform)
    exact: ExactPlanarCompound | None = None
    verification = SemanticVerification.BOUNDED_APPROXIMATION
    if bounded.authority is PlacementTransformAuthority.EXACT:
        exact = transform_compound(region.compound, transform)
        if exact != bounded.compound:
            raise ValueError("shared exact and bounded transform kernels disagree")
        verification = SemanticVerification.EXACT
    return AntennaPlacedRegion(
        region_id=region.region_id,
        role=role,
        local_compound=region.compound,
        layers=region.layers,
        prohibited_object_kinds=(
            region.prohibited_object_kinds
            if isinstance(region, InstalledFootprintKeepoutProvenance)
            else ()
        ),
        bounded_transform=bounded,
        exact_transformed_compound=exact,
        verification=verification,
    )


def derive_antenna_placement(
    layout: BoardLayout,
    netlist: BoardNetlist,
    declaration: AntennaModuleDeclaration,
) -> tuple[PlacementTransform, tuple[AntennaPlacedRegion, ...]]:
    """Derive one exact pose and placed source regions from exact board values."""

    placed_matches = [
        (component, anchor_x)
        for component, anchor_x in layout.placements
        if component.reference == declaration.module_reference
    ]
    if len(placed_matches) != 1:
        raise ValueError("antenna module reference must have exactly one BoardLayout placement")
    netlist_matches = [
        component
        for component in netlist.components
        if component.reference == declaration.module_reference
    ]
    if len(netlist_matches) != 1:
        raise ValueError("antenna module reference must occur exactly once in BoardNetlist")
    placed_component, anchor_x = placed_matches[0]
    netlist_component = netlist_matches[0]
    if not _component_matches(placed_component, declaration):
        raise ValueError("placed antenna component identity does not match declaration")
    if not _component_matches(netlist_component, declaration):
        raise ValueError("netlisted antenna component identity does not match declaration")
    if placed_component != netlist_component:
        raise ValueError("placed and netlisted antenna component snapshots differ")
    transform = PlacementTransform(
        anchor_x_mm=anchor_x,
        anchor_y_mm=placement_y(layout, declaration.module_reference),
        rotation_deg=placement_rotation(layout, declaration.module_reference),
        side="back" if declaration.module_reference in layout.part_flip else "front",
    )
    regions = (
        _placed_region(region=declaration.antenna_region, role="antenna", transform=transform),
        _placed_region(region=declaration.feed_region, role="feed", transform=transform),
        *(
            _placed_region(region=keepout, role="keepout", transform=transform)
            for keepout in declaration.keepouts
        ),
    )
    return transform, tuple(sorted(regions, key=lambda item: item.region_id))


def evaluate_antenna_placement(
    layout: BoardLayout,
    netlist: BoardNetlist,
    declaration: AntennaModuleDeclaration,
) -> AntennaPlacementResult:
    """Retain exact inputs and place module-local regions without broader claims."""

    layout_snapshot = canonical_board_layout_snapshot_json(layout)
    netlist_snapshot = canonical_board_netlist_snapshot_json(netlist)
    transform, regions = derive_antenna_placement(layout, netlist, declaration)
    layout_fingerprint = board_layout_snapshot_fingerprint(layout_snapshot)
    netlist_fingerprint = board_netlist_snapshot_fingerprint(netlist_snapshot)
    payload = {
        "schema_id": "pcbsmith-antenna-placement-result",
        "schema_version": 1,
        "declaration": declaration.model_dump(mode="json"),
        "transform": transform.model_dump(mode="json"),
        "placed_regions": [item.model_dump(mode="json") for item in regions],
        "board_layout_snapshot_json": layout_snapshot,
        "board_layout_snapshot_fingerprint": layout_fingerprint,
        "board_netlist_snapshot_json": netlist_snapshot,
        "board_netlist_snapshot_fingerprint": netlist_fingerprint,
    }
    fingerprint = antenna_placement_result_fingerprint(payload)
    return AntennaPlacementResult(
        declaration=declaration,
        transform=transform,
        placed_regions=regions,
        board_layout_snapshot_json=layout_snapshot,
        board_layout_snapshot_fingerprint=layout_fingerprint,
        board_netlist_snapshot_json=netlist_snapshot,
        board_netlist_snapshot_fingerprint=netlist_fingerprint,
        result_fingerprint=fingerprint,
    )
