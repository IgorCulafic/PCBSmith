"""Manufacturable prototype geometry for the Montenegro display board."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

from shapely.geometry import MultiPolygon, Point, Polygon, box

from pcbsmith.kicad.raster_artwork import RasterTraceSettings, trace_board_outline

Point2D = tuple[float, float]
BOARD_WIDTH_MM = 150.0
OUTLINE_MARGIN_MM = 3.0
OUTLINE_CLOSE_MM = 1.5
DISPLAY_SIZE_MM = (44.5, 37.0)
DISPLAY_EDGE_CLEARANCE_MM = 3.0
LED_INSET_MM = 7.0
LED_COUNT = 35
USB_ANCHOR_MM = (10.5, 75.0)
USB_EXCLUSION_RADIUS_MM = 12.0
ESP32_ANCHOR_MM = (110.0, 70.0)
ESP32_ROTATION_DEG = 270.0
# Rotated KiCad ESP32-S3-WROOM-1 antenna keepout, expanded for placement
# tolerance and front-side LED bodies.
ANTENNA_EXCLUSION_MM = (96.0, 54.0, 139.0, 97.0)


@dataclass(frozen=True)
class LedSite:
    x_mm: float
    y_mm: float
    rotation_deg: float
    boundary_station_mm: float


@dataclass(frozen=True)
class MontenegroGeometry:
    source_file: str
    source_sha256: str
    source_pixels: tuple[int, int]
    width_mm: float
    height_mm: float
    outline: tuple[Point2D, ...]
    outline_area_mm2: float
    outline_perimeter_mm: float
    display_center_mm: Point2D
    display_size_mm: Point2D
    display_edge_clearance_mm: float
    led_sites: tuple[LedSite, ...]
    led_min_spacing_mm: float
    usb_anchor_mm: Point2D
    esp32_anchor_mm: Point2D
    esp32_rotation_deg: float
    antenna_exclusion_mm: tuple[float, float, float, float]

    @property
    def polygon(self) -> Polygon:
        return Polygon(self.outline).buffer(0)

    def as_dict(self) -> dict[str, object]:
        payload = asdict(self)
        payload["schema"] = "pcbsmith-montenegro-geometry-v1"
        payload["prototype_geometry_authority"] = (
            "Source-hashed, smoothed visual-reference derivative; not geodetic or "
            "licensing authority."
        )
        return payload


def _largest_polygon(shape: Polygon | MultiPolygon) -> Polygon:
    if isinstance(shape, Polygon):
        return shape
    if not shape.geoms:
        raise ValueError("Outline smoothing removed the complete silhouette.")
    return max(shape.geoms, key=lambda item: item.area)


def _rounded(value: float) -> float:
    return round(float(value), 4)


def _smooth_outline(raw: Polygon) -> Polygon:
    # Positive then negative buffer closes sub-fabrication notches without
    # cutting off recognizable narrow peninsulas.  This is a prototype
    # simplification, deliberately recorded in the geometry contract.
    closed = raw.buffer(OUTLINE_CLOSE_MM, join_style="round").buffer(
        -OUTLINE_CLOSE_MM, join_style="round"
    )
    if not isinstance(closed, (Polygon, MultiPolygon)):
        raise ValueError("Outline smoothing did not produce polygon geometry.")
    simplified = _largest_polygon(closed).simplify(0.60, preserve_topology=True)
    if not isinstance(simplified, Polygon):
        raise ValueError("Outline simplification did not preserve a polygon.")
    return simplified


def _rotation_from_tangent(boundary: object, station: float) -> float:
    length = float(boundary.length)  # type: ignore[attr-defined]
    delta = min(1.0, length / 500.0)
    before = boundary.interpolate((station - delta) % length)  # type: ignore[attr-defined]
    after = boundary.interpolate((station + delta) % length)  # type: ignore[attr-defined]
    return _rounded(math.degrees(math.atan2(after.y - before.y, after.x - before.x)))


def _sample_led_sites(polygon: Polygon) -> tuple[LedSite, ...]:
    boundary = polygon.exterior
    # A 5 mm LED needs its centre at least 3 mm from Edge.Cuts. Aim for
    # 7 mm, but move toward 3.5 mm only where a narrow geographical feature
    # would otherwise disappear from the illuminated outline.
    safe = polygon.buffer(-4.5, join_style="round")
    if safe.is_empty:
        raise ValueError("The silhouette has no interior region for the LED inset.")
    usb_zone = Point(*USB_ANCHOR_MM).buffer(USB_EXCLUSION_RADIUS_MM)
    antenna_zone = box(*ANTENNA_EXCLUSION_MM)

    candidate_count = 192
    candidates: list[LedSite] = []
    for index in range(candidate_count):
        station = (index + 0.5) * boundary.length / candidate_count
        boundary_point = boundary.interpolate(station)
        delta = min(1.0, boundary.length / 500.0)
        before = boundary.interpolate((station - delta) % boundary.length)
        after = boundary.interpolate((station + delta) % boundary.length)
        dx, dy = after.x - before.x, after.y - before.y
        magnitude = math.hypot(dx, dy)
        if magnitude == 0:
            continue
        normals = ((-dy / magnitude, dx / magnitude), (dy / magnitude, -dx / magnitude))
        interior = None
        for inset in (LED_INSET_MM, 6.0, 5.0, 4.5):
            options = (
                Point(
                    boundary_point.x + normal[0] * inset,
                    boundary_point.y + normal[1] * inset,
                )
                for normal in normals
            )
            interior = next((point for point in options if safe.covers(point)), None)
            if interior is not None:
                break
        if interior is None:
            continue
        if usb_zone.covers(interior) or antenna_zone.covers(interior):
            continue
        candidate = LedSite(
            _rounded(interior.x),
            _rounded(interior.y),
            _rotation_from_tangent(boundary, station),
            _rounded(station),
        )
        if any(
            math.dist((candidate.x_mm, candidate.y_mm), (other.x_mm, other.y_mm)) < 7.5
            for other in candidates
        ):
            continue
        candidates.append(candidate)
    if (
        len(candidates) > 1
        and math.dist(
            (candidates[0].x_mm, candidates[0].y_mm),
            (candidates[-1].x_mm, candidates[-1].y_mm),
        )
        < 7.5
    ):
        candidates.pop()
    if len(candidates) < LED_COUNT:
        raise ValueError(
            f"Only {len(candidates)} LED positions remain after connector/RF exclusions."
        )

    chosen_indices = tuple(
        round(index * (len(candidates) - 1) / (LED_COUNT - 1)) for index in range(LED_COUNT)
    )
    sites = tuple(candidates[index] for index in chosen_indices)
    if len({(site.x_mm, site.y_mm) for site in sites}) != LED_COUNT:
        raise ValueError("LED down-sampling produced duplicate placements.")
    return sites


def build_montenegro_geometry(source_file: Path) -> MontenegroGeometry:
    traced = trace_board_outline(
        source_file,
        target_width_mm=BOARD_WIDTH_MM,
        margin_mm=OUTLINE_MARGIN_MM,
        settings=RasterTraceSettings(simplify_mm=0.60),
    )
    polygon = _smooth_outline(Polygon(traced.outline).buffer(0))
    display_center = (
        _rounded(polygon.centroid.x - 5.0),
        _rounded(polygon.centroid.y),
    )
    display = box(
        display_center[0] - DISPLAY_SIZE_MM[0] / 2,
        display_center[1] - DISPLAY_SIZE_MM[1] / 2,
        display_center[0] + DISPLAY_SIZE_MM[0] / 2,
        display_center[1] + DISPLAY_SIZE_MM[1] / 2,
    )
    display_safe = polygon.buffer(-DISPLAY_EDGE_CLEARANCE_MM)
    if not display_safe.covers(display):
        raise ValueError("The selected 1.5-inch OLED envelope does not fit at the centroid.")

    sites = _sample_led_sites(polygon)
    spacing = min(
        math.dist((first.x_mm, first.y_mm), (second.x_mm, second.y_mm))
        for first, second in zip(sites, (*sites[1:], sites[0]), strict=True)
    )
    if spacing < 6.0:
        raise ValueError(f"LED spacing fell below 6 mm ({spacing:.3f} mm).")

    outline = tuple((_rounded(x), _rounded(y)) for x, y in polygon.exterior.coords[:-1])
    return MontenegroGeometry(
        source_file=str(source_file.resolve()),
        source_sha256=traced.source_sha256,
        source_pixels=traced.source_pixels,
        width_mm=BOARD_WIDTH_MM,
        height_mm=_rounded(polygon.bounds[3] + OUTLINE_MARGIN_MM),
        outline=outline,
        outline_area_mm2=_rounded(polygon.area),
        outline_perimeter_mm=_rounded(polygon.length),
        display_center_mm=display_center,
        display_size_mm=DISPLAY_SIZE_MM,
        display_edge_clearance_mm=DISPLAY_EDGE_CLEARANCE_MM,
        led_sites=sites,
        led_min_spacing_mm=_rounded(spacing),
        usb_anchor_mm=USB_ANCHOR_MM,
        esp32_anchor_mm=ESP32_ANCHOR_MM,
        esp32_rotation_deg=ESP32_ROTATION_DEG,
        antenna_exclusion_mm=ANTENNA_EXCLUSION_MM,
    )


def write_geometry_contract(geometry: MontenegroGeometry, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(geometry.as_dict(), indent=2), encoding="utf-8")
