"""Create a review-only KiCad board containing selected routed net carriers.

Run this helper with KiCad's bundled Python interpreter so ``pcbnew`` is
available.  Footprints, pads, outline, and annotations remain as spatial
context; non-selected tracks, vias, and zones are removed from the copy.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pcbnew


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("board", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--net", action="append", default=[])
    args = parser.parse_args()

    source = args.board.resolve()
    destination = args.output.resolve()
    allowed = frozenset(args.net)
    if not source.is_file():
        raise FileNotFoundError(source)
    if not allowed:
        raise ValueError("at least one --net is required")

    board = pcbnew.LoadBoard(str(source))
    for item in list(board.GetTracks()):
        if item.GetNetname() not in allowed:
            board.Remove(item)
    for zone in list(board.Zones()):
        if zone.GetNetname() not in allowed:
            board.Remove(zone)

    destination.parent.mkdir(parents=True, exist_ok=True)
    pcbnew.SaveBoard(str(destination), board)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
