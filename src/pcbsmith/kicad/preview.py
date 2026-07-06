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
    SilkLine,
    compute_board_layout,
    placement_rotation,
    placement_y,
    rotate_offset,
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
    sensitive_net_names: frozenset[str] = frozenset(),
    layout: BoardLayout | None = None,
) -> Path:
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise BoardGenerationError(
            "Pillow is required for board review plots. "
            "Install the preview extra: pip install 'pcbsmith[preview]'."
        ) from exc

    if layout is None:
        layout = compute_board_layout(netlist, power_net_names, sensitive_net_names)
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
    for component, anchor_x in layout.placements:
        row_y = placement_y(layout, component.reference)
        rotation = placement_rotation(layout, component.reference)
        spec = FOOTPRINT_LIBRARY[component.footprint]
        body_rect = spec.silk_rect or spec.fab_rect
        bx1, by1 = rotate_offset(body_rect[0], body_rect[1], rotation)
        bx2, by2 = rotate_offset(body_rect[2], body_rect[3], rotation)
        x1, x2 = sorted((bx1, bx2))
        y1, y2 = sorted((by1, by2))
        draw.rectangle(
            (
                *px(anchor_x + x1, row_y + y1),
                *px(anchor_x + x2, row_y + y2),
            ),
            outline=SILK,
            width=2,
        )
        for mark in spec.silk_marks:
            if isinstance(mark, SilkLine):
                mx1, my1 = rotate_offset(mark.x1, mark.y1, rotation)
                mx2, my2 = rotate_offset(mark.x2, mark.y2, rotation)
                draw.line(
                    (
                        *px(anchor_x + mx1, row_y + my1),
                        *px(anchor_x + mx2, row_y + my2),
                    ),
                    fill=SILK,
                    width=3,
                )
            else:
                mx, my = rotate_offset(mark.x, mark.y, rotation)
                tx, ty = px(anchor_x + mx, row_y + my)
                draw.text((tx, ty), mark.text, fill=SILK, font=font, anchor="mm")
        for pad in spec.pads:
            pad_dx, pad_dy = rotate_offset(pad.x_mm, pad.y_mm, rotation)
            pad_x = anchor_x + pad_dx
            pad_y = row_y + pad_dy
            half_w = pad.width_mm / 2
            half_h = pad.height_mm / 2
            if rotation % 180:
                half_w, half_h = half_h, half_w
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


def plot_assembly_view(
    netlist: BoardNetlist,
    layout: BoardLayout,
    output: Path,
) -> Path:
    """Assembly diagram: outline, part bodies, EVERY reference (including
    silk-hidden ones), and a value table. This restores the hand-assembly
    information the art boards trade away by hiding references on silk
    (hardening plan 3.3)."""
    try:
        from PIL import Image, ImageDraw
    except ImportError as exc:
        raise BoardGenerationError(
            "Pillow is required for assembly plots. "
            "Install the preview extra: pip install 'pcbsmith[preview]'."
        ) from exc

    from pcbsmith.kicad.board import (
        FOOTPRINT_LIBRARY,
        placement_rotation,
        placement_y,
        rotate_offset,
    )
    from pcbsmith.kicad.shaped_board import back_offset

    table_rows = sorted(
        (component.reference, component.value, component.footprint.split(":")[-1])
        for component, _x in layout.placements
    )
    table_width_px = 460
    row_height_px = 20
    board_width_px = int(layout.width_mm * SCALE_PX_PER_MM) + 2 * IMAGE_MARGIN_PX
    height_px = max(
        int(layout.height_mm * SCALE_PX_PER_MM) + 2 * IMAGE_MARGIN_PX,
        (len(table_rows) + 3) * row_height_px + 2 * IMAGE_MARGIN_PX,
    )
    image = Image.new(
        "RGB", (board_width_px + table_width_px, height_px), BACKGROUND
    )
    draw = ImageDraw.Draw(image)
    font = _font(15)
    small_font = _font(12)

    def px(x_mm: float, y_mm: float) -> tuple[float, float]:
        return (
            IMAGE_MARGIN_PX + x_mm * SCALE_PX_PER_MM,
            IMAGE_MARGIN_PX + y_mm * SCALE_PX_PER_MM,
        )

    if layout.outline:
        draw.polygon(
            [px(x, y) for x, y in layout.outline], outline=BOARD_EDGE, width=3
        )
    else:
        draw.rectangle(
            (*px(0, 0), *px(layout.width_mm, layout.height_mm)),
            outline=BOARD_EDGE,
            width=3,
        )

    front_body = (120, 200, 140)
    back_body = (110, 150, 235)
    for component, anchor_x in layout.placements:
        reference = component.reference
        spec = FOOTPRINT_LIBRARY[component.footprint]
        rotation = placement_rotation(layout, reference)
        anchor_y = placement_y(layout, reference)
        flipped = reference in layout.part_flip
        x1, y1, x2, y2 = spec.fab_rect
        corners = ((x1, y1), (x2, y1), (x2, y2), (x1, y2))
        polygon = []
        for corner in corners:
            if flipped:
                dx, dy = back_offset(corner, rotation)
            else:
                dx, dy = rotate_offset(corner[0], corner[1], rotation)
            polygon.append(px(anchor_x + dx, anchor_y + dy))
        color = back_body if flipped else front_body
        draw.polygon(polygon, outline=color, width=2)
        center = px(anchor_x, anchor_y)
        draw.text(center, reference, fill=REF_TEXT, font=font, anchor="mm")

    table_x = board_width_px + 10
    draw.text(
        (table_x, IMAGE_MARGIN_PX - row_height_px),
        "REF  VALUE  FOOTPRINT   (blue = back side)",
        fill=NET_TEXT,
        font=font,
    )
    for index, (reference, value, footprint) in enumerate(table_rows):
        flipped = reference in layout.part_flip
        draw.text(
            (table_x, IMAGE_MARGIN_PX + index * row_height_px),
            f"{reference:<5} {value:<18} {footprint}",
            fill=back_body if flipped else NET_TEXT,
            font=small_font,
        )
    image.save(output)
    return output
