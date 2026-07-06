"""Component cards: the machine-checkable contract for using a part.

One JSON per part under ``ai_assets/components/`` (hardening plan 6.2).
A card records what the datasheet says about HOW to use the part - pin
function classes and connection requirements, reviewed no-connects,
mandatory support parts, and operating limits - with page locators, so
compositions and boards can be validated against it instead of against
session memory.

Cards are cross-checked against two independent sources: the official
KiCad symbol (pin numbers, names, electrical types) and the footprint
(pad census). A card that disagrees with either never validates.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from pcbsmith.circuit.models import ReviewFinding
from pcbsmith.kicad.board import FOOTPRINT_LIBRARY, BoardNetlist

CARDS_DIR = Path(__file__).resolve().parents[2] / "ai_assets" / "components"

PinRequirement = Literal[
    "required",     # must be on some net
    "must_tie",     # must be on the net mapped from tie_class
    "optional",     # may be connected or left open
    "nc_allowed",   # documented as safe to leave unconnected
    "nc_reserved",  # documented as MUST NOT connect (RESV/NC)
]


class CardPin(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    number: str
    name: str
    function: str  # power_in, gnd, output, feedback, enable, gpio, ...
    requirement: PinRequirement
    tie_class: str | None = None  # for must_tie: e.g. "GND"
    note: str = ""
    locator: str = ""  # datasheet page/section


class SupportPart(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    role: str
    note: str = ""
    locator: str = ""


class DatasheetRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    local_path: str = ""
    sha256: str = ""
    source_url: str = ""


class ComponentCard(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["pcbsmith-component-card-v1"] = "pcbsmith-component-card-v1"
    mpn: str
    manufacturer: str = ""
    description: str = ""
    symbol: str  # official KiCad lib id
    footprint: str  # official KiCad lib id
    datasheet: DatasheetRef = DatasheetRef()
    support_status: Literal["draft", "needs_datasheet_review", "reviewed"] = "draft"
    pins: tuple[CardPin, ...] = ()
    required_support: tuple[SupportPart, ...] = ()
    limits: dict[str, float] = {}

    def nc_pins(self) -> tuple[str, ...]:
        return tuple(
            pin.number
            for pin in self.pins
            if pin.requirement in ("nc_allowed", "nc_reserved", "optional")
        )


class ComponentCardError(RuntimeError):
    pass


def card_path(mpn: str) -> Path:
    safe = mpn.replace("/", "_").replace(":", "_")
    return CARDS_DIR / f"{safe}.json"


def load_card(mpn: str) -> ComponentCard:
    path = card_path(mpn)
    if not path.exists():
        raise ComponentCardError(f"No component card for {mpn} at {path}.")
    return ComponentCard.model_validate_json(path.read_text(encoding="utf-8"))


def validate_card_against_libraries(card: ComponentCard) -> tuple[str, ...]:
    """Census the card against the official symbol and footprint. Returns
    human-readable problems (empty = consistent)."""
    from pcbsmith.kicad.symbols import load_symbol

    problems: list[str] = []
    try:
        symbol = load_symbol(card.symbol)
    except Exception as exc:  # noqa: BLE001 - report, don't crash
        return (f"Symbol {card.symbol} failed to load: {exc}",)
    symbol_numbers = {pin.number for pin in symbol.pins}
    card_numbers = {pin.number for pin in card.pins}
    if symbol_numbers != card_numbers:
        problems.append(
            f"Pin census mismatch vs symbol {card.symbol}: card-only "
            f"{sorted(card_numbers - symbol_numbers)}, symbol-only "
            f"{sorted(symbol_numbers - card_numbers)}."
        )
    if card.footprint in FOOTPRINT_LIBRARY:
        pads = FOOTPRINT_LIBRARY[card.footprint].pads
    else:
        # New parts: census against the official library directly.
        from pcbsmith.kicad.library import load_footprint

        try:
            pads = load_footprint(card.footprint).spec.pads
        except Exception as exc:  # noqa: BLE001 - report, don't crash
            return (
                *problems,
                f"Footprint {card.footprint} failed to load: {exc}",
            )
    pad_numbers = {pad.name for pad in pads if pad.name}
    missing = card_numbers - pad_numbers
    if missing:
        problems.append(
            f"Card pins {sorted(missing)} have no pad on {card.footprint}."
        )
    return tuple(problems)


def card_contract_findings(
    card: ComponentCard,
    reference: str,
    netlist: BoardNetlist,
    tie_nets: dict[str, str],
) -> tuple[ReviewFinding, ...]:
    """Rule 7.4: the part's netlist connectivity must honour its card."""
    net_of = {
        (component_ref, pin): net.name
        for net in netlist.nets
        for component_ref, pin in net.nodes
    }
    findings: list[ReviewFinding] = []

    def finding(pin: CardPin, evidence: str, action: str) -> ReviewFinding:
        return ReviewFinding(
            rule="7.4",
            severity="blocker",
            scope="component",
            where=reference,
            evidence=(
                f"{reference} pin {pin.number} ({pin.name}, card "
                f"{card.mpn}): {evidence}"
            ),
            suggested_action=action,
            source="check",
        )

    for pin in card.pins:
        net = net_of.get((reference, pin.number))
        if pin.requirement == "required" and net is None:
            findings.append(
                finding(
                    pin,
                    "required by the card but on no net.",
                    f"Wire the pin per the datasheet ({pin.locator}).",
                )
            )
        elif pin.requirement == "must_tie":
            target = tie_nets.get(pin.tie_class or "")
            if target is None:
                findings.append(
                    finding(
                        pin,
                        f"must tie to {pin.tie_class} but the authority "
                        "provided no net mapping for that class.",
                        "Pass the tie-class net map to the design checks.",
                    )
                )
            elif net != target:
                findings.append(
                    finding(
                        pin,
                        f"must tie to {pin.tie_class} ({target}) but is on "
                        f"{net or 'no net'}.",
                        f"Tie the pin to {target} ({pin.note or pin.locator}).",
                    )
                )
        elif pin.requirement == "nc_reserved" and net is not None:
            findings.append(
                finding(
                    pin,
                    f"is reserved (must not connect) but is on {net}.",
                    "Disconnect the pin; the datasheet forbids connection.",
                )
            )
    return tuple(findings)


