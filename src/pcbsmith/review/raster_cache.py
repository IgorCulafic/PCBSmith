"""Exact-input pixel cache; never an inspection or native-check authority."""

from __future__ import annotations

import hashlib
import io
import json
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image

Rasterizer = Callable[[Path, Path, int, int, tuple[float, float, float, float] | None], None]


def self_contained_paths(payload: bytes) -> bool:
    """Only font-independent, self-contained SVG can share cached pixels."""
    # KiCad emits this standard declaration. ElementTree does not fetch its DTD,
    # and our rasterizer serializes the parsed tree before resvg sees it. Accept
    # only this exact public identifier/URL with whitespace variation; arbitrary
    # DTDs, internal subsets and entities remain ineligible.
    declarations_removed = re.sub(
        rb'<!DOCTYPE\s+svg\s+PUBLIC\s+"-//W3C//DTD SVG 1.1//EN"\s+'
        rb'"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd"\s*>',
        b"",
        payload,
    )
    if (
        b"<!DOCTYPE" in declarations_removed
        or b"<!ENTITY" in payload
        or b"<?xml-stylesheet" in payload
    ):
        return False
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return False
    for node in root.iter():
        name = node.tag.rsplit("}", 1)[-1]
        if name in {"text", "tspan", "textPath", "script", "foreignObject", "style"}:
            return False
        for key, value in node.attrib.items():
            if key.rsplit("}", 1)[-1] in {"href", "src"} and not value.startswith("#"):
                return False
        # Reject CSS imports, external resource URLs and font declarations.
        content = " ".join([node.text or "", *node.attrib.values()])
        if "@import" in content.lower() or "@font-face" in content.lower() or "\\" in content:
            return False
        if any(
            not url.strip(" \"'").startswith("#")
            for url in re.findall(r"url\((.*?)\)", content, re.I)
        ):
            return False
    return True


def runtime_identity() -> str | None:
    try:
        import resvg_py

        root = Path(resvg_py.__file__).parent
        paths = sorted(
            p for p in root.rglob("*") if p.is_file() and p.suffix in {".py", ".pyd", ".so", ".dll"}
        )
        if not paths:
            return None
        values = {
            str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths
        }
        # The SVG rewriting/raster invocation code is part of the runtime identity.
        values["visual_package.py"] = hashlib.sha256(
            Path(__file__).with_name("visual_package.py").read_bytes()
        ).hexdigest()
        values["raster_cache.py"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
    except (ImportError, OSError, TypeError):
        return None


class CachedSvgRasterizer:
    def __init__(self, rasterizer: Rasterizer, root: Path, identity: str | None) -> None:
        self.rasterizer = rasterizer
        self.root = root
        self.identity = identity
        self.events: list[dict[str, Any]] = []

    def __call__(
        self,
        source: Path,
        destination: Path,
        width: int,
        height: int,
        view_box: tuple[float, float, float, float] | None,
    ) -> None:
        started = time.perf_counter()
        payload = source.read_bytes()
        eligible = self.identity is not None and self_contained_paths(payload)
        inputs = dict(
            schema="pcbsmith-raster-cache-v1",
            svg_sha256=hashlib.sha256(payload).hexdigest(),
            width=width,
            height=height,
            view_box=view_box,
            renderer=self.identity,
        )
        key = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
        entry = self.root / key
        status = "miss" if eligible else "uncached_dependencies"
        if eligible and entry.exists():
            try:
                receipt = json.loads((entry / "receipt.json").read_bytes())
                pixels = (entry / "pixels.png").read_bytes()
                if (
                    receipt["key"] != key
                    or hashlib.sha256(pixels).hexdigest() != receipt["png_sha256"]
                ):
                    raise ValueError("stale raster cache")
                with Image.open(io.BytesIO(pixels)) as im:
                    if im.size != (width, height):
                        raise ValueError("cached raster dimensions differ")
                    im.verify()
                if source.read_bytes() != payload:
                    raise ValueError("SVG source changed during cache lookup")
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(pixels)
                self.events.append(
                    dict(
                        key=key,
                        status="hit",
                        source_sha256=inputs["svg_sha256"],
                        elapsed_seconds=time.perf_counter() - started,
                    )
                )
                return
            except (OSError, ValueError, KeyError, TypeError):
                status = "rejected_cache"
        self.rasterizer(source, destination, width, height, view_box)
        if source.read_bytes() != payload:
            raise ValueError("SVG source changed during rasterization")
        if eligible and not entry.exists():
            try:
                with Image.open(destination) as im:
                    valid = im.size == (width, height)
                    im.verify()
                if valid:
                    pixels = destination.read_bytes()
                    entry.mkdir(parents=True, exist_ok=False)
                    (entry / "pixels.png").write_bytes(pixels)
                    (entry / "receipt.json").write_text(
                        json.dumps(
                            dict(
                                key=key,
                                inputs=inputs,
                                png_sha256=hashlib.sha256(pixels).hexdigest(),
                            ),
                            indent=2,
                        )
                        + "\n",
                        encoding="utf-8",
                    )
            except (OSError, ValueError):
                # Caching is optional; preserve any interrupted/corrupt entry and
                # the actual raster output. It never changes review acceptance.
                status = "uncached_storage"
        self.events.append(
            dict(
                key=key,
                status=status,
                source_sha256=inputs["svg_sha256"],
                elapsed_seconds=time.perf_counter() - started,
            )
        )
