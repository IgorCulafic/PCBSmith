"""Firing fixtures 1 and 3 for bounded module-local antenna placement."""

from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from pcbsmith.antenna_ir import (
    AntennaLocalRegion,
    AntennaModuleDeclaration,
    AntennaPlacementResult,
    InstalledFootprintKeepoutProvenance,
    antenna_geometry_source_fingerprint,
)
from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.kicad.antenna_semantics import evaluate_antenna_placement
from pcbsmith.kicad.board import BoardComponent, BoardLayout, BoardNetlist
from pcbsmith.placement_geometry import (
    ExactPlanarCompound,
    ExactPlanarPolygon,
    PlacementTransformAuthority,
)
from pcbsmith.semantic_ir import EvidenceApplicabilityBinding, SemanticVerification

SOURCE_SHA = "a" * 64


def _compound(
    points: tuple[tuple[float, float], ...],
) -> ExactPlanarCompound:
    return ExactPlanarCompound(polygons=(ExactPlanarPolygon(outer=points),))


def _regions() -> tuple[
    AntennaLocalRegion,
    AntennaLocalRegion,
    tuple[InstalledFootprintKeepoutProvenance, ...],
]:
    antenna = AntennaLocalRegion(
        region_id="region:antenna",
        role="antenna",
        compound=_compound(((0.0, 0.0), (3.0, 0.0), (2.5, 1.0), (0.2, 2.0))),
        layers=("F.Cu", "B.Cu"),
    )
    feed = AntennaLocalRegion(
        region_id="region:feed",
        role="feed",
        compound=_compound(((-1.0, -0.2), (0.0, -0.2), (0.0, 0.2), (-1.0, 0.4))),
        layers=("F.Cu",),
    )
    keepout = InstalledFootprintKeepoutProvenance(
        provenance_id="provenance:keepout:1",
        region_id="region:keepout:1",
        selected_footprint_library_id="RF_Module:Fixture_Antenna",
        component_uuid_path="uuid:path:U1",
        component_revision="module-revision:3",
        component_revision_field_name="revision",
        source_file_sha256=SOURCE_SHA,
        module_guidance_binding_id="binding:module-guidance",
        prohibited_object_rule_id="rule:antenna-keepout",
        compound=_compound(((-1.2, -0.8), (3.5, -0.8), (3.2, 2.7), (-0.7, 2.2))),
        layers=("B.Cu", "F.Cu"),
        prohibited_object_kinds=("zone", "track", "via", "pad", "footprint"),
    )
    return antenna, feed, (keepout,)


def _evidence(*, source_sha: str = SOURCE_SHA) -> EvidenceRef:
    return EvidenceRef(
        kind="module_design_guide",
        title="Fixture module antenna integration guide",
        locator="figure:antenna-and-keepout",
        source_id="source:fixture-module-guide",
        organization_or_author="Fixture Radio Vendor",
        revision="3",
        local_sha256=source_sha,
        source_status="pinned",
        locator_status="figure_bound",
        applicability_status="confirmed",
        required_conditions=("module-revision=3",),
    )


def _binding(
    geometry_fingerprint: str,
    *,
    complete: bool = True,
) -> EvidenceApplicabilityBinding:
    return EvidenceApplicabilityBinding(
        binding_id="binding:module-guidance",
        evidence=(_evidence(),),
        claim_id="claim:module-local-antenna-geometry",
        applicability_record_id="applicability:module-revision:3",
        required_conditions=("module-revision=3", "footprint-revision=3"),
        excluded_conditions=(),
        matched_conditions=(
            ("module-revision=3", "footprint-revision=3")
            if complete
            else ("module-revision=3",)
        ),
        unmatched_conditions=() if complete else ("footprint-revision=3",),
        geometry_source_fingerprint=geometry_fingerprint,
        reviewer_record_id="review:module-guide:3",
    )


def _declaration(
    *,
    keepout_order_reversed: bool = False,
) -> AntennaModuleDeclaration:
    antenna, feed, keepouts = _regions()
    if keepout_order_reversed:
        second = keepouts[0].model_copy(
            update={
                "provenance_id": "provenance:keepout:2",
                "region_id": "region:keepout:2",
                "compound": _compound(((4.0, 0.0), (5.0, 0.0), (5.0, 1.0), (4.0, 1.0))),
            }
        )
        keepouts = (second, keepouts[0])
    geometry_fp = antenna_geometry_source_fingerprint(antenna, feed, keepouts)
    return AntennaModuleDeclaration(
        antenna_id="antenna:U1",
        module_reference="U1",
        selected_footprint_library_id="RF_Module:Fixture_Antenna",
        component_uuid_path="uuid:path:U1",
        component_revision="module-revision:3",
        component_revision_field_name="revision",
        source_file_sha256=SOURCE_SHA,
        module_guidance_binding=_binding(geometry_fp),
        antenna_region=antenna,
        feed_region=feed,
        keepouts=keepouts,
        placement_strategy="edge_overhang",
        edge_or_cutout_requirement_id="requirement:edge-disposition",
        enclosure_exclusion_requirement_id="requirement:enclosure-exclusion",
        rf_validation_requirement_id="requirement:rf-campaign",
    )


