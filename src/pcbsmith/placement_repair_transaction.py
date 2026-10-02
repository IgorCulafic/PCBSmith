"""Topology-aware, isolated placement compaction transactions for IF3."""

from __future__ import annotations

import hashlib
import math
import shutil
import tempfile
from collections import defaultdict
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import Field

from pcbsmith.kicad.library import QuotedString, SExpr, parse_sexpr, serialize_sexpr
from pcbsmith.semantic_ir import SemanticIrModel


def _atom(value: object) -> str:
    return value.value if isinstance(value, QuotedString) else str(value)


def _head(node: object) -> str:
    return _atom(node[0]) if isinstance(node, list) and node else ""


def _child(node: list[SExpr], name: str) -> list[SExpr] | None:
    return next((item for item in node if isinstance(item, list) and _head(item) == name), None)


def _reference(footprint: list[SExpr]) -> str | None:
    for item in footprint:
        if (
            isinstance(item, list)
            and _head(item) == "property"
            and len(item) >= 3
            and _atom(item[1]) == "Reference"
        ):
            return _atom(item[2])
    return None


class PlacementPose(SemanticIrModel):
    schema_id: Literal["pcbsmith-repair-placement-pose"] = "pcbsmith-repair-placement-pose"
    schema_version: Literal[1] = 1
    reference: str
    x_mm: float
    y_mm: float
    rotation_deg: float = 0.0
    side: Literal["front", "back"] = "front"


class TopologyRelation(SemanticIrModel):
    schema_id: Literal["pcbsmith-placement-topology-relation"] = (
        "pcbsmith-placement-topology-relation"
    )
    schema_version: Literal[1] = 1
    first_reference: str
    second_reference: str
    shared_nets: tuple[str, ...] = Field(min_length=1)
    weight: float = Field(gt=0)


class PlacementSnapshot(SemanticIrModel):
    schema_id: Literal["pcbsmith-placement-repair-snapshot"] = "pcbsmith-placement-repair-snapshot"
    schema_version: Literal[1] = 1
    board_sha256: str
    poses: tuple[PlacementPose, ...]
    relations: tuple[TopologyRelation, ...]
    topology_cost: float = Field(ge=0)


class PlacementRepairResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-placement-repair-result"] = "pcbsmith-placement-repair-result"
    schema_version: Literal[1] = 1
    before: PlacementSnapshot
    after: PlacementSnapshot
    requested_references: tuple[str, ...]
    changed_references: tuple[str, ...]
    protected_references: tuple[str, ...]
    accepted: bool
    blockers: tuple[str, ...]
    retained_board: str


def extract_placement_snapshot(board: Path) -> PlacementSnapshot:
    tree = parse_sexpr(board.read_text(encoding="utf-8"))
    net_names: dict[str, str] = {}
    for item in tree:
        if isinstance(item, list) and _head(item) == "net" and len(item) >= 3:
            net_names[_atom(item[1])] = _atom(item[2])
    poses: list[PlacementPose] = []
    nets_by_ref: dict[str, set[str]] = defaultdict(set)
    for footprint in tree:
        if not isinstance(footprint, list) or _head(footprint) != "footprint":
            continue
        reference = _reference(footprint)
        at = _child(footprint, "at")
        layer = _child(footprint, "layer")
        if reference is None or at is None or len(at) < 3:
            continue
        poses.append(
            PlacementPose(
                reference=reference,
                x_mm=float(_atom(at[1])),
                y_mm=float(_atom(at[2])),
                rotation_deg=float(_atom(at[3])) if len(at) >= 4 else 0.0,
                side="back" if layer is not None and _atom(layer[1]).startswith("B.") else "front",
            )
        )
        for pad in footprint:
            if not isinstance(pad, list) or _head(pad) != "pad":
                continue
            net = _child(pad, "net")
            if net is not None and len(net) >= 2:
                name = (
                    _atom(net[2]) if len(net) >= 3 else net_names.get(_atom(net[1]), _atom(net[1]))
                )
                if name:
                    nets_by_ref[reference].add(name)
    relations: list[TopologyRelation] = []
    references = sorted(nets_by_ref)
    for index, first in enumerate(references):
        for second in references[index + 1 :]:
            shared = tuple(sorted(nets_by_ref[first] & nets_by_ref[second]))
            if shared:
                signal_count = sum(
                    name.upper() not in {"GND", "VCC", "VIN", "VOUT"} for name in shared
                )
                relations.append(
                    TopologyRelation(
                        first_reference=first,
                        second_reference=second,
                        shared_nets=shared,
                        weight=float(len(shared) + signal_count),
                    )
                )
    ordered_poses = tuple(sorted(poses, key=lambda item: item.reference))
    ordered_relations = tuple(
        sorted(relations, key=lambda item: (item.first_reference, item.second_reference))
    )
    pose_by_ref = {pose.reference: pose for pose in ordered_poses}
    cost = sum(
        relation.weight
        * math.hypot(
            pose_by_ref[relation.first_reference].x_mm
            - pose_by_ref[relation.second_reference].x_mm,
            pose_by_ref[relation.first_reference].y_mm
            - pose_by_ref[relation.second_reference].y_mm,
        )
        for relation in ordered_relations
    )
    return PlacementSnapshot(
        board_sha256=hashlib.sha256(board.read_bytes()).hexdigest(),
        poses=ordered_poses,
        relations=ordered_relations,
        topology_cost=round(cost, 6),
    )


