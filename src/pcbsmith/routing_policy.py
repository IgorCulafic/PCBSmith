"""Normal board routing policy: pinned Freerouting, no implicit manual fallback."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from pcbsmith.kicad.board_serialization import (
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)

AUTOMATIC_ROUTING_POLICY = "freerouting-one-retry-v1"
AUTOMATIC_ROUTING_ATTEMPTS = 2


def resolve_freerouting_config(board: Path, explicit: Path | None = None) -> Path:
    """Resolve installation settings; missing/broken settings never select another engine."""
    if explicit is not None:
        candidates = [explicit]
    elif configured := os.environ.get("PCBSMITH_FREEROUTING_CONFIG"):
        candidates = [Path(configured)]
    else:
        candidates = [parent / ".pcbsmith/freerouting.json" for parent in board.resolve().parents]
        candidates.append(Path(__file__).resolve().parents[2] / ".pcbsmith/freerouting.json")
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise ValueError(
        "Freerouting configuration missing. Set --freerouting-config, "
        "PCBSMITH_FREEROUTING_CONFIG, or .pcbsmith/freerouting.json. "
        "Routing stopped; no native or manual fallback."
    )


def routing_design_fingerprint(layout_file: Path, netlist_file: Path) -> str:
    """Retry identity excludes annotations, route order, budgets and output paths."""
    layout = parse_canonical_board_layout_snapshot(layout_file.read_text(encoding="utf-8"))
    netlist = parse_canonical_board_netlist_snapshot(netlist_file.read_text(encoding="utf-8"))
    y = dict(layout.part_y_mm)
    rotations = dict(layout.part_rotation)
    placements = sorted(
        (
            part.reference,
            part.footprint,
            x,
            y.get(part.reference, layout.parts_row_y_mm),
            rotations.get(part.reference, 0) % 360,
            part.reference in layout.part_flip,
        )
        for part, x in layout.placements
    )
    payload = {
        "placements": placements,
        "connectivity": sorted(sorted(net.nodes) for net in netlist.nets),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def require_manual_routing_authorization(reason: str | None) -> None:
    if reason is None or not reason.strip():
        raise ValueError(
            "Manual copper routing is disabled by default. Use Freerouting, or record "
            "the user's explicit manual-routing request in manual_routing_authorization."
        )
