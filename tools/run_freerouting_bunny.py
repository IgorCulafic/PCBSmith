from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import pcbnew


def prepare(source: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    board = pcbnew.LoadBoard(str(source))
    for item in list(board.GetTracks()):
        board.Remove(item)
    for index in range(board.GetAreaCount() - 1, -1, -1):
        board.Remove(board.GetArea(index))
    unrouted = output_dir / "bunny-led-freerouting-unrouted.kicad_pcb"
    dsn = output_dir / "bunny-led-freerouting.dsn"
    pcbnew.SaveBoard(str(unrouted), board)
    if not pcbnew.ExportSpecctraDSN(board, str(dsn)):
        raise RuntimeError("KiCad failed to export Specctra DSN")
    project = source.with_suffix(".kicad_pro")
    if project.exists():
        shutil.copy2(project, output_dir / "bunny-led-freerouting.kicad_pro")
    print(unrouted)
    print(dsn)


def import_session(unrouted: Path, session: Path, output: Path) -> None:
    board = pcbnew.LoadBoard(str(unrouted))
    if not pcbnew.ImportSpecctraSES(board, str(session)):
        raise RuntimeError("KiCad failed to import the Specctra session")
    pcbnew.SaveBoard(str(output), board)
    print(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("source", type=Path)
    prep.add_argument("output_dir", type=Path)
    imp = sub.add_parser("import")
    imp.add_argument("unrouted", type=Path)
    imp.add_argument("session", type=Path)
    imp.add_argument("output", type=Path)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.source.resolve(), args.output_dir.resolve())
    else:
        import_session(args.unrouted.resolve(), args.session.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
