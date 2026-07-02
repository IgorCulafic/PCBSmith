from __future__ import annotations

from pcbsmith.circuit.models import CircuitIntent, EvidenceRef, TopologySelection


def select_topology(intent: CircuitIntent) -> TopologySelection:
    if intent.intent_id == "lm2596_buck_regulator" and intent.status == "supported":
        return _lm2596_buck_topology()
    if intent.intent_id == "led_text_matrix" and intent.status == "supported":
        return _led_text_matrix_topology()
    if intent.intent_id != "divider_highpass_led_indicator" or intent.status != "supported":
        return TopologySelection(
            topology_id="unsupported",
            title="Unsupported topology",
            status="unsupported",
            evidence=(),
            warnings=("No supported topology matched the classified intent.",),
        )
    return TopologySelection(
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
            EvidenceRef(
                kind="engineering_assumption",
                title="Generic red LED indicator model",
                locator=(
                    "Vf=2.0V demo assumption; replace with datasheet-backed LED "
                    "before fabrication."
                ),
            ),
        ),
        warnings=(
            "LED brightness and conduction after AC coupling require simulation and human review.",
        ),
    )


def _led_text_matrix_topology() -> TopologySelection:
    return TopologySelection(
        topology_id="led_text_matrix",
        title="Decorative LED text matrix, one series string per glyph column",
        status="selected",
        evidence=(
            EvidenceRef(
                kind="textbook_formula",
                title="Series LED string resistor equation",
                locator="R = (Vsupply - n*Vf) / I_target",
            ),
            EvidenceRef(
                kind="datasheet_fact",
                title="Kingbright LED forward voltage, extracted datasheet fact",
                locator=(
                    "ai_assets/evidence/divider-highpass-led.manifest.json: "
                    "VF typ 1.85 V at 20 mA"
                ),
            ),
        ),
        warnings=(
            "Brightness matching between strings of different lengths depends on "
            "forward-voltage tolerance; human review of the current per string is "
            "required before fabrication.",
        ),
    )


def _lm2596_buck_topology() -> TopologySelection:
    return TopologySelection(
        topology_id="lm2596_buck_regulator",
        title="LM2596 step-down (buck) regulator module, adjustable output",
        status="selected",
        evidence=(
            EvidenceRef(
                kind="datasheet_procedure",
                title="TI LM2596 adjustable output design procedure",
                locator=(
                    "ai_assets/datasheets/ti-lm2596.pdf: Vout = Vref*(1+R2/R1), "
                    "inductor and capacitor selection per design procedure"
                ),
            ),
            EvidenceRef(
                kind="textbook_formula",
                title="Buck inductor ripple equation",
                locator="L_min = Vout*(Vin_max-Vout)/(Vin_max*f_sw*dI)",
            ),
            EvidenceRef(
                kind="textbook_formula",
                title="Buck output capacitor ripple equation",
                locator="C_min = dI/(8*f_sw*dV)",
            ),
        ),
        warnings=(
            "Switching-loop layout area is safety-relevant for this topology; "
            "board generation is gated until switching-loop layout rules exist.",
            "The LM2596 control loop has no public SPICE model; simulation covers "
            "the open-loop averaged power stage only.",
        ),
    )
