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
    return f"pad:{pad.m_Uuid.AsString()}"


def _item_id(item: pcbnew.BOARD_CONNECTED_ITEM) -> str:
    if isinstance(item, pcbnew.PAD):
        return _pad_id(item)
    return f"{type(item).__name__}:{item.m_Uuid.AsString()}"


def _region_shape(fills: pcbnew.SHAPE_POLY_SET, region_index: int) -> pcbnew.SHAPE_POLY_SET:
    region = pcbnew.SHAPE_POLY_SET()
    region.AddOutline(fills.Outline(region_index))
    for hole_index in range(int(fills.HoleCount(region_index))):
        region.AddHole(fills.Hole(region_index, hole_index), 0)
    return region


def _connection_mode(pad: pcbnew.PAD, zone: pcbnew.ZONE, layer: int) -> str:
    """Resolve native footprint/pad inheritance; custom-rule modes are checked separately."""

    layer_override = int(pad.GetZoneLayerOverride(layer))
    if layer_override == 2:  # ZLO_FORCE_NO_ZONE_CONNECTION
        return "none"
    if layer_override not in (0, 1):  # ZLO_NONE or ZLO_FORCE_FLASHED; still resolve mode.
        return "unverified"

    local_connection = int(pad.GetZoneConnectionOverrides())
    mode = int(zone.GetPadConnection()) if local_connection == -1 else local_connection
    if mode == int(pcbnew.ZONE_CONNECTION_THERMAL):
        return "thermal"
    if mode == int(pcbnew.ZONE_CONNECTION_THT_THERMAL):
        return "thermal" if pad.GetAttribute() == pcbnew.PAD_ATTRIB_PTH else "solid"
    if mode == int(pcbnew.ZONE_CONNECTION_NONE):
        return "none"
    if mode == int(pcbnew.ZONE_CONNECTION_FULL):
        return "solid"
    return "unverified"


def _flashed(item, layer):
    if isinstance(item, (pcbnew.PAD, pcbnew.PCB_VIA)):
        return bool(item.FlashLayer(layer))
    return bool(item.IsOnLayer(layer))


def _points(chain):
    return [[int(chain.CPoint(i).x), int(chain.CPoint(i).y)] for i in range(chain.PointCount())]


def _qualified_items(board):
    """Reject unqualified conductors before asserting a complete contact inventory."""

    layers = tuple(board.GetEnabledLayers().CuStack())
    graphics = list(board.GetDrawings())
    for footprint in board.GetFootprints():
        graphics.extend(footprint.GraphicalItems())
        if footprint.IsNetTie() or footprint.GetDuplicatePadNumbersAreJumpers():
            raise ValueError("net ties and logical jumper pads require separate qualification")
        # This SWIG vector is opaque; its board serialization is checked below.
    if any(item.IsOnCopperLayer() for item in graphics):
        raise ValueError("copper graphics are outside the complete fill-contact scope")
    items = []
    for item in (*tuple(board.GetPads()), *tuple(board.GetTracks())):
        if isinstance(item, pcbnew.PAD):
            if item.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
                continue
            if item.GetAttribute() not in (pcbnew.PAD_ATTRIB_SMD, pcbnew.PAD_ATTRIB_PTH):
                raise ValueError("pad plating type is outside the fill-contact scope")
            if item.Padstack().Mode() != pcbnew.PADSTACK.MODE_NORMAL:
                raise ValueError("custom pad stacks require separate contact qualification")
            if any(item.GetShape(layer) == pcbnew.PAD_SHAPE_CUSTOM for layer in layers):
                raise ValueError("custom pad shapes require separate contact qualification")
            if (
                item.GetAttribute() == pcbnew.PAD_ATTRIB_SMD
                and sum(item.IsOnLayer(layer) for layer in layers) != 1
            ):
                raise ValueError("SMD pad must occupy exactly one copper layer")
        if isinstance(item, pcbnew.PCB_VIA):
            if item.GetViaType() != pcbnew.VIATYPE_THROUGH:
                raise ValueError("only ordinary through vias are qualified for fill contacts")
            if item.Padstack().Mode() != pcbnew.PADSTACK.MODE_NORMAL:
                raise ValueError("custom via stacks require separate contact qualification")
        if isinstance(item, (pcbnew.PAD, pcbnew.PCB_VIA)) and any(
            item.IsBackdrilledOrPostMachined(layer) for layer in layers
        ):
            raise ValueError("machined barrels require separate contact qualification")
        if item.GetNetCode() > 0:
            items.append(item)
    return tuple(items)


