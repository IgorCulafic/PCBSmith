"""120 VAC to 3.3 V isolated flyback (UCC28881 + custom transformer).

Composition follows the classic offline flyback stages: fused/MOV input,
discrete bridge, bulk capacitors, TVS on the DC bus, the UCC28881
integrated-FET switcher with an RCD clamp, the custom transformer, a
Schottky secondary, and LMV431 + optocoupler isolated feedback. All
device numbers come from the fetched TI datasheets; the design point
comes from the deterministic DCM calculator.

SAFETY: this composition is a MAINS-VOLTAGE design. Every artifact
carries a standing finding demanding qualified human review, certified
safety parts (Y-capacitor, fusible resistor), and lab verification.
"""

from __future__ import annotations

from pathlib import Path

from pcbsmith.calculators.electronics import solve_offline_flyback
from pcbsmith.circuit.models import (
    CircuitIntent,
    CircuitObject,
    ComponentRole,
    EvidenceRef,
    MathReport,
    TopologySelection,
)
from pcbsmith.core.board import Board
from pcbsmith.core.project import Project
from pcbsmith.core.schematic import Schematic
from pcbsmith.services.project_io import save_board, save_project, save_schematic

SUPPORTED_TOPOLOGY_ID = "offline_flyback_3v3"

SAFETY_FINDING = (
    "MAINS SAFETY (standing, cannot be closed by this pipeline): the "
    "primary side carries 120 VAC / ~190 VDC. The Y-capacitor must be a "
    "certified Y1/Y2 part, the input resistor fusible/flameproof, the MOV "
    "rated for 130 VAC line, and the transformer wound to reinforced-"
    "isolation practice. Creepage >= 6.4 mm is machine-checked on the "
    "board but certification-level review and lab verification by a "
    "qualified engineer are REQUIRED before connecting mains."
)

TRANSFORMER_SPEC_FINDING = (
    "Custom transformer T1 winding specification (for the magnetics "
    "winder): primary Lp per the calculator output on TEZ/EE core, "
    "Np:Ns per the selected turns ratio, reinforced insulation between "
    "windings, primary on pads 1(dot)-4, secondary on pads 5-8(dot); "
    "verify core flux at Ipk before ordering."
)


def _ucc_evidence() -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(
            kind="datasheet_fact",
            title="UCC28881 pinout, limits, and typical application",
            locator="ai_assets/datasheets/ucc28881.pdf p3 (pins), p4 "
            "(700V abs max), p6 (ILIMIT 330-570mA, fSW 52-75kHz, "
            "tON<=6.5us, VFB_TH ~1.03V)",
        ),
    )


def _lmv_evidence() -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(
            kind="datasheet_fact",
            title="LMV431 1.24V reference, IZ(MIN) 80uA, SOT-23 pinout",
            locator="ai_assets/datasheets/lmv431.pdf p1, p3 (pins: 1=K "
            "2=REF 3=A, cross-checked vs TI DBZ family), p5",
        ),
    )


def _assumption(title: str, locator: str) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(kind="engineering_assumption", title=title, locator=locator),
    )


def _reference_practice(title: str, detail: str) -> tuple[EvidenceRef, ...]:
    return (
        EvidenceRef(
            kind="reference_design",
            title=title,
            locator=(
                f"ai_assets/references/flback-001/reference.json: {detail}"
            ),
        ),
    )