_ETYPE_DEFAULTS: dict[str, tuple[str, PinRequirement]] = {
    "power_in": ("power_in", "required"),
    "power_out": ("power_out", "required"),
    "input": ("input", "required"),
    "output": ("output", "optional"),
    "bidirectional": ("gpio", "optional"),
    "passive": ("passive", "required"),
    "no_connect": ("nc", "nc_reserved"),
    "open_collector": ("output", "optional"),
    "open_emitter": ("output", "optional"),
    "tri_state": ("output", "optional"),
    "free": ("other", "optional"),
    "unspecified": ("other", "optional"),
}


def draft_card_from_symbol(
    mpn: str,
    symbol_id: str,
    footprint_id: str,
    *,
    manufacturer: str = "",
    datasheet: DatasheetRef | None = None,
) -> ComponentCard:
    """A DRAFT card seeded from the official symbol's pin table. The
    electrical types give first-guess function classes and requirements;
    a human (or a validated extraction) must review before the card is
    trusted - drafts never claim more than the symbol knows."""
    from pcbsmith.kicad.symbols import load_symbol

    symbol = load_symbol(symbol_id)
    pins = []
    for symbol_pin in sorted(symbol.pins, key=lambda p: (len(p.number), p.number)):
        function, requirement = _ETYPE_DEFAULTS.get(
            symbol_pin.electrical_type, ("other", "optional")
        )
        if symbol_pin.name.upper() in ("GND", "VSS", "GNDA", "AGND"):
            function = "gnd"
        pins.append(
            CardPin(
                number=symbol_pin.number,
                name=symbol_pin.name,
                function=function,
                requirement=requirement,
                note=f"DRAFT: defaulted from symbol pin type "
                     f"'{symbol_pin.electrical_type}'; review the datasheet.",
            )
        )
    return ComponentCard(
        mpn=mpn,
        manufacturer=manufacturer,
        description=f"DRAFT card seeded from {symbol_id}",
        symbol=symbol_id,
        footprint=footprint_id,
        datasheet=datasheet or DatasheetRef(),
        support_status="draft",
        pins=tuple(pins),
    )


def save_card(card: ComponentCard) -> Path:
    path = card_path(card.mpn)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        card.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    return path