def _component(
    *,
    reference: str = "U1",
    footprint: str = "RF_Module:Fixture_Antenna",
    uuid_path: str = "uuid:path:U1",
    revision: str = "module-revision:3",
) -> BoardComponent:
    return BoardComponent(
        reference=reference,
        value="Fixture Radio Module",
        footprint=footprint,
        uuid_path=uuid_path,
        fields=(("revision", revision),),
    )


def _inputs(
    *,
    rotation: float = 0.0,
    back: bool = False,
    component: BoardComponent | None = None,
) -> tuple[BoardLayout, BoardNetlist]:
    selected = component or _component()
    layout = BoardLayout(
        placements=((selected, 10.0),),
        segments=(),
        vias=(),
        width_mm=30.0,
        height_mm=20.0,
        parts_row_y_mm=7.0,
        part_rotation=(("U1", rotation),) if rotation else (),
        part_flip=("U1",) if back else (),
    )
    return layout, BoardNetlist(components=(selected,), nets=())


@pytest.mark.parametrize("rotation", (0.0, 90.0, 180.0, 270.0))
@pytest.mark.parametrize("back", (False, True))
def test_orthogonal_front_and_back_transforms_are_exact(rotation: float, back: bool) -> None:
    layout, netlist = _inputs(rotation=rotation, back=back)

    result = evaluate_antenna_placement(layout, netlist, _declaration())

    assert result.transform.rotation_deg == rotation
    assert result.transform.side == ("back" if back else "front")
    assert all(item.verification is SemanticVerification.EXACT for item in result.placed_regions)
    assert all(
        item.bounded_transform.authority is PlacementTransformAuthority.EXACT
        and item.exact_transformed_compound == item.bounded_transform.compound
        for item in result.placed_regions
    )


@pytest.mark.parametrize("rotation", (17.0, 223.0))
@pytest.mark.parametrize("back", (False, True))
def test_arbitrary_rotations_retain_bounds_without_exact_vertex_claim(
    rotation: float, back: bool
) -> None:
    layout, netlist = _inputs(rotation=rotation, back=back)

    result = evaluate_antenna_placement(layout, netlist, _declaration())

    assert all(
        item.verification is SemanticVerification.BOUNDED_APPROXIMATION
        and item.bounded_transform.authority
        is PlacementTransformAuthority.BOUNDED_APPROXIMATION
        and item.bounded_transform.maximum_error_mm is not None
        and item.exact_transformed_compound is None
        for item in result.placed_regions
    )


def test_back_transform_mirrors_before_rotation() -> None:
    layout, netlist = _inputs(rotation=90.0, back=True)

    result = evaluate_antenna_placement(layout, netlist, _declaration())
    antenna = next(item for item in result.placed_regions if item.role == "antenna")

    # local (3, 0) -> back mirror (-3, 0) -> KiCad 90-degree result (0, 3)
    assert (10.0, 10.0) in antenna.exact_transformed_compound.polygons[0].outer  # type: ignore[union-attr]


def test_local_point_reversal_and_keepout_input_order_are_canonical() -> None:
    declaration = _declaration(keepout_order_reversed=True)
    payload = declaration.model_dump(mode="json")
    payload["antenna_region"]["compound"]["polygons"][0]["outer"] = list(
        reversed(payload["antenna_region"]["compound"]["polygons"][0]["outer"])
    )

    reversed_points = AntennaModuleDeclaration.model_validate(payload)

    assert reversed_points == declaration
    assert tuple(item.region_id for item in declaration.keepouts) == (
        "region:keepout:1",
        "region:keepout:2",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("selected_footprint_library_id", "RF_Module:Stale"),
        ("component_uuid_path", "uuid:path:stale"),
        ("component_revision", "module-revision:stale"),
        ("source_file_sha256", "b" * 64),
    ),
)
def test_stale_keepout_library_uuid_revision_or_source_fails(field: str, value: str) -> None:
    payload = _declaration().model_dump(mode="json")
    payload["keepouts"][0][field] = value

    with pytest.raises(ValidationError, match="keepout provenance is stale"):
        AntennaModuleDeclaration.model_validate(payload)


@pytest.mark.parametrize(
    ("footprint", "uuid_path", "revision"),
    (
        ("RF_Module:Generic_Name", "uuid:path:U1", "module-revision:3"),
        ("RF_Module:Fixture_Antenna", "uuid:wrong", "module-revision:3"),
        ("RF_Module:Fixture_Antenna", "uuid:path:U1", "module-revision:stale"),
    ),
)
def test_generic_or_wrong_placed_identity_cannot_validate(
    footprint: str, uuid_path: str, revision: str
) -> None:
    layout, netlist = _inputs(
        component=_component(footprint=footprint, uuid_path=uuid_path, revision=revision)
    )

    with pytest.raises(ValueError, match="component identity does not match declaration"):
        evaluate_antenna_placement(layout, netlist, _declaration())


