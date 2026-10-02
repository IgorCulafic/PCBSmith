"""Inspect an exact saved board with KiCad's Python runtime, without changing it."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pcbnew


def mm(value):
    return round(pcbnew.ToMM(value), 6)


def snapshot(board):
    footprints = []
    holes = []
    for f in board.GetFootprints():
        pads = []
        for p in f.Pads():
            pos, size, drill = p.GetPosition(), p.GetSize(), p.GetDrillSize()
            row = dict(
                number=p.GetNumber(),
                net=p.GetNetname(),
                x=mm(pos.x),
                y=mm(pos.y),
                width=mm(size.x),
                height=mm(size.y),
                drill_x=mm(drill.x),
                drill_y=mm(drill.y),
                bottom_copper=p.GetLayerSet().Contains(pcbnew.B_Cu),
            )
            pads.append(row)
            if drill.x or drill.y:
                holes.append(dict(x=mm(pos.x), y=mm(pos.y), diameter=mm(max(drill.x, drill.y))))
        pos = f.GetPosition()
        footprints.append(
            dict(
                reference=f.GetReference(),
                value=f.GetValue(),
                x=mm(pos.x),
                y=mm(pos.y),
                rotation=round(f.GetOrientationDegrees(), 6),
                footprint=f.GetFPIDAsString(),
                pads=sorted(pads, key=lambda p: p["number"]),
            )
        )
    tracks = []
    for t in board.GetTracks():
        if t.GetClass() != "PCB_TRACK":
            raise ValueError("This candidate checker expects straight tracks and no vias/arcs")
        start, end = t.GetStart(), t.GetEnd()
        tracks.append(
            dict(
                net=t.GetNetname(),
                layer=board.GetLayerName(t.GetLayer()),
                start=[mm(start.x), mm(start.y)],
                end=[mm(end.x), mm(end.y)],
                width=mm(t.GetWidth()),
            )
        )
    return dict(
        footprints=sorted(footprints, key=lambda f: f["reference"]),
        tracks=sorted(tracks, key=lambda t: json.dumps(t, sort_keys=True)),
        holes=holes,
        zone_count=len(board.Zones()),
        copper_layers=board.GetCopperLayerCount(),
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("board", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--roundtrip", type=Path, required=True)
    args = parser.parse_args()
    if args.roundtrip.exists() or args.output.exists():
        raise ValueError("Inspection outputs must be fresh")
    before = args.board.read_bytes()
    board = pcbnew.LoadBoard(str(args.board.resolve()))
    first = snapshot(board)
    args.roundtrip.parent.mkdir(parents=True, exist_ok=True)
    pcbnew.SaveBoard(str(args.roundtrip.resolve()), board)
    after = snapshot(pcbnew.LoadBoard(str(args.roundtrip.resolve())))
    # Ordering of holes does not carry electrical meaning across native saves.
    for item in (first, after):
        item["holes"].sort(key=lambda p: (p["x"], p["y"], p["diameter"]))
    assert first == after, "Native roundtrip changed measured geometry/connectivity"
    assert args.board.read_bytes() == before, "Source board changed"
    args.output.write_text(
        json.dumps(
            dict(
                status="passed",
                board_sha256=hashlib.sha256(before).hexdigest(),
                source_board=str(args.board.resolve()),
                kicad_version=pcbnew.GetBuildVersion(),
                roundtrip="identical measured geometry and net bindings",
                snapshot=first,
            ),
            indent=2,
        ),
        encoding="utf-8",
    )
    print(
        "Native readback and save/reload match:",
        len(first["footprints"]),
        "footprints,",
        len(first["tracks"]),
        "tracks",
    )
