from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcbsmith.evidence.part_discovery import (
    PartResourceRole,
    installed_part_resource_from_asset,
)
from pcbsmith.kicad.asset_install import (
    KiCadAssetInstallRequest,
    install_kicad_asset,
    write_public_asset_record,
)


def test_private_footprint_installs_outside_repository_and_public_record_is_redacted(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sensor.kicad_mod"
    source.write_text('(footprint "Sensor" (layer "F.Cu"))', encoding="utf-8")
    request = KiCadAssetInstallRequest(
        asset_id="sensor-footprint",
        kind="footprint",
        source_file=str(source),
        library_id="Vendor:Sensor",
        license_status="local_cache_only",
    )

    asset = install_kicad_asset(
        request,
        repository_root=tmp_path / "repo",
        private_asset_root=tmp_path / "private",
    )
    public = tmp_path / "repo" / "asset-record.json"
    write_public_asset_record(public, asset)
    payload = json.loads(public.read_text("utf-8"))

    assert asset.destination_scope == "private"
    assert Path(asset.local_path).is_file()
    assert "local_path" not in payload
    assert not (tmp_path / "repo" / "ai_assets" / "kicad_footprints").exists()


def test_redistributable_symbol_is_normalized_into_repository_vendor_layout(
    tmp_path: Path,
) -> None:
    source = tmp_path / "symbols.kicad_sym"
    source.write_text(
        '(kicad_symbol_lib (version 20241209) (symbol "SHT31" (property "Reference" "U")))',
        encoding="utf-8",
    )
    request = KiCadAssetInstallRequest(
        asset_id="sht31-symbol",
        kind="symbol",
        source_file=str(source),
        library_id="Sensor:SHT31",
        license_status="redistributable",
        redistributable=True,
    )

    asset = install_kicad_asset(
        request,
        repository_root=tmp_path / "repo",
        private_asset_root=tmp_path / "private",
    )

    installed = Path(asset.local_path)
    assert asset.destination_scope == "repository"
    assert installed == (
        tmp_path / "repo" / "ai_assets" / "kicad_symbols" / "Sensor__SHT31.kicad_sym"
    )
    assert "PCBSmith-asset-install" in installed.read_text("utf-8")


def test_model_install_produces_registry_override_for_preflight_and_rendering(
    tmp_path: Path,
) -> None:
    source = tmp_path / "module.step"
    source.write_bytes(b"ISO-10303-21;\nEND-ISO-10303-21;")
    request = KiCadAssetInstallRequest(
        asset_id="oled-module",
        kind="model",
        source_file=str(source),
        model_raw_path="${PCBSMITH_3DMODEL_DIR}/oled.step",
        model_classification="complete_module",
        part_number="OLED-128X64-I2C",
        source_revision="fixture-r1",
        license_status="local_cache_only",
    )

    asset = install_kicad_asset(
        request,
        repository_root=tmp_path / "repo",
        private_asset_root=tmp_path / "private",
    )

    assert asset.model_registry_entry is not None
    assert asset.model_registry_entry.local_path == asset.local_path
    assert asset.model_registry_entry.classification == "complete_module"
    assert asset.schema_id == "pcbsmith-installed-kicad-asset-v2"
    installed_identity = installed_part_resource_from_asset(
        manufacturer="Fixture Displays",
        part_number="OLED-128X64-I2C",
        role=PartResourceRole.MODEL_3D,
        asset=asset,
    )
    assert installed_identity.installed_asset_sha256 == asset.sha256
    assert installed_identity.part_number == "OLED-128X64-I2C"
    assert installed_identity.source_revision == "fixture-r1"


def test_repository_install_rejects_unapproved_redistribution(tmp_path: Path) -> None:
    source = tmp_path / "part.step"
    source.write_bytes(b"ISO-10303-21; fixture")
    request = KiCadAssetInstallRequest(
        asset_id="part",
        kind="model",
        source_file=str(source),
        model_raw_path="part.step",
        model_classification="exact_package",
        license_status="local_cache_only",
        redistributable=True,
    )

    with pytest.raises(ValueError, match="redistributable license"):
        install_kicad_asset(
            request,
            repository_root=tmp_path / "repo",
            private_asset_root=tmp_path / "private",
        )
