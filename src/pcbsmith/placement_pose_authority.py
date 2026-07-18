"""Replay-bound authority for exact placement poses.

This module is intentionally narrower than shaped-board serialization.  It
proves only that complete canonical ``BoardLayout`` snapshots contain one
unambiguous pose per placed reference and that changes are confined to a
declared movable-reference set.  It makes no rendering, read-back, routing, or
DRC claim.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, Self

from pydantic import Field, field_validator, model_validator

from pcbsmith.kicad.board import BoardLayout
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    parse_canonical_board_layout_snapshot,
)
from pcbsmith.placement_ir import PlacementIrModel


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_identity(value: str, field_name: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must contain canonical non-empty references")
    return value


def _canonical_references(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    checked = tuple(_require_identity(value, field_name) for value in values)
    if len(set(checked)) != len(checked):
        raise ValueError(f"{field_name} must contain unique references")
    return tuple(sorted(checked))


def _require_sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
    return value


class ExactPlacementPose(PlacementIrModel):
    """One literal pose derived from the sparse fields of a ``BoardLayout``."""

    schema_id: Literal["pcbsmith-exact-placement-pose"] = "pcbsmith-exact-placement-pose"
    schema_version: Literal[1] = 1
    reference: str = Field(min_length=1)
    x_mm: float
    y_mm: float
    rotation_deg: float
    flipped: bool

    @field_validator("reference")
    @classmethod
    def reference_is_canonical(cls, value: str) -> str:
        return _require_identity(value, "reference")


def _unique_placement_x(layout: BoardLayout, label: str) -> dict[str, float]:
    result: dict[str, float] = {}
    for component, x_mm in layout.placements:
        reference = _require_identity(component.reference, f"{label} placements")
        if reference in result:
            raise ValueError(f"{label} placements repeat reference {reference!r}")
        result[reference] = x_mm
    return result


def _unique_sparse_values(
    entries: tuple[tuple[str, float], ...],
    known_references: set[str],
    label: str,
) -> dict[str, float]:
    result: dict[str, float] = {}
    for reference, value in entries:
        reference = _require_identity(reference, label)
        if reference not in known_references:
            raise ValueError(f"{label} contains shadow reference {reference!r}")
        if reference in result:
            raise ValueError(f"{label} repeats reference {reference!r}")
        result[reference] = value
    return result


def derive_exact_placement_poses(
    layout: BoardLayout,
    *,
    label: str = "layout",
) -> tuple[ExactPlacementPose, ...]:
    """Close sparse layout pose fields into one canonical record per reference."""

    placement_x = _unique_placement_x(layout, label)
    known = set(placement_x)
    y_values = _unique_sparse_values(layout.part_y_mm, known, f"{label} part_y_mm")
    rotation_values = _unique_sparse_values(
        layout.part_rotation, known, f"{label} part_rotation"
    )
    flipped: set[str] = set()
    for reference in layout.part_flip:
        reference = _require_identity(reference, f"{label} part_flip")
        if reference not in known:
            raise ValueError(f"{label} part_flip contains shadow reference {reference!r}")
        if reference in flipped:
            raise ValueError(f"{label} part_flip repeats reference {reference!r}")
        flipped.add(reference)
    return tuple(
        ExactPlacementPose(
            reference=reference,
            x_mm=placement_x[reference],
            y_mm=y_values.get(reference, layout.parts_row_y_mm),
            rotation_deg=rotation_values.get(reference, 0.0),
            flipped=reference in flipped,
        )
        for reference in sorted(known)
    )


def placement_pose_result_fingerprint(
    source_layout_fingerprint: str,
    final_layout_fingerprint: str,
    movable_references: tuple[str, ...],
    source_poses: tuple[ExactPlacementPose, ...],
    final_poses: tuple[ExactPlacementPose, ...],
) -> str:
    _require_sha256(source_layout_fingerprint, "source_layout_fingerprint")
    _require_sha256(final_layout_fingerprint, "final_layout_fingerprint")
    return _fingerprint(
        {
            "schema_id": "pcbsmith-placement-pose-authority-result",
            "schema_version": 1,
            "source_layout_fingerprint": source_layout_fingerprint,
            "final_layout_fingerprint": final_layout_fingerprint,
            "movable_references": movable_references,
            "source_poses": [pose.model_dump(mode="json") for pose in source_poses],
            "final_poses": [pose.model_dump(mode="json") for pose in final_poses],
        }
    )


def _validate_pose_delta(
    source_poses: tuple[ExactPlacementPose, ...],
    final_poses: tuple[ExactPlacementPose, ...],
    movable_references: tuple[str, ...],
) -> None:
    source_by_ref = {pose.reference: pose for pose in source_poses}
    final_by_ref = {pose.reference: pose for pose in final_poses}
    source_refs = set(source_by_ref)
    final_refs = set(final_by_ref)
    if source_refs != final_refs:
        missing = tuple(sorted(source_refs - final_refs))
        extra = tuple(sorted(final_refs - source_refs))
        raise ValueError(
            f"source/final placement reference sets differ: missing={missing!r}, extra={extra!r}"
        )
    unknown_movable = tuple(sorted(set(movable_references) - source_refs))
    if unknown_movable:
        raise ValueError(f"movable references are absent from layouts: {unknown_movable!r}")
    movable = set(movable_references)
    for reference in sorted(source_refs - movable):
        if source_by_ref[reference] != final_by_ref[reference]:
            raise ValueError(f"fixed reference {reference!r} changed exact pose")


class PlacementPoseAuthority(PlacementIrModel):
    """Replayable proof that only declared references changed exact pose."""

    schema_id: Literal["pcbsmith-placement-pose-authority"] = (
        "pcbsmith-placement-pose-authority"
    )
    schema_version: Literal[1] = 1
    authority_scope: Literal["exact_pose_only_no_render_readback_or_drc"] = (
        "exact_pose_only_no_render_readback_or_drc"
    )
    source_layout_snapshot_json: str
    final_layout_snapshot_json: str
    movable_references: tuple[str, ...] = ()
    source_poses: tuple[ExactPlacementPose, ...]
    final_poses: tuple[ExactPlacementPose, ...]
    source_layout_fingerprint: str
    final_layout_fingerprint: str
    result_fingerprint: str

    @field_validator(
        "source_layout_fingerprint", "final_layout_fingerprint", "result_fingerprint"
    )
    @classmethod
    def fingerprints_are_sha256(cls, value: str, info: Any) -> str:
        return _require_sha256(value, info.field_name)

    @model_validator(mode="after")
    def retained_claim_replays_exactly(self) -> Self:
        canonical_movable = _canonical_references(
            self.movable_references, "movable_references"
        )
        object.__setattr__(self, "movable_references", canonical_movable)
        source = parse_canonical_board_layout_snapshot(self.source_layout_snapshot_json)
        final = parse_canonical_board_layout_snapshot(self.final_layout_snapshot_json)
        expected_source = derive_exact_placement_poses(source, label="source layout")
        expected_final = derive_exact_placement_poses(final, label="final layout")
        _validate_pose_delta(expected_source, expected_final, canonical_movable)
        if self.source_poses != expected_source:
            raise ValueError("source pose evidence is stale")
        if self.final_poses != expected_final:
            raise ValueError("final pose evidence is stale")
        source_fingerprint = board_layout_snapshot_fingerprint(
            self.source_layout_snapshot_json
        )
        final_fingerprint = board_layout_snapshot_fingerprint(self.final_layout_snapshot_json)
        if self.source_layout_fingerprint != source_fingerprint:
            raise ValueError("source layout fingerprint is stale")
        if self.final_layout_fingerprint != final_fingerprint:
            raise ValueError("final layout fingerprint is stale")
        result_fingerprint = placement_pose_result_fingerprint(
            source_fingerprint,
            final_fingerprint,
            canonical_movable,
            expected_source,
            expected_final,
        )
        if self.result_fingerprint != result_fingerprint:
            raise ValueError("placement pose result fingerprint is stale")
        return self


def build_placement_pose_authority(
    source_layout: BoardLayout,
    final_layout: BoardLayout,
    movable_references: tuple[str, ...] = (),
) -> PlacementPoseAuthority:
    """Build an isolated exact-pose authority from complete layout snapshots."""

    canonical_movable = _canonical_references(movable_references, "movable_references")
    source_snapshot = canonical_board_layout_snapshot_json(source_layout)
    final_snapshot = canonical_board_layout_snapshot_json(final_layout)
    # Parse before deriving so retained canonical data, not caller-owned
    # containers, is the sole authority for every result field.
    retained_source = parse_canonical_board_layout_snapshot(source_snapshot)
    retained_final = parse_canonical_board_layout_snapshot(final_snapshot)
    source_poses = derive_exact_placement_poses(retained_source, label="source layout")
    final_poses = derive_exact_placement_poses(retained_final, label="final layout")
    _validate_pose_delta(source_poses, final_poses, canonical_movable)
    source_fingerprint = board_layout_snapshot_fingerprint(source_snapshot)
    final_fingerprint = board_layout_snapshot_fingerprint(final_snapshot)
    result_fingerprint = placement_pose_result_fingerprint(
        source_fingerprint,
        final_fingerprint,
        canonical_movable,
        source_poses,
        final_poses,
    )
    return PlacementPoseAuthority(
        source_layout_snapshot_json=source_snapshot,
        final_layout_snapshot_json=final_snapshot,
        movable_references=canonical_movable,
        source_poses=source_poses,
        final_poses=final_poses,
        source_layout_fingerprint=source_fingerprint,
        final_layout_fingerprint=final_fingerprint,
        result_fingerprint=result_fingerprint,
    )
