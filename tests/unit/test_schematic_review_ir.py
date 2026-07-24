from __future__ import annotations

import pytest
from pydantic import ValidationError

from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.evidence.component_pin_evidence import (
    ComponentPinEvidence,
    DatasheetPackageEvidence,
    DatasheetPinEvidence,
)
from pcbsmith.evidence.models import EvidenceLocator
from pcbsmith.kicad.board import BoardComponent, BoardNet, BoardNetlist
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.schematic_review_ir import (
    ComponentReviewResult,
    ReviewApplicability,
    ReviewArea,
    ReviewRunOutcome,
    build_component_review_manifest,
    build_component_review_neighborhood,
    derive_component_review_obligations,
)
from pcbsmith.semantic_ir import SemanticDisposition


def _component(reference: str, value: str) -> BoardComponent:
    return BoardComponent(
        reference=reference,
        value=value,
        footprint="Test:Part",
        uuid_path=stable_kicad_uuid("test-review", reference),
    )


def _pin_evidence() -> ComponentPinEvidence:
    locator = EvidenceLocator(
        local_file="datasheets/MCU-8.pdf",
        page=3,
        table="Pin configuration",
    )
    pin_rows = (
        ("1", "VDD", "supply"),
        ("2", "GND", "ground"),
        ("3", "RESET_N", "configuration"),
        ("4", "XTAL_IN", "clock"),
        ("5", "XTAL_OUT", "clock"),
        ("6", "SDA", "signal"),
        ("7", "SCL", "signal"),
        ("8", "NC", "no_connect"),
    )
    return ComponentPinEvidence(
        manufacturer="Example",
        part_number="MCU-8",
        source_sha256="a" * 64,
        source_local_path="datasheets/MCU-8.pdf",
        extraction_status="machine_extracted",
        package=DatasheetPackageEvidence(
            package_name="SOIC-8",
            exact_variant="MCU-8",
            pin_count=8,
            locator=EvidenceLocator(
                local_file="datasheets/MCU-8.pdf",
                page=2,
                section="Package information",
            ),
        ),
        pins=tuple(
            DatasheetPinEvidence(
                number=number,
                name=name,
                electrical_role=role,
                locator=locator,
            )
            for number, name, role in pin_rows
        ),
    )


def _netlist() -> BoardNetlist:
    return BoardNetlist(
        components=(
            _component("U1", "MCU-8"),
            _component("U2", "SENSOR-4"),
            _component("C1", "100nF"),
            _component("R1", "10k"),
            _component("Y1", "16MHz"),
        ),
        nets=(
            BoardNet("+3V3", (("U1", "1"), ("C1", "1"), ("R1", "1"))),
            BoardNet("GND", (("U1", "2"), ("C1", "2"), ("U2", "2"))),
            BoardNet("RESET", (("U1", "3"), ("R1", "2"))),
            BoardNet("XTAL_A", (("U1", "4"), ("Y1", "1"))),
            BoardNet("XTAL_B", (("U1", "5"), ("Y1", "2"))),
            BoardNet("I2C_SDA", (("U1", "6"), ("U2", "3"))),
            BoardNet("I2C_SCL", (("U1", "7"), ("U2", "4"))),
        ),
    )


def _source() -> EvidenceRef:
    return EvidenceRef(
        kind="datasheet",
        title="MCU-8 datasheet",
        locator="page 3, pin configuration",
        source_id="datasheet:MCU-8",
        local_sha256="a" * 64,
        source_status="pinned",
        locator_status="text_verified",
        applicability_status="confirmed",
    )


def test_neighborhood_exposes_missing_pin_neighbors_and_bridges() -> None:
    neighborhood = build_component_review_neighborhood(
        _netlist(), _pin_evidence(), "U1"
    )

    assert neighborhood.missing_datasheet_pin_numbers == ("8",)
    assert neighborhood.orphan_schematic_pin_numbers == ()
    sda = next(pin for pin in neighborhood.pins if pin.pin_number == "6")
    assert sda.net_name == "I2C_SDA"
    assert sda.neighbors[0].component_reference == "U2"
    assert {bridge.component_reference for bridge in neighborhood.bridges} == {
        "C1",
        "R1",
        "U2",
        "Y1",
    }


