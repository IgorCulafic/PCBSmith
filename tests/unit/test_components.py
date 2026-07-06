from __future__ import annotations

from pcbsmith.components import (
    card_contract_findings,
    draft_card_from_symbol,
    load_card,
    validate_card_against_libraries,
)
from pcbsmith.kicad.board import BoardNet, BoardNetlist

SHIPPED = ("LM2596S-ADJ", "MPU-6050", "ATtiny84A-SSU", "MMBT3904")


def test_shipped_cards_census_clean() -> None:
    for mpn in SHIPPED:
        card = load_card(mpn)
        assert validate_card_against_libraries(card) == (), mpn


def test_must_tie_contract_flags_a_floating_enable() -> None:
    card = load_card("LM2596S-ADJ")
    # ON/OFF (pin 5) wired to VIN instead of GND: a running-but-wrong board.
    netlist = BoardNetlist(
        components=(),
        nets=(
            BoardNet(name="/VIN", nodes=(("U1", "1"), ("U1", "5"))),
            BoardNet(name="/SW", nodes=(("U1", "2"),)),
            BoardNet(name="/GND", nodes=(("U1", "3"),)),
            BoardNet(name="/FB", nodes=(("U1", "4"),)),
        ),
    )
    findings = card_contract_findings(card, "U1", netlist, {"GND": "/GND"})
    assert len(findings) == 1
    assert "must tie to GND" in findings[0].evidence

    good = BoardNetlist(
        components=(),
        nets=(
            BoardNet(name="/VIN", nodes=(("U1", "1"),)),
            BoardNet(name="/SW", nodes=(("U1", "2"),)),
            BoardNet(name="/GND", nodes=(("U1", "3"), ("U1", "5"))),
            BoardNet(name="/FB", nodes=(("U1", "4"),)),
        ),
    )
    assert card_contract_findings(card, "U1", good, {"GND": "/GND"}) == ()


def test_reserved_pin_connection_is_flagged() -> None:
    card = load_card("MPU-6050")
    netlist = BoardNetlist(
        components=(),
        nets=(BoardNet(name="/GND", nodes=(("U1", "19"),)),),  # RESV!
    )
    findings = card_contract_findings(card, "U1", netlist, {"GND": "/GND"})
    assert any("reserved" in finding.evidence for finding in findings)


def test_draft_card_defaults_from_symbol_pin_types() -> None:
    card = draft_card_from_symbol(
        "TEST-MMBT", "Transistor_BJT:MMBT3904",
        "Package_TO_SOT_SMD:SOT-23",
    )
    assert card.support_status == "draft"
    assert {pin.number for pin in card.pins} == {"1", "2", "3"}
    assert validate_card_against_libraries(card) == ()


def test_missing_catch_diode_is_flagged() -> None:
    from pcbsmith.components import support_findings

    card = load_card("LM2596S-ADJ")
    complete = {
        "buck_regulator", "catch_diode", "power_inductor",
        "output_capacitor", "input_capacitor",
    }
    assert support_findings(card, "U1", complete) == ()

    missing = complete - {"catch_diode"}
    findings = support_findings(card, "U1", missing)
    assert len(findings) == 1
    assert findings[0].rule == "7.5"
    assert "catch_diode" in findings[0].evidence
