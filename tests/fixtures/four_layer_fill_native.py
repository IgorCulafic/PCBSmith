"""Native synthetic check-system fixtures, never production board generators.

Run only under KiCad's Python. Each variant changes one deliberate failure input.
"""

import argparse
import json
from pathlib import Path

import pcbnew


def make_fixture(path: Path, variant: str) -> None:
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(4)
    nets = {}
    for name in ("GND", "OTHER"):
        net = pcbnew.NETINFO_ITEM(board, name)
        board.Add(net)
        nets[name] = net

    def point(x, y):
        return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))

    def pad(ref, x, y, net="GND", pth=True, number="1", parent=None):
        footprint = parent or pcbnew.FOOTPRINT(board)
        if parent is None:
            footprint.SetReference(ref)
            footprint.SetValue("SOFTWARE FIXTURE")
            footprint.SetPosition(point(x, y))
            board.Add(footprint)
        item = pcbnew.PAD(footprint)
        item.SetNumber(number)
        item.SetAttribute(pcbnew.PAD_ATTRIB_PTH if pth else pcbnew.PAD_ATTRIB_SMD)
        item.SetShape(pcbnew.PAD_SHAPE_CIRCLE)
        item.SetSize(point(2, 2))
        layers = pcbnew.LSET.AllCuMask() if pth else pcbnew.LSET()
        if not pth:
            layers.AddLayer(pcbnew.F_Cu)
        item.SetLayerSet(layers)
        if pth:
            item.SetDrillSize(point(0.8, 0.8))
        item.SetNet(nets[net])
        item.SetPosition(point(x, y))
        footprint.Add(item)
        return item

    def track(a, b, layer, net="GND"):
        item = pcbnew.PCB_TRACK(board)
        item.SetStart(point(*a))
        item.SetEnd(point(*b))
        item.SetWidth(pcbnew.FromMM(0.5))
        item.SetLayer(layer)
        item.SetNet(nets[net])
        board.Add(item)

    def via(x, y, net="GND", remove=False):
        item = pcbnew.PCB_VIA(board)
        item.SetPosition(point(x, y))
        item.SetWidth(pcbnew.FromMM(1.4))
        item.SetDrill(pcbnew.FromMM(0.8))
        item.SetViaType(pcbnew.VIATYPE_THROUGH)
        item.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        item.SetNet(nets[net])
        if remove:
            item.SetRemoveUnconnected(True)
        board.Add(item)
        return item

    corners = [(0, 0), (60, 0), (60, 40), (0, 40)]
    for start, end in zip(corners, corners[1:] + corners[:1], strict=True):
        edge = pcbnew.PCB_SHAPE(board)
        edge.SetShape(pcbnew.SHAPE_T_SEGMENT)
        edge.SetStart(point(*start))
        edge.SetEnd(point(*end))
        edge.SetLayer(pcbnew.Edge_Cuts)
        edge.SetWidth(pcbnew.FromMM(0.05))
        board.Add(edge)

    pad("SRC", 5, 5, pth=False)
    track((5, 5), (10, 5), pcbnew.F_Cu)
    track((10, 5), (15, 5), pcbnew.F_Cu)
    if variant != "broken_chain":
        via(15, 5)
    track((15, 5), (20, 5), pcbnew.In2_Cu)
    track((20, 5), (30, 5), pcbnew.In2_Cu)
    joined = pad("LOAD", 40, 10)
    pad("LOAD", 40, 15, parent=joined.GetParentFootprint())  # duplicate logical pad number
    pad("FOREIGN", 45, 20, "OTHER")
    pad("NOZONE", 35, 20).SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_NONE)
    removed = pad("REMOVED", 50, 15)
    removed.SetUnconnectedLayerMode(pcbnew.UNCONNECTED_LAYER_MODE_START_END_ONLY)
    removed.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_NONE)
    via(50, 25, "OTHER")
    hole = pad("HOLE", 35, 25)
    hole.SetAttribute(pcbnew.PAD_ATTRIB_NPTH)
    hole.SetDrillSize(point(2, 2))
    hole.SetNetCode(0)
    for layer in (pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.B_Cu):
        zone = pcbnew.ZONE(board)
        zone.SetLayer(layer)
        zone.SetNet(nets["GND"])
        zone.SetLocalClearance(pcbnew.FromMM(0.3))
        zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        zone.SetMinThickness(pcbnew.FromMM(0.2))
        zone.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
        zone.SetThermalReliefGap(pcbnew.FromMM(0.4))
        zone.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.4))
        outline = zone.Outline()
        outline.NewOutline()
        for x, y in ((25, 2), (55, 2), (55, 35), (25, 35)):
            outline.Append(point(x, y))
        if variant == "zone_hole" and layer == pcbnew.In1_Cu:
            outline.NewHole(0)
            for x, y in ((26, 22), (30, 22), (30, 28), (26, 28)):
                outline.Append(point(x, y), 0, 0)
        board.Add(zone)

    if variant in {
        "island",
        "zone_overlap",
        "zone_gap",
        "zone_layer_gap",
        "zone_hole",
        "orphan_cluster",
        "fragmented",
        "fragmented_load",
        "fragmented_bridge",
    }:
        floating = pcbnew.ZONE(board)
        floating.SetLayer(pcbnew.In1_Cu)
        floating.SetNet(nets["GND"])
        floating.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        floating.SetLocalClearance(pcbnew.FromMM(0.3))
        floating.SetMinThickness(pcbnew.FromMM(0.2))
        floating.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
        outline = floating.Outline()
        outline.NewOutline()
        bounds = (
            ((27, 23), (29, 23), (29, 27), (27, 27))
            if variant == "zone_hole"
            else (
                (20, 22),
                (27 if variant == "zone_overlap" else 24, 22),
                (27 if variant == "zone_overlap" else 24, 28),
                (20, 28),
            )
            if variant in {"zone_overlap", "zone_gap"}
            else ((3, 12), (20, 12), (20, 18), (3, 18))
        )
        for x, y in bounds:
            outline.Append(point(x, y))
        board.Add(floating)
        if variant == "orphan_cluster":
            other = floating.Duplicate(False)
            other.Move(point(0, 3))
            board.Add(other)
        if variant.startswith("fragmented"):
            # Clearance from this foreign-net track cuts one declared zone into two regions.
            track((12, 11), (12, 19), pcbnew.In1_Cu, "OTHER")
            first = pad("FRAGMENT", 5, 15)
            if variant != "fragmented":
                pad("FRAGMENT", 17, 15, parent=first.GetParentFootprint())
            if variant == "fragmented_bridge":
                track((5, 15), (17, 15), pcbnew.B_Cu)
        if variant == "zone_layer_gap":
            # Same projection on B.Cu reaches the main plane; In1.Cu has no barrel to it.
            second = pcbnew.ZONE(board)
            second.SetLayer(pcbnew.B_Cu)
            second.SetNet(nets["GND"])
            second.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
            second.SetLocalClearance(pcbnew.FromMM(0.3))
            second.SetMinThickness(pcbnew.FromMM(0.2))
            second.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
            outline = second.Outline()
            outline.NewOutline()
            for x, y in bounds:
                outline.Append(point(x, y))
            board.Add(second)
            track((10, 13), (30, 13), pcbnew.B_Cu)

    if variant in {"thermal_good", "thermal_starved", "thermal_zero"}:
        # One isolated inner-layer test plane; the pad itself is its declared source.
        tp = pad("THERMAL", 12, 28 if variant == "thermal_good" else 21.5)
        tp.SetLocalZoneConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        zone = pcbnew.ZONE(board)
        zone.SetLayer(pcbnew.In1_Cu)
        zone.SetNet(nets["GND"])
        zone.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
        zone.SetLocalClearance(pcbnew.FromMM(0.3))
        zone.SetMinThickness(pcbnew.FromMM(0.2))
        zone.SetThermalReliefGap(pcbnew.FromMM(0.4))
        zone.SetThermalReliefSpokeWidth(pcbnew.FromMM(0.4))
        zone.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
        outline = zone.Outline()
        outline.NewOutline()
        for x, y in ((3, 21), (21, 21), (21, 36), (3, 36)):
            outline.Append(point(x, y))
        board.Add(zone)
        if variant == "thermal_zero":
            tp.SetLocalThermalSpokeWidthOverride(pcbnew.FromMM(0.05))

    if variant == "unsupported_copper":
        graphic = pcbnew.PCB_SHAPE(board)
        graphic.SetShape(pcbnew.SHAPE_T_SEGMENT)
        graphic.SetStart(point(2, 2))
        graphic.SetEnd(point(3, 2))
        graphic.SetWidth(pcbnew.FromMM(0.5))
        graphic.SetLayer(pcbnew.F_Cu)
        board.Add(graphic)
    if variant == "unsupported_jumpers":
        joined.GetParentFootprint().SetDuplicatePadNumbersAreJumpers(True)

    path.parent.mkdir(parents=True, exist_ok=True)
    assert not path.exists(), "retain previous synthetic fixture"
    pcbnew.SaveBoard(str(path), board)
    path.with_suffix(".kicad_pro").write_text(
        json.dumps(
            {
                "board_design_settings": {
                    "rule_severities": {"starved_thermal": "error"},
                    "drc_exclusions": [],
                    "rules": {
                        "min_clearance": 0.2,
                        "min_connection": 0.2,
                        "min_through_hole_diameter": 0.3,
                        "min_via_annular_width": 0.15,
                    },
                }
            }
        )
    )
    path.with_suffix(".kicad_dru").write_text(
        "(version 1)\n(rule fully_spoked_pads (constraint min_resolved_spokes 4))\n"
    )
    path.with_suffix(".fixture.json").write_text(
        json.dumps(
            {
                "variant": variant,
                "purpose": "synthetic native check qualification only",
                "pads": {
                    f"pad:{p.m_Uuid.AsString()}": (
                        f"{p.GetParentFootprint().GetReference()}.{p.GetNumber()}"
                    )
                    for p in board.GetPads()
                },
                "source_pads": [
                    f"pad:{p.m_Uuid.AsString()}"
                    for p in board.GetPads()
                    if p.GetParentFootprint().GetReference() in {"SRC", "THERMAL"}
                    or (
                        p.GetParentFootprint().GetReference() == "FRAGMENT"
                        and p.GetPosition().x == pcbnew.FromMM(5)
                    )
                ],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "variant",
        choices=[
            "connected",
            "broken_chain",
            "island",
            "zone_overlap",
            "zone_gap",
            "zone_layer_gap",
            "zone_hole",
            "orphan_cluster",
            "fragmented",
            "fragmented_load",
            "fragmented_bridge",
            "thermal_good",
            "thermal_starved",
            "thermal_zero",
            "unsupported_copper",
            "unsupported_jumpers",
        ],
    )
    args = parser.parse_args()
    make_fixture(args.output, args.variant)