def test_obligations_cover_each_relevant_area_and_cross_ic_interface() -> None:
    neighborhood = build_component_review_neighborhood(
        _netlist(), _pin_evidence(), "U1"
    )
    obligations = derive_component_review_obligations(neighborhood)

    assert {item.area for item in obligations} == set(ReviewArea)
    interface = next(item for item in obligations if item.area is ReviewArea.INTERFACE)
    assert interface.neighbor_component_references == ("U2",)
    assert interface.net_names == ("I2C_SCL", "I2C_SDA")
    assert interface.applicability is ReviewApplicability.APPLICABLE
    unused = next(item for item in obligations if item.area is ReviewArea.UNUSED_PINS)
    assert unused.pin_numbers == ("8",)


def test_manifest_rejects_missing_coverage_and_query_budget_overrun() -> None:
    neighborhood = build_component_review_neighborhood(
        _netlist(), _pin_evidence(), "U1"
    )
    obligations = derive_component_review_obligations(neighborhood)
    results = tuple(_result_for(item) for item in obligations)

    with pytest.raises(ValidationError, match="coverage is not closed"):
        build_component_review_manifest(
            project_id="fixture",
            board_revision="r001",
            netlist=_netlist(),
            neighborhood=neighborhood,
            obligations=obligations,
            results=results[:-1],
            trace_ids=("trace:U1",),
        )
    with pytest.raises(ValidationError, match="exceeds"):
        ComponentReviewResult(
            obligation_id=obligations[0].obligation_id,
            disposition=SemanticDisposition.UNVERIFIED,
            rationale="Evidence retrieval budget was exhausted.",
            evidence_query_count=3,
            evidence_query_budget=2,
        )


def test_complete_manifest_is_replay_bound_and_derives_outcome() -> None:
    netlist = _netlist()
    neighborhood = build_component_review_neighborhood(
        netlist, _pin_evidence(), "U1"
    )
    obligations = derive_component_review_obligations(neighborhood)
    results = tuple(_result_for(item) for item in obligations)

    manifest = build_component_review_manifest(
        project_id="fixture",
        board_revision="r001",
        netlist=netlist,
        neighborhood=neighborhood,
        obligations=obligations,
        results=results,
        trace_ids=("trace:U1",),
    )

    assert manifest.outcome is ReviewRunOutcome.COMPLETE
    assert len(manifest.results) == len(manifest.obligations)
    with pytest.raises(ValidationError, match="fingerprint is stale"):
        type(manifest).model_validate(
            manifest.model_dump() | {"manifest_fingerprint": "b" * 64}
        )


def test_unresolved_applicability_cannot_be_claimed_as_pass() -> None:
    neighborhood = build_component_review_neighborhood(
        _netlist(), _pin_evidence(), "U1"
    )
    obligation = derive_component_review_obligations(neighborhood)[0].model_copy(
        update={"applicability": ReviewApplicability.UNRESOLVED}
    )
    result = ComponentReviewResult(
        obligation_id=obligation.obligation_id,
        disposition=SemanticDisposition.PASS,
        rationale="Incorrect hard pass.",
        check_ids=("check:fixture",),
        evidence_query_count=0,
        evidence_query_budget=2,
    )
    with pytest.raises(ValidationError, match="unresolved obligation"):
        build_component_review_manifest(
            project_id="fixture",
            board_revision="r001",
            netlist=_netlist(),
            neighborhood=neighborhood,
            obligations=(obligation,),
            results=(result,),
            trace_ids=("trace:U1",),
        )


def _result_for(obligation) -> ComponentReviewResult:
    if obligation.applicability is ReviewApplicability.NOT_APPLICABLE:
        return ComponentReviewResult(
            obligation_id=obligation.obligation_id,
            disposition=SemanticDisposition.NOT_APPLICABLE,
            rationale=obligation.rationale,
            evidence_query_count=0,
            evidence_query_budget=2,
        )
    return ComponentReviewResult(
        obligation_id=obligation.obligation_id,
        disposition=SemanticDisposition.PASS,
        rationale="Checked against the exact netlist and cited datasheet.",
        check_ids=(f"check:{obligation.area.value}",),
        evidence=(_source(),),
        evidence_query_count=1,
        evidence_query_budget=2,
    )
