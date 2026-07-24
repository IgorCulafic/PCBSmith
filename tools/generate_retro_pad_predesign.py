"""Generate the Retro-Pad normalized brief and deterministic concept review.

This command deliberately stops before schematic or PCB generation.
"""

# The exact user brief below is retained verbatim; do not wrap its source lines.
# ruff: noqa: E501

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pcbsmith.kicad.concept_review import (
    ConceptItem,
    examine_concept,
    write_concept_review_package,
)
from pcbsmith.kicad.raster_artwork import trace_board_outline
from pcbsmith.predesign_gate import ConceptApproval, write_approval_request
from pcbsmith.project_brief import (
    ArtworkRequirement,
    AssetReference,
    BriefFinding,
    ComponentRequirement,
    MechanicalRequirement,
    PlacementRequirement,
    ProjectBriefDraft,
    RequirementValue,
    Resolution,
    normalize_project_brief,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "retro-pad-r002"
SOURCE = ROOT / "outputs" / "retro-pad-r001"
PREDESIGN = OUTPUT / "predesign"
OUTLINE_FILE = SOURCE / "input" / "board_outline.png"
ART_FILE = SOURCE / "input" / "silkscreen_art.png"
TARGET_WIDTH_MM = 120.0
MAXIMUM_HEIGHT_MM = 48.0

APPROVED_AMENDMENT = """Approved amendment — 2026-07-20
The user authorized increasing the board to 120 mm × 48 mm maximum. Preserve the
supplied dogbone proportions by scaling it uniformly to 120 mm wide (about
46.5 mm high), and use the previously proposed inward symmetric mounting holes.
"""

ORIGINAL_BRIEF = """Project: "Retro-Pad" USB Macro Keyboard
This project tests the ability to place mechanical components accurately, handle polarized components in repeating sub-circuits, route USB data lines, and integrate external DXF/PNG shapes for board outlines and silkscreens.

1. Functional Requirements
What it should do: A programmable USB macro pad that acts as a standard Human Interface Device (HID) keyboard. It features 4 mechanical key switches and 1 rotary encoder with a push-button function.

Power & Current: Powered entirely via USB Type-C (5.0V DC). Approximate current draw is < 150mA.

Components & ICs:

MCU: Select a suitable microcontroller with native USB support (e.g., RP2040, ATmega32U4, or CH552G).

Actuators: 4x Cherry MX-compatible mechanical keyboard switches, 1x EC11-style rotary encoder.

Indicators: 4x WS2812B (NeoPixel) reverse-mount RGB LEDs, positioned on the bottom of the board shining up through holes under the mechanical switches.

Passives: Appropriate decoupling capacitors, pull-up/pull-down resistors, and a crystal oscillator (if required by the chosen MCU).

Anti-Ghosting Diodes: 4x small-signal switching diodes (e.g., 1N4148 in a small SOD-123 SMD package).

Switch Matrix Logic: Do not wire the 4 mechanical switches directly to individual GPIO pins. You must construct a 2x2 switch matrix. Each switch must have a diode placed in series to prevent current backflow (ghosting) when multiple keys are pressed simultaneously.

Connectors: 1x USB Type-C (16-pin or 24-pin receptacle). Must be located exactly on the top edge of the board, centered horizontally.

2. Physical & Spatial Constraints
Max Dimensions: 100mm (width) x 40mm (height).

Mounting Holes: Four M2.5 (2.7mm drill diameter) unplated mounting holes. They must be located in the four corners, exactly 4mm from the X and Y edges of the board.

Fixed Component Locations: The USB Type-C port must sit on the top edge. The 4 mechanical switches should be evenly spaced on the left side of the board. The rotary encoder should be located on the far right side of the board.

3. Graphics & Silkscreen Requirements
Use the provided Python script below to generate the required image assets.

Board Outline PNG: A "dogbone" retro controller shape.

Real-World Dimension: The width of the generated image from tip to tip is exactly 100mm.

Silkscreen Art PNG: A pixel-art heart.

Side: Front (Top) Copper/Silkscreen layer.

Approximate Position: Centered between the 4 mechanical switches and the rotary encoder.

Physical Width: 12mm.

Rotation: 0 degrees (Upright).

Mirroring: None (do not mirror).

4. Manufacturing & Assembly
Assembly Style: Mostly SMD to test surface-mount routing. Prefer 0805 or 0603 packages for passive components so it remains hand-solderable for prototyping. The switches and rotary encoder must be Through-Hole (THT).

Fabrication Requirements: Standard 2-layer FR4 board, 1.6mm thickness. Clearances must pass standard budget fab house DRC: 6 mil (0.15mm) minimum trace width, 6 mil minimum clearance, 0.3mm minimum via drill size.

Safety/Environmental: Include a basic ESD protection diode array (e.g., USBLC6-2SC6) on the USB D+/D- lines.
"""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _value(
    requirement_id: str,
    value: str | float | int | bool,
    unit: str | None,
    source_text: str,
    *,
    resolution: Resolution = "explicit",
    rationale: str | None = None,
) -> RequirementValue:
    return RequirementValue(
        requirement_id=requirement_id,
        value=value,
        unit=unit,
        source="user",
        resolution=resolution,
        source_text=source_text,
        rationale=rationale,
    )


def _draft(outline_height_mm: float) -> ProjectBriefDraft:
    components = (
        ComponentRequirement(
            component_id="mcu",
            quantity=1,
            role="native USB MCU",
            selection="ATmega32U4-AU",
            footprint_id="Package_QFP:TQFP-44_10x10mm_P0.8mm",
            side="back",
            mounting="smd",
            source="engineering",
            resolution="assumed",
        ),
        ComponentRequirement(
            component_id="keys",
            quantity=4,
            role="mechanical key switch",
            selection="Cherry MX compatible",
            footprint_id="Button_Switch_Keyboard:SW_Cherry_MX_1.00u_PCB",
            side="front",
            mounting="tht",
        ),
        ComponentRequirement(
            component_id="encoder",
            quantity=1,
            role="rotary encoder with push",
            selection="EC11",
            footprint_id="Rotary_Encoder:RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm",
            side="front",
            mounting="tht",
            resolution="assumed",
        ),
        ComponentRequirement(
            component_id="rgb",
            quantity=4,
            role="reverse-mount addressable RGB",
            selection="SK6812MINI-E",
            footprint_id="LED_SMD:LED_SK6812MINI-E_3.2x2.8mm_P1.5mm_ReverseMount",
            side="back",
            mounting="smd",
            source="engineering",
            resolution="assumed",
        ),
        ComponentRequirement(
            component_id="matrix-diodes",
            quantity=4,
            role="anti-ghosting diode",
            selection="1N4148W",
            footprint_id="Diode_SMD:D_SOD-123",
            side="back",
            mounting="smd",
        ),
        ComponentRequirement(
            component_id="usb",
            quantity=1,
            role="USB-C receptacle",
            selection="GCT USB4105",
            footprint_id="Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal",
            side="front",
            mounting="smd",
            source="engineering",
            resolution="assumed",
        ),
        ComponentRequirement(
            component_id="usb-esd",
            quantity=1,
            role="USB data ESD array",
            selection="USBLC6-2SC6",
            footprint_id="Package_TO_SOT_SMD:SOT-23-6_Handsoldering",
            side="back",
            mounting="smd",
        ),
    )
    placements = (
        PlacementRequirement(
            placement_id="usb.top-center",
            subject="USB-C receptacle",
            relation="centered on top edge",
            side="front",
            anchor_semantics="mating-face center on a selected accessible top boundary segment",
            resolution="derived",
            source_text="exactly on the top edge, centered horizontally",
        ),
        PlacementRequirement(
            placement_id="keys.left",
            subject="four key switches",
            relation="evenly spaced on left side",
            side="front",
            anchor_semantics=(
                "physical 2x2 key-center grid proposed; prompt only specifies logical 2x2"
            ),
            resolution="derived",
            source_text="evenly spaced on the left side",
        ),
        PlacementRequirement(
            placement_id="encoder.right",
            subject="rotary encoder",
            relation="far right",
            side="front",
            anchor_semantics="shaft center",
            resolution="assumed",
            source_text="far right side",
        ),
    )
    return ProjectBriefDraft(
        project_id="retro-pad",
        title="Retro-Pad USB Macro Keyboard",
        original_text=f"{ORIGINAL_BRIEF}\n\n{APPROVED_AMENDMENT}",
        functional_requirements=(
            _value(
                "function.usb-hid",
                "standard USB HID keyboard",
                None,
                "acts as a standard HID keyboard",
            ),
            _value("matrix.shape", "2x2", None, "must construct a 2x2 switch matrix"),
        ),
        electrical_requirements=(
            _value("power.input", 5.0, "V DC", "powered entirely via USB Type-C (5.0V DC)"),
            _value(
                "power.current",
                150.0,
                "mA",
                "approximate current draw is < 150mA",
                resolution="derived",
                rationale="Firmware RGB brightness limiting enforces the approved current target.",
            ),
        ),
        manufacturing_requirements=(
            _value("fab.trace-min", 0.15, "mm", "6 mil minimum trace width"),
            _value("fab.clearance-min", 0.15, "mm", "6 mil minimum clearance"),
            _value("fab.via-drill-min", 0.30, "mm", "0.3mm minimum via drill size"),
        ),
        mechanics=MechanicalRequirement(
            maximum_width_mm=_value(
                "mechanical.max-width",
                TARGET_WIDTH_MM,
                "mm",
                "Approved amendment: 120 mm maximum width",
                resolution="derived",
                rationale="User explicitly authorized the larger board after placement review.",
            ),
            maximum_height_mm=_value(
                "mechanical.max-height",
                MAXIMUM_HEIGHT_MM,
                "mm",
                "Approved amendment: 48 mm maximum height",
                resolution="derived",
                rationale="Uniform outline scaling remains below this maximum.",
            ),
            board_thickness_mm=_value("mechanical.thickness", 1.6, "mm", "1.6mm thickness"),
            layer_count=_value("mechanical.layers", 2, "copper layers", "2-layer FR4 board"),
            outline_asset_id="dogbone-outline",
            mounting_hole_diameter_mm=_value(
                "mechanical.hole-diameter", 2.7, "mm", "2.7mm drill diameter"
            ),
            mounting_hole_centers_mm=(
                (9.5, 9.5),
                (110.5, 9.5),
                (9.5, outline_height_mm - 9.5),
                (110.5, outline_height_mm - 9.5),
            ),
        ),
        components=components,
        placements=placements,
        artwork=(
            ArtworkRequirement(
                artwork_id="pixel-heart",
                asset_id="heart-art",
                side="front",
                anchor_mm=None,
                anchor_semantics="geometric midpoint between key-group and encoder centers",
                width_mm=12.0,
                rotation_deg=0.0,
                mirrored=False,
                placement_resolution="derived",
            ),
        ),
        assets=(
            AssetReference(
                asset_id="dogbone-outline",
                purpose="outline",
                source_file=str(OUTLINE_FILE.resolve()),
                source_sha256=_sha(OUTLINE_FILE),
                physical_width_mm=TARGET_WIDTH_MM,
            ),
            AssetReference(
                asset_id="heart-art",
                purpose="silkscreen",
                source_file=str(ART_FILE.resolve()),
                source_sha256=_sha(ART_FILE),
                physical_width_mm=12.0,
            ),
        ),
        spirit_anchors=(
            "recognizable dogbone retro-controller silhouette",
            "four-key left cluster",
            "encoder on far right",
            "pixel-heart focal point between controls",
        ),
        engineering_freedoms=(
            "select native-USB MCU",
            "place support electronics on back",
            "choose exact 2x2 physical key-grid spacing",
            "limit RGB brightness in firmware",
        ),
    )


def _items(height: float) -> tuple[ConceptItem, ...]:
    key_centers = ((17.46, 18.58), (36.51, 18.58), (22.54, 27.47), (41.59, 27.47))
    items: list[ConceptItem] = []
    accepted_holes = (
        (9.5, 9.5),
        (110.5, 9.5),
        (9.5, height - 9.5),
        (110.5, height - 9.5),
    )
    for index, center in enumerate(accepted_holes, 1):
        items.append(
            ConceptItem(
                item_id=f"H{index}",
                label=f"H{index}",
                side="both",
                kind="mounting_hole",
                anchor_mm=center,
                diameter_mm=2.7,
                containment="shape",
                requirement_resolution="derived",
                note="user-approved symmetric curved-boundary inset",
            )
        )
    for index, center in enumerate(key_centers, 1):
        items.extend(
            (
                ConceptItem(
                    item_id=f"SW{index}.mounts",
                    label=f"SW{index}",
                    side="front",
                    kind="footprint",
                    anchor_mm=center,
                    rotation_deg=180.0 if index < 3 else 0.0,
                    footprint_id="Button_Switch_Keyboard:SW_Cherry_MX_1.00u_PCB",
                    containment="pads_and_holes",
                    requirement_resolution="derived",
                ),
                ConceptItem(
                    item_id=f"SW{index}.keycap",
                    label=f"K{index}",
                    side="front",
                    kind="rectangle",
                    anchor_mm=(
                        center[0] + (2.54 if index < 3 else -2.54),
                        center[1] + (-5.08 if index < 3 else 5.08),
                    ),
                    size_mm=(18.0, 18.0),
                    containment="shape",
                    body_overhang_allowed=True,
                    requirement_resolution="derived",
                    note=(
                        "nominal 18 mm keycap envelope; user-approved overhang while "
                        "the switch mounting geometry remains contained"
                    ),
                ),
                ConceptItem(
                    item_id=f"LED{index}.aperture",
                    label="",
                    side="both",
                    kind="aperture",
                    anchor_mm=(
                        20.0 if index in (1, 3) else 35.05,
                        8.0 if index < 3 else 38.05,
                    ),
                    size_mm=(2.0, 2.0),
                    containment="shape",
                    requirement_resolution="derived",
                ),
            )
        )
    items.extend(
        (
            ConceptItem(
                item_id="J1",
                label="USB-C",
                side="front",
                kind="footprint",
                anchor_mm=(60.0, 13.3),
                rotation_deg=180.0,
                footprint_id="Connector_USB:USB_C_Receptacle_GCT_USB4105-xx-A_16P_TopMnt_Horizontal",
                containment="pads_and_holes",
                requirement_resolution="derived",
            ),
            ConceptItem(
                item_id="SW5.mounts",
                label="",
                side="front",
                kind="footprint",
                anchor_mm=(98.0, 20.5),
                footprint_id="Rotary_Encoder:RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm",
                containment="pads_and_holes",
                requirement_resolution="derived",
            ),
            ConceptItem(
                item_id="SW5.body",
                label="ENC",
                side="front",
                kind="footprint",
                anchor_mm=(98.0, 20.5),
                footprint_id="Rotary_Encoder:RotaryEncoder_Alps_EC11E-Switch_Vertical_H20mm",
                containment="body",
                requirement_resolution="derived",
            ),
            ConceptItem(
                item_id="ART1",
                label="12 mm heart",
                side="front",
                kind="rectangle",
                anchor_mm=(76.0, 31.0),
                size_mm=(12.0, 12.0),
                containment="shape",
                requirement_resolution="derived",
            ),
            ConceptItem(
                item_id="U1",
                label="ATmega32U4",
                side="back",
                kind="footprint",
                anchor_mm=(70.0, 29.0),
                footprint_id="Package_QFP:TQFP-44_10x10mm_P0.8mm",
                containment="courtyard",
                requirement_resolution="assumed",
            ),
            ConceptItem(
                item_id="U2",
                label="USB ESD",
                side="front",
                kind="footprint",
                anchor_mm=(61.0, 21.5),
                footprint_id="Package_TO_SOT_SMD:SOT-23-6_Handsoldering",
                containment="courtyard",
                requirement_resolution="assumed",
            ),
        )
    )
    for index, center in enumerate(
        ((20.0, 8.0), (35.05, 8.0), (20.0, 38.05), (35.05, 38.05)), 1
    ):
        items.append(
            ConceptItem(
                item_id=f"D{index + 4}",
                label=f"L{index}",
                side="back",
                kind="footprint",
                anchor_mm=center,
                rotation_deg=0.0,
                footprint_id="LED_SMD:LED_SK6812MINI-E_3.2x2.8mm_P1.5mm_ReverseMount",
                containment="courtyard",
                requirement_resolution="derived",
            )
        )
    for index, center in enumerate(((11.0, 23.0), (24.0, 23.0), (33.0, 23.0), (46.0, 23.0)), 1):
        items.append(
            ConceptItem(
                item_id=f"D{index}",
                label=f"D{index}",
                side="back",
                kind="footprint",
                anchor_mm=center,
                rotation_deg=90.0,
                footprint_id="Diode_SMD:D_SOD-123",
                containment="courtyard",
                requirement_resolution="assumed",
            )
        )
    return tuple(items)


def main() -> int:
    trace = trace_board_outline(OUTLINE_FILE, target_width_mm=TARGET_WIDTH_MM)
    height = trace.target_size_mm[1]
    review = examine_concept(
        "retro-pad",
        trace.outline,
        _items(height),
        hard_conflicts=(),
        assumptions=(
            "The concept uses a physical 2x2 key cluster; the prompt only requires a "
            "logical 2x2 matrix.",
            "USB-C top-edge placement uses the central upper boundary segment and the "
            "GCT USB4105 footprint.",
            "The four RGB parts are SK6812MINI-E reverse-mount devices, not ordinary "
            "top-emitting WS2812B packages.",
            "The user approved a uniformly scaled 120 mm dogbone and inward symmetric holes.",
        ),
    )
    geometric_conflicts: tuple[BriefFinding, ...] = ()
    brief = normalize_project_brief(_draft(height), examiner_findings=geometric_conflicts)
    PREDESIGN.mkdir(parents=True, exist_ok=True)
    (PREDESIGN / "original-brief.md").write_text(
        f"{ORIGINAL_BRIEF}\n\n{APPROVED_AMENDMENT}", encoding="utf-8"
    )
    (PREDESIGN / "normalized-brief.json").write_text(
        brief.model_dump_json(indent=2), encoding="utf-8"
    )
    write_concept_review_package(review, PREDESIGN)
    approval_file = PREDESIGN / "concept-approval.json"
    existing_approval = (
        ConceptApproval.model_validate_json(approval_file.read_text(encoding="utf-8"))
        if approval_file.exists()
        else None
    )
    if existing_approval is None or not existing_approval.approved:
        write_approval_request(
            project_id="retro-pad",
            normalized_brief_file=PREDESIGN / "normalized-brief.json",
            concept_review_file=PREDESIGN / "concept-review.json",
            output_file=approval_file,
        )
    summary = {
        "schema": "pcbsmith-predesign-run-v1",
        "project_id": "retro-pad",
        "brief_outcome": brief.outcome,
        "concept_outcome": review.outcome,
        "routing_authorized": False,
        "next_gate": "user review and explicit concept/mechanical decision",
    }
    (PREDESIGN / "predesign-summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
