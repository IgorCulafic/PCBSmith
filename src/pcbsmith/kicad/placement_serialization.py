"""Build the first shaped-board R5.6b serialization authority envelope."""

from __future__ import annotations

from pcbsmith.kicad.board import BoardLayout, BoardNetlist, render_board_from_layout
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.placement_serialization_ir import (
    DEFAULT_SHAPED_SERIALIZATION_DELTA_POLICY,
    PlacementSerializationAuthority,
    ShapedSerializationDeltaPolicy,
    _sha256_text,
    _validate_and_derive,
    placement_serialization_input_fingerprint,
    placement_serialization_profile_fingerprint,
    placement_serialization_result_fingerprint,
)
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile


def build_placement_serialization_authority(
    source_layout: BoardLayout,
    source_netlist: BoardNetlist,
    final_layout: BoardLayout,
    target_net_names: tuple[str, ...],
    movable_references: tuple[str, ...],
    *,
    profile: PcbRuleProfile = DEFAULT_PCB_RULE_PROFILE,
    delta_policy: ShapedSerializationDeltaPolicy = (DEFAULT_SHAPED_SERIALIZATION_DELTA_POLICY),
) -> PlacementSerializationAuthority:
    """Prove a lossless declared delta and deterministic real KiCad emission."""

    targets = tuple(sorted(set(target_net_names)))
    movable = tuple(sorted(set(movable_references)))
    source_layout_json = canonical_board_layout_snapshot_json(source_layout)
    final_layout_json = canonical_board_layout_snapshot_json(final_layout)
    netlist_json = canonical_board_netlist_snapshot_json(source_netlist)
    source_layout_fp = board_layout_snapshot_fingerprint(source_layout_json)
    final_layout_fp = board_layout_snapshot_fingerprint(final_layout_json)
    netlist_fp = board_netlist_snapshot_fingerprint(netlist_json)
    profile_fp = placement_serialization_profile_fingerprint(profile)
    policy_fp = delta_policy.semantic_fingerprint()
    # Run validation before rendering so unauthorized deltas never acquire a
    # seemingly authoritative board artifact.
    field_evidence, identity_evidence = _validate_and_derive(
        source_layout,
        final_layout,
        source_netlist,
        delta_policy,
        movable,
        targets,
    )
    first_render = render_board_from_layout(source_netlist, final_layout, profile=profile)
    second_render = render_board_from_layout(source_netlist, final_layout, profile=profile)
    if first_render != second_render:
        raise ValueError("clean repeated KiCad renders are not byte-identical")
    rendered_sha = _sha256_text(first_render)
    input_fp = placement_serialization_input_fingerprint(
        source_layout_fp,
        netlist_fp,
        profile_fp,
        policy_fp,
        targets,
        movable,
    )
    result_fp = placement_serialization_result_fingerprint(
        input_fp,
        final_layout_fp,
        field_evidence,
        identity_evidence,
        rendered_sha,
    )
    return PlacementSerializationAuthority(
        source_layout_snapshot_json=source_layout_json,
        source_netlist_snapshot_json=netlist_json,
        final_layout_snapshot_json=final_layout_json,
        profile=profile,
        target_net_names=targets,
        movable_references=movable,
        delta_policy=delta_policy,
        field_delta_evidence=field_evidence,
        component_identity_evidence=identity_evidence,
        rendered_board_text=first_render,
        rendered_board_sha256=rendered_sha,
        source_layout_fingerprint=source_layout_fp,
        source_netlist_fingerprint=netlist_fp,
        final_layout_fingerprint=final_layout_fp,
        profile_fingerprint=profile_fp,
        policy_fingerprint=policy_fp,
        input_fingerprint=input_fp,
        result_fingerprint=result_fp,
    )
