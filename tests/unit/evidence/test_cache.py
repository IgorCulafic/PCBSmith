from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pcbsmith.evidence import EvidenceCache, EvidenceManifest

FIXTURE_MANIFEST = Path("tests/fixtures/evidence/divider_highpass_led_complete.json")


def test_evidence_cache_loads_manifest_and_resolves_cached_files() -> None:
    cache = EvidenceCache.from_manifest(FIXTURE_MANIFEST)

    component = cache.first_component_for_role("divider_top")

    assert component is not None
    assert component.part_number == "FIX-10K-0603-R1"
    assert component.fact("resistance_ohms").value == 10000.0
    assert cache.cached_files
    assert all(path.is_absolute() for path in cache.cached_files)
    assert cache.cached_files[0].name == "fixture-passives-led.txt"


def test_evidence_cache_reports_missing_role_without_fetching() -> None:
    cache = EvidenceCache.from_manifest(FIXTURE_MANIFEST)

    assert cache.components_for_role("buck_controller") == ()
    assert cache.first_component_for_role("buck_controller") is None


def test_evidence_manifest_rejects_unknown_schema(tmp_path: Path) -> None:
    manifest_path = tmp_path / "bad-evidence.json"
    data = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    data["schema"] = "wrong-schema"
    manifest_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValidationError):
        EvidenceManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))

