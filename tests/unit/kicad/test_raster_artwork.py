from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

pytest.importorskip("cv2")
pytest.importorskip("shapely")
from PIL import Image, ImageDraw

from pcbsmith.kicad.raster_artwork import (
    SilkscreenArtworkRequest,
    trace_board_outline,
    trace_silkscreen_artwork,
)


def _image(path: Path) -> Path:
    image = Image.new("L", (100, 80), 255)
    draw = ImageDraw.Draw(image)
    draw.ellipse((10, 5, 90, 75), fill=0)
    draw.ellipse((42, 30, 58, 46), fill=255)
    image.save(path)
    return path


def test_outline_trace_is_scaled_deterministic_and_source_pinned(tmp_path: Path) -> None:
    source = _image(tmp_path / "outline.png")

    first = trace_board_outline(source, target_width_mm=50.0, margin_mm=2.0)
    second = trace_board_outline(source, target_width_mm=50.0, margin_mm=2.0)

    assert first == second
    assert first.source_sha256 == hashlib.sha256(source.read_bytes()).hexdigest()
    assert first.target_size_mm[0] == 50.0
    assert min(x for x, _y in first.outline) >= 2.0
    assert max(x for x, _y in first.outline) <= 48.0


def test_silkscreen_trace_preserves_outer_and_hole_contours_as_lines(tmp_path: Path) -> None:
    source = _image(tmp_path / "logo.png")

    artwork = trace_silkscreen_artwork(
        source,
        request=SilkscreenArtworkRequest(
            artwork_id="front-logo",
            target_width_mm=20.0,
            anchor_mm=(25.0, 15.0),
            rotation_deg=90,
            side="front",
        ),
        board_origin_mm=20.0,
    )

    assert artwork.contour_count == 2
    assert artwork.graphics
    assert all('(layer "F.SilkS")' in graphic for graphic in artwork.graphics)
    assert len(set(artwork.graphics)) == len(artwork.graphics)


def test_back_artwork_requires_explicit_side_and_mirror_is_recorded(tmp_path: Path) -> None:
    source = _image(tmp_path / "logo.png")

    artwork = trace_silkscreen_artwork(
        source,
        request=SilkscreenArtworkRequest(
            artwork_id="back-logo",
            target_width_mm=15.0,
            anchor_mm=(20.0, 20.0),
            side="back",
            mirror=True,
        ),
        board_origin_mm=20.0,
    )

    assert artwork.side == "back"
    assert artwork.mirror is True
    assert all('(layer "B.SilkS")' in graphic for graphic in artwork.graphics)