def _item_components(connectivity, items):
    """Use native track/pad/via connectivity; never query a multi-region parent zone."""

    inventory = {_item_id(item): item for item in items}
    # GetConnectedItems can return a PCB_TRACK proxy for a PCB_VIA/PCB_ARC.
    # Resolve the physical UUID against the typed board inventory, not proxy class names.
    by_uuid = {item.m_Uuid.AsString(): identity for identity, item in inventory.items()}
    seen = set()
    components = []
    for identity, item in sorted(inventory.items()):
        if identity in seen:
            continue
        connected = {identity}
        for other in connectivity.GetConnectedItems(item, pcbnew.EXCLUDE_ZONES):
            other_id = by_uuid.get(other.m_Uuid.AsString())
            if other_id is None:
                raise ValueError("native connectivity returned unqualified copper")
            connected.add(other_id)
        if connected - inventory.keys() or connected & seen:
            raise ValueError("native non-zone components do not partition physical copper")
        if any(inventory[i].GetNetCode() != item.GetNetCode() for i in connected):
            raise ValueError("native component crosses net identity")
        seen.update(connected)
        components.append(
            {
                "net_name": str(item.GetNetname()),
                "item_ids": sorted(connected),
                "pad_ids": sorted(i for i in connected if i.startswith("pad:")),
            }
        )
    return components


