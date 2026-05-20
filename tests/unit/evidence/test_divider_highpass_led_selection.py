from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.evidence import EvidenceCache
from pcbsmith.evidence.divider_highpass_led import (
    apply_component_selection,
    select_divider_highpass_led_components,
)
from pcbsmith.generation.divider_highpass_led import compose_divider_highpass_led

FIXTURE_MANIFEST = Path("tests/fixtures/evidence/divider_highpass_led_complete.json")


def _circuit():
    intent = classify_circuit_intent("voltage divider high-pass LED indicator")
    return compose_divider_highpass_led(intent, select_topology(intent))


def test_selects_all_divider_highpass_led_components_from_cache() -> None:
    circuit = _circuit()
    cache = EvidenceCache.from_manifest(FIXTURE_MANIFEST)

    report = select_divider_highpass_led_components(circuit, cache)
    enriched = apply_component_selection(circuit, report)

    assert report.status == "passed"
    assert {selection.reference for selection in report.selections} == {
        "R1",
        "R2",
        "C1",
        "R3",
        "D1",
    }
    assert all(selection.status == "selected" for selection in report.selections)
    assert all(component.support_status == "supported" for component in enriched.components)
    assert enriched.components[-1].value == "Fixture red LED"
    assert "FIX-RED-LED-0603-D1" in enriched.components[-1].evidence[0].title
    assert "D1 fixture facts" in enriched.components[-1].evidence[0].locator


def test_missing_role_evidence_keeps_component_in_datasheet_review(tmp_path: Path) -> None:
    data = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    data["components"] = [
        component for component in data["components"] if component["role"] != "indicator_led"
    ]
    manifest_path = _write_temp_manifest(tmp_path, "missing-led.json", data)
    circuit = _circuit()

    report = select_divider_highpass_led_components(
        circuit,
        EvidenceCache.from_manifest(manifest_path),
    )
    enriched = apply_component_selection(circuit, report)

    d1 = next(component for component in enriched.components if component.reference == "D1")
    assert report.status == "needs_human_review"
    assert d1.support_status == "needs_datasheet_review"
    assert any("No cached evidence found for D1" in finding for finding in report.findings)


def test_under_rated_led_resistor_blocks_selection(tmp_path: Path) -> None:
    data = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    for component in data["components"]:
        if component["role"] == "led_current_limit":
            for fact in component["facts"]:
                if fact["name"] == "power_rating_w":
                    fact["value"] = 0.001
    manifest_path = _write_temp_manifest(tmp_path, "under-rated-r3.json", data)
    circuit = _circuit()

    report = select_divider_highpass_led_components(
        circuit,
        EvidenceCache.from_manifest(manifest_path),
    )
    enriched = apply_component_selection(circuit, report)

    r3 = next(component for component in enriched.components if component.reference == "R3")
    assert report.status == "failed"
    assert r3.support_status == "unsupported"
    assert any("R3 power rating" in finding for finding in report.findings)


def test_selector_skips_failed_candidate_when_later_cached_candidate_passes(
    tmp_path: Path,
) -> None:
    data = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    components = []
    for component in data["components"]:
        if component["role"] == "led_current_limit":
            bad_component = json.loads(json.dumps(component))
            bad_component["part_number"] = "FIX-680R-UNDER-RATED-FIRST"
            for fact in bad_component["facts"]:
                if fact["name"] == "power_rating_w":
                    fact["value"] = 0.001
            components.append(bad_component)
        components.append(component)
    data["components"] = components
    manifest_path = _write_temp_manifest(tmp_path, "choose-second-r3.json", data)

    report = select_divider_highpass_led_components(
        _circuit(),
        EvidenceCache.from_manifest(manifest_path),
    )

    r3_selection = next(selection for selection in report.selections if selection.reference == "R3")
    assert report.status == "passed"
    assert r3_selection.component is not None
    assert r3_selection.component.part_number == "FIX-680R-0603-R3"


def _write_temp_manifest(tmp_path: Path, filename: str, data: dict) -> Path:
    fixture_file = (FIXTURE_MANIFEST.parent / "fixture-passives-led.txt").resolve()
    for component in data["components"]:
        for cached_file in component["files"]:
            cached_file["local_path"] = str(fixture_file)
    manifest_path = tmp_path / filename
    manifest_path.write_text(json.dumps(data), encoding="utf-8")
    return manifest_path
