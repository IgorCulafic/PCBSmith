from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from pcbsmith.evidence.source_intake import SourceIntakeRequest, SourceIntakeService
from pcbsmith.kicad.asset_install import normalized_library_payload
from pcbsmith.kicad.asset_resolution import AssetPin, resolve_or_acquire_asset, resolve_pinned_asset
from pcbsmith.native_project import resolve_symbol


def fixture(tmp_path, monkeypatch, *, kind="footprint", private=False):
    monkeypatch.setattr("pcbsmith.board_job.require_library_worker", lambda: None)
    from pcbsmith.kicad import library, symbols

    monkeypatch.setattr(library, "INSTALLED_SHARE_DIRS", ())
    monkeypatch.setattr(symbols, "INSTALLED_SHARE_DIRS", ())
    payload = (
        (
            b'(footprint "X" (layer "F.Cu") (pad "1" thru_hole circle (at 0 0) '
            b'(size 2 2) (drill 1) (layers "*.Cu" "*.Mask")))'
        )
        if kind == "footprint"
        else b'(kicad_symbol_lib (symbol "X" (property "Reference" "U")))'
    )
    raw_sha = hashlib.sha256(payload).hexdigest()
    pin = AssetPin(
        kind=kind,
        library_id="Fixture:X",
        sha256=hashlib.sha256(normalized_library_payload(kind, "Fixture:X", payload)).hexdigest(),
    )
    calls = []

    class Downloader:
        def download(self, url):
            calls.append(url)
            return payload

    service = SourceIntakeService(
        private_manifest_path=tmp_path / "private.json",
        public_manifest_path=tmp_path / "public.json",
        cache_dir=tmp_path / "cache",
        downloader=Downloader(),
        clock=lambda: "2026-09-07T00:00:00Z",
    )
    intake = SourceIntakeRequest(
        source_id="fixture",
        source_url="https://example.org/X",
        approved_hosts=("example.org",),
        intended_consumer="unit fixture",
        expected_kind="text",
        license_status="local_cache_only" if private else "redistributable",
        expected_sha256=raw_sha,
    )
    args = dict(
        repository_root=tmp_path / "repo",
        private_asset_root=tmp_path / "private",
        intake=intake,
        service=service,
    )
    return pin, args, calls


@pytest.mark.parametrize("kind", ["footprint", "symbol"])
@pytest.mark.parametrize("private", [False, True])
def test_true_miss_once_then_offline_hit(tmp_path, monkeypatch, kind, private):
    pin, args, calls = fixture(tmp_path, monkeypatch, kind=kind, private=private)
    first = resolve_or_acquire_asset(pin, **args)
    assert first["status"] == "installed" and len(calls) == 1
    args["service"] = None
    second = resolve_or_acquire_asset(pin, **args)
    assert second["path"] == first["path"] and second["fetch_count"] == 0
    assert len(calls) == 1


def test_concurrent_miss_fetches_once(tmp_path, monkeypatch):
    pin, args, calls = fixture(tmp_path, monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: resolve_or_acquire_asset(pin, **args), range(2)))
    assert len(calls) == 1
    assert {r["status"] for r in results} == {"installed", "local_hit"}


def test_conflicting_revision_and_corruption_never_fetch(tmp_path, monkeypatch):
    pin, args, calls = fixture(tmp_path, monkeypatch)
    result = resolve_or_acquire_asset(pin, **args)
    with pytest.raises(ValueError, match="Conflicting"):
        resolve_or_acquire_asset(pin.model_copy(update={"sha256": "0" * 64}), **args)
    Path(result["path"]).write_bytes(b"corrupt")
    with pytest.raises(ValueError, match="corrupt"):
        resolve_or_acquire_asset(pin, **args)
    assert len(calls) == 1


def test_bad_normalized_hash_does_not_install(tmp_path, monkeypatch):
    pin, args, _ = fixture(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="normalized"):
        resolve_or_acquire_asset(pin.model_copy(update={"sha256": "0" * 64}), **args)
    assert not list((tmp_path / "repo").rglob("*.kicad_mod"))