def _complete_region_contacts(records, shapes, components):
    """Join only actual same-layer filled copper, then traverse native item components."""

    adjacency = {r["region_id"]: set() for r in records}
    item_nodes = {}
    pad_nodes = {}
    for index, component in enumerate(components):
        adjacency[index] = set()
        pad_nodes[index] = component["pad_ids"]
        for item in component["item_ids"]:
            item_nodes[item] = index
    links = []
    for index, record in enumerate(records):
        identity = record["region_id"]
        for item in record["direct_contact_ids"]:
            node = item_nodes[item]
            adjacency[identity].add(node)
            adjacency[node].add(identity)
        for other in records[:index]:
            target = other["region_id"]
            if (record["layer"], record["net_name"]) != (other["layer"], other["net_name"]):
                continue
            if shapes[identity].Collide(shapes[target]):
                adjacency[identity].add(target)
                adjacency[target].add(identity)
                links.append(sorted((identity, target)))
    reached = {}
    for record in records:
        identity = record["region_id"]
        if identity in reached:
            continue
        pending = [identity]
        visited = set()
        pads = set()
        while pending:
            node = pending.pop()
            if node in visited:
                continue
            visited.add(node)
            pads.update(pad_nodes.get(node, ()))
            pending.extend(adjacency[node] - visited)
        for node in visited:
            reached[node] = sorted(pads)
    for record in records:
        record["reachable_pad_ids"] = reached[record["region_id"]]
    return {
        "authority": "native-copper-items-and-filled-regions-v1",
        "item_components": components,
        "region_contacts": sorted(links),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("board", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    board_path = args.board.resolve()
    board_sha = hashlib.sha256(board_path.read_bytes()).hexdigest()
    if "(jumper_pad_groups" in board_path.read_text(encoding="utf-8"):
        raise ValueError("logical jumper groups require separate contact qualification")
    board = pcbnew.LoadBoard(str(board_path))
    connectivity = board.GetConnectivity()
    records: list[dict[str, object]] = []
    region_shapes = {}
    pad_zone_contacts = []
    items = _qualified_items(board)
    components = _item_components(connectivity, items)
    custom_rules = board_path.with_suffix(".kicad_dru")
    custom_connection_rules = (
        custom_rules.is_file() and "zone_connection" in custom_rules.read_text()
    )
    for zone_index, zone in enumerate(board.Zones()):
        if zone.GetIsRuleArea():
            raise ValueError("rule-area zones are outside the qualified fill-contact scope")
        if len(tuple(zone.GetLayerSet().CuStack())) != 1:
            raise ValueError("fill-contact qualification requires one copper layer per zone")
        if zone.GetNetCode() <= 0:
            raise ValueError("filled copper requires an explicit net identity")
        layer = zone.GetLayer()
        zone_uuid = str(zone.m_Uuid.AsString())
        zone_id = f"zone:{zone_uuid}"
        zone_contacts = []
        for pad in board.GetPads():
            if (
                pad.GetNetCode() != zone.GetNetCode()
                or not pad.IsOnLayer(layer)
                or pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH
                or not zone.Outline().Collide(pad.GetEffectiveShape(layer))
            ):
                continue
            mode = _connection_mode(pad, zone, layer)
            if custom_connection_rules:
                mode = "unverified"
            elif not pad.FlashLayer(layer):
                mode = "none"
            contact = {
                "contact_id": f"{zone_id}:{board.GetLayerName(layer)}:{_pad_id(pad)}",
                "pad_id": _pad_id(pad),
                "logical_pad_id": f"{pad.GetParentFootprint().GetReference()}.{pad.GetNumber()}",
                "zone_id": zone_id,
                "layer": str(board.GetLayerName(layer)),
                "mode": mode,
                "flashed": bool(pad.FlashLayer(layer)),
                "contacting_region_ids": [],
            }
            zone_contacts.append(contact)
        pad_zone_contacts.extend(zone_contacts)
        if not zone.HasFilledPolysForLayer(layer):
            continue
        fills = zone.GetFilledPolysList(layer)
        outline_count = int(fills.OutlineCount())
        for region_index in range(outline_count):
            is_island = bool(zone.IsIsland(layer, region_index))
            region = _region_shape(fills, region_index)
            region.Unfracture()
            if region.OutlineCount() != 1:
                raise ValueError("native filled outline cannot be mapped to one polygon with holes")
            candidates = [
                item
                for item in items
                if item.GetNetCode() == zone.GetNetCode()
                and item.IsOnLayer(layer)
                and _flashed(item, layer)
                and region.Collide(item.GetEffectiveShape(layer))
            ]
            direct_contact_ids = tuple(sorted(_item_id(item) for item in candidates))
            direct_pads = tuple(
                sorted(_pad_id(item) for item in candidates if isinstance(item, pcbnew.PAD))
            )
            thermal_applicable: set[str] = set()
            thermal_unverified: set[str] = set()
            region_id = f"{zone_id}:filled:{region_index}"
            region_shapes[region_id] = region
            for contact in zone_contacts:
                if contact["pad_id"] in direct_pads:
                    contact["contacting_region_ids"].append(region_id)
                if contact["mode"] == "thermal":
                    thermal_applicable.add(contact["pad_id"])
                if contact["mode"] == "unverified":
                    thermal_unverified.add(contact["pad_id"])
            records.append(
                {
                    "region_id": region_id,
                    "zone_id": zone_id,
                    "zone_index": zone_index,
                    "region_index": region_index,
                    "net_name": str(zone.GetNetname()),
                    "layer": str(board.GetLayerName(layer)),
                    "is_island": is_island,
                    "direct_contact_ids": list(direct_contact_ids),
                    "connected_pad_ids": list(direct_pads),
                    "reachable_pad_ids": [],  # Populated by the complete region graph below.
                    "thermal_applicable_pad_ids": sorted(thermal_applicable),
                    "thermal_resolution_unverified_pad_ids": sorted(thermal_unverified),
                    "pad_mapping_exact": True,
                    "pad_mapping_scope": "integer_effective_shape_contact_graph",
                    "thermal_spoke_status": "unverified",
                    "outline_nm": _points(region.Outline(0)),
                    "holes_nm": [_points(region.Hole(0, h)) for h in range(region.HoleCount(0))],
                }
            )
    payload = {
        "schema_id": "pcbsmith-kicad-final-fill-connectivity-observation-v1",
        "board_file": str(board_path),
        "board_sha256": board_sha,
        "kicad_version": pcbnew.GetBuildVersion(),
        "island_authority": "ZONE.IsIsland(layer, filled_outline_index)",
        "records": records,
        "pad_zone_contacts": pad_zone_contacts,
        "region_contact_graph": _complete_region_contacts(records, region_shapes, components),
        "qualification_boundary": (
            "Native same-net non-zone components joined through per-filled-outline integer "
            "contacts and same-layer zone overlaps. Empty reachable-pad sets prove isolated "
            "copper within the explicitly checked conductor scope. IsIsland is retained as "
            "a raw native flag, not a complete authority. No thermal-spoke, current-path "
            "length, ampacity or fabrication qualification is inferred."
        ),
    }
    if hashlib.sha256(board_path.read_bytes()).hexdigest() != board_sha:
        raise ValueError("native contact observation changed source board")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