def compose_flyback(
    intent: CircuitIntent,
    topology: TopologySelection,
) -> CircuitObject:
    if intent.intent_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported intent for flyback composition")
    if topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported topology for flyback composition")

    design = solve_offline_flyback(
        vac_min_v=float(intent.assumptions["vac_min_v"]),
        vac_max_v=float(intent.assumptions["vac_max_v"]),
        vout_v=float(intent.assumptions["vout_v"]),
        iout_a=float(intent.assumptions["iout_a"]),
        reflected_voltage_v=float(intent.assumptions["reflected_voltage_v"]),
        clamp_resistance_ohms=680e3,  # RC1 below
    )
    if design["status"] == "error":
        raise ValueError("; ".join(design["errors"]))
    out = design["outputs"]

    def resistor(
        reference: str, role: str, value: str, footprint: str,
        evidence: tuple[EvidenceRef, ...],
    ) -> ComponentRole:
        return ComponentRole(
            reference=reference, role=role, symbol_id="stdlib:R", value=value,
            support_status="needs_datasheet_review", footprint=footprint,
            evidence=evidence,
        )

    def capacitor(
        reference: str, role: str, value: str, footprint: str,
        evidence: tuple[EvidenceRef, ...],
    ) -> ComponentRole:
        return ComponentRole(
            reference=reference, role=role, symbol_id="stdlib:C", value=value,
            support_status="needs_datasheet_review", footprint=footprint,
            evidence=evidence,
        )

    smd_r = "Resistor_SMD:R_0603_1608Metric"
    smd_c = "Capacitor_SMD:C_0603_1608Metric"
    axial = "Resistor_THT:R_Axial_DIN0414_L11.9mm_D4.5mm_P15.24mm_Horizontal"
    disc = "Capacitor_THT:C_Disc_D9.0mm_W5.0mm_P10.00mm"

    components = (
        ComponentRole(
            reference="J1", role="mains_input_terminal",
            symbol_id="stdlib:CONN_01X02", value="120VAC L/N",
            support_status="needs_datasheet_review",
            footprint="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-3-2-5.08_1x02_P5.08mm_Horizontal",
            evidence=_assumption(
                "Mains-rated terminal block",
                "Phoenix MKDS 1.5 class; verify 300V/UL rating of the "
                "ordered part.",
            ),
        ),
        resistor(
            "RF1", "fusible_input_resistor", "10R fusible 1W", axial,
            _assumption(
                "Fusible flameproof resistor as input fuse",
                "Article input stage; MUST be a fusible/flameproof type.",
            ),
        ),
        ComponentRole(
            reference="RV1", role="input_mov",
            symbol_id="stdlib:VARISTOR", value="130VAC MOV (07D201K)",
            support_status="needs_datasheet_review",
            footprint="Varistor:RV_Disc_D7mm_W3.5mm_P5mm",
            evidence=_assumption(
                "MOV surge clamp on the AC input",
                "130 VAC rated disc varistor per the input-stage plan.",
            ),
        ),
        ComponentRole(
            reference="BR1", role="bridge_rectifier",
            symbol_id="stdlib:D_BRIDGE", value="DB107 (600V 1A)",
            support_status="needs_datasheet_review",
            footprint="Diode_THT:Diode_Bridge_DIP-4_W7.62mm_P5.08mm",
            evidence=_reference_practice(
                "Integrated bridge instead of four discretes",
                "FLBACK-001 uses an HD06 MiniDIP bridge; one 4-pin "
                "package replaces the 16x24mm diode field. 600V >> 190V "
                "peak bus.",
            ),
        ),
        capacitor(
            "CB1", "bulk_capacitor", "10uF 450V",
            "Capacitor_THT:CP_Radial_D10.0mm_P5.00mm",
            _reference_practice(
                "Single high-voltage bulk can",
                "FLBACK-001 buffers the same 2W with one Rubycon 450BXW "
                "10uF/450V 10x16mm can; 9.4uF+ holds vdc_min per the "
                "calculator energy balance.",
            ),
        ),
        capacitor(
            "CX1", "x2_line_capacitor", "100nF X2 275VAC",
            "Capacitor_THT:C_Rect_L18.0mm_W7.0mm_P15.00mm_FKS3_FKP3",
            _reference_practice(
                "X2 film capacitor across the filtered line",
                "FLBACK-001 C5 (Panasonic ECQ-UA 100nF 275VAC). MUST be "
                "an X2 SAFETY-RATED part; the footprint is a geometric "
                "match (L18 P15).",
            ),
        ),
        capacitor(
            "CY2", "line_y_capacitor", "2.2nF Y1 300VAC", disc,
            _reference_practice(
                "Line-to-earth Y capacitor (L side)",
                "FLBACK-001 C10/C11 (Vishay VY2 2.2nF 300VAC). MUST be a "
                "certified Y1/Y2 safety capacitor.",
            ),
        ),
        capacitor(
            "CY3", "line_y_capacitor", "2.2nF Y1 300VAC", disc,
            _reference_practice(
                "Line-to-earth Y capacitor (N side)",
                "FLBACK-001 C10/C11 (Vishay VY2 2.2nF 300VAC). MUST be a "
                "certified Y1/Y2 safety capacitor.",
            ),
        ),
        ComponentRole(
            reference="E1", role="earth_terminal",
            symbol_id="stdlib:CONN_01X01", value="EARTH",
            support_status="needs_datasheet_review",
            footprint=(
                "Connector_Wire:SolderWire-2.5sqmm_1x01_D2.4mm_OD3.6mm"
            ),
            evidence=_reference_practice(
                "Protective-earth wire pad",
                "FLBACK-001 brings mains in on 14-gauge wire pads "
                "including earth; the line Y-caps return to it.",
            ),
        ),
        ComponentRole(
            reference="D5", role="bus_tvs",
            symbol_id="stdlib:D", value="SMAJ200A",
            support_status="needs_datasheet_review",
            footprint="Diode_SMD:D_SMA",
            evidence=_assumption(
                "TVS on the rectified bus",
                "200V standoff > 187V peak bus; clamps line transients.",
            ),
        ),
        ComponentRole(
            reference="U1", role="flyback_switcher",
            symbol_id="stdlib:UCC28881", value="UCC28881",
            support_status="supported",
            footprint="Package_SO:SOIC-8_5.3x6.2mm_P1.27mm",
            evidence=_ucc_evidence(),
        ),
        capacitor(
            "CV1", "vdd_capacitor", "100nF", smd_c,
            _ucc_evidence(),
        ),
        resistor(
            "RC1", "clamp_resistor", "680k 0.5W", axial,
            _assumption(
                "RCD clamp resistor",
                "Sized for ~0.1W leakage-energy dissipation at Vclamp 250V.",
            ),
        ),
        capacitor(
            "CC1", "clamp_capacitor", "2.2nF 630V", disc,
            _assumption(
                "RCD clamp capacitor",
                "Holds the clamp voltage between cycles; 630V+ rated.",
            ),
        ),
        ComponentRole(
            reference="D6", role="clamp_diode",
            symbol_id="stdlib:D", value="US1M",
            support_status="needs_datasheet_review",
            footprint="Diode_SMD:D_SMA",
            evidence=_assumption(
                "Fast clamp diode", "1000V 1A fast recovery for the clamp.",
            ),
        ),
        ComponentRole(
            reference="T1", role="flyback_transformer",
            symbol_id="stdlib:FLYBACK_TRANSFORMER",
            value=(
                f"CUSTOM TEZ-22x24 Lp={out['primary_inductance_h'] * 1e6:.0f}uH "
                f"Np:Ns={out['turns_ratio_selected']:.0f}:1 reinforced"
            ),
            support_status="needs_datasheet_review",
            footprint="Transformer_THT:Transformer_Breve_TEZ-22x24",
            evidence=_assumption(
                "Custom flyback transformer on a TEZ-22 land pattern",
                "Winding spec in the math findings; reinforced isolation.",
            ),
        ),
        ComponentRole(
            reference="D7", role="secondary_rectifier",
            symbol_id="stdlib:D_SCHOTTKY", value="SS34",
            support_status="needs_datasheet_review",
            footprint="Diode_SMD:D_SMA",
            evidence=_assumption(
                "Schottky secondary rectifier",
                f"PIV requirement {out['secondary_piv_v']:.1f}V << 40V "
                "rating; 3A >> 0.5A load.",
            ),
        ),
        ComponentRole(
            reference="CO1", role="output_capacitor", symbol_id="stdlib:CP",
            value="470uF 6.3V low-ESR",
            support_status="needs_datasheet_review",
            footprint="Capacitor_SMD:CP_Elec_8x10",
            evidence=_assumption(
                "Low-ESR output bulk", "Flyback pulse filtering at 3.3V.",
            ),
        ),
        capacitor("CO2", "output_hf_capacitor", "100nF", smd_c,
                  _assumption("HF output ceramic", "High-frequency bypass.")),
        ComponentRole(
            reference="U2", role="feedback_optocoupler",
            symbol_id="stdlib:PC817", value="PC817",
            support_status="needs_datasheet_review",
            footprint="Package_DIP:DIP-4_W7.62mm",
            evidence=_assumption(
                "Optocoupler isolated feedback",
                "PC817 class; verify CTR bin and isolation rating.",
            ),
        ),
        ComponentRole(
            reference="U3", role="shunt_reference",
            symbol_id="stdlib:LMV431", value="LMV431",
            support_status="supported",
            footprint="Package_TO_SOT_SMD:SOT-23",
            evidence=_lmv_evidence(),
        ),
        resistor(
            "RFB1", "feedback_upper_resistor",
            f"{out['feedback_upper_ohms'] / 1000:g}k", smd_r, _lmv_evidence(),
        ),
        resistor(
            "RFB2", "feedback_lower_resistor",
            f"{out['feedback_lower_ohms'] / 1000:g}k", smd_r, _lmv_evidence(),
        ),
        resistor(
            "RO1", "opto_led_resistor", "180R", smd_r,
            _assumption(
                "Optocoupler LED series resistor",
                "(3.3 - Vf_led - Vka_min)/5mA headroom chain.",
            ),
        ),
        resistor(
            "RO2", "reference_bias_resistor", "1k", smd_r,
            _lmv_evidence(),
        ),
        resistor(
            "RP1", "fb_pulldown_resistor", "2.2k", smd_r,
            _ucc_evidence(),
        ),
        capacitor(
            "CY1", "y_capacitor", "2.2nF Y1", disc,
            _assumption(
                "Y-capacitor across the isolation barrier",
                "MUST be a certified Y1/Y2 safety capacitor.",
            ),
        ),
        ComponentRole(
            reference="TP1", role="test_point",
            symbol_id="stdlib:TESTPOINT", value="TP HV+",
            support_status="needs_datasheet_review",
            footprint="TestPoint:TestPoint_THTPad_D2.0mm_Drill1.0mm",
            evidence=_reference_practice(
                "Rectified-bus test point",
                "FLBACK-001 TP1; every power design carries probe points.",
            ),
        ),
        ComponentRole(
            reference="TP2", role="test_point",
            symbol_id="stdlib:TESTPOINT", value="TP GNDS",
            support_status="needs_datasheet_review",
            footprint="TestPoint:TestPoint_THTPad_D2.0mm_Drill1.0mm",
            evidence=_reference_practice(
                "Secondary-ground test point",
                "FLBACK-001 TP2; the isolated-side probe reference.",
            ),
        ),
        capacitor(
            "CF1", "feedback_comp_capacitor", "DNP", smd_c,
            _reference_practice(
                "Do-not-populate compensation option across the upper "
                "divider resistor",
                "FLBACK-001 keeps C8/R6 as DNP positions; the pad site "
                "costs nothing and rescues a marginal loop in the lab.",
            ),
        ),
        ComponentRole(
            reference="J2", role="output_terminal",
            symbol_id="stdlib:CONN_01X02", value="3.3V OUT",
            support_status="needs_datasheet_review",
            footprint="TerminalBlock_Phoenix:TerminalBlock_Phoenix_MKDS-3-2-5.08_1x02_P5.08mm_Horizontal",
            evidence=_assumption("Output terminal block", "Low-voltage side."),
        ),
    )

    findings = (
        *(str(w) for w in design["warnings"]),
        SAFETY_FINDING,
        TRANSFORMER_SPEC_FINDING,
        "The switching stage is verified by the deterministic DCM design "
        "equations against datasheet limits; it is NOT SPICE-simulated. "
        "The simulated network is the secondary feedback chain only.",
    )
    return CircuitObject(
        intent=intent,
        topology=topology,
        components=components,
        nets=(
            "L", "N", "ACL", "HVP", "HVM", "SW", "CLAMP", "VDD", "FB",
            "SEC", "3V3", "GNDS", "FBS", "OPK", "LEDA",
        ),
        math=MathReport(
            status="warning",
            calculations={key: float(value) for key, value in design["outputs"].items()},
            findings=findings,
        ),
    )


def write_flyback_project(
    circuit: CircuitObject,
    project_dir: Path,
    *,
    project_name: str,
) -> None:
    if circuit.topology.topology_id != SUPPORTED_TOPOLOGY_ID:
        raise ValueError("Unsupported circuit for project generation")
    project = Project(name=project_name)
    save_project(project_dir, project)
    save_schematic(project_dir, project.schematics[0], Schematic(id="main"))
    save_board(project_dir, project.boards[0], Board(id="main"))
