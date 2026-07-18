from __future__ import annotations

import warnings

from pcbsmith.circuit import (
    AuthorityStatus,
    CircuitIntent,
    CircuitReviewBundle,
    ComponentRole,
    EvidenceRef,
    EvidenceReport,
    KiCadReport,
    ReconciliationReport,
    RevisionRecord,
    SimulationReport,
    TopologySelection,
)
from pcbsmith.circuit.models import ReviewFinding


def test_circuit_intent_records_supported_scope() -> None:
    intent = CircuitIntent(
        raw_request="voltage divider to high-pass filter and LED indicator",
        intent_id="divider_highpass_led_indicator",
        status="supported",
        assumptions={"supply_voltage_v": 5.0},
        unsupported_reasons=(),
    )

    assert intent.intent_id == "divider_highpass_led_indicator"
    assert intent.status == "supported"
    assert intent.assumptions["supply_voltage_v"] == 5.0


def test_topology_selection_requires_evidence() -> None:
    selection = TopologySelection(
        topology_id="divider_highpass_led_indicator",
        title="Voltage divider, AC-coupled high-pass, LED indicator",
        status="selected",
        evidence=(
            EvidenceRef(
                kind="textbook_formula",
                title="Voltage divider equation",
                locator="Vout = Vin * Rbottom / (Rtop + Rbottom)",
            ),
            EvidenceRef(
                kind="textbook_formula",
                title="RC high-pass cutoff equation",
                locator="fc = 1 / (2*pi*R*C)",
            ),
        ),
        warnings=("Generic LED model requires human review for real brightness.",),
    )

    assert len(selection.evidence) == 2
    assert selection.status == "selected"


def test_component_role_is_explicit_about_demo_support() -> None:
    role = ComponentRole(
        reference="D1",
        role="indicator_led",
        symbol_id="stdlib:LED",
        value="Generic red LED, Vf=2.0V assumption",
        support_status="demo_only",
        evidence=(
            EvidenceRef(
                kind="assumption",
                title="Generic indicator LED assumption",
                locator="Requires replacement with datasheet-backed part before fabrication.",
            ),
        ),
    )

    assert role.support_status == "demo_only"


def test_review_bundle_status_is_not_passed_when_human_review_is_required() -> None:
    with warnings.catch_warnings(record=True) as captured:
        warnings.simplefilter("always")
        bundle = CircuitReviewBundle(
            schema="pcbsmith-circuit-review-bundle-v1",
            intent_id="divider_highpass_led_indicator",
            status="needs_human_review",
            items=("Generic LED is demo-only.",),
            simulation=SimulationReport(backend="ngspice", status="unavailable"),
            artifacts={},
        )

    assert bundle.status == "needs_human_review"
    assert bundle.model_dump(by_alias=True)["schema"] == "pcbsmith-circuit-review-bundle-v1"
    assert captured == []


def test_authority_models_separate_kicad_and_reconciliation() -> None:
    status: AuthorityStatus = "not_run"
    kicad = KiCadReport(
        status="passed",
        schematic_file="Slice.kicad_sch",
        erc_report="erc.json",
        spice_netlist="Slice.cir",
        findings=(),
    )
    evidence = EvidenceReport(
        status=status,
        findings=(),
        cached_files=("datasheet.pdf",),
    )
    reconciliation = ReconciliationReport(
        status="warning",
        checks=("component references matched KiCad export",),
        findings=("Generic LED still needs datasheet-backed model.",),
    )
    revision = RevisionRecord(
        revision_id="rev-1",
        parent_revision_id=None,
        changed_artifacts=("Slice.kicad_sch",),
        authority_checks=("kicad_erc", "spice_export"),
        findings=("KiCad ERC passed.",),
        next_action="Run ngspice from KiCad-exported SPICE netlist.",
    )

    assert kicad.status == "passed"
    assert evidence.status == "not_run"
    assert evidence.cached_files == ("datasheet.pdf",)
    assert reconciliation.status == "warning"
    assert revision.revision_id == "rev-1"


def test_evidence_ref_carries_authority_and_applicability() -> None:
    evidence = EvidenceRef(
        kind="standard_table",
        title="Scoped fabrication rule",
        locator="Table 1",
        source_id="example-standard",
        organization_or_author="Example body",
        revision="2026",
        official_url="https://example.invalid/standard",
        local_sha256="a" * 64,
        source_status="pinned",
        locator_status="figure_verified",
        applicability_status="conditional",
        required_conditions=("declared fabrication profile",),
        exclusions=("safety insulation approval",),
        origin_id="rule:ordinary-spacing",
    )

    assert evidence.source_status == "pinned"
    assert evidence.locator_status == "figure_verified"
    assert evidence.applicability_status == "conditional"
    assert evidence.exclusions == ("safety insulation approval",)


def test_review_finding_fingerprint_is_stable_for_same_semantic_identity() -> None:
    first = ReviewFinding(
        rule="R1.spacing",
        severity="blocker",
        scope="net",
        where="/A to /B",
        evidence="First wording",
        suggested_action="Move the traces.",
        source="check",
        phase="physical_validation",
        category="ordinary_clearance",
        net_refs=("/A", "/B"),
        constraint_ids=("fab:clearance",),
    )
    revised_wording = first.model_copy(
        update={"evidence": "Improved explanatory wording"},
    )

    assert first.fingerprint is not None
    assert first.fingerprint.startswith("pcbsmith:")
    assert revised_wording.fingerprint == first.fingerprint


def test_review_finding_fingerprint_changes_with_referenced_objects() -> None:
    common = dict(
        rule="R1.spacing",
        severity="blocker",
        scope="net",
        where="pair",
        evidence="Too close",
        suggested_action="Move the traces.",
        source="check",
        phase="physical_validation",
        category="ordinary_clearance",
        constraint_ids=("fab:clearance",),
    )
    first = ReviewFinding(**common, net_refs=("/A", "/B"))
    second = ReviewFinding(**common, net_refs=("/A", "/C"))

    assert first.fingerprint != second.fingerprint
