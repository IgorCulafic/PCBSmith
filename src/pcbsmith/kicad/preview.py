"""Editor-style 2D review plot for generated boards.

Draws both copper layers, pads, vias, references, and net names to a PNG so a
model (or a human without KiCad open) can visually review the layout. This is
the machine-review counterpart of the pcbnew editor view.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pcbsmith.kicad.board import (
    FOOTPRINT_LIBRARY,
    BoardGenerationError,
    BoardLayout,
    BoardNetlist,
    compute_board_layout,
)

SCALE_PX_PER_MM = 28
IMAGE_MARGIN_PX = 60

BACKGROUND = (24, 30, 44)
BOARD_EDGE = (220, 220, 220)
F_CU = (200, 52, 52)
B_CU = (66, 110, 210)
PAD_FILL = (214, 60, 60)
THT_HOLE = (16, 18, 26)
VIA_FILL = (222, 178, 44)
SILK = (232, 224, 160)
REF_TEXT = (240, 232, 150)
NET_TEXT = (235, 235, 235)
LANE_TEXT = (150, 190, 255)


def plot_board_review(
    netlist: BoardNetlist,
    output: Path,
    power_net_names: frozenset[str] = frozenset(),
) -> Path:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise BoardGenerationError(
            "Pillow is required for board review plots. "
            "Install the preview extra: pip install 'pcbsmith[preview]'."
        ) from exc

    layout = compute_board_layout(netlist, power_net_names)
    width_px = int(layout.width_mm * SCALE_PX_PER_MM) + 2 * IMAGE_MARGIN_PX
    height_px = int(layout.height_mm * SCALE_PX_PER_MM) + 2 * IMAGE_MARGIN_PX
    image = Image.new("RGB", (width_px, height_px), BACKGROUND)
    draw = ImageDraw.Draw(image)
    font = _font(16)
    small_font = _font(12)

    def px(x_mm: float, y_mm: float) -> tuple[float, float]:
        return (
            IMAGE_MARGIN_PX + x_mm * SCALE_PX_PER_MM,
            IMAGE_MARGIN_PX + y_mm * SCALE_PX_PER_MM,
        )

    draw.rectangle(
        (*px(0, 0), *px(layout.width_mm, layout.height_mm)),
        outline=BOARD_EDGE,
        width=3,
    )

    _draw_tracks(draw, layout, "B.Cu", B_CU, px)
    _draw_lane_labels(draw, layout, small_font, px)
    _draw_tracks(draw, layout, "F.Cu", F_CU, px)
    _draw_footprints(draw, netlist, layout, font, small_font, px)
    _draw_vias(draw, layout, px)

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output)
    return output


def _draw_tracks(
    draw: Any,
    layout: BoardLayout,
    layer: str,
    color: tuple[int, int, int],
    px: Any,
) -> None:
    for segment in layout.segments:
        if segment.layer == layer:
            draw.line(
                (*px(segment.x1, segment.y1), *px(segment.x2, segment.y2)),
                fill=color,
                width=max(2, int(segment.width_mm * SCALE_PX_PER_MM)),
            )


def _draw_lane_labels(draw: Any, layout: BoardLayout, font: Any, px: Any) -> None:
    for segment in layout.segments:
        if segment.layer != "B.Cu":
            continue
        mid_x = (segment.x1 + segment.x2) / 2
        x, y = px(mid_x, segment.y1)
        draw.text((x, y - 16), segment.net_name, fill=LANE_TEXT, font=font, anchor="mm")


def _draw_vias(draw: Any, layout: BoardLayout, px: Any) -> None:
    radius = 0.35 * SCALE_PX_PER_MM
    hole = 0.15 * SCALE_PX_PER_MM
    for via in layout.vias:
        x, y = px(via.x, via.y)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=VIA_FILL)
        draw.ellipse((x - hole, y - hole, x + hole, y + hole), fill=BACKGROUND)


def _draw_footprints(
    draw: Any,
    netlist: BoardNetlist,
    layout: BoardLayout,
    font: Any,
    small_font: Any,
    px: Any,
) -> None:
    pad_nets = {
        (reference, pin): net.name
        for net in netlist.nets
        for reference, pin in net.nodes
    }
    row_y = layout.parts_row_y_mm
    for component, anchor_x in layout.placements:
        spec = FOOTPRINT_LIBRARY[component.footprint]
        body_rect = spec.silk_rect or spec.fab_rect
        x1, y1, x2, y2 = body_rect
        draw.rectangle(
            (
                *px(anchor_x + x1, row_y + y1),
                *px(anchor_x + x2, row_y + y2),
            ),
            outline=SILK,
            width=2,
        )
        for pad in spec.pads:
            pad_x = anchor_x + pad.x_mm
            pad_y = row_y + pad.y_mm
            half_w = pad.width_mm / 2
            half_h = pad.height_mm / 2
            if pad.kind == "smd":
                draw.rectangle(
                    (
                        *px(pad_x - half_w, pad_y - half_h),
                        *px(pad_x + half_w, pad_y + half_h),
                    ),
                    fill=PAD_FILL,
                )
            else:
                cx, cy = px(pad_x, pad_y)
                ring = half_w * SCALE_PX_PER_MM
                hole = (pad.drill_mm / 2) * SCALE_PX_PER_MM
                draw.ellipse((cx - ring, cy - ring, cx + ring, cy + ring), fill=PAD_FILL)
                draw.ellipse((cx - hole, cy - hole, cx + hole, cy + hole), fill=THT_HOLE)
            net_name = pad_nets.get((component.reference, pad.name))
            if net_name:
                label_x, label_y = px(pad_x, pad_y + half_h)
                draw.text(
                    (label_x, label_y + 10),
                    net_name,
                    fill=NET_TEXT,
                    font=small_font,
                    anchor="ma",
                )
        center_x = anchor_x + (spec.x_min + spec.x_max) / 2
        ref_x, ref_y = px(center_x, row_y + spec.y_min - 1.5)
        draw.text(
            (ref_x, ref_y),
            component.reference,
            fill=REF_TEXT,
            font=font,
            anchor="ms",
        )


def _font(size: int) -> Any:
    from PIL import ImageFont

    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()
