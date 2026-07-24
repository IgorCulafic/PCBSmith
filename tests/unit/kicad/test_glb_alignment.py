from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from pcbsmith.kicad.glb_alignment import read_component_model_bounds


def _write_glb(path: Path, document: dict[str, object]) -> None:
    body = json.dumps(document, separators=(",", ":")).encode("utf-8")
    body += b" " * ((4 - len(body) % 4) % 4)
    total = 12 + 8 + len(body)
    path.write_bytes(
        struct.pack("<III", 0x46546C67, 2, total)
        + struct.pack("<II", len(body), 0x4E4F534A)
        + body
    )


def test_reads_transformed_component_descendant_bounds(tmp_path: Path) -> None:
    glb = tmp_path / "assembly.glb"
    _write_glb(
        glb,
        {
            "asset": {"version": "2.0"},
            "scene": 0,
            "scenes": [{"nodes": [0]}],
            "nodes": [
                {"children": [1]},
                {"name": "Q1", "translation": [0.1, 0.002, 0.03], "children": [2]},
                {"mesh": 0},
            ],
            "meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}],
            "accessors": [{"min": [-0.005, 0.0, -0.01], "max": [0.005, 0.003, 0.01]}],
        },
    )

    bounds = read_component_model_bounds(glb, ("Q1",))["Q1"]

    assert bounds.board_center_mm == pytest.approx((100.0, 30.0))
    assert bounds.x_min_mm == pytest.approx(95.0)
    assert bounds.x_max_mm == pytest.approx(105.0)
    assert bounds.y_min_mm == pytest.approx(2.0)
    assert bounds.y_max_mm == pytest.approx(5.0)
    assert bounds.z_min_mm == pytest.approx(20.0)
    assert bounds.z_max_mm == pytest.approx(40.0)
