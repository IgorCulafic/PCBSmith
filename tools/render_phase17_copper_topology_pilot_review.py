"""Render standardized review views for retained copper-topology pilot boards."""

from __future__ import annotations

import argparse
from pathlib import Path

from tools.render_phase17_corpus_review import render_case

DEFAULT_CASES = ("RC30", "RC31", "RC34", "RC40")


def _latest_board(root: Path, case_id: str) -> tuple[str, Path]:
    matches = sorted((root / "cases").glob(f"{case_id}-*"))
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected one pilot case for {case_id}, found {matches}")
    attempts = sorted(matches[0].glob("attempt-*"))
    if not attempts:
        raise FileNotFoundError(f"No pilot attempts for {case_id}")
    attempt = attempts[-1]
    board = attempt / "copper-topology.kicad_pcb"
    if not board.exists() or board.stat().st_size == 0:
        raise FileNotFoundError(f"Missing retained pilot board: {board}")
    return attempt.name, board


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root",
        type=Path,
        default=Path("experiments/phase17-routing-corpus-40/copper-topology-pilot-v3-safe"),
    )
    parser.add_argument(
        "--kicad-cli",
        type=Path,
        default=Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"),
    )
    parser.add_argument("--cases", nargs="+", default=DEFAULT_CASES)
    args = parser.parse_args()
    root = args.root.resolve()
    review = root / "review" / "representative"
    for case_id in args.cases:
        attempt, board = _latest_board(root, case_id)
        render_case(args.kicad_cli.resolve(), board, review / case_id)
        print(f"{case_id}: {attempt} -> {review / case_id}")


if __name__ == "__main__":
    main()
