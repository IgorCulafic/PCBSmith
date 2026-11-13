"""Synthetic native reference-plane fixtures; never production board preparation."""

import json
import sys
from pathlib import Path

import pcbnew


def make_fixture(path, variant):
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(4)
    nets = {}
    for name in ("GND", "SIG", "OTHER"):
        net = pcbnew.NETINFO_ITEM(board, name)
        board.Add(net)
        nets[name] = net

    def xy(x, y):
        return pcbnew.VECTOR2I(pcbnew.FromMM(x), pcbnew.FromMM(y))

    def pad(ref, x, y, layer, net):
        fp = pcbnew.FOOTPRINT(board)
        fp.SetReference(ref)
        fp.SetPosition(xy(x, y))
        fp.SetLayer(layer)
        board.Add(fp)
        p = pcbnew.PAD(fp)
        p.SetNumber("1")
        p.SetAttribute(pcbnew.PAD_ATTRIB_SMD)
        p.SetShape(pcbnew.PAD_SHAPE_RECT)
        p.SetSize(xy(1, 1))
        layers = pcbnew.LSET()
        layers.AddLayer(layer)
        p.SetLayerSet(layers)
        p.SetNet(nets[net])
        p.SetPosition(xy(x, y))
        fp.Add(p)
        return p

    pad("J1", 10, 15, pcbnew.F_Cu, "SIG")
    pad("J2", 30, 15, pcbnew.B_Cu, "SIG")
    source = pad("G0", 10, 5, pcbnew.F_Cu, "GND")
    for a, b, layer in (((10, 15), (20, 15), pcbnew.F_Cu), ((20, 15), (30, 15), pcbnew.B_Cu)):
        t = pcbnew.PCB_TRACK(board)
        t.SetStart(xy(*a))
        t.SetEnd(xy(*b))
        t.SetWidth(pcbnew.FromMM(0.3))
        t.SetLayer(layer)
        t.SetNet(nets["SIG"])
        board.Add(t)
    positions = [
        (20, 15, "SIG"),
        (
            20,
            20 if variant == "distant_stitch" else 16.5,
            "OTHER" if variant == "wrong_stitch" else "GND",
        ),
    ]
    if variant != "orphan_reference":
        positions.append((10, 5, "GND"))
    for x, y, net in positions:
        v = pcbnew.PCB_VIA(board)
        v.SetPosition(xy(x, y))
        v.SetWidth(pcbnew.FromMM(0.8))
        v.SetDrill(pcbnew.FromMM(0.4))
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetLayerPair(pcbnew.F_Cu, pcbnew.B_Cu)
        v.SetNet(nets[net])
        board.Add(v)
    corners = [(0, 0), (60, 0), (60, 40), (0, 40)]
    for start, end in zip(corners, corners[1:] + corners[:1], strict=True):
        edge = pcbnew.PCB_SHAPE(board)
        edge.SetShape(pcbnew.SHAPE_T_SEGMENT)
        edge.SetStart(xy(*start))
        edge.SetEnd(xy(*end))
        edge.SetLayer(pcbnew.Edge_Cuts)
        edge.SetWidth(pcbnew.FromMM(0.05))
        board.Add(edge)
    for layer in (pcbnew.In1_Cu, pcbnew.In2_Cu):
        zone = pcbnew.ZONE(board)
        zone.SetLayer(layer)
        zone.SetNet(nets["GND"])
        zone.SetLocalClearance(pcbnew.FromMM(0.2))
        zone.SetMinThickness(pcbnew.FromMM(0.2))
        zone.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        zone.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_NEVER)
        outline = zone.Outline()
        outline.NewOutline()
        for x, y in ((1, 1), (59, 1), (59, 39), (1, 39)):
            outline.Append(xy(x, y))
        hole = None
        if variant == "void" and layer == pcbnew.In1_Cu:
            hole = ((14, 14), (16, 14), (16, 16), (14, 16))
        if variant == "disconnected_stitch" and layer == pcbnew.In2_Cu:
            hole = ((19.4, 15.9), (20.6, 15.9), (20.6, 17.1), (19.4, 17.1))
        if hole:
            outline.NewHole(0)
            for x, y in hole:
                outline.Append(xy(x, y), 0, 0)
        board.Add(zone)
    assert not path.exists()
    pcbnew.SaveBoard(str(path), board)
    path.with_suffix(".kicad_pro").write_text(json.dumps({"board_design_settings": {}}))
    path.with_suffix(".policy.json").write_text(
        json.dumps(
            {
                "schema_id": "pcbsmith-native-adjacent-reference-policy-v1",
                "layer_references": {"F.Cu": ["In1.Cu", "GND"], "B.Cu": ["In2.Cu", "GND"]},
                "source_pad_ids": {"GND": ["pad:" + source.m_Uuid.AsString()]},
                "maximum_stitch_distance_mm": "2",
                "allowed_transition_void_half_size_mm": None
                if variant == "no_void_allowance"
                else "0.8",
                "rationale": "Synthetic geometry qualification: 0.8 mm via, 0.2 mm plane "
                "clearance, bounded 0.8 mm transition box; no SI claim.",
            }
        )
    )


if __name__ == "__main__":
    make_fixture(Path(sys.argv[1]), sys.argv[2])
