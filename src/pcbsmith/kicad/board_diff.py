"""Board-diff: turn user edits in KiCad into structured learning signal.

The user's hand edits are the highest-quality feedback the pipeline gets
(hardening plan 4.2): P1's rotation became rule 8.3; D1's relocation on
the buck taught 2-D switching-loop placement. This module diffs a
(possibly user-edited) ``.kicad_pcb`` against a reference - either the
``layout.json`` snapshot every board authority now emits, or another
generated board file - and emits ``human-edits.json`` plus draft entries
in ``docs/ai-rule-suggestions.md`` for promotion into real rules.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

Placement = tuple[float, float, float, str]  # x, y, rotation, layer


@dataclass(frozen=True)
class PlacementEdit:
    reference: str
    generated: Placement | None
    edited: Placement | None

    def describe(self) -> str:
        if self.generated is None:
            return f"{self.reference}: added by hand at {self.edited}"
        if self.edited is None:
            return f"{self.reference}: removed by hand"
        gx, gy, grot, glayer = self.generated
        ex, ey, erot, elayer = self.edited
        parts = []
        if (gx, gy) != (ex, ey):
            parts.append(
                f"moved ({gx:g}, {gy:g}) -> ({ex:g}, {ey:g}) "
                f"[d=({ex - gx:+.2f}, {ey - gy:+.2f})mm]"
            )
        if grot != erot:
            parts.append(f"rotated {grot:g} -> {erot:g}")
        if glayer != elayer:
            parts.append(f"side {glayer} -> {elayer}")
        return f"{self.reference}: " + "; ".join(parts)


def parse_board_placements(board_text: str) -> dict[str, Placement]:
    """Reference -> (x, y, rotation, layer) from a .kicad_pcb, using
    quote-aware brace matching (descriptions may contain parentheses)."""
    placements: dict[str, Placement] = {}
    for match in re.finditer(r'\(footprint "([^"]+)"', board_text):
        start = match.start()
        depth = 0
        index = start
        length = len(board_text)
        while index < length:
            char = board_text[index]
            if char == '"':
                index += 1
                while index < length and board_text[index] != '"':
                    index += 2 if board_text[index] == "\\" else 1
            elif char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        block = board_text[start : index + 1]
        reference = re.search(r'\(property "Reference" "([^"]+)"', block)
        at = re.search(
            r"\(at (-?[\d.]+) (-?[\d.]+)(?: (-?[\d.]+))?\)", block
        )
        layer = re.search(r'\(layer "([^"]+)"\)', block)
        if reference and at:
            placements[reference.group(1)] = (
                float(at.group(1)),
                float(at.group(2)),
                float(at.group(3) or 0.0),
                layer.group(1) if layer else "F.Cu",
            )
    return placements


def diff_placements(
    generated: dict[str, Placement],
    edited: dict[str, Placement],
    *,
    tolerance_mm: float = 0.01,
) -> tuple[PlacementEdit, ...]:
    edits: list[PlacementEdit] = []
    for reference in sorted(set(generated) | set(edited)):
        before = generated.get(reference)
        after = edited.get(reference)
        if before is not None and after is not None:
            moved = (
                abs(before[0] - after[0]) > tolerance_mm
                or abs(before[1] - after[1]) > tolerance_mm
            )
            if not moved and before[2] == after[2] and before[3] == after[3]:
                continue
        edits.append(
            PlacementEdit(reference=reference, generated=before, edited=after)
        )
    return tuple(edits)


def write_layout_snapshot(
    placements: dict[str, Placement], path: Path
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema": "pcbsmith-layout-snapshot-v1",
                "placements": {
                    reference: {
                        "x_mm": x, "y_mm": y, "rotation": rot, "layer": layer,
                    }
                    for reference, (x, y, rot, layer) in sorted(placements.items())
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def load_layout_snapshot(path: Path) -> dict[str, Placement]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        reference: (
            entry["x_mm"], entry["y_mm"], entry["rotation"], entry["layer"],
        )
        for reference, entry in data["placements"].items()
    }


def append_rule_suggestion(
    suggestions_file: Path,
    revision_dir: str,
    edits: tuple[PlacementEdit, ...],
) -> None:
    lines = [
        "",
        f"## Human board edit ({date.today().isoformat()}, `{revision_dir}`)",
        "",
        "Source: `pcbsmith board-diff` (plan 4.2). The user moved parts by",
        "hand; each delta below is a candidate placement rule. Review and",
        "promote or discard.",
        "",
    ]
    lines.extend(f"- {edit.describe()}" for edit in edits)
    lines.append("")
    with suggestions_file.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
