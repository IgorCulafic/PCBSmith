"""Generate the evidence-bound proof for newly exposed design-readiness gaps."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pcbsmith.design_readiness import (
    AutomaticGateState,
    ComponentCandidate,
    ComponentUseIntent,
    DesignChangeKind,
    DesignReadinessStage,
    PowerConversionContract,
    PowerPathReview,
    PowerRailLoad,
    PowerSourceContract,
    ReleaseGateSnapshot,
    ScopedDesignChange,
    SourceCurrentAuthority,
    SupportCircuitReview,
    SupportObservation,
    SupportRequirement,
    SupportRequirementKind,
    VisualSubjectRequirement,
    VisualSubjectReview,
    derive_design_release,
    evaluate_design_readiness,
    plan_dependency_scoped_invalidation,
    review_component_alternatives,
    review_power_path,
    review_support_circuits,
    review_visual_subjects,
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_OUTPUT = ROOT / "outputs" / "montenegro-env-display-r001"
OUTPUT = ROOT / "experiments" / "design-readiness-hardening-2026-08-21"


def _component_reviews() -> tuple[Any, Any]:
    intent = ComponentUseIntent(
        intent_id="montenegro-border-lighting",
        role_id="presentation_border",
        required_capabilities=("emits_light", "single_color"),
        forbidden_capabilities=("individually_addressable", "rgb"),
        preferred_mounting="smd",
        hand_assembly_required=True,
        maximum_body_width_mm=3.5,
        maximum_body_height_mm=3.5,
        maximum_pin_count=2,
        maximum_unit_current_a=0.025,
        evidence_ids=("user-review:2026-08-20:two-pin-led",),
    )
    candidates = (
        ComponentCandidate(
            candidate_id="kingbright-apt1608sgc",
            manufacturer_part_number="APT1608SGC",
            capabilities=("emits_light", "single_color"),
            behavioral_capabilities=("emits_light",),
            mounting="smd",
            body_width_mm=1.6,
            body_height_mm=0.8,
            pin_count=2,
            maximum_unit_current_a=0.02,
            hand_assembly_suitable=True,
            model_classification="exact_package",
            support_requirement_ids=("border-led-current-limiting",),
            evidence_ids=("ai_assets/datasheets/apt1608sgc.pdf:p1-2",),
        ),
        ComponentCandidate(
            candidate_id="generic-3528-two-pin",
            manufacturer_part_number="TBD-3528-2PIN",
            capabilities=("emits_light", "single_color"),
            behavioral_capabilities=("emits_light",),
            mounting="smd",
            body_width_mm=3.5,
            body_height_mm=2.8,
            pin_count=2,
            maximum_unit_current_a=0.02,
            hand_assembly_suitable=True,
            model_classification="proxy",
            support_requirement_ids=("border-led-current-limiting",),
            evidence_ids=("user-review:2026-08-20:3528-or-smaller",),
        ),
        ComponentCandidate(
            candidate_id="ws2812b-5050",
            manufacturer_part_number="WS2812B",
            capabilities=("emits_light", "individually_addressable", "rgb"),
            behavioral_capabilities=("emits_light", "individually_addressable", "rgb"),
            mounting="smd",
            body_width_mm=5.0,
            body_height_mm=5.0,
            pin_count=4,
            maximum_unit_current_a=0.06,
            hand_assembly_suitable=True,
            model_classification="exact_package",
            support_requirement_ids=("addressable-led-local-decoupling",),
            evidence_ids=("legacy-board:WS2812B",),
        ),
    )
    return (
        review_component_alternatives(
            intent=intent,
            candidates=candidates,
            selected_candidate_id="ws2812b-5050",
        ),
        review_component_alternatives(
            intent=intent,
            candidates=candidates,
            selected_candidate_id="kingbright-apt1608sgc",
        ),
    )


def _support_review() -> SupportCircuitReview:
    requirements = (
        SupportRequirement(
            requirement_id="border-led-current-limiting",
            subject_reference="D1-D35",
            kind=SupportRequirementKind.CURRENT_LIMITING,
            minimum_value=1.0,
            units="ohm",
            source_ids=("ai_assets/datasheets/apt1608sgc.pdf:p2",),
            rationale="Every two-pin LED branch needs calculated current limiting.",
        ),
        SupportRequirement(
            requirement_id="sht45-local-decoupling",
            subject_reference="U4",
            kind=SupportRequirementKind.LOCAL_DECOUPLING,
            maximum_distance_mm=3.0,
            minimum_value=0.1,
            units="uF",
            source_ids=("sensirion:SHT4x-datasheet",),
            rationale="The sensor supply needs local decoupling.",
        ),
        SupportRequirement(
            requirement_id="sht45-thermal-isolation",
            subject_reference="U4",
            kind=SupportRequirementKind.THERMAL_ISOLATION,
            source_ids=("sensirion:design-guide:p8-10",),
            rationale="Internal board heating biases temperature and relative humidity.",
        ),
        SupportRequirement(
            requirement_id="sht45-air-exposure",
            subject_reference="U4",
            kind=SupportRequirementKind.AIR_EXPOSURE,
            source_ids=("sensirion:design-guide:p17-18",),
            rationale="A small dead volume and environmental opening are required.",
        ),
    )
    observations = (
        SupportObservation(
            requirement_id="sht45-local-decoupling",
            disposition="verified",
            supporting_references=("C5",),
            measured_distance_mm=2.0,
            observed_value=0.1,
            evidence_ids=("legacy-schematic:C5-U4",),
            rationale="The saved design declares a 100 nF sensor capacitor.",
        ),
        SupportObservation(
            requirement_id="sht45-thermal-isolation",
            disposition="unverified",
            rationale="No quantitative copper/heat-source isolation proof is recorded.",
        ),
        SupportObservation(
            requirement_id="sht45-air-exposure",
            disposition="unverified",
            rationale="No enclosure aperture or airflow evidence is recorded.",
        ),
    )
    return review_support_circuits(requirements=requirements, observations=observations)


def _power_review() -> PowerPathReview:
    return review_power_path(
        source=PowerSourceContract(
            source_id="usb-c-vbus",
            rail_id="+5V",
            voltage_v=5.0,
            available_continuous_current_a=3.0,
            available_peak_current_a=3.0,
            current_authority=SourceCurrentAuthority.UNRESOLVED,
            current_detection_verified=False,
            direct_input_capacitance_uf=110.0,
            direct_input_capacitance_limit_uf=10.0,
            inrush_limiting_verified=False,
            evidence_ids=("usb2-spec:p205", "usb-type-c-r2.5:p201",),
        ),
        loads=(
            PowerRailLoad(
                load_id="legacy-ws2812-full-white",
                rail_id="+5V",
                continuous_current_a=2.10,
                peak_current_a=2.10,
                evidence_ids=("legacy-generation-summary:led-budget",),
            ),
            PowerRailLoad(
                load_id="legacy-logic-display",
                rail_id="+3V3",
                continuous_current_a=0.56,
                peak_current_a=0.56,
                evidence_ids=("legacy-generation-summary:logic-budget",),
            ),
        ),
        conversions=(
            PowerConversionContract(
                conversion_id="ncp1117-3v3",
                input_rail_id="+5V",
                output_rail_id="+3V3",
                input_voltage_v=5.0,
                output_voltage_v=3.3,
                kind="linear",
                efficiency=0.66,
                maximum_output_current_a=1.0,
                verified_dissipation_limit_w=None,
                evidence_ids=("onsemi:ncp1117:p9",),
            ),
        ),
    )


def _visual_review() -> VisualSubjectReview:
    requirements = (
        VisualSubjectRequirement(
            subject_id="sht45-3d",
            component_reference="U4",
            artifact_id="3d:populated:sensor-detail",
            minimum_crop_width_px=160,
            minimum_crop_height_px=160,
            minimum_occupancy_fraction=0.04,
            model_required=True,
            aligned_model_required=True,
        ),
        VisualSubjectRequirement(
            subject_id="oled-3d",
            component_reference="MECH1",
            artifact_id="3d:populated:oled-detail",
            minimum_crop_width_px=320,
            minimum_crop_height_px=240,
            minimum_occupancy_fraction=0.10,
            model_required=True,
            aligned_model_required=True,
        ),
    )
    # The old package has full-board 3D renders and 2D detail crops, but no
    # component-specific 3D observations.  Absence is evidence, not a pass.
    return review_visual_subjects(requirements=requirements, observations=())


def _write_markdown(payload: dict[str, Any]) -> str:
    legacy = payload["component_alternatives"]["legacy_selection"]
    revised = payload["component_alternatives"]["revised_selection"]
    lines = [
        "# Design-readiness hardening proof",
        "",
        "## Outcome",
        "",
        "The prior Montenegro candidate remains on **engineering hold**. The proof does not "
        "modify or regenerate that board; it replays its declared electrical assumptions and "
        "evidence through the new fail-closed contracts.",
        "",
        f"- Legacy WS2812B selection: `{legacy['disposition']}`.",
        f"- Two-pin APT1608 alternative: `{revised['disposition']}` at the component gate, "
        "but implementation remains blocked until current-limiting branches are designed.",
        f"- Support-circuit review: `{payload['support_circuits']['disposition']}`.",
        f"- System power-path review: `{payload['power_path']['disposition']}`.",
        f"- Quantitative required-subject review: `{payload['visual_subjects']['disposition']}`.",
        f"- Derived release state: `{payload['release']['state']}`.",
        "",
        "## Newly enforced findings",
        "",
    ]
    for group in ("component_alternatives", "support_circuits", "power_path", "visual_subjects"):
        if group == "component_alternatives":
            findings = legacy["blockers"]
        else:
            findings = payload[group]["blockers"]
        lines.append(f"### {group.replace('_', ' ').title()}")
        lines.append("")
        lines.extend(f"- `{item}`" for item in findings)
        lines.append("")
    lines.extend(
        (
            "## Incremental-change consequence",
            "",
            "The selected fixes do not automatically authorize a whole-board restart. The "
            "machine-readable invalidation plans list affected artifacts and preserve unrelated "
            "ones. Only a declared architecture change sets `whole_board_restart_required=true`.",
            "",
            "## Evidence basis",
            "",
            "- Kingbright APT1608SGC datasheet, pages 1-2: 1.6 x 0.8 mm two-pin LED and "
            "forward-voltage/current evidence.",
            "- Sensirion humidity/temperature design guide, pages 8-10 and 17-18: thermal "
            "isolation, environmental exposure, and response-time obligations.",
            "- USB 2.0 specification, page 205 (section 7.2.4.1): 10 uF / 44 ohm direct-load "
            "inrush model.",
            "- USB Type-C Release 2.5, page 201: sink current states and the requirement to "
            "remain within default current unless higher current is detected/contracted.",
            "- onsemi NCP1117 datasheet, page 9: mandatory output capacitance, input bypass, "
            "and regulator application constraints.",
            "- Existing candidate evidence: generation-summary DRC failure, pending visual "
            "inspection, and passed model-path preflight.",
            "",
            "## Important limitation",
            "",
            "Pixel occupancy proves that a declared crop is not blank; it does not identify a "
            "part or prove assembly correctness by itself. Component identity remains bound to "
            "the crop declaration and 3D-model preflight, and final acceptance remains a "
            "separate gate.",
            "",
        )
    )
    return "\n".join(lines)


def main() -> int:
    summary = json.loads((SOURCE_OUTPUT / "generation-summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((SOURCE_OUTPUT / "review" / "manifest.json").read_text(encoding="utf-8"))
    legacy_selection, revised_selection = _component_reviews()
    support = _support_review()
    power = _power_review()
    visual = _visual_review()
    readiness = evaluate_design_readiness(
        stage=DesignReadinessStage.SAVED_CANDIDATE,
        component_reviews=(legacy_selection,),
        support_review=support,
        power_review=power,
        visual_review=visual,
    )
    release = derive_design_release(
        ReleaseGateSnapshot(
            candidate_generated=True,
            review_package_generated=True,
            visual_inspection=AutomaticGateState.PENDING,
            routing=AutomaticGateState.PASSED,
            drc=AutomaticGateState.FAILED,
            design_readiness=AutomaticGateState.FAILED,
            model_preflight=AutomaticGateState.PASSED,
        )
    )
    changes = {
        "led_selection": plan_dependency_scoped_invalidation(
            (
                ScopedDesignChange(
                    change_id="replace-border-led-family",
                    kind=DesignChangeKind.COMPONENT_SELECTION,
                    component_references=tuple(f"D{index}" for index in range(1, 36)),
                    net_names=("+5V", "GND", "LED_DATA_5V"),
                    rationale="Replace unrequested addressable RGB packages with two-pin LEDs.",
                ),
            )
        ),
        "sensor_environment": plan_dependency_scoped_invalidation(
            (
                ScopedDesignChange(
                    change_id="isolate-sensor-environment",
                    kind=DesignChangeKind.PLACEMENT,
                    component_references=("U4", "C5"),
                    net_names=("+3V3", "GND", "I2C_SDA", "I2C_SCL"),
                    rationale="Create an edge/air/thermal-isolation implementation for U4.",
                ),
            )
        ),
        "model_alignment": plan_dependency_scoped_invalidation(
            (
                ScopedDesignChange(
                    change_id="verify-oled-sensor-models",
                    kind=DesignChangeKind.MODEL,
                    component_references=("MECH1", "U4"),
                    rationale="Bind exact transforms and generate quantitative 3D detail crops.",
                ),
            )
        ),
    }
    payload = {
        "schema": "pcbsmith-design-readiness-hardening-proof-v1",
        "source_candidate": {
            "path": str(SOURCE_OUTPUT.relative_to(ROOT)).replace("\\", "/"),
            "board_sha256": summary["board_sha256"],
            "drc_status": summary["drc"]["status"],
            "drc_findings": summary["drc"]["findings"],
            "model_preflight_status": summary["model_preflight"]["status"],
            "visual_package_status": manifest["package_status"],
        },
        "component_alternatives": {
            "legacy_selection": legacy_selection.model_dump(mode="json"),
            "revised_selection": revised_selection.model_dump(mode="json"),
        },
        "support_circuits": support.model_dump(mode="json"),
        "power_path": power.model_dump(mode="json"),
        "visual_subjects": visual.model_dump(mode="json"),
        "design_readiness": readiness.model_dump(mode="json"),
        "release": release.model_dump(mode="json"),
        "invalidation_plans": {
            name: plan.model_dump(mode="json") for name, plan in sorted(changes.items())
        },
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "proof.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (OUTPUT / "REPORT.md").write_text(_write_markdown(payload), encoding="utf-8")
    print(OUTPUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
