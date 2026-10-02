"""Validated JSON placement input for the registered generic board builder."""

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.library import SExpr, SList

if TYPE_CHECKING:
    from pcbsmith.kicad.board import BoardLayout, BoardNetlist
    from pcbsmith.rule_profiles import PcbRuleProfile


class BoardLabelInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    text: str = Field(min_length=1)
    at_mm: tuple[float, float]
    size_mm: float = Field(default=1, gt=0)
    layer: str = "F.SilkS"

    @model_validator(mode="after")
    def supported(self) -> Self:
        if self.layer not in {"F.SilkS", "B.SilkS"}:
            raise ValueError("Layout labels are limited to silkscreen")
        if any(not math.isfinite(x) for x in self.at_mm):
            raise ValueError("Finite label coordinates required")
        return self


class ReviewedLayoutInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    placements: dict[str, tuple[float, float, float]]
    reference_positions: dict[str, tuple[float, float, float]] = {}
    labels: tuple[BoardLabelInput, ...] = ()

    @model_validator(mode="after")
    def finite(self) -> Self:
        for pose in (*self.placements.values(), *self.reference_positions.values()):
            if any(not math.isfinite(v) for v in pose):
                raise ValueError("Finite pose coordinates required")
        if not set(self.reference_positions) <= set(self.placements):
            raise ValueError("Reference text targets an absent component")
        return self

    def bind(self, netlist: BoardNetlist) -> BoardLayout:
        from pcbsmith.kicad.board import BoardLayout

        if set(self.placements) != {c.reference for c in netlist.components}:
            raise ValueError("Reviewed placement must cover the exact native component set")
        graphics = []
        for i, label in enumerate(self.labels):
            x, y = label.at_mm
            size = label.size_mm
            mirror = " (justify mirror)" if label.layer == "B.SilkS" else ""
            label_uuid = stable_kicad_uuid("layout-label", str(i), label.text)
            graphics.append(
                f"(gr_text {json.dumps(label.text)} (at {x + 20:g} {y + 20:g}) "
                f'(layer "{label.layer}") (uuid "{label_uuid}") '
                f"(effects (font (size {size:g} {size:g}) (thickness {size / 7:g})){mirror}))"
            )
        return BoardLayout(
            placements=tuple((c, self.placements[c.reference][0]) for c in netlist.components),
            segments=(),
            vias=(),
            width_mm=self.width_mm,
            height_mm=self.height_mm,
            part_y_mm=tuple((r, p[1]) for r, p in self.placements.items()),
            part_rotation=tuple((r, p[2]) for r, p in self.placements.items()),
            part_reference_at=tuple(self.reference_positions.items()),
            graphics=tuple(graphics),
        )


