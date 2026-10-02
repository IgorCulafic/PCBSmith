"""Read-only KiCad pcbnew bridge for per-filled-outline island evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import wx

_ASSERT_APP = wx.App.Get() or wx.App(False)
_ASSERT_APP.SetAssertMode(wx.APP_ASSERT_EXCEPTION)
wx.Image.CleanUpHandlers()

import pcbnew  # noqa: E402


def _pad_id(pad: pcbnew.PAD) -> str:
    return f"{pad.GetParentFootprint().GetReference()}.{pad.GetNumber()}"


def _item_id(item: pcbnew.BOARD_CONNECTED_ITEM) -> str:
    if isinstance(item, pcbnew.PAD):
        return f"pad:{_pad_id(item)}"
    return f"{type(item).__name__}:{item.m_Uuid.AsString()}"


def _region_shape(
    fills: pcbnew.SHAPE_POLY_SET, region_index: int
) -> pcbnew.SHAPE_POLY_SET:
    region = pcbnew.SHAPE_POLY_SET()
    region.AddOutline(fills.Outline(region_index))
    for hole_index in range(int(fills.HoleCount(region_index))):
        region.AddHole(fills.Hole(region_index, hole_index), 0)
    return region


def _thermal_applicability(
    pad: pcbnew.PAD, zone: pcbnew.ZONE, layer: int
) -> tuple[bool, bool]:
    """Return (thermal_applicable, resolution_unverified) for one exact contact."""

    layer_override = int(pad.GetZoneLayerOverride(layer))
    if layer_override == 2:  # ZLO_FORCE_NO_ZONE_CONNECTION
        return False, False
    if layer_override == 1:  # ZLO_FORCE_FLASHED
        return False, False
    if layer_override != 0:
        return False, True

    local_connection = int(pad.GetLocalZoneConnection())
    mode = int(zone.GetPadConnection()) if local_connection == -1 else local_connection
    if mode == int(pcbnew.ZONE_CONNECTION_THERMAL):
        return True, False
    if mode == int(pcbnew.ZONE_CONNECTION_THT_THERMAL):
        return pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH, False
    if mode in (int(pcbnew.ZONE_CONNECTION_NONE), int(pcbnew.ZONE_CONNECTION_FULL)):
        return False, False
    return False, True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("board", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    board_path = args.board.resolve()
    board_sha = hashlib.sha256(board_path.read_bytes()).hexdigest()
    board = pcbnew.LoadBoard(str(board_path))
    connectivity = board.GetConnectivity()
    records: list[dict[str, object]] = []
    for zone_index, zone in enumerate(board.Zones()):
        layer = zone.GetLayer()
        if not zone.HasFilledPolysForLayer(layer):
            continue
        fills = zone.GetFilledPolysList(layer)
        outline_count = int(fills.OutlineCount())
        zone_uuid = str(zone.m_Uuid.AsString())
        for region_index in range(outline_count):
            is_island = bool(zone.IsIsland(layer, region_index))
            region = _region_shape(fills, region_index)
            candidates = [
                item
                for item in (*tuple(board.GetPads()), *tuple(board.GetTracks()))
                if item.GetNetCode() == zone.GetNetCode()
                and item.IsOnLayer(layer)
                and region.Collide(item.GetEffectiveShape(layer))
            ]
            direct_contact_ids = tuple(sorted(_item_id(item) for item in candidates))
            direct_pads = tuple(
                sorted(_pad_id(item) for item in candidates if isinstance(item, pcbnew.PAD))
            )
            reachable_pads: set[str] = set(direct_pads)
            thermal_applicable: set[str] = set()
            thermal_unverified: set[str] = set()
            for pad in (item for item in candidates if isinstance(item, pcbnew.PAD)):
                applicable, unresolved = _thermal_applicability(pad, zone, layer)
                if applicable:
                    thermal_applicable.add(_pad_id(pad))
                if unresolved:
                    thermal_unverified.add(_pad_id(pad))
            for item in candidates:
                reachable_pads.update(
                    _pad_id(connected)
                    for connected in (*tuple(connectivity.GetConnectedItems(item)), item)
                    if isinstance(connected, pcbnew.PAD)
                )
            records.append(
                {
                    "region_id": f"zone:{zone_uuid}:filled:{region_index}",
                    "zone_id": f"zone:{zone_uuid}",
                    "zone_index": zone_index,
                    "region_index": region_index,
                    "net_name": str(zone.GetNetname()),
                    "layer": str(board.GetLayerName(layer)),
                    "is_island": is_island,
                    "direct_contact_ids": [] if is_island else list(direct_contact_ids),
                    "connected_pad_ids": [] if is_island else list(direct_pads),
                    "reachable_pad_ids": [] if is_island else sorted(reachable_pads),
                    "thermal_applicable_pad_ids": (
                        [] if is_island else sorted(thermal_applicable)
                    ),
                    "thermal_resolution_unverified_pad_ids": (
                        [] if is_island else sorted(thermal_unverified)
                    ),
                    "pad_mapping_exact": True,
                    "pad_mapping_scope": (
                        "isolated_region_exact"
                        if is_island
                        else "integer_effective_shape_contact_graph"
                    ),
                    "thermal_spoke_status": "unverified",
                }
            )
    payload = {
        "schema_id": "pcbsmith-kicad-final-fill-connectivity-observation-v1",
        "board_file": str(board_path),
        "board_sha256": board_sha,
        "kicad_version": pcbnew.GetBuildVersion(),
        "island_authority": "ZONE.IsIsland(layer, filled_outline_index)",
        "records": records,
        "qualification_boundary": (
            "KiCad exact isolated-outline state plus per-outline integer effective-shape "
            "contacts to same-net pads, tracks, and vias. Thermal-spoke adequacy remains "
            "unverified."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