def _apply_poses(board: Path, targets: dict[str, PlacementPose]) -> None:
    tree = parse_sexpr(board.read_text(encoding="utf-8"))
    seen: set[str] = set()
    for footprint in tree:
        if not isinstance(footprint, list) or _head(footprint) != "footprint":
            continue
        reference = _reference(footprint)
        if reference not in targets:
            continue
        at = _child(footprint, "at")
        if at is None:
            raise ValueError(f"footprint {reference} has no pose")
        target = targets[reference]
        at[:] = ["at", str(target.x_mm), str(target.y_mm)]
        if target.rotation_deg:
            at.append(str(target.rotation_deg))
        seen.add(reference)
    if seen != set(targets):
        raise ValueError(f"unknown placement references: {sorted(set(targets) - seen)}")
    board.write_text(serialize_sexpr(tree) + "\n", encoding="utf-8")


def _copy_project_context(source_board: Path, candidate_dir: Path) -> Path:
    """Copy the selected board plus the project-local authority needed by KiCad."""

    candidate_dir.mkdir(parents=True, exist_ok=True)
    for source in source_board.parent.iterdir():
        if source == source_board:
            continue
        if source.is_dir() and source.name.endswith(".pretty"):
            shutil.copytree(source, candidate_dir / source.name)
            continue
        if not source.is_file():
            continue
        if source.name in {"fp-lib-table", "sym-lib-table"} or source.suffix in {
            ".kicad_pro",
            ".kicad_prl",
            ".kicad_sch",
            ".kicad_sym",
        }:
            shutil.copy2(source, candidate_dir / source.name)
    candidate = candidate_dir / source_board.name
    shutil.copy2(source_board, candidate)
    return candidate


def _on_grid(value_mm: float, grid_mm: float) -> bool:
    quotient = value_mm / grid_mm
    return math.isclose(quotient, round(quotient), abs_tol=1e-7)


