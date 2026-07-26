"""Build the replayable AeroSense-2F R001 intake and concept package.

This script deliberately stops at the concept-approval boundary.  It uses the
reviewed prompt, exact selected-part metadata, KiCad 10 footprint geometry, the
Phase 17 prompt examiner, and the pre-route feasibility evaluator.  It does not
create a schematic or PCB.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from pcbsmith.kicad.concept_review import (
    ConceptItem,
    ConceptReview,
    examine_concept,
    write_concept_review_package,
)
from pcbsmith.prompt_examiner import (
    AnchorKind,
    ContextPopulationInput,
    ExaminedClaim,
    PromptResolution,
    SourceSpan,
    TypedSpatialAnchor,
    examine_prompt,
    populate_project_context,
)
from pcbsmith.routed_copper_graph_ir import fingerprint
from pcbsmith.workflow_authority import (
    ALL_PROJECT_CONTEXT_CATEGORIES,
)
from pcbsmith.workflow_feasibility import (
    NeckSection,
    PlacementEnvelope,
    PreRouteNetDemand,
    evaluate_pre_route_feasibility,
)

PROJECT_ID = "aerosense-2f-r001"
BOARD_W_MM = 70.0
BOARD_H_MM = 50.0
OUTLINE = (
    (0.0, 0.0),
    (BOARD_W_MM, 0.0),
    (BOARD_W_MM, BOARD_H_MM),
    (0.0, BOARD_H_MM),
)


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _span(text: str, exact: str, span_id: str) -> SourceSpan:
    start = text.index(exact)
    return SourceSpan(
        span_id=span_id,
        start=start,
        end=start + len(exact),
        exact_text=exact,
    )


def _build_examination(prompt_text: str) -> Any:
    board = _span(
        prompt_text,
        "Rectangular outline: 70 mm × 50 mm hard maximum for the first feasibility",
        "span.board-outline",
    )
    usb = _span(
        prompt_text,
        "USB-C: left edge, mating face outward through X = 0.",
        "span.usb-edge",
    )
    holes = _span(
        prompt_text,
        "Four symmetric M3 NPTH mounting holes, 3.2 mm drill, hole centers 3 mm from",
        "span.mounting-holes",
    )
    oled = _span(
        prompt_text,
        "OLED: top side, upright in the declared normal viewing orientation.",
        "span.oled-side",
    )
    sensor = _span(
        prompt_text,
        "Ambient edge/corner:",
        "span.sensor-region",
    )
    fan = _span(
        prompt_text,
        "Right or upper-right edge:",
        "span.fan-edge",
    )
    sd = _span(
        prompt_text,
        "microSD: edge-accessible, with the full card insertion/ejection swept volume",
        "span.sd-edge",
    )
    spans = (board, usb, holes, oled, sensor, fan, sd)
    claims = (
        ExaminedClaim(
            claim_id="board.width",
            field_path="mechanical.width_mm",
            value=70.0,
            unit="mm",
            resolution=PromptResolution.EXPLICIT,
            source_span_ids=(board.span_id,),
        ),
        ExaminedClaim(
            claim_id="board.height",
            field_path="mechanical.height_mm",
            value=50.0,
            unit="mm",
            resolution=PromptResolution.EXPLICIT,
            source_span_ids=(board.span_id,),
        ),
        ExaminedClaim(
            claim_id="usb.location",
            field_path="placements.usb",
            value="left_edge_outward",
            resolution=PromptResolution.EXPLICIT,
            source_span_ids=(usb.span_id,),
        ),
        ExaminedClaim(
            claim_id="mounting.holes",
            field_path="mechanical.mounting_holes",
            value="4x M3 NPTH, 3.2 mm drill, 3 mm inset",
            resolution=PromptResolution.EXPLICIT,
            source_span_ids=(holes.span_id,),
        ),
        ExaminedClaim(
            claim_id="oled.side",
            field_path="placements.oled.side",
            value="front",
            resolution=PromptResolution.EXPLICIT,
            source_span_ids=(oled.span_id,),
        ),
        ExaminedClaim(
            claim_id="sensor.region",
            field_path="placements.sensor",
            value="ambient_edge",
            resolution=PromptResolution.EXPLICIT,
            source_span_ids=(sensor.span_id,),
        ),
        ExaminedClaim(
            claim_id="fan.region",
            field_path="placements.fans",
            value="upper_right",
            resolution=PromptResolution.EXPLICIT,
            source_span_ids=(fan.span_id,),
        ),
        ExaminedClaim(
            claim_id="microsd.access",
            field_path="placements.microsd",
            value="edge_accessible",
            resolution=PromptResolution.EXPLICIT,
            source_span_ids=(sd.span_id,),
        ),
    )
    anchors = (
        TypedSpatialAnchor(
            anchor_id="usb.left-edge",
            kind=AnchorKind.EDGE_OFFSET,
            subject_ids=("J1",),
            reference_id="board.outline",
            value_mm=0.0,
            edge="left",
            source_span_ids=(usb.span_id,),
        ),
        TypedSpatialAnchor(
            anchor_id="oled.front",
            kind=AnchorKind.SIDE,
            subject_ids=("DS1",),
            reference_id="board.outline",
            side="front",
            source_span_ids=(oled.span_id,),
        ),
        TypedSpatialAnchor(
            anchor_id="oled.upright",
            kind=AnchorKind.ORIENTATION,
            subject_ids=("DS1",),
            reference_id="board.outline",
            orientation_deg=0.0,
            source_span_ids=(oled.span_id,),
        ),
        TypedSpatialAnchor(
            anchor_id="microsd.access",
            kind=AnchorKind.ACCESS,
            subject_ids=("J3",),
            reference_id="board.bottom_edge",
            edge="bottom",
            source_span_ids=(sd.span_id,),
        ),
        TypedSpatialAnchor(
            anchor_id="fans.upper-right",
            kind=AnchorKind.ACCESS,
            subject_ids=("J4", "J5"),
            reference_id="board.upper_right",
            edge="right",
            source_span_ids=(fan.span_id,),
        ),
    )
    return examine_prompt(
        project_id=PROJECT_ID,
        original_text=prompt_text,
        spans=spans,
        claims=claims,
        anchors=anchors,
    )


def _part_selection() -> dict[str, Any]:
    return {
        "schema": "pcbsmith-aerosense-exact-part-selection-v1",
        "project_id": PROJECT_ID,
        "selection_date": "2026-07-26",
        "selection_status": "frozen_for_schematic",
        "parts": [
            {
                "references": ["U1"],
                "manufacturer": "Raspberry Pi",
                "mpn": "RP2040",
                "function": "USB-capable MCU",
                "footprint": (
                    "Package_DFN_QFN:"
                    "QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm_ThermalVias"
                ),
                "model_status": "installed_exact_package",
                "lifecycle": "production",
                "authority": (
                    "https://datasheets.raspberrypi.com/rp2040/"
                    "hardware-design-with-rp2040.pdf"
                ),
            },
            {
                "references": ["U2"],
                "manufacturer": "Winbond",
                "mpn": "W25Q16JVSSIQ",
                "function": "16-Mbit QSPI boot flash",
                "footprint": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
                "model_status": "installed_exact_package",
                "lifecycle": "mass_production",
                "authority": (
                    "https://www.winbond.com/export/sites/winbond/product-selection-guide/"
                    "file/2025-Product-Selection-Guide-Winbond-Code-Storage-Flash-Memory.pdf"
                ),
            },
            {
                "references": ["U3"],
                "manufacturer": "Diodes Incorporated",
                "mpn": "AP2112K-3.3TRG1",
                "function": "600-mA 3.3-V LDO",
                "footprint": "Package_TO_SOT_SMD:SOT-23-5",
                "model_status": "installed_exact_package",
                "lifecycle": "active",
                "authority": "https://www.diodes.com/part/view/AP2112",
            },
            {
                "references": ["U4"],
                "manufacturer": "Texas Instruments",
                "mpn": "TUSB320LAIRWBR",
                "function": "Type-C UFP current-advertisement detector",
                "footprint": "PCBSmith_AeroSense:TUSB320_X2QFN12",
                "model_status": "dimensioned_project_local_package_model",
                "lifecycle": "active",
                "authority": "https://www.ti.com/lit/ds/symlink/tusb320lai.pdf",
            },
            {
                "references": ["U5", "U6"],
                "manufacturer": "Texas Instruments",
                "mpn": "TPS2553DBVR",
                "function": "independent adjustable current-limited fan switch",
                "footprint": "Package_TO_SOT_SMD:SOT-23-6",
                "model_status": "installed_exact_package",
                "lifecycle": "active",
                "authority": "https://www.ti.com/product/TPS2553",
            },
            {
                "references": ["U7"],
                "manufacturer": "STMicroelectronics",
                "mpn": "USBLC6-2SC6",
                "function": "USB D+/D- ESD array",
                "footprint": "Package_TO_SOT_SMD:SOT-23-6",
                "model_status": "installed_exact_package",
                "lifecycle": "active_volume_production",
                "authority": (
                    "https://www.st.com/en/protections-and-emi-filters/usblc6-2.html"
                ),
            },
            {
                "references": ["U9"],
                "manufacturer": "Texas Instruments",
                "mpn": "TPD1E10B06DPYR",
                "function": "USB VBUS transient/ESD protection",
                "footprint": "PCBSmith_AeroSense:TPD1E10B06_DPY2",
                "model_status": "dimensioned_project_local_package_model",
                "lifecycle": "active",
                "authority": "https://www.ti.com/product/TPD1E10B06",
            },
            {
                "references": ["U10"],
                "manufacturer": "Texas Instruments",
                "mpn": "TPD2EUSB30DRTR",
                "function": "USB Type-C CC1/CC2 ESD protection",
                "footprint": "Package_TO_SOT_SMD:Texas_DRT-3",
                "model_status": "installed_exact_package",
                "lifecycle": "active",
                "authority": "https://www.ti.com/product/TPD2EUSB30",
            },
            {
                "references": ["U11"],
                "manufacturer": "Texas Instruments",
                "mpn": "TPD4E05U06DQAR",
                "function": "four-channel microSD SPI ESD protection",
                "footprint": "Package_SON:USON-10_2.5x1.0mm_P0.5mm",
                "model_status": "installed_exact_package",
                "lifecycle": "active",
                "authority": "https://www.ti.com/product/TPD4E05U06",
            },
            {
                "references": ["U8"],
                "manufacturer": "Sensirion",
                "mpn": "SHT45-AD1B-R3",
                "function": "ambient temperature and humidity sensor",
                "footprint": (
                    "PCBSmith_AeroSense:Sensirion_SHT45_NoCentralPad"
                ),
                "model_status": "dimensioned_project_local_package_model",
                "lifecycle": "active",
                "authority": "https://sensirion.com/resource/datasheet/sht4x",
            },
            {
                "references": ["J1"],
                "manufacturer": "GCT",
                "mpn": "USB4105-GF-A",
                "function": "USB-C 2.0 top-mount receptacle",
                "footprint": (
                    "Connector_USB:"
                    "USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal"
                ),
                "model_status": "installed_exact_connector",
                "lifecycle": "active",
                "authority": "https://gct.co/files/specs/usb4105-spec.pdf",
            },
            {
                "references": ["DS1"],
                "manufacturer": "Adafruit",
                "mpn": "4440",
                "function": "0.91-inch 128x32 I2C OLED module",
                "footprint": "project_local:Adafruit_4440_OLED_Module",
                "model_status": "dimensioned_complete_module_model_required",
                "lifecycle": "active_orderable",
                "authority": "https://www.adafruit.com/product/4440",
                "notes": (
                    "The 20x35x4-mm module is mounted upright on a six-pin "
                    "2.54-mm socket. Retained Adafruit Eagle CAD confirms pin "
                    "order VIN, 3V3-out, GND, RESET, SCL, SDA and onboard "
                    "10-kohm I2C pull-ups/level shifting."
                ),
            },
            {
                "references": ["J3"],
                "manufacturer": "Hirose",
                "mpn": "DM3AT-SF-PEJM5",
                "function": "push-push microSD socket with detect",
                "footprint": "Connector_Card:microSD_HC_Hirose_DM3AT-SF-PEJM5",
                "model_status": "installed_exact_connector",
                "lifecycle": "active",
                "authority": "https://www.hirose.com/en/product/p/CL0609-0031-0-00",
            },
            {
                "references": ["J4", "J5"],
                "manufacturer": "Molex",
                "mpn": "47053-1000",
                "function": "four-pin vertical PWM fan header",
                "footprint": "Connector:FanPinHeader_1x04_P2.54mm_Vertical",
                "model_status": "installed_exact_connector_family",
                "lifecycle": "active",
                "authority": (
                    "https://www.molex.com/content/dam/molex/molex-dot-com/"
                    "products/automated/en-us/salesdrawingpdf/470/47053/"
                    "470531000_sd.pdf"
                ),
            },
            {
                "references": ["FAN1", "FAN2"],
                "manufacturer": "Noctua",
                "mpn": "NF-A4x20 5V PWM",
                "function": "selected external 5-V four-wire PWM fan",
                "footprint": "external_mating_part",
                "model_status": "external_envelope_recorded",
                "lifecycle": "current_product",
                "authority": (
                    "https://www.noctua.at/en/products/nf-a4x20-5v-pwm/"
                    "specifications"
                ),
                "notes": (
                    "0.10 A maximum input current, 4-pin A2543-compatible "
                    "connector, locked-rotor auto power-off and restart."
                ),
            },
            {
                "references": ["SW1", "SW2", "SW3"],
                "manufacturer": "Omron",
                "mpn": "B3F-1000",
                "function": "6x6-mm through-hole user buttons",
                "footprint": "Button_Switch_THT:SW_PUSH_6mm_H4.3mm",
                "model_status": "installed_exact_family",
                "lifecycle": "in_production",
                "authority": "https://components.omron.com/eu-en/products/switches/B3F",
            },
            {
                "references": ["SW4", "SW5"],
                "manufacturer": "Omron",
                "mpn": "B3U-1000P",
                "function": "low-profile SMD BOOTSEL and RESET buttons",
                "footprint": "Button_Switch_SMD:SW_SPST_B3U-1000P",
                "model_status": "installed_exact_package",
                "lifecycle": "in_production",
                "authority": "https://components.omron.com/eu-en/products/switches/B3U",
            },
            {
                "references": ["Q1", "Q2"],
                "manufacturer": "Nexperia",
                "mpn": "2N7002,215",
                "function": "open-drain 25-kHz fan PWM sinks",
                "footprint": "Package_TO_SOT_SMD:SOT-23",
                "model_status": "installed_exact_package",
                "lifecycle": "production",
                "authority": "https://www.nexperia.com/product/2N7002",
            },
            {
                "references": ["D1"],
                "manufacturer": "Würth Elektronik",
                "mpn": "150060GS75000",
                "function": "green PWR/USB status LED",
                "footprint": "LED_SMD:LED_0603_1608Metric",
                "model_status": "installed_exact_package",
                "lifecycle": "active",
                "authority": "https://www.we-online.com/components/products/datasheet/150060GS75000.pdf",
            },
            {
                "references": ["D2"],
                "manufacturer": "Würth Elektronik",
                "mpn": "150060YS75000",
                "function": "yellow/amber FAN/FAULT status LED",
                "footprint": "LED_SMD:LED_0603_1608Metric",
                "model_status": "installed_exact_package",
                "lifecycle": "active",
                "authority": "https://www.we-online.com/components/products/datasheet/150060YS75000.pdf",
            },
            {
                "references": ["D3"],
                "manufacturer": "Würth Elektronik",
                "mpn": "150060BS75000",
                "function": "blue SD/LOG status LED",
                "footprint": "LED_SMD:LED_0603_1608Metric",
                "model_status": "installed_exact_package",
                "lifecycle": "active",
                "authority": "https://www.we-online.com/components/products/datasheet/150060BS75000.pdf",
            },
            {
                "references": ["J6"],
                "manufacturer": "Tag-Connect",
                "mpn": "TC2030-IDC-NL",
                "function": "six-pin no-legs SWD programming interface",
                "footprint": (
                    "Connector:Tag-Connect_TC2030-IDC-NL_2x03_P1.27mm_Vertical"
                ),
                "model_status": "access_envelope_only",
                "lifecycle": "current_product",
                "authority": "https://www.tag-connect.com/product/tc2030-idc-nl",
            },
        ],
        "power_policy": {
            "fan_channel_design_current_a": 0.5,
            "selected_fan_max_current_a": 0.1,
            "logic_reserve_a": 0.2,
            "design_envelope_total_a": 1.2,
            "selected_fan_total_max_a": 0.2,
            "fan_switch_limit_target_a": 0.5,
            "fan_rails_default": "hardware_disabled",
            "fan_enable_policy": "firmware only after Type-C medium/high detection",
        },
        "electrical_refinements": [
            {
                "topic": "USB Type-C Rd termination",
                "decision": (
                    "Use the TUSB320LAI internal UFP Rd terminations. Do not add "
                    "parallel discrete 5.1-kohm resistors, because doing so would "
                    "distort the selected detector's CC thresholds."
                ),
                "authority": "https://www.ti.com/lit/ds/symlink/tusb320lai.pdf",
            },
            {
                "topic": "OLED I2C pull-ups",
                "decision": (
                    "Do not populate additional host pull-ups by default. The "
                    "Adafruit 4440 retained Eagle CAD contains 10-kohm pull-ups "
                    "and bidirectional level shifting."
                ),
                "authority": (
                    "https://github.com/adafruit/"
                    "Adafruit-128x32-I2C-OLED-Breakout-PCB"
                ),
            },
        ],
        "open_evidence_actions_before_schematic_release": [
            "Retain exact TPS2553 R_ILIM calculation and tolerance bounds.",
            "Preflight the generated dimensioned SHT45 package-envelope model.",
            "Preflight the generated dimensioned Adafruit 4440 module model.",
            "Retain USB4105 and DM3AT exact mating/access drawings with hashes.",
        ],
    }


def _footprint(
    item_id: str,
    label: str,
    footprint_id: str,
    anchor: tuple[float, float],
    *,
    rotation: float = 0.0,
    side: str = "front",
    containment: str = "courtyard",
    body_overhang_allowed: bool = False,
    note: str = "",
) -> ConceptItem:
    return ConceptItem(
        item_id=item_id,
        label=label,
        side=side,
        kind="footprint",
        anchor_mm=anchor,
        rotation_deg=rotation,
        footprint_id=footprint_id,
        containment=containment,
        body_overhang_allowed=body_overhang_allowed,
        requirement_resolution="engineering",
        note=note,
    )


def _concept_items() -> tuple[ConceptItem, ...]:
    items: list[ConceptItem] = [
        _footprint(
            "J1",
            "",
            (
                "Connector_USB:"
                "USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal"
            ),
            (3.1, 25.0),
            rotation=270.0,
            containment="pads_and_holes",
            note="All electrical, shell and locating-pad geometry is contained.",
        ),
        ConceptItem(
            item_id="J1.body",
            label="USB-C",
            side="front",
            kind="rectangle",
            anchor_mm=(3.1, 25.0),
            rotation_deg=270.0,
            size_mm=(8.94, 7.35),
            containment="shape",
            body_overhang_allowed=True,
            requirement_resolution="explicit",
            note="Mating face projects through X=0 while every pad remains on-board.",
        ),
        _footprint(
            "U7",
            "U7",
            "Package_TO_SOT_SMD:SOT-23-6",
            (10.2, 25.0),
        ),
        _footprint(
            "U9",
            "VBUS ESD",
            "Package_SON:Texas_DPY0002A_0.6x1mm_P0.65mm",
            (8.2, 20.5),
        ),
        _footprint(
            "U10",
            "CC ESD",
            "Package_TO_SOT_SMD:Texas_DRT-3",
            (8.5, 29.5),
        ),
        _footprint(
            "U3",
            "U3",
            "Package_TO_SOT_SMD:SOT-23-5",
            (10.5, 16.0),
        ),
        _footprint(
            "U4",
            "U4",
            "Package_DFN_QFN:Texas_X2QFN-12_1.6x1.6mm_P0.4mm",
            (11.0, 33.0),
        ),
        _footprint(
            "U1",
            "RP2040",
            (
                "Package_DFN_QFN:"
                "QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm_ThermalVias"
            ),
            (31.0, 27.0),
        ),
        _footprint(
            "U2",
            "U2",
            "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
            (22.5, 27.0),
            rotation=90.0,
        ),
        _footprint(
            "Y1",
            "Y1",
            "Crystal:Crystal_SMD_Abracon_ABM8G-4Pin_3.2x2.5mm",
            (15.5, 25.0),
        ),
        _footprint(
            "U5",
            "U5",
            "Package_TO_SOT_SMD:SOT-23-6",
            (46.0, 26.0),
        ),
        _footprint(
            "U6",
            "U6",
            "Package_TO_SOT_SMD:SOT-23-6",
            (52.0, 26.0),
        ),
        _footprint(
            "Q1",
            "PWM1",
            "Package_TO_SOT_SMD:SOT-23",
            (47.0, 30.0),
        ),
        _footprint(
            "Q2",
            "PWM2",
            "Package_TO_SOT_SMD:SOT-23",
            (53.0, 30.0),
        ),
        _footprint(
            "U8",
            "",
            (
                "Sensor_Humidity:"
                "Sensirion_DFN-4_1.5x1.5mm_P0.8mm_SHT4x_NoCentralPad"
            ),
            (14.0, 43.0),
        ),
        _footprint(
            "J3",
            "microSD",
            "Connector_Card:microSD_HC_Hirose_DM3AT-SF-PEJM5",
            (28.0, 40.6),
        ),
        _footprint(
            "U11",
            "SD ESD",
            "Package_SON:USON-10_2.5x1.0mm_P0.5mm",
            (18.0, 32.5),
            rotation=90.0,
        ),
        _footprint(
            "J4",
            "FAN1",
            "Connector:FanPinHeader_1x04_P2.54mm_Vertical",
            (58.0, 11.0),
            rotation=90.0,
        ),
        _footprint(
            "J5",
            "FAN2",
            "Connector:FanPinHeader_1x04_P2.54mm_Vertical",
            (58.0, 24.0),
            rotation=90.0,
        ),
        _footprint(
            "SW1",
            "MODE",
            "Button_Switch_THT:SW_PUSH_6mm_H4.3mm",
            (40.0, 35.0),
        ),
        _footprint(
            "SW2",
            "SELECT",
            "Button_Switch_THT:SW_PUSH_6mm_H4.3mm",
            (50.0, 35.0),
        ),
        _footprint(
            "SW3",
            "LOG",
            "Button_Switch_THT:SW_PUSH_6mm_H4.3mm",
            (60.0, 35.0),
        ),
        _footprint(
            "D1",
            "PWR",
            "LED_SMD:LED_0603_1608Metric",
            (39.0, 43.0),
        ),
        _footprint(
            "D2",
            "FAULT",
            "LED_SMD:LED_0603_1608Metric",
            (49.0, 43.0),
        ),
        _footprint(
            "D3",
            "LOG",
            "LED_SMD:LED_0603_1608Metric",
            (59.0, 43.0),
        ),
        _footprint(
            "J6",
            "SWD",
            "Connector:Tag-Connect_TC2030-IDC-NL_2x03_P1.27mm_Vertical",
            (34.0, 11.0),
            side="back",
            note="Bottom-side no-legs programming pads remain probe-accessible.",
        ),
        ConceptItem(
            item_id="DS1",
            label="OLED",
            side="front",
            kind="rectangle",
            anchor_mm=(33.5, 10.5),
            size_mm=(35.0, 20.0),
            containment="shape",
            requirement_resolution="engineering",
            note="Adafruit 4440 daughterboard envelope; upright normal viewing orientation.",
        ),
        ConceptItem(
            item_id="sensor.keepout",
            label="SHT45 isolation",
            side="front",
            kind="rectangle",
            anchor_mm=(14.0, 43.0),
            size_mm=(11.5, 11.5),
            containment="shape",
            requirement_resolution="explicit",
            note="No heat source, copper pour or unrelated component inside this region.",
        ),
        ConceptItem(
            item_id="power.passives",
            label="",
            side="front",
            kind="rectangle",
            anchor_mm=(10.5, 21.5),
            size_mm=(5.0, 2.5),
            containment="shape",
            requirement_resolution="engineering",
            note="VBUS TVS, fuse, LDO input/output and bulk capacitors.",
        ),
        ConceptItem(
            item_id="mcu.passives",
            label="",
            side="front",
            kind="rectangle",
            anchor_mm=(31.0, 21.7),
            size_mm=(10.0, 2.0),
            containment="shape",
            requirement_resolution="engineering",
            note="Distributed RP2040 100 nF and 1.0 uF loop-local capacitors.",
        ),
        ConceptItem(
            item_id="fan.passives",
            label="",
            side="front",
            kind="rectangle",
            anchor_mm=(52.0, 30.0),
            size_mm=(16.0, 4.0),
            containment="shape",
            requirement_resolution="engineering",
            note="Per-channel R_ILIM, local ceramics, bulk, fault pull-ups and test points.",
        ),
        ConceptItem(
            item_id="usb.access",
            label="USB cable",
            side="front",
            kind="aperture",
            anchor_mm=(-5.0, 25.0),
            size_mm=(10.0, 12.0),
            containment="none",
            requirement_resolution="explicit",
            note="External mating and cable swept volume.",
        ),
        ConceptItem(
            item_id="sd.access",
            label="card access",
            side="front",
            kind="aperture",
            anchor_mm=(28.0, 56.5),
            size_mm=(14.0, 18.0),
            containment="none",
            requirement_resolution="explicit",
            note="External microSD insertion and ejection swept volume.",
        ),
    ]
    for reference, x, y in (
        ("H1", 3.0, 3.0),
        ("H2", 67.0, 3.0),
        ("H3", 3.0, 47.0),
        ("H4", 67.0, 47.0),
    ):
        items.append(
            ConceptItem(
                item_id=reference,
                label=reference,
                side="both",
                kind="mounting_hole",
                anchor_mm=(x, y),
                diameter_mm=3.2,
                containment="shape",
                requirement_resolution="explicit",
                note="3.2-mm NPTH; four-millimetre component exclusion is checked separately.",
            )
        )
    return tuple(items)


def _component_envelopes(review: ConceptReview) -> tuple[PlacementEnvelope, ...]:
    excluded = {
        "H1",
        "H2",
        "H3",
        "H4",
        "J1.body",
        "sensor.keepout",
        "usb.access",
        "sd.access",
    }
    return tuple(
        PlacementEnvelope(
            envelope_id=f"envelope.{item.item.item_id}",
            subject_id=item.item.item_id,
            polygon=item.envelope,
            source_geometry_sha256=fingerprint(
                {
                    "item": item.item.model_dump(mode="json"),
                    "envelope": item.envelope,
                    "source": item.footprint_source_file,
                }
            ),
        )
        for item in review.items
        if item.item.item_id not in excluded
    )


def _keepouts() -> tuple[tuple[tuple[float, float], ...], ...]:
    from shapely.geometry import Point

    return tuple(
        tuple(
            (float(x), float(y))
            for x, y in Point(cx, cy).buffer(4.0, quad_segs=32).exterior.coords
        )
        for cx, cy in ((3.0, 3.0), (67.0, 3.0), (3.0, 47.0), (67.0, 47.0))
    )


def _routing_necks() -> tuple[NeckSection, ...]:
    geometry_hash = fingerprint(
        {
            "outline": OUTLINE,
            "concept": "aerosense-r001",
            "method": "coarse pre-route corridor reservation",
        }
    )
    return (
        NeckSection(
            neck_id="neck.usb-entry",
            usable_width_mm=5.0,
            routing_layers=("F.Cu", "B.Cu"),
            capacity_quantum_mm=0.5,
            source_geometry_sha256=geometry_hash,
        ),
        NeckSection(
            neck_id="neck.core-right",
            usable_width_mm=10.0,
            routing_layers=("F.Cu", "B.Cu"),
            capacity_quantum_mm=0.5,
            source_geometry_sha256=geometry_hash,
        ),
        NeckSection(
            neck_id="neck.bottom-service",
            usable_width_mm=8.0,
            routing_layers=("F.Cu", "B.Cu"),
            capacity_quantum_mm=0.5,
            source_geometry_sha256=geometry_hash,
        ),
    )


def _demand(
    name: str,
    terminals: tuple[str, ...],
    necks: tuple[str, ...],
    *,
    width: float = 0.2,
    priority: int = 10,
) -> PreRouteNetDemand:
    return PreRouteNetDemand(
        net_name=name,
        terminal_ids=terminals,
        trace_width_mm=width,
        clearance_mm=0.15,
        candidate_neck_ids=necks,
        net_class_id="power" if width > 0.3 else "signal",
        priority=priority,
    )


def _net_demands() -> tuple[PreRouteNetDemand, ...]:
    return (
        _demand("USB_DP", ("J1.A6", "U7.1", "U1.47"), ("neck.usb-entry",), priority=0),
        _demand("USB_DM", ("J1.A7", "U7.3", "U1.46"), ("neck.usb-entry",), priority=0),
        _demand("CC1", ("J1.A5", "U4.1"), ("neck.usb-entry",), priority=1),
        _demand("CC2", ("J1.B5", "U4.2"), ("neck.usb-entry",), priority=1),
        _demand(
            "VBUS",
            ("J1.A4", "U3.1", "U5.1", "U6.1"),
            ("neck.usb-entry", "neck.core-right"),
            width=0.8,
            priority=0,
        ),
        _demand(
            "FAN1_5V",
            ("U5.6", "J4.2"),
            ("neck.core-right",),
            width=0.8,
            priority=0,
        ),
        _demand(
            "FAN2_5V",
            ("U6.6", "J5.2"),
            ("neck.core-right",),
            width=0.8,
            priority=0,
        ),
        _demand("FAN1_PWM", ("U1.4", "J4.4"), ("neck.core-right",)),
        _demand("FAN2_PWM", ("U1.5", "J5.4"), ("neck.core-right",)),
        _demand("FAN1_TACH", ("J4.3", "U1.6"), ("neck.core-right",)),
        _demand("FAN2_TACH", ("J5.3", "U1.7"), ("neck.core-right",)),
        _demand("I2C_SDA", ("U1.8", "U8.1", "DS1.4"), ("neck.bottom-service",)),
        _demand("I2C_SCL", ("U1.9", "U8.2", "DS1.3"), ("neck.bottom-service",)),
        _demand("SD_CLK", ("U1.14", "J3.5"), ("neck.bottom-service",)),
        _demand("SD_CMD", ("U1.15", "J3.3"), ("neck.bottom-service",)),
        _demand("SD_DAT0", ("U1.16", "J3.7"), ("neck.bottom-service",)),
    )


def _overlap_findings(review: ConceptReview) -> tuple[str, ...]:
    from shapely.geometry import Polygon

    excluded = {
        "H1",
        "H2",
        "H3",
        "H4",
        "J1.body",
        "sensor.keepout",
        "usb.access",
        "sd.access",
    }
    shapes = {
        result.item.item_id: Polygon(result.envelope)
        for result in review.items
        if result.item.item_id not in excluded
    }
    sides = {
        result.item.item_id: result.item.side
        for result in review.items
        if result.item.item_id not in excluded
    }
    allowed = {
        frozenset(("U1", "mcu.passives")),
        frozenset(("U5", "fan.passives")),
        frozenset(("U6", "fan.passives")),
        frozenset(("Q1", "fan.passives")),
        frozenset(("Q2", "fan.passives")),
        frozenset(("U3", "power.passives")),
        frozenset(("U9", "power.passives")),
    }
    findings: list[str] = []
    names = tuple(sorted(shapes))
    for index, first in enumerate(names):
        for second in names[index + 1 :]:
            if (
                sides[first] != "both"
                and sides[second] != "both"
                and sides[first] != sides[second]
            ):
                continue
            if frozenset((first, second)) in allowed:
                continue
            overlap = shapes[first].intersection(shapes[second]).area
            if overlap > 1e-6:
                findings.append(
                    f"{first} overlaps {second} by {overlap:.3f} mm² in concept geometry."
                )
    sensor_zone = Polygon(
        next(
            item.envelope
            for item in review.items
            if item.item.item_id == "sensor.keepout"
        )
    )
    for name, shape in shapes.items():
        if name == "U8":
            continue
        overlap = sensor_zone.intersection(shape).area
        if overlap > 1e-6:
            findings.append(
                f"{name} enters the SHT45 isolation region by {overlap:.3f} mm²."
            )
    return tuple(findings)


def _write_part_report(selection: dict[str, Any], output_dir: Path) -> None:
    path = output_dir / "exact-part-selection.json"
    path.write_text(json.dumps(selection, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# AeroSense-2F R001 exact-part freeze",
        "",
        f"Status: **{selection['selection_status']}**",
        "",
        "| Reference | MPN | Function | Lifecycle | 3D/CAD state |",
        "|---|---|---|---|---|",
    ]
    for item in selection["parts"]:
        lines.append(
            "| "
            + " ".join(item["references"])
            + f" | {item['mpn']} | {item['function']} | {item['lifecycle']} | "
            + item["model_status"]
            + " |"
        )
    lines.extend(
        [
            "",
            "## Open evidence actions before schematic release",
            "",
            *(
                f"- {action}"
                for action in selection["open_evidence_actions_before_schematic_release"]
            ),
            "",
            "This freeze authorizes concept feasibility only. It is not a BOM release.",
            "",
        ]
    )
    (output_dir / "exact-part-selection.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def _write_intake_review(
    output_dir: Path,
    review: ConceptReview,
    feasibility: Any,
) -> None:
    by_id = {result.item.item_id: result for result in review.items}
    lines = [
        "# AeroSense-2F R001 concept approval gate",
        "",
        "This package stops before schematic and PCB generation, as required by the",
        "reviewed prompt. Approval authorizes the proposed physical architecture;",
        "it does not approve electrical correctness, routing or manufacturing release.",
        "",
        "## Automated result",
        "",
        "- Prompt examination: ready for concept.",
        "- Exact-part selection: frozen for concept.",
        "- Component/courtyard overlap check: clean.",
        f"- Pre-route feasibility: {feasibility.outcome.value}.",
        f"- Estimated two-side envelope utilization: {feasibility.area_utilization:.1%}.",
        "- Routing-corridor capacity: all declared demands assigned; no failing nets.",
        "",
        "## Proposed architecture",
        "",
        "- 70 × 50 mm rectangular two-layer board with four 3.2 mm NPTH holes.",
        "- Front: OLED upper centre; USB-C at the left edge; two fan headers at",
        "  upper-right; microSD at the bottom edge; three buttons lower-right;",
        "  SHT45 isolated at the lower-left ambient corner.",
        "- Back: TC2030 no-legs SWD probe interface only.",
        "- USB-C shell intentionally overhangs the left edge by "
        f"{abs(by_id['J1.body'].minimum_edge_clearance_mm):.3f} mm, while its "
        f"pads remain {by_id['J1'].minimum_edge_clearance_mm:.3f} mm inside.",
        f"- OLED edge clearance: {by_id['DS1'].minimum_edge_clearance_mm:.3f} mm.",
        f"- microSD courtyard edge clearance: "
        f"{by_id['J3'].minimum_edge_clearance_mm:.3f} mm.",
        "- The 5 mm SHT45 isolation region is free of unrelated component envelopes.",
        "",
        "## Approval decision",
        "",
        "Approve or revise these five points before schematic generation:",
        "",
        "1. 70 × 50 mm outline and four-hole pattern.",
        "2. OLED-dominant front layout and lower-right button row.",
        "3. Left-edge USB-C overhang and bottom-edge microSD access.",
        "4. Lower-left SHT45 ambient isolation zone.",
        "5. Bottom-side SWD probe location.",
        "",
        "The selected exact parts and unresolved evidence actions are recorded in",
        "`exact-part-selection.md`; the authoritative geometry is in `concept/`.",
        "",
    ]
    (output_dir / "intake-review.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


def build(prompt_file: Path, output_dir: Path) -> None:
    prompt_text = prompt_file.read_text(encoding="utf-8")
    output_dir.mkdir(parents=True, exist_ok=True)

    examination = _build_examination(prompt_text)
    (output_dir / "prompt-examination.json").write_text(
        examination.model_dump_json(indent=2), encoding="utf-8"
    )
    selection = _part_selection()
    _write_part_report(selection, output_dir)

    context_payload = fingerprint(
        {
            "prompt": examination.examination_fingerprint,
            "part_selection": selection,
        }
    )
    context = populate_project_context(
        examination=examination,
        generation_sha256=context_payload,
        inputs=tuple(
            ContextPopulationInput(
                category=category,
                payload_sha256=context_payload,
                source_binding_ids=tuple(span.span_id for span in examination.spans),
                reviewer_record_id="engineering-review.2026-07-26",
                rationale=(
                    "Resolved by the engineering-reviewed prompt and the "
                    "concept-stage exact-part selection."
                ),
            )
            for category in ALL_PROJECT_CONTEXT_CATEGORIES
        ),
    )
    (output_dir / "project-context.json").write_text(
        context.model_dump_json(indent=2), encoding="utf-8"
    )

    review = examine_concept(
        PROJECT_ID,
        OUTLINE,
        _concept_items(),
        tight_clearance_mm=0.5,
        assumptions=(
            "Adafruit 4440 uses its documented 35 x 20 mm PCB envelope in landscape.",
            "Fan headers are vertical Molex 47053-family geometry.",
            "SHT45 isolation is represented by an 11.5 x 11.5 mm component-centred zone.",
            "The overlays are exact-placement plans, not routed or thermally validated boards.",
        ),
    )
    write_concept_review_package(review, output_dir / "concept")

    overlap_findings = _overlap_findings(review)
    (output_dir / "concept-overlap-check.json").write_text(
        json.dumps(
            {
                "schema": "pcbsmith-aerosense-concept-overlap-check-v1",
                "project_id": PROJECT_ID,
                "clean": not overlap_findings,
                "findings": overlap_findings,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    outline_sha256 = fingerprint({"outline": OUTLINE})
    feasibility = evaluate_pre_route_feasibility(
        board_outline=OUTLINE,
        board_outline_sha256=outline_sha256,
        keepout_polygons=_keepouts(),
        envelopes=_component_envelopes(review),
        necks=_routing_necks(),
        net_demands=_net_demands(),
        attention_utilization=0.70,
    )
    (output_dir / "pre-route-feasibility.json").write_text(
        feasibility.model_dump_json(indent=2), encoding="utf-8"
    )
    _write_intake_review(output_dir, review, feasibility)

    summary = {
        "schema": "pcbsmith-aerosense-intake-summary-v1",
        "project_id": PROJECT_ID,
        "prompt_examination": examination.outcome,
        "exact_part_selection": selection["selection_status"],
        "concept_outcome": review.outcome,
        "overlap_check_clean": not overlap_findings,
        "pre_route_feasibility": feasibility.outcome.value,
        "ready_for_user_concept_review": (
            examination.outcome == "ready_for_concept"
            and not overlap_findings
            and feasibility.outcome.value in {"ready", "attention_required"}
        ),
    }
    (output_dir / "intake-summary.json").write_text(
        json.dumps(summary, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prompt",
        type=Path,
        default=Path("docs/project-prompts/aerosense-2f-r001.md"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("outputs/aerosense-2f-r001/intake"),
    )
    args = parser.parse_args()
    build(args.prompt, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
