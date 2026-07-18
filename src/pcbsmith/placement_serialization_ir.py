"""Replay-bound authority for deterministic shaped-board KiCad serialization.

This module is deliberately limited to the first R5.6b gate.  It proves that a
declared placement/target-route delta is lossless and that the resulting real
``BoardLayout`` renders deterministically.  KiCad read-back, save-roundtrip,
CLI DRC, and corpus claims belong to later gates.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, TypeAdapter, field_validator, model_validator

from pcbsmith.kicad.board import (
    BoardComponent,
    BoardLayout,
    BoardNetlist,
    TrackSegment,
    ViaSpec,
    render_board_from_layout,
)
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.placement_ir import PlacementIrModel
from pcbsmith.placement_pose_authority import build_placement_pose_authority
from pcbsmith.rule_profiles import PcbRuleProfile

_LAYOUT_ADAPTER = TypeAdapter(BoardLayout)
_COMPONENT_ADAPTER = TypeAdapter(BoardComponent)


def _canonical_json(payload: Any) -> str:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _fingerprint(payload: Any) -> str:
    return _sha256_text(_canonical_json(payload))


def _require_sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


def placement_serialization_profile_fingerprint(profile: PcbRuleProfile) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-placement-serialization-profile",
            "schema_version": 1,
            "profile": profile.model_dump(mode="json"),
        }
    )


class LayoutFieldDeltaClass(StrEnum):
    IMMUTABLE_PRESERVED = "immutable_preserved"
    DECLARED_PLACEMENT_TRANSFORMABLE = "declared_placement_transformable"
    DECLARED_TARGET_ROUTE_REPLACEABLE = "declared_target_route_replaceable"


class LayoutFieldDeltaRule(PlacementIrModel):
    schema_id: Literal["pcbsmith-layout-field-delta-rule"] = "pcbsmith-layout-field-delta-rule"
    schema_version: Literal[1] = 1
    field_name: str = Field(min_length=1)
    delta_class: LayoutFieldDeltaClass


# This list is intentionally explicit.  A future BoardLayout field must cause
# validation to fail until its semantics are consciously classified here.
_EXPECTED_FIELD_RULES = (
    LayoutFieldDeltaRule(
        field_name="placements",
        delta_class=LayoutFieldDeltaClass.DECLARED_PLACEMENT_TRANSFORMABLE,
    ),
    LayoutFieldDeltaRule(
        field_name="segments",
        delta_class=LayoutFieldDeltaClass.DECLARED_TARGET_ROUTE_REPLACEABLE,
    ),
    LayoutFieldDeltaRule(
        field_name="vias",
        delta_class=LayoutFieldDeltaClass.DECLARED_TARGET_ROUTE_REPLACEABLE,
    ),
    LayoutFieldDeltaRule(
        field_name="width_mm",
        delta_class=LayoutFieldDeltaClass.IMMUTABLE_PRESERVED,
    ),
    LayoutFieldDeltaRule(
        field_name="height_mm",
        delta_class=LayoutFieldDeltaClass.IMMUTABLE_PRESERVED,
    ),
    LayoutFieldDeltaRule(
        field_name="parts_row_y_mm",
        delta_class=LayoutFieldDeltaClass.IMMUTABLE_PRESERVED,
    ),
    LayoutFieldDeltaRule(
        field_name="part_y_mm",
        delta_class=LayoutFieldDeltaClass.DECLARED_PLACEMENT_TRANSFORMABLE,
    ),
    LayoutFieldDeltaRule(
        field_name="part_rotation",
        delta_class=LayoutFieldDeltaClass.DECLARED_PLACEMENT_TRANSFORMABLE,
    ),
    LayoutFieldDeltaRule(
        field_name="zones",
        delta_class=LayoutFieldDeltaClass.IMMUTABLE_PRESERVED,
    ),
    LayoutFieldDeltaRule(
        field_name="outline",
        delta_class=LayoutFieldDeltaClass.IMMUTABLE_PRESERVED,
    ),
    LayoutFieldDeltaRule(
        field_name="graphics",
        delta_class=LayoutFieldDeltaClass.IMMUTABLE_PRESERVED,
    ),
    LayoutFieldDeltaRule(
        field_name="part_flip",
        delta_class=LayoutFieldDeltaClass.DECLARED_PLACEMENT_TRANSFORMABLE,
    ),
    LayoutFieldDeltaRule(
        field_name="hide_references",
        delta_class=LayoutFieldDeltaClass.IMMUTABLE_PRESERVED,
    ),
    LayoutFieldDeltaRule(
        field_name="part_reference_at",
        delta_class=LayoutFieldDeltaClass.IMMUTABLE_PRESERVED,
    ),
    LayoutFieldDeltaRule(
        field_name="mask_apertures",
        delta_class=LayoutFieldDeltaClass.IMMUTABLE_PRESERVED,
    ),
    LayoutFieldDeltaRule(
        field_name="cutouts",
        delta_class=LayoutFieldDeltaClass.IMMUTABLE_PRESERVED,
    ),
)


class ShapedSerializationDeltaPolicy(PlacementIrModel):
    """Closed-world field mutation policy for the first R5.6b authority gate."""

    schema_id: Literal["pcbsmith-shaped-serialization-delta-policy"] = (
        "pcbsmith-shaped-serialization-delta-policy"
    )
    schema_version: Literal[1] = 1
    policy_id: Literal["r5.6b-shaped-layout-delta-v1"] = "r5.6b-shaped-layout-delta-v1"
    field_rules: tuple[LayoutFieldDeltaRule, ...] = _EXPECTED_FIELD_RULES

    @model_validator(mode="after")
    def classifications_cover_exact_real_schema(self) -> Self:
        reflected = tuple(field.name for field in fields(BoardLayout))
        declared = tuple(rule.field_name for rule in self.field_rules)
        if declared != reflected:
            raise ValueError(
                "BoardLayout field classification is stale or reordered: "
                f"reflected={reflected!r}, declared={declared!r}"
            )
        if self.field_rules != _EXPECTED_FIELD_RULES:
            raise ValueError("R5.6b field delta semantics must equal the reviewed closed policy")
        return self


DEFAULT_SHAPED_SERIALIZATION_DELTA_POLICY = ShapedSerializationDeltaPolicy()


class LayoutFieldDeltaEvidence(PlacementIrModel):
    schema_id: Literal["pcbsmith-layout-field-delta-evidence"] = (
        "pcbsmith-layout-field-delta-evidence"
    )
    schema_version: Literal[1] = 1
    field_name: str
    delta_class: LayoutFieldDeltaClass
    changed: bool
    source_value_fingerprint: str
    final_value_fingerprint: str
    affected_references: tuple[str, ...] = ()
    affected_target_nets: tuple[str, ...] = ()

    @field_validator("source_value_fingerprint", "final_value_fingerprint")
    @classmethod
    def value_fingerprint_is_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)


class ComponentSerializationIdentityEvidence(PlacementIrModel):
    schema_id: Literal["pcbsmith-component-serialization-identity-evidence"] = (
        "pcbsmith-component-serialization-identity-evidence"
    )
    schema_version: Literal[1] = 1
    reference: str
    component_fingerprint: str

    @field_validator("component_fingerprint")
    @classmethod
    def component_fingerprint_is_sha256(cls, value: str) -> str:
        return _require_sha256(value, "component_fingerprint")


def _component_fingerprint(component: BoardComponent) -> str:
    return _fingerprint(
        {
            "schema_id": "pcbsmith-board-component-identity",
            "schema_version": 1,
            "component": _COMPONENT_ADAPTER.dump_python(component, mode="json"),
        }
    )


def _canonical_set(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    canonical = tuple(sorted(set(values)))
    if not canonical or any(not value or value != value.strip() for value in canonical):
        raise ValueError(f"{name} must be a non-empty set of canonical identities")
    return canonical


def _unique_components(
    components: tuple[BoardComponent, ...], name: str
) -> dict[str, BoardComponent]:
    result: dict[str, BoardComponent] = {}
    uuids: set[str] = set()
    for component in components:
        if not component.reference or component.reference != component.reference.strip():
            raise ValueError(f"{name} has a non-canonical component reference")
        if component.reference in result:
            raise ValueError(f"{name} repeats component reference {component.reference!r}")
        if not component.uuid_path or component.uuid_path != component.uuid_path.strip():
            raise ValueError(f"{name} has a non-canonical component UUID/path")
        if component.uuid_path in uuids:
            raise ValueError(f"{name} repeats component UUID/path {component.uuid_path!r}")
        result[component.reference] = component
        uuids.add(component.uuid_path)
    return result


def _mapping_entries_for_reference(
    entries: tuple[tuple[str, float], ...], ref: str
) -> tuple[Any, ...]:
    return tuple(entry for entry in entries if entry[0] == ref)


def _field_affected_references(
    field_name: str,
    source: BoardLayout,
    final: BoardLayout,
    movable: tuple[str, ...],
) -> tuple[str, ...]:
    if field_name == "placements":
        source_x = {component.reference: x_mm for component, x_mm in source.placements}
        final_x = {component.reference: x_mm for component, x_mm in final.placements}
        return tuple(ref for ref in movable if source_x[ref] != final_x[ref])
    if field_name in {"part_y_mm", "part_rotation"}:
        source_entries = getattr(source, field_name)
        final_entries = getattr(final, field_name)
        return tuple(
            ref
            for ref in movable
            if _mapping_entries_for_reference(source_entries, ref)
            != _mapping_entries_for_reference(final_entries, ref)
        )
    if field_name == "part_flip":
        return tuple(
            ref
            for ref in movable
            if tuple(item for item in source.part_flip if item == ref)
            != tuple(item for item in final.part_flip if item == ref)
        )
    return ()


def _field_affected_target_nets(
    field_name: str,
    source: BoardLayout,
    final: BoardLayout,
    targets: tuple[str, ...],
) -> tuple[str, ...]:
    if field_name not in {"segments", "vias"}:
        return ()
    source_items = getattr(source, field_name)
    final_items = getattr(final, field_name)
    return tuple(
        net
        for net in targets
        if tuple(item for item in source_items if item.net_name == net)
        != tuple(item for item in final_items if item.net_name == net)
    )


def _fixed_pose_entries(
    entries: tuple[tuple[str, float], ...], movable: set[str]
) -> tuple[tuple[str, float], ...]:
    return tuple(entry for entry in entries if entry[0] not in movable)


def _validate_pose_delta(
    source: BoardLayout,
    final: BoardLayout,
    movable_references: tuple[str, ...],
) -> None:
    # Close the sparse pose fields first.  This rejects duplicate/shadow
    # records and proves that only the declared movable references change.
    build_placement_pose_authority(source, final, movable_references)
    movable = set(movable_references)
    source_refs = tuple(component.reference for component, _x_mm in source.placements)
    final_refs = tuple(component.reference for component, _x_mm in final.placements)
    if source_refs != final_refs:
        raise ValueError("final placements must preserve source component order and references")
    known = set(source_refs)
    if not movable <= known:
        raise ValueError(f"movable references are absent from layout: {sorted(movable - known)!r}")
    for (source_component, source_x), (final_component, final_x) in zip(
        source.placements, final.placements, strict=True
    ):
        if source_component != final_component:
            raise ValueError(
                f"placement changed component identity for {source_component.reference!r}"
            )
        if source_component.reference not in movable and source_x != final_x:
            raise ValueError(f"fixed component {source_component.reference!r} changed x position")
    for field_name in ("part_y_mm", "part_rotation"):
        source_entries = getattr(source, field_name)
        final_entries = getattr(final, field_name)
        if any(entry[0] not in known for entry in (*source_entries, *final_entries)):
            raise ValueError(f"{field_name} contains a reference absent from placements")
        if _fixed_pose_entries(source_entries, movable) != _fixed_pose_entries(
            final_entries, movable
        ):
            raise ValueError(f"{field_name} changed a fixed reference or its literal ordering")
    if any(ref not in known for ref in (*source.part_flip, *final.part_flip)):
        raise ValueError("part_flip contains a reference absent from placements")
    if tuple(ref for ref in source.part_flip if ref not in movable) != tuple(
        ref for ref in final.part_flip if ref not in movable
    ):
        raise ValueError("part_flip changed a fixed reference or its literal ordering")


def _validate_route_delta(
    source: BoardLayout,
    final: BoardLayout,
    target_net_names: tuple[str, ...],
    known_net_names: set[str],
) -> None:
    targets = set(target_net_names)
    for field_name in ("segments", "vias"):
        source_items: tuple[TrackSegment, ...] | tuple[ViaSpec, ...] = getattr(source, field_name)
        final_items: tuple[TrackSegment, ...] | tuple[ViaSpec, ...] = getattr(final, field_name)
        if any(item.net_name not in known_net_names for item in (*source_items, *final_items)):
            raise ValueError(f"{field_name} contains a net absent from the retained netlist")
        source_fixed = tuple(item for item in source_items if item.net_name not in targets)
        final_fixed = tuple(item for item in final_items if item.net_name not in targets)
        if source_fixed != final_fixed:
            raise ValueError(
                f"{field_name} changed fixed/non-target copper or its literal ordering"
            )


def _derive_delta_evidence(
    source: BoardLayout,
    final: BoardLayout,
    policy: ShapedSerializationDeltaPolicy,
    movable_references: tuple[str, ...],
    target_net_names: tuple[str, ...],
) -> tuple[LayoutFieldDeltaEvidence, ...]:
    source_payload = _LAYOUT_ADAPTER.dump_python(source, mode="json")
    final_payload = _LAYOUT_ADAPTER.dump_python(final, mode="json")
    if not isinstance(source_payload, dict) or not isinstance(final_payload, dict):
        raise ValueError("BoardLayout schema did not serialize to an object")
    evidence: list[LayoutFieldDeltaEvidence] = []
    for rule in policy.field_rules:
        source_value = getattr(source, rule.field_name)
        final_value = getattr(final, rule.field_name)
        if (
            rule.delta_class is LayoutFieldDeltaClass.IMMUTABLE_PRESERVED
            and source_value != final_value
        ):
            raise ValueError(f"final layout changed preserved field {rule.field_name!r}")
        evidence.append(
            LayoutFieldDeltaEvidence(
                field_name=rule.field_name,
                delta_class=rule.delta_class,
                changed=source_value != final_value,
                source_value_fingerprint=_fingerprint(
                    {
                        "schema_id": "pcbsmith-layout-field-value",
                        "schema_version": 1,
                        "field_name": rule.field_name,
                        "value": source_payload[rule.field_name],
                    }
                ),
                final_value_fingerprint=_fingerprint(
                    {
                        "schema_id": "pcbsmith-layout-field-value",
                        "schema_version": 1,
                        "field_name": rule.field_name,
                        "value": final_payload[rule.field_name],
                    }
                ),
                affected_references=_field_affected_references(
                    rule.field_name, source, final, movable_references
                ),
                affected_target_nets=_field_affected_target_nets(
                    rule.field_name, source, final, target_net_names
                ),
            )
        )
    return tuple(evidence)


def _validate_and_derive(
    source: BoardLayout,
    final: BoardLayout,
    netlist: BoardNetlist,
    policy: ShapedSerializationDeltaPolicy,
    movable_references: tuple[str, ...],
    target_net_names: tuple[str, ...],
) -> tuple[
    tuple[LayoutFieldDeltaEvidence, ...], tuple[ComponentSerializationIdentityEvidence, ...]
]:
    source_components = _unique_components(
        tuple(component for component, _x in source.placements), "source layout"
    )
    final_components = _unique_components(
        tuple(component for component, _x in final.placements), "final layout"
    )
    netlist_components = _unique_components(netlist.components, "source netlist")
    if source_components != final_components:
        raise ValueError("source/final component identities differ")
    if source_components != netlist_components:
        raise ValueError("layout component identities differ from retained netlist")
    known_net_names = tuple(net.name for net in netlist.nets)
    if any(not name or name != name.strip() for name in known_net_names):
        raise ValueError("retained netlist has a non-canonical net name")
    if len(set(known_net_names)) != len(known_net_names):
        raise ValueError("retained netlist repeats a net name")
    unknown_targets = tuple(sorted(set(target_net_names) - set(known_net_names)))
    if unknown_targets:
        raise ValueError(f"target nets are absent from retained netlist: {unknown_targets!r}")
    _validate_pose_delta(source, final, movable_references)
    _validate_route_delta(source, final, target_net_names, set(known_net_names))
    delta_evidence = _derive_delta_evidence(
        source, final, policy, movable_references, target_net_names
    )
    identity_evidence = tuple(
        ComponentSerializationIdentityEvidence(
            reference=reference,
            component_fingerprint=_component_fingerprint(source_components[reference]),
        )
        for reference in sorted(source_components)
    )
    return delta_evidence, identity_evidence


def placement_serialization_input_fingerprint(
    source_layout_fingerprint: str,
    source_netlist_fingerprint: str,
    profile_fingerprint: str,
    policy_fingerprint: str,
    target_net_names: tuple[str, ...],
    movable_references: tuple[str, ...],
) -> str:
    for name, value in (
        ("source_layout_fingerprint", source_layout_fingerprint),
        ("source_netlist_fingerprint", source_netlist_fingerprint),
        ("profile_fingerprint", profile_fingerprint),
        ("policy_fingerprint", policy_fingerprint),
    ):
        _require_sha256(value, name)
    return _fingerprint(
        {
            "schema_id": "pcbsmith-placement-serialization-input",
            "schema_version": 1,
            "source_layout_fingerprint": source_layout_fingerprint,
            "source_netlist_fingerprint": source_netlist_fingerprint,
            "profile_fingerprint": profile_fingerprint,
            "policy_fingerprint": policy_fingerprint,
            "target_net_names": target_net_names,
            "movable_references": movable_references,
        }
    )


def placement_serialization_result_fingerprint(
    input_fingerprint: str,
    final_layout_fingerprint: str,
    field_delta_evidence: tuple[LayoutFieldDeltaEvidence, ...],
    component_identity_evidence: tuple[ComponentSerializationIdentityEvidence, ...],
    rendered_board_sha256: str,
) -> str:
    for name, value in (
        ("input_fingerprint", input_fingerprint),
        ("final_layout_fingerprint", final_layout_fingerprint),
        ("rendered_board_sha256", rendered_board_sha256),
    ):
        _require_sha256(value, name)
    return _fingerprint(
        {
            "schema_id": "pcbsmith-placement-serialization-result-fingerprint",
            "schema_version": 1,
            "input_fingerprint": input_fingerprint,
            "final_layout_fingerprint": final_layout_fingerprint,
            "field_delta_evidence": [item.model_dump(mode="json") for item in field_delta_evidence],
            "component_identity_evidence": [
                item.model_dump(mode="json") for item in component_identity_evidence
            ],
            "rendered_board_sha256": rendered_board_sha256,
        }
    )


class PlacementSerializationAuthority(PlacementIrModel):
    """Replayable proof of allowed layout deltas and deterministic KiCad text."""

    schema_id: Literal["pcbsmith-placement-serialization-authority"] = (
        "pcbsmith-placement-serialization-authority"
    )
    schema_version: Literal[1] = 1
    authority_scope: Literal["render_repeat_only_no_readback_or_drc"] = (
        "render_repeat_only_no_readback_or_drc"
    )
    renderer_id: Literal["pcbsmith.kicad.board.render_board_from_layout-v1"] = (
        "pcbsmith.kicad.board.render_board_from_layout-v1"
    )
    source_layout_snapshot_json: str
    source_netlist_snapshot_json: str
    final_layout_snapshot_json: str
    profile: PcbRuleProfile
    target_net_names: tuple[str, ...] = Field(min_length=1)
    movable_references: tuple[str, ...] = Field(min_length=1)
    delta_policy: ShapedSerializationDeltaPolicy
    field_delta_evidence: tuple[LayoutFieldDeltaEvidence, ...]
    component_identity_evidence: tuple[ComponentSerializationIdentityEvidence, ...]
    rendered_board_text: str
    rendered_board_sha256: str
    source_layout_fingerprint: str
    source_netlist_fingerprint: str
    final_layout_fingerprint: str
    profile_fingerprint: str
    policy_fingerprint: str
    input_fingerprint: str
    result_fingerprint: str

    @field_validator(
        "rendered_board_sha256",
        "source_layout_fingerprint",
        "source_netlist_fingerprint",
        "final_layout_fingerprint",
        "profile_fingerprint",
        "policy_fingerprint",
        "input_fingerprint",
        "result_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="before")
    @classmethod
    def canonicalize_set_like_inputs(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        result = dict(value)
        for name in ("target_net_names", "movable_references"):
            raw = result.get(name)
            if isinstance(raw, (tuple, list)):
                result[name] = tuple(sorted(set(raw)))
        return result

    @model_validator(mode="after")
    def retained_authority_replays_exactly(self) -> Self:
        targets = _canonical_set(self.target_net_names, "target_net_names")
        movable = _canonical_set(self.movable_references, "movable_references")
        if targets != self.target_net_names or movable != self.movable_references:
            raise ValueError("set-like authority inputs did not canonicalize")
        source = parse_canonical_board_layout_snapshot(self.source_layout_snapshot_json)
        final = parse_canonical_board_layout_snapshot(self.final_layout_snapshot_json)
        netlist = parse_canonical_board_netlist_snapshot(self.source_netlist_snapshot_json)
        source_layout_fp = board_layout_snapshot_fingerprint(self.source_layout_snapshot_json)
        final_layout_fp = board_layout_snapshot_fingerprint(self.final_layout_snapshot_json)
        netlist_fp = board_netlist_snapshot_fingerprint(self.source_netlist_snapshot_json)
        profile_fp = placement_serialization_profile_fingerprint(self.profile)
        policy_fp = self.delta_policy.semantic_fingerprint()
        expected_evidence, expected_identity = _validate_and_derive(
            source,
            final,
            netlist,
            self.delta_policy,
            movable,
            targets,
        )
        if self.source_layout_fingerprint != source_layout_fp:
            raise ValueError("source layout fingerprint is stale")
        if self.final_layout_fingerprint != final_layout_fp:
            raise ValueError("final layout fingerprint is stale")
        if self.source_netlist_fingerprint != netlist_fp:
            raise ValueError("source netlist fingerprint is stale")
        if self.profile_fingerprint != profile_fp:
            raise ValueError("complete profile fingerprint is stale")
        if self.policy_fingerprint != policy_fp:
            raise ValueError("field delta policy fingerprint is stale")
        if self.field_delta_evidence != expected_evidence:
            raise ValueError("field delta evidence is stale")
        if self.component_identity_evidence != expected_identity:
            raise ValueError("component identity evidence is stale")
        try:
            first_render = render_board_from_layout(netlist, final, profile=self.profile)
            second_render = render_board_from_layout(netlist, final, profile=self.profile)
        except Exception as error:
            raise ValueError(f"retained final layout cannot be rendered: {error}") from error
        if first_render != second_render:
            raise ValueError("clean repeated KiCad renders are not byte-identical")
        if self.rendered_board_text != first_render:
            raise ValueError("retained KiCad board text differs from clean render")
        rendered_sha = _sha256_text(first_render)
        if self.rendered_board_sha256 != rendered_sha:
            raise ValueError("rendered KiCad board SHA-256 is stale")
        input_fp = placement_serialization_input_fingerprint(
            source_layout_fp,
            netlist_fp,
            profile_fp,
            policy_fp,
            targets,
            movable,
        )
        if self.input_fingerprint != input_fp:
            raise ValueError("placement serialization input fingerprint is stale")
        result_fp = placement_serialization_result_fingerprint(
            input_fp,
            final_layout_fp,
            expected_evidence,
            expected_identity,
            rendered_sha,
        )
        if self.result_fingerprint != result_fp:
            raise ValueError("placement serialization result fingerprint is stale")
        return self