def run_placement_repair_transaction(
    *,
    source_board: Path,
    target_poses: tuple[PlacementPose, ...],
    retained_root: Path,
    minimum_anchor_spacing_mm: float,
    exact_validator: Callable[[Path], tuple[str, ...]],
    placement_grid_mm: float | None = None,
) -> PlacementRepairResult:
    """Evaluate one bounded pose delta while preserving project authority."""

    before = extract_placement_snapshot(source_board)
    before_by_ref = {pose.reference: pose for pose in before.poses}
    targets = {pose.reference: pose for pose in target_poses}
    if len(targets) != len(target_poses):
        raise ValueError("target placement references must be unique")
    unknown = sorted(set(targets) - set(before_by_ref))
    if unknown:
        raise ValueError(f"unknown placement references: {unknown}")
    retained_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pcbsmith-placement-") as temporary:
        candidate_dir = Path(temporary) / "project"
        candidate = _copy_project_context(source_board, candidate_dir)
        _apply_poses(candidate, targets)
        proposed = extract_placement_snapshot(candidate)
        proposed_by_ref = {pose.reference: pose for pose in proposed.poses}
        blockers: list[str] = []
        proposed_changed = tuple(
            sorted(ref for ref in before_by_ref if before_by_ref[ref] != proposed_by_ref[ref])
        )
        if not proposed_changed:
            blockers.append("no_effect")
        if set(proposed_changed) - set(targets):
            blockers.append("protected_placement_changed")
        positions = [(pose.reference, pose.x_mm, pose.y_mm) for pose in proposed.poses]
        for index, (first, x1, y1) in enumerate(positions):
            for second, x2, y2 in positions[index + 1 :]:
                if math.hypot(x1 - x2, y1 - y2) < minimum_anchor_spacing_mm:
                    blockers.append(f"anchor_spacing:{first}:{second}")
        if proposed.topology_cost >= before.topology_cost:
            blockers.append("topology_cost_not_improved")
        if placement_grid_mm is not None:
            if placement_grid_mm <= 0:
                raise ValueError("placement grid must be positive")
            for reference in sorted(targets):
                pose = proposed_by_ref[reference]
                if not _on_grid(pose.x_mm, placement_grid_mm) or not _on_grid(
                    pose.y_mm, placement_grid_mm
                ):
                    blockers.append(f"placement_off_grid:{reference}")

        blockers.extend(exact_validator(candidate))
        after = extract_placement_snapshot(candidate)
        after_by_ref = {pose.reference: pose for pose in after.poses}
        changed = tuple(
            sorted(ref for ref in before_by_ref if before_by_ref[ref] != after_by_ref[ref])
        )
        protected = tuple(sorted(set(before_by_ref) - set(targets)))
        if set(changed) - set(targets):
            blockers.append("exact_validator_changed_protected_placement")
        if any(after_by_ref[ref] != proposed_by_ref[ref] for ref in targets):
            blockers.append("exact_validator_changed_requested_placement")

        retained_dir = retained_root / f"candidate-{after.board_sha256[:12]}"
        shutil.copytree(candidate_dir, retained_dir)
        retained = retained_dir / source_board.name
    if hashlib.sha256(source_board.read_bytes()).hexdigest() != before.board_sha256:
        raise RuntimeError("placement transaction mutated its source board")
    if hashlib.sha256(retained.read_bytes()).hexdigest() != after.board_sha256:
        raise RuntimeError("retained placement candidate does not match its final snapshot")
    return PlacementRepairResult(
        before=before,
        after=after,
        requested_references=tuple(sorted(targets)),
        changed_references=changed,
        protected_references=protected,
        accepted=not blockers,
        blockers=tuple(sorted(set(blockers))),
        retained_board=str(retained),
    )


def assess_requested_placement(
    source: Path,
    candidate: Path,
    targets: tuple[PlacementPose, ...],
    *,
    optimize: bool = False,
    added_references: tuple[str, ...] = (),
) -> tuple[str, ...]:
    """Shared pose-preservation/objective check for explicit working revisions."""
    before, after = extract_placement_snapshot(source), extract_placement_snapshot(candidate)
    previous = {p.reference: p for p in before.poses}
    current = {p.reference: p for p in after.poses}
    requested = {p.reference: p for p in targets}
    blockers = []
    if set(previous) & set(added_references) or set(previous) | set(added_references) != set(
        current
    ):
        blockers.append("placement_identity_inventory_changed")
    for ref in previous.keys() & current.keys():
        expected = requested.get(ref, previous[ref])
        if current[ref] != expected:
            blockers.append(f"placement_pose_differs:{ref}")
    if optimize and after.topology_cost >= before.topology_cost:
        blockers.append("optimization repair did not improve topology cost")
    return tuple(blockers)
