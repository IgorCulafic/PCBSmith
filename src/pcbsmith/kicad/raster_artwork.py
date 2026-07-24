"""Deterministic PNG-to-board-outline and PNG-to-silkscreen adapters."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from pcbsmith.kicad.shaped_board import silk_line

Point = tuple[float, float]


class RasterTraceSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    threshold: int = Field(default=127, ge=0, le=255)
    invert: bool = True
    simplify_mm: float = Field(default=0.10, ge=0)
    minimum_contour_area_px: float = Field(default=4.0, ge=0)


class BoardOutlineTrace(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["pcbsmith-raster-outline-v1"] = "pcbsmith-raster-outline-v1"
    source_file: str
    source_sha256: str
    source_pixels: tuple[int, int]
    target_size_mm: tuple[float, float]
    margin_mm: float
    settings: RasterTraceSettings
    outline: tuple[Point, ...] = Field(min_length=3)


class SilkscreenArtworkRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    artwork_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    target_width_mm: float = Field(gt=0)
    anchor_mm: Point
    side: Literal["front", "back"] = "front"
    rotation_deg: float = 0.0
    mirror: bool = False
    line_width_mm: float = Field(default=0.20, gt=0)


class SilkscreenArtwork(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["pcbsmith-raster-silkscreen-v1"] = "pcbsmith-raster-silkscreen-v1"
    artwork_id: str
    source_file: str
    source_sha256: str
    source_pixels: tuple[int, int]
    target_size_mm: tuple[float, float]
    anchor_mm: Point
    side: Literal["front", "back"]
    rotation_deg: float
    mirror: bool
    line_width_mm: float
    contour_count: int
    graphics: tuple[str, ...]


def trace_board_outline(
    source_file: Path,
    *,
    target_width_mm: float,
    margin_mm: float = 0.0,
    settings: RasterTraceSettings | None = None,
) -> BoardOutlineTrace:
    settings = settings or RasterTraceSettings()
    if target_width_mm <= 2 * margin_mm:
        raise ValueError("Target width must be larger than twice the outline margin.")
    image, mask, cv2 = _load_mask(source_file, settings)
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    usable = tuple(
        contour
        for contour in contours
        if cv2.contourArea(contour) >= settings.minimum_contour_area_px
    )
    if not usable:
        raise ValueError(f"No usable silhouette found in {source_file}.")
    contour = max(usable, key=cv2.contourArea)
    raw = tuple((float(item[0][0]), float(item[0][1])) for item in contour)
    polygon = _valid_polygon(raw)
    min_x, min_y, max_x, max_y = polygon.bounds
    available_width = target_width_mm - 2 * margin_mm
    scale = available_width / (max_x - min_x)
    scaled = _valid_polygon(
        tuple(
            (
                (x - min_x) * scale + margin_mm,
                (y - min_y) * scale + margin_mm,
            )
            for x, y in polygon.exterior.coords
        )
    ).simplify(settings.simplify_mm, preserve_topology=True)
    scaled = _largest_polygon(scaled)
    points = tuple(
        (round(float(x), 4), round(float(y), 4)) for x, y in tuple(scaled.exterior.coords)[:-1]
    )
    target_height = float(scaled.bounds[3] + margin_mm)
    return BoardOutlineTrace(
        source_file=str(source_file.resolve()),
        source_sha256=hashlib.sha256(source_file.read_bytes()).hexdigest(),
        source_pixels=(int(image.shape[1]), int(image.shape[0])),
        target_size_mm=(target_width_mm, target_height),
        margin_mm=margin_mm,
        settings=settings,
        outline=points,
    )


def trace_silkscreen_artwork(
    source_file: Path,
    *,
    request: SilkscreenArtworkRequest,
    board_origin_mm: float,
    settings: RasterTraceSettings | None = None,
) -> SilkscreenArtwork:
    settings = settings or RasterTraceSettings()
    image, mask, cv2 = _load_mask(source_file, settings)
    contours, _hierarchy = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    usable = tuple(
        contour
        for contour in contours
        if cv2.contourArea(contour) >= settings.minimum_contour_area_px
    )
    if not usable:
        raise ValueError(f"No usable silkscreen contours found in {source_file}.")
    source_width = float(image.shape[1])
    source_height = float(image.shape[0])
    scale = request.target_width_mm / source_width
    target_height = source_height * scale
    angle = math.radians(request.rotation_deg)
    cosine = math.cos(angle)
    sine = math.sin(angle)

    def transform(point: Point) -> Point:
        x = (point[0] - source_width / 2) * scale
        y = (point[1] - source_height / 2) * scale
        if request.mirror:
            x = -x
        rotated_x = x * cosine - y * sine
        rotated_y = x * sine + y * cosine
        return (
            round(request.anchor_mm[0] + rotated_x, 4),
            round(request.anchor_mm[1] + rotated_y, 4),
        )

    graphics: list[str] = []
    layer = "F.SilkS" if request.side == "front" else "B.SilkS"
    occurrence = 0
    tolerance_px = settings.simplify_mm / scale if scale > 0 else 0.0
    for contour in sorted(usable, key=lambda item: (-cv2.contourArea(item), item.shape[0])):
        approximated = cv2.approxPolyDP(contour, tolerance_px, True)
        points = tuple(transform((float(item[0][0]), float(item[0][1]))) for item in approximated)
        if len(points) < 2:
            continue
        for start, end in zip(points, (*points[1:], points[0]), strict=True):
            graphics.append(
                silk_line(
                    start,
                    end,
                    board_origin_mm,
                    width=request.line_width_mm,
                    layer=layer,
                    occurrence=occurrence,
                )
            )
            occurrence += 1
    return SilkscreenArtwork(
        artwork_id=request.artwork_id,
        source_file=str(source_file.resolve()),
        source_sha256=hashlib.sha256(source_file.read_bytes()).hexdigest(),
        source_pixels=(int(source_width), int(source_height)),
        target_size_mm=(request.target_width_mm, target_height),
        anchor_mm=request.anchor_mm,
        side=request.side,
        rotation_deg=request.rotation_deg,
        mirror=request.mirror,
        line_width_mm=request.line_width_mm,
        contour_count=len(usable),
        graphics=tuple(graphics),
    )


def _load_mask(source_file: Path, settings: RasterTraceSettings) -> tuple[Any, Any, Any]:
    try:
        import cv2
    except ImportError as exc:
        raise RuntimeError("Install the artwork extra: pip install 'pcbsmith[artwork]'.") from exc
    image = cv2.imread(str(source_file), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise FileNotFoundError(source_file)
    if len(image.shape) == 3 and image.shape[2] == 4 and image[:, :, 3].max() > 0:
        mask = image[:, :, 3]
        if settings.invert:
            _threshold, mask = cv2.threshold(mask, settings.threshold, 255, cv2.THRESH_BINARY)
    else:
        gray = image if len(image.shape) == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        mode = cv2.THRESH_BINARY_INV if settings.invert else cv2.THRESH_BINARY
        _threshold, mask = cv2.threshold(gray, settings.threshold, 255, mode)
    return image, mask, cv2


def _valid_polygon(points: tuple[Point, ...]) -> Any:
    try:
        from shapely.geometry import Polygon  # type: ignore[import-untyped]
    except ImportError as exc:
        raise RuntimeError("Install the artwork extra: pip install 'pcbsmith[artwork]'.") from exc
    polygon = Polygon(points).buffer(0)
    return _largest_polygon(polygon)


def _largest_polygon(shape: Any) -> Any:
    from shapely.geometry import MultiPolygon, Polygon

    if isinstance(shape, Polygon):
        if shape.is_empty or shape.area <= 0:
            raise ValueError("Raster contour did not produce a valid polygon.")
        return shape
    if isinstance(shape, MultiPolygon) and shape.geoms:
        return max(shape.geoms, key=lambda item: item.area)
    raise ValueError("Raster contour did not produce a usable polygon.")
