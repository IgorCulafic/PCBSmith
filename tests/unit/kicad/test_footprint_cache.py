import os
from pathlib import Path

import pytest

from pcbsmith.kicad import library


def fixture_file(root: Path, width: str) -> Path:
    path = root / "footprints" / "Fixture__Pad.kicad_mod"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f'(footprint "Pad" (layer "F.Cu") (pad "1" smd rect '
        f'(at 0 0) (size {width} 1) (layers "F.Cu" "F.Paste" "F.Mask")))',
        encoding="utf-8",
    )
    return path


def test_cache_follows_private_context_and_revision_and_explicit_reload(tmp_path, monkeypatch):
    monkeypatch.setattr(library, "VENDORED_DIR", tmp_path / "absent")
    monkeypatch.setattr(library, "INSTALLED_SHARE_DIRS", ())
    first = tmp_path / "a"
    second = tmp_path / "b"
    path = fixture_file(first, "1")
    fixture_file(second, "2")
    monkeypatch.setenv(library.PRIVATE_ASSET_ROOT_ENV, str(first))
    original = library.load_footprint("Fixture:Pad")
    assert library.load_footprint("Fixture:Pad") is original
    monkeypatch.setenv(library.PRIVATE_ASSET_ROOT_ENV, str(second))
    assert library.load_footprint("Fixture:Pad").spec.pads[0].width_mm == 2
    monkeypatch.setenv(library.PRIVATE_ASSET_ROOT_ENV, str(first))
    assert library.load_footprint("Fixture:Pad") is original
    stamp = path.stat().st_mtime_ns
    fixture_file(first, "3")
    os.utime(path, ns=(stamp + 1_000_000, stamp + 1_000_000))
    assert library.load_footprint("Fixture:Pad").spec.pads[0].width_mm == 3
    fixture_file(first, "4")
    os.utime(path, ns=(stamp + 1_000_000, stamp + 1_000_000))
    library.load_footprint.cache_clear()  # deliberate reload for timestamp-preserving tools
    assert library.load_footprint("Fixture:Pad").spec.pads[0].width_mm == 4


def test_lazy_defaults_do_not_require_optional_installed_library(monkeypatch):
    def unavailable(_):
        raise library.FootprintLibraryError("optional library absent")

    monkeypatch.setattr(library, "_footprint_file", unavailable)
    values = library.LazyFootprintLibrary()
    assert len(values) > 0 and library.LIBRARY_FOOTPRINT_IDS[0] in values
    assert list(values) == list(library.LIBRARY_FOOTPRINT_IDS)
    with pytest.raises(library.FootprintLibraryError, match="optional"):
        values[library.LIBRARY_FOOTPRINT_IDS[0]]


@pytest.mark.parametrize("identifier", ["../x:Pad", "X:../Pad", "X:a/b", "X:C:Pad", ":Pad"])
def test_footprint_ids_cannot_escape_roots(identifier):
    with pytest.raises(library.FootprintLibraryError):
        library.load_footprint(identifier)