def test_wrong_source_hash_and_incomplete_applicability_fail() -> None:
    payload = _declaration().model_dump(mode="json")
    payload["source_file_sha256"] = "b" * 64
    with pytest.raises(ValidationError, match="pin the declared source"):
        AntennaModuleDeclaration.model_validate(payload)

    antenna, feed, keepouts = _regions()
    payload = _declaration().model_dump(mode="json")
    payload["module_guidance_binding"] = _binding(
        antenna_geometry_source_fingerprint(antenna, feed, keepouts), complete=False
    ).model_dump(mode="json")
    with pytest.raises(ValidationError, match="applicability must be complete"):
        AntennaModuleDeclaration.model_validate(payload)


@pytest.mark.parametrize(("missing", "duplicate"), ((True, False), (False, True)))
def test_missing_or_duplicate_placement_fails(missing: bool, duplicate: bool) -> None:
    component = _component()
    placements = () if missing else ((component, 10.0),)
    if duplicate:
        placements = (*placements, (component, 12.0))
    layout = BoardLayout(
        placements=placements,
        segments=(),
        vias=(),
        width_mm=30.0,
        height_mm=20.0,
    )
    netlist = BoardNetlist(components=(component,), nets=())

    with pytest.raises(ValueError, match="exactly one BoardLayout placement"):
        evaluate_antenna_placement(layout, netlist, _declaration())


@pytest.mark.parametrize(("missing", "duplicate"), ((True, False), (False, True)))
def test_missing_or_duplicate_netlist_component_fails(missing: bool, duplicate: bool) -> None:
    layout, _netlist = _inputs()
    component = _component()
    components = () if missing else (component,)
    if duplicate:
        components = (*components, component)

    with pytest.raises(ValueError, match="exactly once in BoardNetlist"):
        evaluate_antenna_placement(
            layout, BoardNetlist(components=components, nets=()), _declaration()
        )


def test_result_json_replays_and_transformed_geometry_tamper_fails() -> None:
    layout, netlist = _inputs()
    first = evaluate_antenna_placement(layout, netlist, _declaration())
    second = evaluate_antenna_placement(layout, netlist, _declaration())

    assert first == second
    assert AntennaPlacementResult.model_validate_json(first.model_dump_json()) == first

    payload = deepcopy(first.model_dump(mode="json"))
    region = payload["placed_regions"][0]
    for key in ("bounded_transform", "exact_transformed_compound"):
        compound = region[key]["compound"] if key == "bounded_transform" else region[key]
        compound["polygons"][0]["outer"] = [
            [point[0] + 0.25, point[1]] for point in compound["polygons"][0]["outer"]
        ]
    with pytest.raises(ValidationError, match="does not replay"):
        AntennaPlacementResult.model_validate(payload)


def test_declaration_retains_keepout_layers_kinds_and_later_requirements() -> None:
    declaration = _declaration()
    keepout = declaration.keepouts[0]

    assert keepout.layers == ("B.Cu", "F.Cu")
    assert keepout.prohibited_object_kinds == ("footprint", "pad", "track", "via", "zone")
    assert declaration.edge_or_cutout_requirement_id == "requirement:edge-disposition"
    assert declaration.enclosure_exclusion_requirement_id == "requirement:enclosure-exclusion"
    assert declaration.rf_validation_requirement_id == "requirement:rf-campaign"


def test_duplicate_keepout_provenance_ids_fail() -> None:
    declaration = _declaration(keepout_order_reversed=True)
    payload = declaration.model_dump(mode="json")
    payload["keepouts"][1]["provenance_id"] = payload["keepouts"][0]["provenance_id"]
    # Rebind exact geometry so duplicate provenance identity is the failing condition.
    antenna = AntennaLocalRegion.model_validate(payload["antenna_region"])
    feed = AntennaLocalRegion.model_validate(payload["feed_region"])
    keepouts = tuple(
        InstalledFootprintKeepoutProvenance.model_validate(item) for item in payload["keepouts"]
    )
    payload["module_guidance_binding"]["geometry_source_fingerprint"] = (
        antenna_geometry_source_fingerprint(antenna, feed, keepouts)
    )

    with pytest.raises(ValidationError, match="provenance identities must be unique"):
        AntennaModuleDeclaration.model_validate(payload)


def test_keepout_requires_explicit_prohibited_object_rule_identity() -> None:
    payload = _declaration().model_dump(mode="json")
    payload["keepouts"][0]["prohibited_object_rule_id"] = ""

    with pytest.raises(ValidationError):
        AntennaModuleDeclaration.model_validate(payload)
