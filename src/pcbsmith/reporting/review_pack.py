"""Deterministic review pack: the artifacts a human reviewer wants.

Track 8.1 (docs/hardening-and-generalization-plan.md): Flux's
most-loved copilot features - block diagram, pin tables, FMEA, test
plan, BOM consolidation - need an LLM there because their design data
is a drawing. Ours is structured (roles, cards, nets, calculator
outputs), so every section here is generated deterministically and can
never hallucinate. The pack is one markdown file per revision,
registered in the review bundle as ``review_pack``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pcbsmith.circuit.models import ComponentRole

# Nets with more than this many members render as a bus node in the
# block diagram instead of a pairwise-edge clique.
_NET_NODE_THRESHOLD = 3


@dataclass(frozen=True)
class TestStep:
    __test__ = False  # not a pytest class, despite the name

    name: str
    procedure: str
    expected: str
    safety: str = ""


# Curated failure-mode knowledge per composition role. Coverage names
# the machine check, simulation, or finding that watches the mode -
# "bench only" is the honest value when nothing does.
ROLE_FMEA: dict[str, tuple[tuple[str, str, str], ...]] = {
    "fusible_input_resistor": (
        ("Fails open under surge", "Unit dead (safe state)",
         "By design - fusible part; SAFETY finding demands flameproof type"),
        ("Wrong (non-fusible) part fitted", "Fire risk under fault",
         "SAFETY finding requires review; bench only"),
    ),
    "input_mov": (
        ("Degrades after repeated surges", "Loss of surge protection",
         "Bench only - periodic replacement note"),
        ("Shorts at end of life", "Fusible resistor opens (safe state)",
         "Covered by fusible input resistor"),
    ),
    "bridge_rectifier": (
        ("One diode open", "Half-wave ripple, bulk voltage sags",
         "Test plan bulk-voltage step catches it"),
        ("Reversed installation", "Short across the line",
         "Polarity silk + pin-net table; ERC nets"),
    ),
    "bulk_capacitor": (
        ("Capacitance loss / ESR rise", "Ripple grows, switcher brownouts",
         "Calculator energy balance sets margin; test plan ripple step"),
        ("Reverse polarity", "Vent/failure",
         "Polarity silk mark (rule 8.1); assembly note"),
    ),
    "x2_line_capacitor": (
        ("Non-X2 part fitted", "Line-to-line fault not self-healing",
         "Value string demands X2; SAFETY finding; bench only"),
    ),
    "line_y_capacitor": (
        ("Non-Y-rated part fitted", "Line-to-earth shock hazard",
         "Value string demands Y1; rule 10.4 covers placement only"),
        ("Leakage current too high", "Touch current limit exceeded",
         "Bench only - measure per IEC 60990"),
    ),
    "earth_terminal": (
        ("Earth wire not landed", "Y-caps float, EMI path lost",
         "Test plan continuity step"),
    ),
    "bus_tvs": (
        ("Standoff below bus peak", "TVS conducts in normal operation",
         "Calculator drain/bus stress outputs; evidence note"),
    ),
    "flyback_switcher": (
        ("Drain overvoltage from leakage spike", "Device destroyed",
         "Clamp network (rule 7.5 required support); calculator drain_peak_v"),
        ("FB pin floating", "Output runs away",
         "ic_pin_connectivity (rule 7.3) + FB network required support"),
    ),
    "clamp_resistor": (
        ("Under-rated power", "Resistor burns",
         "Calculator clamp_dissipation_w warning"),
    ),
    "clamp_capacitor": (
        ("Voltage rating below clamp", "Cap fails short, clamp lost",
         "Value string states rating; evidence note; bench only"),
    ),
    "clamp_diode": (
        ("Too-slow recovery", "Clamp ineffective, drain spikes",
         "Value string demands fast type; bench only"),
    ),
    "vdd_capacitor": (
        ("Missing/open", "Switcher restarts erratically",
         "Rule 7.5 required support; ERC connectivity"),
    ),
    "flyback_transformer": (
        ("Insulation failure primary-secondary", "SHOCK HAZARD",
         "TRANSFORMER_SPEC finding demands reinforced insulation + review"),
        ("Wrong polarity (dot swap)", "Not a flyback; no regulation",
         "Pin-net table fixes dots; test plan startup step"),
    ),
    "secondary_rectifier": (
        ("PIV exceeded", "Rectifier shorts, output lost",
         "Calculator secondary_piv_v vs rating in evidence"),
    ),
    "output_capacitor": (
        ("ESR too high", "Output ripple out of spec",
         "Test plan ripple step"),
    ),
    "output_hf_capacitor": (
        ("Missing", "HF noise on the rail",
         "ERC connectivity; bench only for effect"),
    ),
    "feedback_optocoupler": (
        ("CTR degradation over life", "Regulation drifts",
         "Evidence note demands CTR bin; test plan regulation step"),
        ("Isolation failure", "SHOCK HAZARD",
         "Rule 10.1 covers spacing; certified part per SAFETY finding"),
    ),
    "shunt_reference": (
        ("Cathode current below minimum", "Reference unregulated",
         "Card required_support cathode_bias; ngspice .op verifies"),
    ),
    "feedback_upper_resistor": (
        ("Value drift", "Output voltage shifts",
         "ngspice .op checks divider at 1.24V; 1% parts"),
    ),
    "feedback_lower_resistor": (
        ("Value drift", "Output voltage shifts",
         "ngspice .op checks divider at 1.24V; 1% parts"),
    ),
    "opto_led_resistor": (
        ("Too large", "LED starves, loop opens",
         "ngspice .op checks LED current window"),
    ),
    "reference_bias_resistor": (
        ("Missing", "LMV431 below minimum cathode current",
         "Card required_support; ngspice .op"),
    ),
    "fb_pulldown_resistor": (
        ("Missing", "FB pin floats at startup",
         "Rule 7.5 required support"),
    ),
    "y_capacitor": (
        ("Non-Y-rated part fitted", "Barrier bridged unsafely",
         "SAFETY finding demands certified Y1; rule 10.1 spacing"),
    ),
    "feedback_comp_capacitor": (
        ("Populated when not needed", "Loop slows",
         "DNP by default; BOM note"),
    ),
    "test_point": (),
    "mains_input_terminal": (
        ("Under-rated for mains", "Contact failure/arcing",
         "Evidence note demands 300V/UL rating; bench only"),
    ),
    "output_terminal": (),
    # Buck converter roles.
    "buck_regulator": (
        ("Thermal shutdown under load", "Output drops out cyclically",
         "Thermal pour (rule 3.2); test plan load step"),
        ("Feedback pin open", "Output runs to Vin",
         "ic_pin_connectivity (rule 7.3); card must_tie contract"),
    ),
    "catch_diode": (
        ("Reversed installation", "Shoot-through, diode burns",
         "Polarity silk (rule 8.1); pin-net convention (rule 8.4)"),
        ("Under-rated current", "Overheats at load",
         "Card required_support sizing note; evidence"),
    ),
    "power_inductor": (
        ("Saturation at peak current", "Ripple spikes, regulation lost",
         "Calculator ripple sizing; test plan ripple step"),
    ),
    "input_capacitor": (
        ("Missing/high ESR", "Input transients reach the regulator",
         "Rule 7.5 required support; test plan"),
    ),
    "input_hf_capacitor": (
        ("Missing", "HF noise into the regulator",
         "Rule 7.5 required support"),
    ),
    "feedback_upper": (
        ("Value drift", "Output voltage shifts",
         "ngspice .op divider check; 1% parts"),
    ),
    "feedback_lower": (
        ("Value drift", "Output voltage shifts",
         "ngspice .op divider check; 1% parts"),
    ),
    "indicator_led": (
        ("Reversed installation", "Indicator dark (cosmetic)",
         "Series-LED polarity check (rule 7.1); polarity silk"),
    ),
    "indicator_resistor": (
        ("Under-rated power", "Resistor discolours",
         "Calculator warns past the 0603 rating"),
    ),
    # IMU breakout roles.
    "imu_sensor": (
        ("Wrong I2C address strap", "Host cannot find device",
         "AD0 pulldown in composition; test plan I2C scan"),
        ("Regulator caps missing", "Erratic readings",
         "Card required_support (datasheet section 7.2)"),
    ),
    "mcu": (
        ("Unprogrammed at assembly", "Board inert",
         "Bench only - firmware contract finding"),
    ),
    # LED matrix / art roles.
    "matrix_led": (
        ("Reversed installation", "String dark",
         "Series-LED polarity check (rule 7.1)"),
    ),
    "string_resistor": (
        ("Under-rated power", "Resistor overheats",
         "Calculator warns past the 0603 rating"),
    ),
    "led_current_limit": (
        ("Wrong value", "LED over/under-driven",
         "Calculator E24 selection with datasheet VF evidence"),
    ),
    # Generic connectors and passives.
    "input_connector": (
        ("Miswired harness", "Reverse polarity into the board",
         "+/- silk marks (rule 8.2); bench only"),
    ),
    "power_connector": (
        ("Miswired harness", "Reverse polarity into the board",
         "+/- silk marks (rule 8.2); bench only"),
    ),
    "output_connector": (),
    "io_connector": (),
    "drive_connector": (),
    "divider_top": (
        ("Value drift", "Divider ratio shifts",
         "ngspice .op checks the node voltage"),
    ),
    "divider_bottom": (
        ("Value drift", "Divider ratio shifts",
         "ngspice .op checks the node voltage"),
    ),
    "highpass_series_capacitor": (
        ("Value drift", "Corner frequency shifts",
         "Calculator sets the corner; ngspice AC behavior"),
    ),
    # 555 servo tester roles.
    "power_input_terminal": (
        ("Reverse supply connection", "IC and servo damaged",
         "Silk +V/GND marks; test plan polarity step; bench only"),
    ),
    "timer_ic": (
        ("RESET pin floating", "Timer held off by noise",
         "Card must_tie VCC (rule 7.4); ERC connectivity"),
        ("Socket pin misseat", "Erratic oscillation",
         "Socketed DIP by design; test plan frequency step"),
    ),
    "timing_charge_resistor": (
        ("Value drift", "Frame rate shifts",
         "Calculator frame-rate outputs; test plan frequency step"),
    ),
    "forward_branch_resistor": (
        ("Value drift", "FORWARD pulse width shifts",
         "Calculator pulse-width outputs; test plan pulse step"),
    ),
    "reverse_branch_resistor": (
        ("Value drift", "REVERSE pulse width shifts",
         "Calculator pulse-width outputs; test plan pulse step"),
    ),
    "base_resistor": (
        ("Open", "Servo signal stuck high",
         "ngspice saturation check covers nominal; bench only for open"),
    ),
    "collector_pullup": (
        ("Open", "Servo signal stuck low, servo limp",
         "ngspice high-level check covers nominal; bench only for open"),
    ),
    "timing_capacitor": (
        ("Value drift/leakage", "Pulse width and frame rate shift",
         "Calculator timing outputs; test plan frequency step"),
    ),
    "control_bypass_capacitor": (
        ("Missing", "Threshold jitter from supply noise",
         "SLFS022 p18 bypass note; flagged 10n-vs-100n discrepancy"),
    ),
    "vcc_bypass_capacitor": (
        ("Missing", "Timer resets on servo current spikes",
         "Card required_support (rule 7.5); ERC connectivity"),
    ),
    "servo_bulk_capacitor": (
        ("Capacitance loss / ESR rise", "Brownout under servo stall",
         "Sized 470uF for stall transients; test plan stall step"),
        ("Reverse polarity", "Vent/failure",
         "Polarity silk mark (rule 8.1); assembly note"),
    ),
    "signal_inverter_transistor": (
        ("Wrong pinout orientation", "No servo signal",
         "TO-92 pin-net table from the BC547 symbol; silk outline"),
        ("Insufficient base drive", "Signal never saturates low",
         "Calculator forced-beta output; ngspice saturation check"),
    ),
    "forward_button": (
        ("Contact bounce", "Momentary pulse-width jitter",
         "Acceptable for a tester; noted in the test plan"),
    ),
    "reverse_button": (
        ("Contact bounce", "Momentary pulse-width jitter",
         "Acceptable for a tester; noted in the test plan"),
    ),
    "servo_header": (
        ("Servo plugged in reversed", "Servo unpowered or damaged",
         "GND/+V/SIG silk labels at the pins; test plan hookup step"),
    ),
}

_FALLBACK_FMEA_ROW = (
    "No curated failure modes for this role",
    "Unknown",
    "Human review required",
)


def pin_nets_from_netlist(netlist: object) -> dict[str, dict[str, str]]:
    """Derive {reference: {pin: net}} from a parsed BoardNetlist - the
    topology-independent source, available in every board authority."""
    pin_nets: dict[str, dict[str, str]] = {}
    for net in netlist.nets:  # type: ignore[attr-defined]
        for reference, pin in net.nodes:
            pin_nets.setdefault(reference, {})[pin] = net.name
    return pin_nets


def render_block_diagram(
    components: Sequence[ComponentRole],
    pin_nets: Mapping[str, Mapping[str, str]],
) -> str:
    """Mermaid graph: components as nodes; nets with more than
    _NET_NODE_THRESHOLD members become bus nodes, the rest are edges."""
    members: dict[str, list[str]] = {}
    for reference, pins in pin_nets.items():
        for net in pins.values():
            members.setdefault(net, [])
            if reference not in members[net]:
                members[net].append(reference)

    lines = ["```mermaid", "graph LR"]
    role_of = {c.reference: c.role for c in components}
    for component in components:
        role = role_of.get(component.reference, "")
        lines.append(
            f'  {component.reference}["{component.reference} {role}"]'
        )
    edges: set[tuple[str, str, str]] = set()
    for net, refs in sorted(members.items()):
        if len(refs) > _NET_NODE_THRESHOLD:
            node = re.sub(r"[^A-Za-z0-9]", "_", net).strip("_")
            lines.append(f"  {node}(({net}))")
            for reference in refs:
                edges.add((reference, node, ""))
        else:
            for index in range(len(refs) - 1):
                edges.add((refs[index], refs[index + 1], net))
    for source, target, label in sorted(edges):
        if label:
            lines.append(f"  {source} ---|{label}| {target}")
        else:
            lines.append(f"  {source} --- {target}")
    lines.append("```")
    return "\n".join(lines)


def render_pin_tables(cards: Sequence[tuple[str, str]]) -> str:
    """Pin-function tables for every component that has a card."""
    from pcbsmith.components import load_card

    sections: list[str] = []
    for reference, mpn in cards:
        card = load_card(mpn)
        rows = [
            f"### {reference} - {card.mpn} ({card.description})",
            "",
            "| Pin | Name | Function | Requirement | Note |",
            "| --- | --- | --- | --- | --- |",
        ]
        for pin in card.pins:
            rows.append(
                f"| {pin.number} | {pin.name} | {pin.function} "
                f"| {pin.requirement} | {pin.note} |"
            )
        sections.append("\n".join(rows))
    return "\n\n".join(sections) if sections else "_No component cards._"


def render_fmea(components: Sequence[ComponentRole]) -> str:
    lines = [
        "| Ref | Role | Failure mode | Effect | Coverage |",
        "| --- | --- | --- | --- | --- |",
    ]
    for component in components:
        rows = ROLE_FMEA.get(component.role)
        if rows is None:
            rows = (_FALLBACK_FMEA_ROW,)
        for mode, effect, coverage in rows:
            lines.append(
                f"| {component.reference} | {component.role} "
                f"| {mode} | {effect} | {coverage} |"
            )
    return "\n".join(lines)


def render_test_plan(steps: Sequence[TestStep]) -> str:
    if not steps:
        return "_No test plan defined for this topology._"
    lines = [
        "| # | Step | Procedure | Expected | Safety |",
        "| --- | --- | --- | --- | --- |",
    ]
    for index, step in enumerate(steps, start=1):
        lines.append(
            f"| {index} | {step.name} | {step.procedure} "
            f"| {step.expected} | {step.safety} |"
        )
    return "\n".join(lines)


_VALUE_RE = re.compile(
    r"^(\d+(?:\.\d+)?)\s*(k|K|M|R|m)?\s*(?:ohm)?$"
    r"|^(\d+(?:\.\d+)?)\s*(pF|nF|uF|µF)$",
    re.IGNORECASE,
)

_R_MULTIPLIERS = {"": 1.0, "r": 1.0, "k": 1e3, "m": 1e6}
_C_MULTIPLIERS = {"pf": 1e-12, "nf": 1e-9, "uf": 1e-6, "µf": 1e-6}


def _parse_passive_value(value: str) -> tuple[str, float] | None:
    match = _VALUE_RE.match(value.strip())
    if match is None:
        return None
    if match.group(1) is not None:
        suffix = (match.group(2) or "").lower()
        if suffix == "m" and match.group(2) == "m":
            return None  # milliohm shunts are not consolidation fodder
        return ("R", float(match.group(1)) * _R_MULTIPLIERS.get(suffix, 1.0))
    return ("C", float(match.group(3)) * _C_MULTIPLIERS[match.group(4).lower()])


def bom_consolidation_notes(
    components: Sequence[ComponentRole],
) -> tuple[str, ...]:
    """Flux-style passive-consolidation lint, deterministic and scoped
    to plain SMD passives (consolidating THT safety parts is nonsense).
    Flags: identical values in different SMD footprints, and values
    within 10% sharing a footprint."""
    passives: list[tuple[str, str, float, str, str]] = []
    for component in components:
        if component.footprint is None or not component.footprint.startswith(
            ("Resistor_SMD:", "Capacitor_SMD:")
        ):
            continue
        parsed = _parse_passive_value(component.value)
        if parsed is None:
            continue
        kind, numeric = parsed
        passives.append(
            (kind, component.value, numeric, component.footprint,
             component.reference)
        )

    notes: list[str] = []
    for i in range(len(passives)):
        for j in range(i + 1, len(passives)):
            kind_a, value_a, num_a, fp_a, ref_a = passives[i]
            kind_b, value_b, num_b, fp_b, ref_b = passives[j]
            if kind_a != kind_b:
                continue
            if num_a == num_b and fp_a != fp_b:
                notes.append(
                    f"{ref_a} ({value_a}, {fp_a.split(':')[1]}) and "
                    f"{ref_b} ({value_b}, {fp_b.split(':')[1]}) share a "
                    "value in different footprints - consider one package."
                )
            elif (
                fp_a == fp_b
                and num_a != num_b
                and abs(num_a - num_b) / max(num_a, num_b) <= 0.10
            ):
                notes.append(
                    f"{ref_a} ({value_a}) and {ref_b} ({value_b}) are "
                    "within 10% in the same footprint - check whether one "
                    "value serves both."
                )
    return tuple(notes)


def render_review_pack(
    *,
    project_name: str,
    components: Sequence[ComponentRole],
    pin_nets: Mapping[str, Mapping[str, str]],
    cards: Sequence[tuple[str, str]] = (),
    test_steps: Sequence[TestStep] = (),
    notes: Sequence[str] = (),
) -> str:
    consolidation = bom_consolidation_notes(components)
    consolidation_text = (
        "\n".join(f"- {note}" for note in consolidation)
        if consolidation
        else "_No consolidation opportunities found._"
    )
    notes_text = (
        "\n".join(f"- {note}" for note in notes) + "\n\n" if notes else ""
    )
    return f"""# Review pack: {project_name}

Generated deterministically from the design's structured data
(roles, cards, nets, calculator outputs). Nothing in this file is
model-generated; every claim traces to code or evidence.

{notes_text}## Block diagram

{render_block_diagram(components, pin_nets)}

## Test plan

{render_test_plan(test_steps)}

## FMEA

{render_fmea(components)}

## Pin functions

{render_pin_tables(cards)}

## BOM consolidation

{consolidation_text}
"""