def synchronize_native_placement(
    source_text: str, base_layout: BoardLayout, netlist: BoardNetlist, profile: PcbRuleProfile
) -> BoardLayout:
    """Refresh supported detached fields from saved CAD, never alter the CAD.

    This is deliberately not a general importer: preserve the base outline,
    routing, mask and other declarations, then require complete native semantic
    equality. Unsupported changes fail rather than being silently discarded.
    The resulting snapshot is input data, not an engineering approval.
    """
    from dataclasses import replace

    from pcbsmith.kicad.board import BOARD_SHEET_ORIGIN_MM
    from pcbsmith.kicad.library import _atom, _children, parse_sexpr, serialize_sexpr
    from pcbsmith.kicad.routing_candidate_transaction import require_saved_layout_matches

    # Keep the exact established fingerprint when the snapshot already matches.
    try:
        require_saved_layout_matches(source_text, base_layout, netlist, profile)
    except ValueError as exc:
        if (
            str(exc)
            != "detached layout does not match saved board geometry and electrical semantics"
        ):
            raise
    else:
        return base_layout

    root = parse_sexpr(source_text)
    if not root or root[0] != "kicad_pcb":
        raise ValueError("native placement input must be a KiCad board")
    poses = {}
    references = {}
    for footprint in _children(root, "footprint"):
        reference_fields = [
            node
            for node in footprint
            if isinstance(node, list)
            and len(node) >= 3
            and node[0] in {"property", "fp_text"}
            and _atom(node[1]).lower() == "reference"
        ]
        if len(reference_fields) != 1:
            raise ValueError("exactly one native reference field required per footprint")
        field = reference_fields[0]
        reference = _atom(field[2])
        if reference in poses:
            raise ValueError("duplicate native component reference")
        at = list(_children(footprint, "at"))
        text_at = list(_children(field, "at"))
        if len(at) != 1 or len(text_at) != 1:
            raise ValueError("native component/reference pose is missing or ambiguous")

        def pose(node: SList) -> tuple[float, float, float]:
            values = tuple(float(_atom(v)) for v in node[1:])
            if len(values) not in {2, 3} or not all(math.isfinite(v) for v in values):
                raise ValueError("unsupported native pose")
            return values[0], values[1], values[2] if len(values) == 3 else 0.0

        x, y, angle = pose(at[0])
        poses[reference] = (x - BOARD_SHEET_ORIGIN_MM, y - BOARD_SHEET_ORIGIN_MM, angle)
        references[reference] = pose(text_at[0])
    expected = {component.reference for component in netlist.components}
    if set(poses) != expected or {c.reference for c, _ in base_layout.placements} != expected:
        raise ValueError("native, base layout and netlist component sets differ")

    def silk(node: SExpr) -> bool:
        if not isinstance(node, list) or not node or not str(node[0]).startswith("gr_"):
            return False
        layers = list(_children(node, "layer"))
        return len(layers) == 1 and _atom(layers[0][1]) in {"F.SilkS", "B.SilkS"}

    graphics = tuple(g for g in base_layout.graphics if not silk(parse_sexpr(g)))
    graphics += tuple(serialize_sexpr(node) for node in root if silk(node))
    result = replace(
        base_layout,
        placements=tuple((c, poses[c.reference][0]) for c, _ in base_layout.placements),
        part_y_mm=tuple((c.reference, poses[c.reference][1]) for c, _ in base_layout.placements),
        part_rotation=tuple(
            (c.reference, poses[c.reference][2]) for c, _ in base_layout.placements
        ),
        part_reference_at=tuple(
            (c.reference, references[c.reference]) for c, _ in base_layout.placements
        ),
        graphics=graphics,
    )
    require_saved_layout_matches(source_text, result, netlist, profile)
    return result


def main() -> None:
    """Read-only native synchronization; output is an unapproved input snapshot."""
    import argparse
    import hashlib
    from pathlib import Path

    from pcbsmith.kicad.board_serialization import (
        board_layout_snapshot_fingerprint,
        canonical_board_layout_snapshot_json,
        parse_canonical_board_layout_snapshot,
        parse_canonical_board_netlist_snapshot,
    )
    from pcbsmith.kicad.project_dependencies import project_footprint_scope
    from pcbsmith.rule_profiles import PcbRuleProfile

    parser = argparse.ArgumentParser(description=main.__doc__)
    for name in ("board", "base-layout", "netlist", "profile", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    parser.add_argument("--source-sha256", required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("snapshot output must be new; preserve previous preparations")
    paths = dict(
        board=args.board, base_layout=args.base_layout, netlist=args.netlist, profile=args.profile
    )
    payloads = {key: path.read_bytes() for key, path in paths.items()}
    hashes = {key: hashlib.sha256(data).hexdigest() for key, data in payloads.items()}
    if hashes["board"] != args.source_sha256:
        raise ValueError("native board differs from expected source SHA-256")
    with project_footprint_scope(args.board.parent):
        layout = synchronize_native_placement(
            payloads["board"].decode("utf-8"),
            parse_canonical_board_layout_snapshot(payloads["base_layout"].decode("utf-8")),
            parse_canonical_board_netlist_snapshot(payloads["netlist"].decode("utf-8")),
            PcbRuleProfile.model_validate_json(payloads["profile"]),
        )
    snapshot = canonical_board_layout_snapshot_json(layout)
    if any(path.read_bytes() != payloads[key] for key, path in paths.items()):
        raise ValueError("source changed during native input synchronization")
    receipt = dict(
        schema_id="pcbsmith-native-placement-input-v1",
        status="matched_native_snapshot",
        input_paths={key: str(path.resolve()) for key, path in paths.items()},
        input_sha256=hashes,
        layout_fingerprint=board_layout_snapshot_fingerprint(snapshot),
        approval="none; refresh dependent engineering/review inputs through their owners",
    )
    args.output.mkdir(parents=True)
    (args.output / "layout.json").write_text(snapshot, encoding="utf-8")
    (args.output / "preparation.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
