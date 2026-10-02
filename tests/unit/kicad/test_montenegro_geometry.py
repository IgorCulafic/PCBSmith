from pathlib import Path

import cv2
import numpy as np

from pcbsmith.kicad.montenegro_geometry import (
    LED_COUNT,
    build_montenegro_geometry,
)


def test_geometry_contract_smooths_and_places_leds(tmp_path: Path) -> None:
    source = tmp_path / "silhouette.png"
    image = np.full((800, 800), 255, dtype=np.uint8)
    cv2.rectangle(image, (60, 60), (740, 740), 0, -1)
    assert cv2.imwrite(str(source), image)

    geometry = build_montenegro_geometry(source)

    assert geometry.width_mm == 150.0
    assert len(geometry.led_sites) == LED_COUNT
    assert geometry.led_min_spacing_mm >= 6.0
    assert geometry.polygon.buffer(-3.0).covers(
        __import__("shapely.geometry", fromlist=["box"]).box(
            geometry.display_center_mm[0] - geometry.display_size_mm[0] / 2,
            geometry.display_center_mm[1] - geometry.display_size_mm[1] / 2,
            geometry.display_center_mm[0] + geometry.display_size_mm[0] / 2,
            geometry.display_center_mm[1] + geometry.display_size_mm[1] / 2,
        )
    )
