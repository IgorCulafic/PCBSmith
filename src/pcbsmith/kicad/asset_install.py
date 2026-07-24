"""Validated installation of downloaded KiCad symbols, footprints, and models.

Redistributable assets may be vendored into ``ai_assets``.  Everything else is
placed under an explicitly configured private root and loaded through
``PCBSMITH_PRIVATE_ASSET_ROOT``; the global KiCad installation is never mutated.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pcbsmith.evidence.source_intake import inspect_source_payload
from pcbsmith.kicad.library import QuotedString, SExpr, SList, parse_sexpr, serialize_sexpr
from pcbsmith.kicad.model_preflight import ModelClassification, ModelRegistryEntry


class KiCadAssetInstallRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    asset_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    kind: Literal["symbol", "footprint", "model"]
    source_file: str
    license_status: str = Field(min_length=1)
    redistributable: bool = False
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    library_id: str | None = None
    model_raw_path: str | None = None
    model_classification: ModelClassification | None = None
    part_number: str | None = None
    source_url: str | None = None
    source_revision: str | None = None


class InstalledKiCadAsset(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    schema_id: Literal[
        "pcbsmith-installed-kicad-asset-v1", "pcbsmith-installed-kicad-asset-v2"
    ] = Field(
        validation_alias="schema", serialization_alias="schema"
    )
    asset_id: str
    kind: Literal["symbol", "footprint", "model"]
    sha256: str
    byte_count: int
    license_status: str
    redistributable: bool
    destination_scope: Literal["repository", "private"]
    logical_path: str
    local_path: str
    library_id: str | None = None
    part_number: str | None = None
    source_url: str | None = None
    source_revision: str | None = None
    model_registry_entry: ModelRegistryEntry | None = None

    @model_validator(mode="after")
    def v2_identity_is_retained(self) -> InstalledKiCadAsset:
        if self.schema_id == "pcbsmith-installed-kicad-asset-v1" and (
            self.part_number is not None
            or self.source_url is not None
            or self.source_revision is not None
        ):
            raise ValueError("v1 installed-asset records cannot carry v2 part identity")
        return self


def install_kicad_asset(
    request: KiCadAssetInstallRequest,
    *,
    repository_root: Path,
    private_asset_root: Path,
) -> InstalledKiCadAsset:
    source = Path(request.source_file).resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    payload = source.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if request.expected_sha256 is not None and digest != request.expected_sha256:
        raise ValueError(
            f"Asset SHA-256 mismatch: expected {request.expected_sha256}, got {digest}."
        )
    if request.redistributable and request.license_status != "redistributable":
        raise ValueError("Repository installation requires redistributable license status.")
    scope: Literal["repository", "private"] = "repository" if request.redistributable else "private"
    base = (
        repository_root.resolve() / "ai_assets"
        if scope == "repository"
        else private_asset_root.resolve()
    )
    library_id = request.library_id
    model_entry: ModelRegistryEntry | None = None

    if request.kind == "footprint":
        library, name = _library_parts(library_id, "footprint")
        tree = parse_sexpr(payload.decode("utf-8"))
        if _head(tree) not in {"footprint", "module"}:
            raise ValueError("Footprint asset is not a KiCad footprint s-expression.")
        relative = Path("kicad_footprints" if scope == "repository" else "footprints") / (
            f"{library}__{name}.kicad_mod"
        )
        normalized_payload = (serialize_sexpr(tree) + "\n").encode("utf-8")
    elif request.kind == "symbol":
        library, name = _library_parts(library_id, "symbol")
        tree = parse_sexpr(payload.decode("utf-8"))
        symbol = _find_symbol(tree, name)
        if symbol is None:
            raise ValueError(f"Symbol asset does not contain the requested symbol {name}.")
        if _direct_children(symbol, "extends"):
            raise ValueError("Derived external symbols must be flattened before installation.")
        wrapper: SList = [
            "kicad_symbol_lib",
            ["version", "20241209"],
            ["generator", QuotedString("PCBSmith-asset-install")],
            symbol,
        ]
        safe_name = name.replace("/", "_")
        relative = Path("kicad_symbols" if scope == "repository" else "symbols") / (
            f"{library}__{safe_name}.kicad_sym"
        )
        normalized_payload = (serialize_sexpr(wrapper) + "\n").encode("utf-8")
    else:
        if request.model_raw_path is None or request.model_classification is None:
            raise ValueError("Model installation requires raw path and classification.")
        suffix = source.suffix.lower()
        expected_kind: Literal["vrml", "step"] = "vrml" if suffix == ".wrl" else "step"
        inspect_source_payload(payload, expected_kind=expected_kind)
        relative = Path("kicad_models" if scope == "repository" else "models") / (
            f"{request.asset_id}-{digest[:12]}{suffix}"
        )
        normalized_payload = payload

    destination = base / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and destination.read_bytes() != normalized_payload:
        raise ValueError(f"Refusing to overwrite a different installed asset: {destination}")
    destination.write_bytes(normalized_payload)
    installed_digest = hashlib.sha256(normalized_payload).hexdigest()
    if request.kind == "model":
        assert request.model_raw_path is not None
        assert request.model_classification is not None
        model_entry = ModelRegistryEntry(
            raw_path=request.model_raw_path,
            classification=request.model_classification,
            license_status=request.license_status,
            part_number=request.part_number,
            source_url=request.source_url,
            local_path=str(destination),
            expected_sha256=installed_digest,
            redistributable=request.redistributable,
        )
    return InstalledKiCadAsset(
        schema_id="pcbsmith-installed-kicad-asset-v2",
        asset_id=request.asset_id,
        kind=request.kind,
        sha256=installed_digest,
        byte_count=len(normalized_payload),
        license_status=request.license_status,
        redistributable=request.redistributable,
        destination_scope=scope,
        logical_path=relative.as_posix(),
        local_path=str(destination),
        library_id=library_id,
        part_number=request.part_number,
        source_url=request.source_url,
        source_revision=request.source_revision,
        model_registry_entry=model_entry,
    )


def write_public_asset_record(path: Path, asset: InstalledKiCadAsset) -> None:
    """Write commit-safe metadata without the private absolute destination."""
    payload = asset.model_dump(mode="json", by_alias=True, exclude={"local_path"})
    if asset.destination_scope == "private" and payload.get("model_registry_entry"):
        payload["model_registry_entry"].pop("local_path", None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _library_parts(library_id: str | None, kind: str) -> tuple[str, str]:
    if library_id is None or ":" not in library_id:
        raise ValueError(f"{kind.capitalize()} installation requires Library:Name.")
    return tuple(library_id.split(":", 1))  # type: ignore[return-value]


def _find_symbol(root: SList, name: str) -> SList | None:
    if _head(root) == "symbol" and len(root) > 1 and _atom(root[1]) == name:
        return root
    return next(
        (
            child
            for child in _direct_children(root, "symbol")
            if len(child) > 1 and _atom(child[1]) == name
        ),
        None,
    )


def _direct_children(node: SList, head: str) -> tuple[SList, ...]:
    return tuple(
        child for child in node if isinstance(child, list) and child and _head(child) == head
    )


def _head(node: SList) -> str:
    return _atom(node[0]) if node else ""


def _atom(node: SExpr) -> str:
    if isinstance(node, QuotedString):
        return node.value
    if isinstance(node, str):
        return node
    raise ValueError("Expected a KiCad atom.")
