"""Exact local-first asset resolution over the existing shared library owners.

Acquisition is opt-in and uses SourceIntakeService; a conflicting local identity
is an error, never a reason to fetch or silently replace an asset.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pcbsmith.evidence.source_intake import SourceIntakeRequest, SourceIntakeService
from pcbsmith.operations.file_transaction import FileTransactionError, _project_lock


class AssetMissing(FileNotFoundError):
    """No candidate exists in the configured local collections."""


class AssetPin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    kind: Literal["symbol", "footprint"]
    library_id: str = Field(pattern=r"^[A-Za-z0-9_+.-]+:[A-Za-z0-9_+.-]+$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    local_path: str | None = None


@contextmanager
def asset_lock(root: Path) -> Iterator[None]:
    """Reuse the OS-backed lock; contention has a finite ten-second allowance."""
    deadline = time.monotonic() + 10
    with ExitStack() as stack:
        while True:
            try:
                stack.enter_context(_project_lock(root))
                break
            except FileTransactionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)
        yield


def validate_pin(pin: AssetPin, path: Path) -> Path:
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != pin.sha256:
        raise ValueError(f"Conflicting or corrupt pinned asset: {pin.library_id}: {path}")
    from pcbsmith.kicad.library import _atom, _children, parse_sexpr

    tree = parse_sexpr(payload.decode("utf-8"))
    name = pin.library_id.split(":")[1]
    if pin.kind == "footprint":
        if _atom(tree[0]) not in {"footprint", "module"} or _atom(tree[1]).split(":")[-1] != name:
            raise ValueError("Pinned footprint package/name mismatch")
    elif _atom(tree[0]) != "kicad_symbol_lib" or not any(
        _atom(node[1]) == name for node in _children(tree, "symbol")
    ):
        raise ValueError("Pinned symbol name mismatch")
    return path.resolve()


def resolve_pinned_asset(
    pin: AssetPin,
    *,
    symbol_root: Path | None = None,
    repository_root: Path | None = None,
    private_asset_root: Path | None = None,
) -> Path:
    """Pinned local copy wins; otherwise use exactly the shared owner's precedence."""
    if pin.local_path is not None:
        # A missing explicit pin is corruption, not a cache miss.
        return validate_pin(pin, Path(pin.local_path))
    from pcbsmith.kicad.library import FootprintLibraryError

    try:
        if pin.kind == "footprint":
            from pcbsmith.kicad.library import _footprint_file

            path = _footprint_file(
                pin.library_id,
                repository_root=repository_root,
                private_asset_root=private_asset_root,
            )
        else:
            from pcbsmith.kicad.symbols import symbol_source_file

            path = symbol_source_file(
                pin.library_id,
                installed_root=symbol_root,
                repository_root=repository_root,
                private_asset_root=private_asset_root,
            )
    except (FileNotFoundError, FootprintLibraryError) as exc:
        raise AssetMissing(str(exc)) from exc
    return validate_pin(pin, path)


def resolve_or_acquire_asset(
    pin: AssetPin,
    *,
    repository_root: Path,
    private_asset_root: Path,
    intake: SourceIntakeRequest | None = None,
    service: SourceIntakeService | None = None,
    symbol_root: Path | None = None,
) -> dict[str, str | int]:
    """Resolve first, then acquire/install on a genuine miss under a shared lock.

    The installed-byte hash is the pin; intake.expected_sha256 pins original
    downloaded bytes before the existing installer normalizes them.
    """
    from pcbsmith.board_job import require_library_worker
    from pcbsmith.kicad.asset_install import KiCadAssetInstallRequest, install_kicad_asset

    require_library_worker()
    # One scope-wide lock also serializes the intake manifest read/modify/write.
    with ExitStack() as locks:
        for root in sorted({repository_root.resolve(), private_asset_root.resolve()}, key=str):
            locks.enter_context(asset_lock(root / "resolution"))
        try:
            path = resolve_pinned_asset(
                pin,
                symbol_root=symbol_root,
                repository_root=repository_root,
                private_asset_root=private_asset_root,
            )
            return {
                "status": "local_hit",
                "path": str(path),
                "sha256": pin.sha256,
                "fetch_count": 0,
            }
        except AssetMissing:
            pass
        if intake is None or service is None or intake.expected_sha256 is None:
            raise ValueError(
                f"Asset miss needs approved, hash-pinned source intake: {pin.library_id}"
            )
        if intake.expected_kind != "text":
            raise ValueError("Symbol/footprint acquisition requires a text asset")
        record = service.acquire(intake)
        if record.status not in {"cache_hit", "downloaded"} or not record.local_path:
            raise ValueError(f"Asset intake failed: {record.status}: {record.findings}")
        # Validate normalized identity BEFORE publication into the shared collection.
        from pcbsmith.kicad.asset_install import normalized_library_payload

        payload = normalized_library_payload(
            pin.kind, pin.library_id, Path(record.local_path).read_bytes()
        )
        if hashlib.sha256(payload).hexdigest() != pin.sha256:
            raise ValueError("Acquired normalized asset differs from installed hash pin")
        installed = install_kicad_asset(
            KiCadAssetInstallRequest(
                asset_id=intake.source_id,
                kind=pin.kind,
                library_id=pin.library_id,
                source_file=record.local_path,
                expected_sha256=intake.expected_sha256,
                license_status=intake.license_status,
                redistributable=intake.license_status == "redistributable",
                source_url=intake.source_url,
            ),
            repository_root=repository_root,
            private_asset_root=private_asset_root,
        )
        validate_pin(
            pin.model_copy(update={"local_path": installed.local_path}), Path(installed.local_path)
        )
        return {
            "status": "installed",
            "path": installed.local_path,
            "sha256": installed.sha256,
            "fetch_count": (record.retrieval.attempt_count if record.retrieval else 1)
            if record.status == "downloaded"
            else 0,
            "source_sha256": intake.expected_sha256,
        }
