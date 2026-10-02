import json

import pytest
from PIL import Image

from pcbsmith.review.raster_cache import CachedSvgRasterizer, self_contained_paths

SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16">'
    b'<path d="M0 0 L16 16" stroke="black"/></svg>'
)


def test_exact_inputs_reuse_pixels_but_no_decisions(tmp_path):
    calls = []

    def raster(source, destination, width, height, view):
        calls.append((width, height, view))
        Image.new("RGB", (width, height), "white").save(destination)

    source = tmp_path / "source.svg"
    source.write_bytes(SVG)
    cache = CachedSvgRasterizer(raster, tmp_path / "cache", "runtime-1")
    cache(source, tmp_path / "one.png", 16, 16, None)
    cache(source, tmp_path / "two.png", 16, 16, None)
    assert len(calls) == 1 and [e["status"] for e in cache.events] == ["miss", "hit"]
    assert (tmp_path / "one.png").read_bytes() == (tmp_path / "two.png").read_bytes()
    receipt = json.loads(next((tmp_path / "cache").glob("*/receipt.json")).read_text())
    assert "inspection" not in receipt and "accepted" not in receipt
    source.write_bytes(SVG.replace(b"black", b"red"))
    cache(source, tmp_path / "changed.png", 16, 16, None)
    cache(source, tmp_path / "size.png", 18, 18, None)
    cache(source, tmp_path / "crop.png", 18, 18, (0, 0, 8, 8))
    other = CachedSvgRasterizer(raster, tmp_path / "cache", "runtime-2")
    other(source, tmp_path / "runtime.png", 18, 18, (0, 0, 8, 8))
    assert len(calls) == 5


@pytest.mark.parametrize(
    "fragment",
    [
        b"<text>LED</text>",
        b"<style>rect {fill:red}</style>",
        b'<image href="file:///bad.png"/>',
        b'<use href="https://example.invalid/a.svg#id"/>',
        b'<path fill="url(http://example.invalid/a.svg)"/>',
        b"<foreignObject/>",
    ],
)
def test_external_or_font_inputs_never_reused(tmp_path, fragment):
    source = tmp_path / "source.svg"
    source.write_bytes(b"<svg>" + fragment + b"</svg>")
    assert not self_contained_paths(source.read_bytes())
    calls = []

    def raster(s, d, w, h, v):
        calls.append(d)
        Image.new("RGB", (w, h)).save(d)

    cache = CachedSvgRasterizer(raster, tmp_path / "cache", "runtime")
    cache(source, tmp_path / "a.png", 10, 10, None)
    cache(source, tmp_path / "b.png", 10, 10, None)
    assert len(calls) == 2 and not (tmp_path / "cache").exists()


@pytest.mark.parametrize("damage", ["pixels", "receipt", "missing"])
def test_corrupt_cache_renders_again_and_retains_failed_entry(tmp_path, damage):
    source = tmp_path / "source.svg"
    source.write_bytes(SVG)
    calls = []

    def raster(s, d, w, h, v):
        calls.append(d)
        Image.new("RGB", (w, h)).save(d)

    cache = CachedSvgRasterizer(raster, tmp_path / "cache", "runtime")
    cache(source, tmp_path / "a.png", 10, 10, None)
    entry = next((tmp_path / "cache").iterdir())
    if damage == "pixels":
        (entry / "pixels.png").write_bytes(b"corrupt")
    elif damage == "receipt":
        (entry / "receipt.json").write_text("{}")
    else:
        (entry / "receipt.json").unlink()
    cache(source, tmp_path / "b.png", 10, 10, None)
    assert len(calls) == 2 and cache.events[-1]["status"] == "rejected_cache"
    assert entry.exists()


def test_source_change_during_render_is_rejected(tmp_path):
    source = tmp_path / "source.svg"
    source.write_bytes(SVG)

    def raster(s, d, w, h, v):
        s.write_bytes(SVG + b" ")
        Image.new("RGB", (w, h)).save(d)

    cache = CachedSvgRasterizer(raster, tmp_path / "cache", "runtime")
    with pytest.raises(ValueError, match="source changed"):
        cache(source, tmp_path / "a.png", 10, 10, None)
    assert not (tmp_path / "cache").exists()



def test_only_inert_kicad_public_doctype_is_cacheable():
    declaration = (
        b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" '
        b'"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd">'
    )
    assert self_contained_paths(declaration + SVG)
    assert not self_contained_paths(declaration.replace(b"http:", b"file:") + SVG)
    assert not self_contained_paths(declaration[:-1] + b' [<!ENTITY x "bad">]>' + SVG)
    assert not self_contained_paths(declaration + b'<svg><text>font dependent</text></svg>')
