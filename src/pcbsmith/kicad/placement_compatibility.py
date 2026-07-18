"""Opt-in compatibility adapter from legacy rectangular layouts into R5 probes.

This is deliberately not shaped-body authority and changes no legacy entrypoint.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel

from pcbsmith.kicad.board import (
    BoardLayout,
    BoardNetlist,
    placement_rotation,
    placement_y,
)
from pcbsmith.kicad.placement_routability import (
    PlacementProbe,
    board_layout_fingerprint,
    build_placement_probe,
)
from pcbsmith.placement_compatibility_ir import (
    LegacyRectangularPlacementAdapterPolicy,
    LegacyRectangularPlacementAdapterResult,
    legacy_rectangular_adapter_input_fingerprint,
    legacy_rectangular_layout_snapshot_fingerprint,
    legacy_rectangular_netlist_snapshot_fingerprint,
    legacy_rectangular_profile_fingerprint,
    legacy_rectangular_source_authority_fingerprint,
)
from pcbsmith.placement_ir import (
    ComponentPose,
    PlacementBudget,
    PlacementProbePolicy,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile

DEFAULT_LEGACY_RECTANGULAR_PLACEMENT_ADAPTER_POLICY = LegacyRectangularPlacementAdapterPolicy()


def _fp(payload: object) -> str:
    text = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(text.encode()).hexdigest()


def _canonical_payload(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("compatibility snapshot cannot contain non-finite floats")
        return value
    if isinstance(value, Enum):
        return {
            "enum_type": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": _canonical_payload(value.value),
        }
    if isinstance(value, BaseModel):
        return {
            "model_type": f"{type(value).__module__}.{type(value).__qualname__}",
            "value": _canonical_payload(value.model_dump(mode="json")),
        }
    if is_dataclass(value) and not isinstance(value, type):
        return {
            "dataclass_type": f"{type(value).__module__}.{type(value).__qualname__}",
            "fields": [
                (field.name, _canonical_payload(getattr(value, field.name)))
                for field in fields(value)
            ],
        }
    if isinstance(value, Mapping):
        encoded = [
            (_canonical_payload(key), _canonical_payload(item)) for key, item in value.items()
        ]
        return sorted(
            encoded,
            key=lambda item: json.dumps(
                item[0], sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ),
        )
    if isinstance(value, (tuple, list)):
        return [_canonical_payload(item) for item in value]
    raise TypeError(f"unsupported compatibility snapshot value {type(value)!r}")


def _json_snapshot(payload: object, name: str) -> str:
    if not isinstance(payload, dict):
        raise TypeError(f"{name} snapshot must be an object")
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def board_layout_snapshot_json(layout: BoardLayout) -> str:
    return _json_snapshot(_canonical_payload(layout), "BoardLayout")


def board_netlist_snapshot_json(netlist: BoardNetlist) -> str:
    return _json_snapshot(
        {
            "components": [
                {
                    "reference": item.reference,
                    "value": item.value,
                    "footprint": item.footprint,
                    "uuid_path": item.uuid_path,
                    "fields": item.fields,
                }
                for item in sorted(netlist.components, key=lambda item: item.reference)
            ],
            "nets": [
                {"name": item.name, "nodes": tuple(sorted(item.nodes))}
                for item in sorted(netlist.nets, key=lambda item: item.name)
            ],
        },
        "BoardNetlist",
    )


def board_netlist_fingerprint(netlist: BoardNetlist) -> str:
    """Canonical complete fingerprint for compatibility source authority."""

    return legacy_rectangular_netlist_snapshot_fingerprint(board_netlist_snapshot_json(netlist))


def placement_compatibility_profile_fingerprint(profile: PcbRuleProfile) -> str:
    """Bind the complete declared profile without claiming universal authority."""

    return legacy_rectangular_profile_fingerprint(profile)


@dataclass(frozen=True)
class LegacyRectangularPlacementInput:
    """Retained legacy sources plus their field-preserving minimum R5 probe."""

    source_layout: BoardLayout
    source_netlist: BoardNetlist
    source_profile: PcbRuleProfile
    probe: PlacementProbe
    result: LegacyRectangularPlacementAdapterResult

    def __post_init__(self) -> None:
        if board_layout_fingerprint(self.source_layout) != self.result.source_layout_fingerprint:
            raise ValueError("compatibility source layout fingerprint is stale")
        if board_netlist_fingerprint(self.source_netlist) != self.result.source_netlist_fingerprint:
            raise ValueError("compatibility source netlist fingerprint is stale")
        if (
            placement_compatibility_profile_fingerprint(self.source_profile)
            != self.result.source_profile_fingerprint
        ):
            raise ValueError("compatibility source profile fingerprint is stale")
        if self.probe.result != self.result.probe_result:
            raise ValueError("compatibility result does not retain its exact probe result")


def _validate_legacy_rectangle(
    layout: BoardLayout,
    policy: LegacyRectangularPlacementAdapterPolicy,
) -> None:
    if not math.isfinite(layout.width_mm) or not math.isfinite(layout.height_mm):
        raise ValueError("legacy rectangular dimensions must be finite")
    if layout.width_mm <= 0 or layout.height_mm <= 0:
        raise ValueError("legacy rectangular dimensions must be positive")
    if layout.cutouts:
        raise ValueError("legacy rectangular compatibility does not provide cutout authority")
    outline = layout.outline
    if outline is None or outline == ():
        return
    if not policy.allow_explicit_canonical_rectangle:
        raise ValueError("adapter policy forbids an explicit rectangle")
    expected = (
        (0.0, 0.0),
        (layout.width_mm, 0.0),
        (layout.width_mm, layout.height_mm),
        (0.0, layout.height_mm),
    )
    if outline != expected:
        raise ValueError("legacy rectangular compatibility is not exact shaped-body authority")


def _source_poses(layout: BoardLayout) -> tuple[ComponentPose, ...]:
    references = tuple(component.reference for component, _x_mm in layout.placements)
    if not references or len(set(references)) != len(references):
        raise ValueError("compatibility layout requires unique placed references")
    flipped = set(layout.part_flip)
    return tuple(
        ComponentPose(
            reference=component.reference,
            x_mm=x_mm,
            y_mm=placement_y(layout, component.reference),
            rotation_deg=placement_rotation(layout, component.reference),
            side="back" if component.reference in flipped else "front",
        )
        for component, x_mm in sorted(layout.placements, key=lambda item: item[0].reference)
    )


def adapt_legacy_rectangular_placement(
    source_layout: BoardLayout,
    source_netlist: BoardNetlist,
    target_nets: tuple[str, ...],
    *,
    budget: PlacementBudget,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    policy: LegacyRectangularPlacementAdapterPolicy = (
        DEFAULT_LEGACY_RECTANGULAR_PLACEMENT_ADAPTER_POLICY
    ),
) -> LegacyRectangularPlacementInput:
    """Build an explicit compatibility-only R5 base probe from a legacy rectangle."""

    _validate_legacy_rectangle(source_layout, policy)
    layout_references = {component.reference for component, _x in source_layout.placements}
    netlist_references = {component.reference for component in source_netlist.components}
    if layout_references != netlist_references:
        raise ValueError("compatibility layout and netlist component references differ")
    known_net_names = tuple(sorted(net.name for net in source_netlist.nets))
    if not known_net_names or len(set(known_net_names)) != len(known_net_names):
        raise ValueError("compatibility netlist requires unique named nets")
    targets = tuple(sorted(set(target_nets)))
    if not targets or targets != target_nets:
        raise ValueError("target_nets must be non-empty, sorted, and unique")
    unknown = tuple(sorted(set(targets) - set(known_net_names)))
    if unknown:
        raise ValueError(f"compatibility target nets are absent from netlist: {unknown!r}")

    probe = build_placement_probe(
        source_layout,
        _source_poses(source_layout),
        targets,
        known_net_names=known_net_names,
        policy=PlacementProbePolicy(
            required_references=tuple(sorted(layout_references)),
            allow_unchanged_non_target_references=False,
        ),
        budget=budget,
    )
    layout_fingerprint = board_layout_fingerprint(source_layout)
    layout_snapshot_json = board_layout_snapshot_json(source_layout)
    if legacy_rectangular_layout_snapshot_fingerprint(layout_snapshot_json) != layout_fingerprint:
        raise ValueError("compatibility layout snapshot differs from live layout authority")
    netlist_snapshot_json = board_netlist_snapshot_json(source_netlist)
    netlist_fingerprint = board_netlist_fingerprint(source_netlist)
    profile_fingerprint = placement_compatibility_profile_fingerprint(profile)
    authority_fingerprint = legacy_rectangular_source_authority_fingerprint(
        layout_fingerprint,
        netlist_fingerprint,
        profile_fingerprint,
    )
    policy_fingerprint = policy.semantic_fingerprint()
    result = LegacyRectangularPlacementAdapterResult(
        policy=policy,
        policy_fingerprint=policy_fingerprint,
        source_layout_snapshot_json=layout_snapshot_json,
        source_netlist_snapshot_json=netlist_snapshot_json,
        source_profile=profile,
        source_layout_fingerprint=layout_fingerprint,
        source_netlist_fingerprint=netlist_fingerprint,
        source_profile_fingerprint=profile_fingerprint,
        source_authority_fingerprint=authority_fingerprint,
        probe_result=probe.result,
        probe_result_fingerprint=probe.result.semantic_fingerprint(),
        input_fingerprint=legacy_rectangular_adapter_input_fingerprint(
            policy_fingerprint,
            authority_fingerprint,
            budget.semantic_fingerprint(),
            targets,
        ),
        target_net_names=targets,
    )
    return LegacyRectangularPlacementInput(
        source_layout=source_layout,
        source_netlist=source_netlist,
        source_profile=profile,
        probe=probe,
        result=result,
    )
