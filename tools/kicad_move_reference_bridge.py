"""Crash-contained KiCad bridge that moves one footprint reference field."""

from __future__ import annotations

import argparse
from pathlib import Path

import wx

_ASSERT_APP = wx.App.Get() or wx.App(False)
_ASSERT_APP.SetAssertMode(wx.APP_ASSERT_EXCEPTION)
wx.Image.CleanUpHandlers()

import pcbnew  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("reference")
    parser.add_argument("dx_mm", type=float)
    parser.add_argument("dy_mm", type=float)
    args = parser.parse_args()
    board = pcbnew.LoadBoard(str(args.source.resolve()))
    footprint = next(
        (item for item in board.GetFootprints() if item.GetReference() == args.reference),
        None,
    )
    if footprint is None:
        raise ValueError(f"footprint reference not found: {args.reference}")
    field = footprint.Reference()
    position = field.GetPosition()
    field.SetPosition(
        pcbnew.VECTOR2I(
            position.x + pcbnew.FromMM(args.dx_mm),
            position.y + pcbnew.FromMM(args.dy_mm),
        )
    )
    args.candidate.parent.mkdir(parents=True, exist_ok=True)
    pcbnew.SaveBoard(str(args.candidate.resolve()), board)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
