"""Deterministic component-model bounds read back from KiCad GLB assemblies."""

from __future__ import annotations

import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np


@dataclass(frozen=True)
class GlbBounds:
    """World-axis bounds in millimetres (GLB Y is assembly height)."""

    x_min_mm: float
    x_max_mm: float
    y_min_mm: float
    y_max_mm: float
    z_min_mm: float
    z_max_mm: float

    @property
    def board_center_mm(self) -> tuple[float, float]:
        return (
            (self.x_min_mm + self.x_max_mm) / 2.0,
            (self.z_min_mm + self.z_max_mm) / 2.0,
        )


def read_component_model_bounds(
    glb_file: Path,
    references: tuple[str, ...],
) -> dict[str, GlbBounds]:
    """Return descendant mesh bounds for named KiCad component nodes."""
    document = _read_glb_json(glb_file)
    nodes = document.get("nodes", [])
    by_name = {
        node.get("name"): index
        for index, node in enumerate(nodes)
        if isinstance(node, dict) and node.get("name")
    }
    missing = sorted(set(references) - by_name.keys())
    if missing:
        raise ValueError(f"GLB assembly is missing component nodes: {missing}")

    roots = tuple(document.get("scenes", [{}])[document.get("scene", 0)].get("nodes", ()))
    world: dict[int, np.ndarray] = {}

    def visit(index: int, parent: np.ndarray) -> None:
        node = nodes[index]
        transform = parent @ _node_matrix(node)
        world[index] = transform
        for child in node.get("children", ()):
            visit(int(child), transform)

    identity = np.identity(4, dtype=float)
    for root in roots:
        visit(int(root), identity)

    return {
        reference: _descendant_bounds(document, by_name[reference], world)
        for reference in references
    }


def _read_glb_json(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    if len(payload) < 20:
        raise ValueError("GLB payload is truncated")
    magic, version, total_length = struct.unpack_from("<III", payload, 0)
    if magic != 0x46546C67 or version != 2 or total_length != len(payload):
        raise ValueError("Expected a complete GLB 2.0 payload")
    json_length, json_type = struct.unpack_from("<II", payload, 12)
    if json_type != 0x4E4F534A:
        raise ValueError("First GLB chunk is not JSON")
    return cast(
        dict[str, Any],
        json.loads(payload[20 : 20 + json_length].decode("utf-8").rstrip(" \x00")),
    )


def _node_matrix(node: dict[str, Any]) -> np.ndarray:
    if "matrix" in node:
        raw = np.asarray(node["matrix"], dtype=float)
        if raw.size != 16:
            raise ValueError("GLB node matrix must contain 16 values")
        return raw.reshape((4, 4)).T

    translation = np.asarray(node.get("translation", (0.0, 0.0, 0.0)), dtype=float)
    scale = np.asarray(node.get("scale", (1.0, 1.0, 1.0)), dtype=float)
    quaternion = np.asarray(node.get("rotation", (0.0, 0.0, 0.0, 1.0)), dtype=float)
    rotation = _quaternion_matrix(quaternion)
    matrix = np.identity(4, dtype=float)
    matrix[:3, :3] = rotation * scale[np.newaxis, :]
    matrix[:3, 3] = translation
    return matrix


def _quaternion_matrix(quaternion: np.ndarray) -> np.ndarray:
    if quaternion.size != 4:
        raise ValueError("GLB quaternion must contain four values")
    x, y, z, w = quaternion
    norm = math.sqrt(float(x * x + y * y + z * z + w * w))
    if norm == 0:
        raise ValueError("GLB quaternion must not be zero")
    x, y, z, w = x / norm, y / norm, z / norm, w / norm
    return np.asarray(
        (
            (1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)),
            (2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)),
            (2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)),
        ),
        dtype=float,
    )


def _descendant_bounds(
    document: dict[str, Any],
    root: int,
    world: dict[int, np.ndarray],
) -> GlbBounds:
    nodes = document["nodes"]
    meshes = document.get("meshes", [])
    accessors = document.get("accessors", [])
    points: list[np.ndarray] = []

    def collect(index: int) -> None:
        node = nodes[index]
        mesh_index = node.get("mesh")
        if mesh_index is not None:
            mesh = meshes[int(mesh_index)]
            for primitive in mesh.get("primitives", ()):
                position = primitive.get("attributes", {}).get("POSITION")
                if position is None:
                    continue
                accessor = accessors[int(position)]
                lower = accessor.get("min")
                upper = accessor.get("max")
                if lower is None or upper is None:
                    raise ValueError("GLB POSITION accessor lacks min/max bounds")
                for x in (lower[0], upper[0]):
                    for y in (lower[1], upper[1]):
                        for z in (lower[2], upper[2]):
                            points.append(world[index] @ np.asarray((x, y, z, 1.0)))
        for child in node.get("children", ()):
            collect(int(child))

    collect(root)
    if not points:
        raise ValueError(f"GLB component node {root} has no descendant mesh")
    xyz = np.asarray(points, dtype=float)[:, :3] * 1000.0
    minimum = xyz.min(axis=0)
    maximum = xyz.max(axis=0)
    return GlbBounds(
        x_min_mm=float(minimum[0]),
        x_max_mm=float(maximum[0]),
        y_min_mm=float(minimum[1]),
        y_max_mm=float(maximum[1]),
        z_min_mm=float(minimum[2]),
        z_max_mm=float(maximum[2]),
    )
