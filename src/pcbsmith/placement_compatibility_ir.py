"""Versioned authority records for opt-in legacy rectangular R5 compatibility."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.placement_ir import PlacementIrModel, PlacementProbeResult
from pcbsmith.rule_profiles import PcbRuleProfile


def _fp(payload: object) -> str:
    text = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(text.encode()).hexdigest()


def _sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be lowercase SHA-256")
    return value


class LegacyRectangularPlacementAdapterPolicy(PlacementIrModel):
    """Explicitly narrow authority for the opt-in legacy rectangle seam."""

    schema_id: Literal["pcbsmith-legacy-rectangular-placement-adapter-policy"] = (
        "pcbsmith-legacy-rectangular-placement-adapter-policy"
    )
    schema_version: Literal[1] = 1
    adapter_id: Literal["legacy-rectangular-r5-compatibility-v1"] = (
        "legacy-rectangular-r5-compatibility-v1"
    )
    template_source: Literal["legacy_rectangular_adapter"] = "legacy_rectangular_adapter"
    authority_scope: Literal["compatibility_only_not_exact_shaped_body"] = (
        "compatibility_only_not_exact_shaped_body"
    )
    allow_explicit_canonical_rectangle: bool = True


class LegacyRectangularPlacementAdapterResult(PlacementIrModel):
    """Bound source authority and the minimum R5 probe produced from it."""

    schema_id: Literal["pcbsmith-legacy-rectangular-placement-adapter-result"] = (
        "pcbsmith-legacy-rectangular-placement-adapter-result"
    )
    schema_version: Literal[1] = 1
    compatibility_only: Literal[True] = True
    exact_shaped_body_authority: Literal[False] = False
    policy: LegacyRectangularPlacementAdapterPolicy
    policy_fingerprint: str
    source_layout_snapshot_json: str
    source_netlist_snapshot_json: str
    source_profile: PcbRuleProfile
    source_layout_fingerprint: str
    source_netlist_fingerprint: str
    source_profile_fingerprint: str
    source_authority_fingerprint: str
    probe_result: PlacementProbeResult
    probe_result_fingerprint: str
    input_fingerprint: str
    target_net_names: tuple[str, ...] = Field(min_length=1)

    @field_validator(
        "policy_fingerprint",
        "source_layout_fingerprint",
        "source_netlist_fingerprint",
        "source_profile_fingerprint",
        "source_authority_fingerprint",
        "probe_result_fingerprint",
        "input_fingerprint",
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _sha256(value, info.field_name)

    @model_validator(mode="after")
    def nested_authority_is_coherent(self) -> Self:
        targets = tuple(sorted(set(self.target_net_names)))
        if targets != self.target_net_names:
            raise ValueError("target_net_names must be sorted and unique")
        if self.policy_fingerprint != self.policy.semantic_fingerprint():
            raise ValueError("adapter policy fingerprint is stale")
        if self.probe_result_fingerprint != self.probe_result.semantic_fingerprint():
            raise ValueError("adapter probe result fingerprint is stale")
        if self.source_layout_fingerprint != legacy_rectangular_layout_snapshot_fingerprint(
            self.source_layout_snapshot_json
        ):
            raise ValueError("adapter source layout snapshot fingerprint is stale")
        if self.source_netlist_fingerprint != legacy_rectangular_netlist_snapshot_fingerprint(
            self.source_netlist_snapshot_json
        ):
            raise ValueError("adapter source netlist snapshot fingerprint is stale")
        if self.source_profile_fingerprint != legacy_rectangular_profile_fingerprint(
            self.source_profile
        ):
            raise ValueError("adapter source profile fingerprint is stale")
        if self.probe_result.telemetry.template_fingerprint != self.source_layout_fingerprint:
            raise ValueError("adapter probe is not bound to the retained source layout")
        if targets != self.probe_result.target_policy.target_net_names:
            raise ValueError("adapter target nets differ from the probe target policy")
        authority = legacy_rectangular_source_authority_fingerprint(
            self.source_layout_fingerprint,
            self.source_netlist_fingerprint,
            self.source_profile_fingerprint,
        )
        if self.source_authority_fingerprint != authority:
            raise ValueError("adapter source authority fingerprint is stale")
        expected = legacy_rectangular_adapter_input_fingerprint(
            self.policy_fingerprint,
            authority,
            self.probe_result.budget.semantic_fingerprint(),
            targets,
        )
        if self.input_fingerprint != expected:
            raise ValueError("adapter input fingerprint is stale")
        object.__setattr__(self, "target_net_names", targets)
        return self


def _canonical_snapshot(snapshot_json: str, name: str) -> dict[str, Any]:
    try:
        payload = json.loads(snapshot_json)
    except json.JSONDecodeError as error:
        raise ValueError(f"{name} snapshot JSON is invalid") from error
    if not isinstance(payload, dict):
        raise ValueError(f"{name} snapshot JSON must contain an object")
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    if snapshot_json != canonical:
        raise ValueError(f"{name} snapshot JSON must be canonical")
    return payload


def legacy_rectangular_layout_snapshot_fingerprint(snapshot_json: str) -> str:
    snapshot = _canonical_snapshot(snapshot_json, "source layout")
    if snapshot.get("dataclass_type") != "pcbsmith.kicad.board.BoardLayout" or not isinstance(
        snapshot.get("fields"), list
    ):
        raise ValueError("source layout snapshot JSON has the wrong schema/type")
    return _fp(
        {
            "schema_id": "pcbsmith-board-layout-complete",
            "schema_version": 1,
            "layout": snapshot,
        }
    )


def legacy_rectangular_netlist_snapshot_fingerprint(snapshot_json: str) -> str:
    snapshot = _canonical_snapshot(snapshot_json, "source netlist")
    if (
        set(snapshot) != {"components", "nets"}
        or not isinstance(snapshot["components"], list)
        or not isinstance(snapshot["nets"], list)
    ):
        raise ValueError("source netlist snapshot JSON has the wrong schema/type")
    return _fp(
        {
            "schema_id": "pcbsmith-board-netlist",
            "schema_version": 1,
            **snapshot,
        }
    )


def legacy_rectangular_profile_fingerprint(profile: PcbRuleProfile) -> str:
    return _fp(
        {
            "schema_id": "pcbsmith-placement-compatibility-profile",
            "schema_version": 1,
            "profile": profile.model_dump(mode="json"),
        }
    )


def legacy_rectangular_source_authority_fingerprint(
    layout_fingerprint: str,
    netlist_fingerprint: str,
    profile_fingerprint: str,
) -> str:
    for name, value in (
        ("layout_fingerprint", layout_fingerprint),
        ("netlist_fingerprint", netlist_fingerprint),
        ("profile_fingerprint", profile_fingerprint),
    ):
        _sha256(value, name)
    return _fp(
        {
            "schema_id": "pcbsmith-legacy-rectangular-placement-source-authority",
            "schema_version": 1,
            "layout_fingerprint": layout_fingerprint,
            "netlist_fingerprint": netlist_fingerprint,
            "profile_fingerprint": profile_fingerprint,
        }
    )


def legacy_rectangular_adapter_input_fingerprint(
    policy_fingerprint: str,
    source_authority_fingerprint: str,
    budget_fingerprint: str,
    target_net_names: tuple[str, ...],
) -> str:
    for name, value in (
        ("policy_fingerprint", policy_fingerprint),
        ("source_authority_fingerprint", source_authority_fingerprint),
        ("budget_fingerprint", budget_fingerprint),
    ):
        _sha256(value, name)
    targets = tuple(sorted(set(target_net_names)))
    if not targets or targets != target_net_names:
        raise ValueError("target_net_names must be non-empty, sorted, and unique")
    return _fp(
        {
            "schema_id": "pcbsmith-legacy-rectangular-placement-adapter-input",
            "schema_version": 1,
            "policy_fingerprint": policy_fingerprint,
            "source_authority_fingerprint": source_authority_fingerprint,
            "budget_fingerprint": budget_fingerprint,
            "target_net_names": targets,
        }
    )