def test_explicit_board_pin_wins_and_missing_pin_is_not_miss(tmp_path, monkeypatch):
    pin, args, calls = fixture(tmp_path, monkeypatch)
    first = resolve_or_acquire_asset(pin, **args)
    local = tmp_path / "moved-board" / "Fixture.pretty" / "X.kicad_mod"
    local.parent.mkdir(parents=True)
    local.write_bytes(Path(first["path"]).read_bytes())
    pinned = pin.model_copy(update={"local_path": str(local)})
    Path(first["path"]).write_bytes(b"new shared revision")
    assert resolve_pinned_asset(pinned) == local.resolve()
    with pytest.raises(FileNotFoundError):
        resolve_or_acquire_asset(
            pinned.model_copy(update={"local_path": str(local) + ".missing"}), **args
        )
    assert len(calls) == 1


def test_package_name_mismatch_rejected_before_install():
    with pytest.raises(ValueError, match="package/name"):
        normalized_library_payload("footprint", "Test:Other", b'(footprint "X")')


def test_native_symbol_preparation_uses_shared_source(tmp_path, monkeypatch):
    from pcbsmith.kicad import symbols

    vendor = tmp_path / "shared"
    vendor.mkdir()
    path = vendor / "L__X.kicad_sym"
    path.write_text('(kicad_symbol_lib (symbol "X" (symbol "X_1_1")))')
    monkeypatch.setattr(symbols, "VENDORED_DIR", vendor)
    _, source = resolve_symbol("L:X", tmp_path / "unavailable-installed")
    assert source == path


def test_miss_requires_hash_pinned_approved_intake(tmp_path, monkeypatch):
    pin, args, calls = fixture(tmp_path, monkeypatch)
    args["intake"] = None
    with pytest.raises(ValueError, match="approved"):
        resolve_or_acquire_asset(pin, **args)
    assert not calls


def test_acquisition_requires_supervised_board_job(tmp_path, monkeypatch):
    from pcbsmith.board_job import ROOT_ENV, TOKEN_ENV, JobStopped

    monkeypatch.delenv(ROOT_ENV, raising=False)
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    pin = AssetPin(kind="footprint", library_id="L:X", sha256="0" * 64)
    with pytest.raises(JobStopped):
        resolve_or_acquire_asset(
            pin, repository_root=tmp_path, private_asset_root=tmp_path / "private"
        )


def test_relocated_project_scope_beats_changed_shared_asset(tmp_path, monkeypatch):
    import json
    import shutil

    from pcbsmith.kicad.library import FootprintLibraryError, load_footprint
    from pcbsmith.kicad.project_dependencies import project_footprint_scope

    pin, args, _ = fixture(tmp_path, monkeypatch)
    first = resolve_or_acquire_asset(pin, **args)
    original = tmp_path / "board"
    local = original / "Fixture.pretty" / "X.kicad_mod"
    local.parent.mkdir(parents=True)
    local.write_bytes(Path(first["path"]).read_bytes())
    (original / "fp-lib-table").write_text(
        '(fp_lib_table (lib (name "Fixture") (uri "${KIPRJMOD}/Fixture.pretty")))'
    )
    (original / "library-sources.json").write_text(
        json.dumps([{"kind": "footprint", "id": pin.library_id, "sha256": pin.sha256}])
    )
    moved = tmp_path / "elsewhere" / "board"
    shutil.copytree(original, moved)
    Path(first["path"]).write_bytes(b"changed shared version")
    with project_footprint_scope(moved):
        fp = load_footprint(pin.library_id)
        assert fp.source_file == (moved / "Fixture.pretty/X.kicad_mod").resolve()
        with pytest.raises(FootprintLibraryError, match="pinned project"):
            load_footprint("Fixture:Missing")
    (moved / "Fixture.pretty/X.kicad_mod").write_bytes(b"corrupt local")
    with pytest.raises(ValueError, match="hash mismatch"):
        with project_footprint_scope(moved):
            pytest.fail("corrupt dependency scope must not open")
