from __future__ import annotations

from pcbsmith.circuit.models import CircuitIntent, EvidenceRef, TopologySelection


def select_topology(intent: CircuitIntent) -> TopologySelection:
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
