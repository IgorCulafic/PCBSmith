from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.circuit.intent import classify_circuit_intent
from pcbsmith.circuit.topologies import select_topology
from pcbsmith.evidence.cache import EvidenceCache
from pcbsmith.evidence.divider_highpass_led import apply_component_selection
from pcbsmith.evidence.lm2596_buck import select_lm2596_buck_components
from pcbsmith.generation.lm2596_buck import compose_lm2596_buck

MANIFEST = (
    Path(__file__).resolve().parents[3]
    / "ai_assets"
    / "evidence"
    / "lm2596-buck.manifest.json"
)


def _circuit():
    intent = classify_circuit_intent(
        "Make the LM2596 DC-DC Buck Converter Step-Down Power Module"
    )
    return compose_lm2596_buck(intent, select_topology(intent))


def test_real_manifest_validates_the_regulator() -> None:
    circuit = _circuit()
    cache = EvidenceCache.from_manifest(MANIFEST)

    report = select_lm2596_buck_components(circuit, cache)

    assert report.selections[0].status == "selected"
    # The passives are honestly not covered, so never better than review.
    assert report.status == "needs_human_review"

    updated = apply_component_selection(circuit, report)
    by_ref = {component.reference: component for component in updated.components}
    assert by_ref["U1"].support_status == "supported"
    assert any(
        evidence.kind == "component_fact" for evidence in by_ref["U1"].evidence
    )


def test_conflicting_vref_fails_validation(tmp_path: Path) -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for fact in manifest["components"][0]["facts"]:
        if fact["name"] == "feedback_reference_v_typ":
            fact["value"] = 0.8
    bad = tmp_path / "bad.manifest.json"
    bad.write_text(json.dumps(manifest), encoding="utf-8")

    report = select_lm2596_buck_components(
        _circuit(), EvidenceCache.from_manifest(bad)
    )

    assert report.status == "failed"
    assert any("feedback reference" in finding for finding in report.findings)
