from __future__ import annotations

from pcbsmith.circuit.models import CircuitIntent, EvidenceRef, TopologySelection


def select_topology(intent: CircuitIntent) -> TopologySelection:
    if intent.intent_id == "lm2596_buck_regulator" and intent.status == "supported":
        return _lm2596_buck_topology()
    if intent.intent_id == "led_text_matrix" and intent.status == "supported":
        return _led_text_matrix_topology()
    if intent.intent_id == "mpu6050_imu" and intent.status == "supported":
        return _mpu6050_imu_topology()
    if intent.intent_id == "clover_tilt_indicator" and intent.status == "supported":
        return _clover_topology()
    if intent.intent_id == "pear_led_rings" and intent.status == "supported":
        return _pear_topology()
    if intent.intent_id == "metal_detector_coil" and intent.status == "supported":
        return _metal_detector_topology()
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


def _metal_detector_topology() -> TopologySelection:
    return TopologySelection(
        topology_id="metal_detector_coil",
        title="Metal detector: exposed PCB spiral coil + Colpitts oscillator",
        status="selected",
        evidence=(
            EvidenceRef(
                kind="textbook_formula",
                title="Planar spiral inductance (current-sheet approximation)",
                locator="Mohan et al., IEEE JSSC 34(10) 1999",
            ),
            EvidenceRef(
                kind="textbook_formula",
                title="Colpitts oscillator frequency",
                locator="f = 1 / (2*pi*sqrt(L * C1*C2/(C1+C2)))",
            ),
            EvidenceRef(
                kind="engineering_assumption",
                title="Eddy-current detection mechanism",
                locator=(
                    "Conductive metal near the coil reduces L and raises "
                    "the oscillation frequency; measured externally at FOUT."
                ),
            ),
        ),
        warnings=(
            "Detection sensitivity and the frequency-measurement backend "
            "are an external contract; only the oscillator is verified.",
        ),
    )


def _pear_topology() -> TopologySelection:
    return TopologySelection(
        topology_id="pear_led_rings",
        title="Pear-shaped board with three independently driven LED edge rings",
        status="selected",
        evidence=(
            EvidenceRef(
                kind="textbook_formula",
                title="LED series resistor sizing",
                locator="R = (Vsupply - Vf) / I, nearest E24",
            ),
            EvidenceRef(
                kind="engineering_assumption",
                title="Ring drive contract",
                locator=(
                    "Each ring net L1..L3 is driven externally at the supply "
                    "voltage; branches are one resistor + one LED to ground."
                ),
            ),
        ),
        warnings=(
            "LED forward voltage is an engineering assumption; validate "
            "against a datasheet-backed part before fabrication.",
        ),
    )


def _clover_topology() -> TopologySelection:
    return TopologySelection(
        topology_id="clover_tilt_indicator",
        title="Four-leaf-clover tilt indicator: MPU-6050 + ATtiny84A + leaf LEDs",
        status="selected",
        evidence=(
            EvidenceRef(
                kind="datasheet_procedure",
                title="MPU-6050 typical operating circuit",
                locator="ai_assets/datasheets/mpu6050.pdf p22 section 7.2",
            ),
            EvidenceRef(
                kind="datasheet_fact",
                title="ATtiny84A supply range and I/O drive",
                locator="ai_assets/datasheets/attiny84a.pdf p1, p174",
            ),
            EvidenceRef(
                kind="textbook_formula",
                title="LED series resistor and I2C pullup sizing",
                locator="R = (VDD-Vf)/I; Rmax = tr/(0.8473*Cb)",
            ),
        ),
        warnings=(
            "Tilt-to-LED behaviour is firmware on the ATtiny84A; this "
            "pipeline verifies the hardware only.",
            "The green LED forward voltage (2.2 V) is an engineering "
            "assumption pending a datasheet-backed part.",
        ),
    )


def _mpu6050_imu_topology() -> TopologySelection:
    return TopologySelection(
        topology_id="mpu6050_imu",
        title="MPU-6050 6-axis IMU breakout, I2C, 3.3 V supply",
        status="selected",
        evidence=(
            EvidenceRef(
                kind="datasheet_procedure",
                title="InvenSense MPU-6050 typical operating circuit",
                locator=(
                    "ai_assets/datasheets/mpu6050.pdf p22 section 7.2: REGOUT "
                    "0.1uF, VDD bypass 0.1uF, CPOUT 2.2nF, VLOGIC 10nF"
                ),
            ),
            EvidenceRef(
                kind="datasheet_fact",
                title="MPU-6050 pin out and unused-pin handling",
                locator=(
                    "ai_assets/datasheets/mpu6050.pdf p21 section 7.1: CLKIN "
                    "and FSYNC to GND if unused; RESV 19/21/22 do not connect"
                ),
            ),
            EvidenceRef(
                kind="textbook_formula",
                title="I2C pullup sizing",
                locator="Rmax = tr/(0.8473*Cb); Rmin = (VDD-VOL)/IOL",
            ),
        ),
        warnings=(
            "The MEMS sensor core and digital interface have no SPICE model; "
            "only the passive I2C bus conditions are simulated.",
            "INT, AUX_DA, and AUX_CL are not broken out on the 4-pin header.",
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
