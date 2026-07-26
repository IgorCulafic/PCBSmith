"""Generate AeroSense-2F visual and manufacturer-neutral release evidence."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from pcbsmith.kicad.model_preflight import (
    ModelRegistryEntry,
    ModelRequirement,
    preflight_board_models,
)
from pcbsmith.manufacturing_ir import (
    CurrentPathCoverage,
    CurrentPathCoverageStatus,
    CurrentPathElementKind,
    CurrentPathRecord,
    FabricationElectricalProfile,
    Ipc2152Context,
    StackupLayer,
    StackupLayerKind,
)
from pcbsmith.manufacturing_release import (
    INTERACTIVE_HTML_BOM_PINNED_VERSION,
    InteractiveBomProfile,
    assemble_neutral_manufacturing_package,
    evaluate_baseline_dfm_dft,
    export_kicad_neutral_sources,
    extract_saved_board_manufacturing_identities,
    generate_interactive_html_bom,
    inspect_version_pinned_tool,
)
from pcbsmith.review.visual_package import (
    DetailRegion,
    ReviewFeatures,
    generate_visual_review_package,
    rasterize_svg_with_resvg,
)

ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "outputs" / "aerosense-2f-r001"
DESIGN = PROJECT / "design"
BOARD = DESIGN / "aerosense-2f-r001.kicad_pcb"
PLACEMENT_BOARD = DESIGN / "aerosense-2f-r001-placement.kicad_pcb"
KICAD_CLI = Path("C:/Program Files/KiCad/10.0/bin/kicad-cli.exe")
KICAD_PYTHON = Path("C:/Program Files/KiCad/10.0/bin/python.exe")
IBOM = (
    ROOT
    / ".pcbsmith"
    / "tools"
    / "InteractiveHtmlBom-v2.11.2"
    / "InteractiveHtmlBom"
    / "generate_interactive_bom.py"
)

NET_CLASSES: dict[str, tuple[str, ...]] = {
    "power_ground": (
        "/VBUS",
        "/3V3",
        "/1V1",
        "/ADC_3V3",
        "/GND",
        "/FAN1_5V",
        "/FAN2_5V",
    ),
    "high_current": ("/VBUS", "/FAN1_5V", "/FAN2_5V", "/GND"),
    "sensitive_analog_sensor": (
        "/ADC_3V3",
        "/I2C_SDA",
        "/I2C_SCL",
        "/GND",
    ),
    "fast_bus": (
        "/USB_DP_CONN",
        "/USB_DM_CONN",
        "/USB_DP_ESD",
        "/USB_DM_ESD",
        "/USB_DP_MCU",
        "/USB_DM_MCU",
        "/QSPI_SCLK",
        "/QSPI_SD0",
        "/QSPI_SD1",
        "/QSPI_SD2",
        "/QSPI_SD3",
        "/QSPI_SS",
        "/SD_CS_MCU",
        "/SD_MOSI_MCU",
        "/SD_SCLK_MCU",
        "/SD_CS_CARD",
        "/SD_MOSI_CARD",
        "/SD_SCLK_CARD",
        "/SD_MISO",
    ),
    "matched_pair": (
        "/USB_DP_CONN",
        "/USB_DM_CONN",
        "/USB_DP_ESD",
        "/USB_DM_ESD",
        "/USB_DP_MCU",
        "/USB_DM_MCU",
    ),
}


def _replace_directory(source: Path, destination: Path) -> None:
    destination = destination.resolve()
    project_root = PROJECT.resolve()
    if project_root not in destination.parents:
        raise ValueError(f"refusing to replace directory outside project: {destination}")
    if destination.exists():
        shutil.rmtree(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))


def _model_registry(board: Path) -> tuple[ModelRegistryEntry, ...]:
    inventory = preflight_board_models(board)
    entries: dict[str, ModelRegistryEntry] = {}
    for item in inventory.models:
        if item.status != "resolved" or item.resolved_path is None:
            continue
        proxy = item.raw_path.startswith("${KIPRJMOD}/models/")
        entries[item.raw_path] = ModelRegistryEntry(
            raw_path=item.raw_path,
            local_path=item.resolved_path,
            expected_sha256=item.sha256,
            classification="proxy" if proxy else "exact_package",
            license_status=(
                "project_generated_visual_proxy"
                if proxy
                else "KiCad_official_library_local_install"
            ),
            source_url=(
                None
                if proxy
                else "https://gitlab.com/kicad/libraries/kicad-packages3D"
            ),
            redistributable=proxy,
        )
    return tuple(entries.values())


def _model_preflight(board: Path):
    requirements = (
        "J1",
        "J3",
        "J4",
        "J5",
        "DS1",
        "U1",
        "U2",
        "U3",
        "U4",
        "U5",
        "U6",
        "U7",
        "U8",
        "U9",
        "U10",
        "U11",
        "Y1",
        "Q1",
        "Q2",
        "SW1",
        "SW2",
        "SW3",
        "SW4",
        "SW5",
    )
    return preflight_board_models(
        board,
        registry=_model_registry(board),
        requirements=tuple(
            ModelRequirement(
                reference=reference,
                accepted_classifications=("exact_package", "complete_module", "proxy"),
            )
            for reference in requirements
        ),
    )


def _net_class_overlays(board: Path) -> dict[str, str]:
    overlay_root = DESIGN / "evidence" / "net-class-overlays"
    if overlay_root.exists():
        shutil.rmtree(overlay_root)
    overlay_root.mkdir(parents=True)
    outputs: dict[str, str] = {}
    filter_script = ROOT / "tools" / "filter_kicad_board_nets.py"
    for class_name, nets in NET_CLASSES.items():
        filtered = overlay_root / f"{class_name}.kicad_pcb"
        command = [
            str(KICAD_PYTHON),
            str(filter_script),
            str(board),
            str(filtered),
        ]
        for net in nets:
            command.extend(("--net", net))
        subprocess.run(command, check=True)
        svg = overlay_root / f"{class_name}.svg"
        subprocess.run(
            [
                str(KICAD_CLI),
                "pcb",
                "export",
                "svg",
                "--output",
                str(svg),
                "--layers",
                "F.Cu,B.Cu,Edge.Cuts",
                "--mode-single",
                "--page-size-mode",
                "2",
                "--exclude-drawing-sheet",
                str(filtered),
            ],
            check=True,
        )
        png = overlay_root / f"{class_name}.png"
        rasterize_svg_with_resvg(svg, png, 3840, 2743, None)
        outputs[class_name] = str(png)
    return outputs


def _review_features(*, final: bool, overlays: dict[str, str] | None = None):
    return ReviewFeatures(
        has_bottom_components=True,
        has_holes=True,
        has_zones=True,
        has_keepouts=True,
        has_cutouts=False,
        has_vias=final,
        declared_classes=tuple(NET_CLASSES) if final else (),
        class_overlays={} if overlays is None else overlays,
        detail_regions=(
            DetailRegion(
                region_id="usb-power-entry",
                bounds_mm=(0.0, 10.0, 20.0, 39.0),
                reason="USB orientation, ESD ordering, Type-C state and regulator spacing",
                side="front",
            ),
            DetailRegion(
                region_id="rp2040-core",
                bounds_mm=(17.0, 18.0, 43.0, 34.0),
                reason="RP2040, QSPI, crystal, USB and local bypass topology",
                side="front",
            ),
            DetailRegion(
                region_id="fan-ui",
                bounds_mm=(39.0, 5.0, 70.0, 48.0),
                reason="fan power, PWM, tach, fault, controls and indicator access",
                side="front",
            ),
            DetailRegion(
                region_id="sensor-sd",
                bounds_mm=(7.0, 30.0, 39.0, 50.0),
                reason="SHT45 isolation, microSD entry and card-interface protection",
                side="front",
            ),
            DetailRegion(
                region_id="back-support-test",
                bounds_mm=(4.0, 2.0, 66.0, 44.0),
                reason="back-side support placement, SWD and grouped test-pad access",
                side="back",
            ),
        ),
    )


def _generate_review(
    *,
    board: Path,
    stage: str,
    destination: Path,
    overlays: dict[str, str] | None = None,
) -> dict[str, object]:
    preflight = _model_preflight(board)
    if preflight.status != "passed":
        raise RuntimeError(f"{stage} model preflight did not pass: {preflight.findings}")
    evidence = DESIGN / "evidence"
    (evidence / f"model-preflight-{stage}.json").write_text(
        preflight.model_dump_json(indent=2, by_alias=True),
        encoding="utf-8",
    )
    with tempfile.TemporaryDirectory(prefix=f".review-{stage}-", dir=PROJECT) as temporary:
        temp_root = Path(temporary)
        manifest = generate_visual_review_package(
            board_file=board,
            output_dir=temp_root,
            stage=stage,  # type: ignore[arg-type]
            features=_review_features(final=stage == "final", overlays=overlays),
            model_preflight=preflight,
            source_revision=subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=ROOT,
                text=True,
            ).strip(),
        )
        _replace_directory(temp_root / "review", destination)
    return {
        "stage": stage,
        "package_status": manifest.package_status,
        "workflow_conformance": manifest.workflow_conformance_status,
        "artifact_count": len(manifest.artifacts),
        "model_preflight": preflight.status,
    }


def _fabrication_profile() -> FabricationElectricalProfile:
    return FabricationElectricalProfile.build(
        profile_id="aerosense-2f-neutral-enig-2layer-v1",
        minimum_trace_width_mm=0.153,
        minimum_copper_clearance_mm=0.153,
        minimum_finished_drill_mm=0.30,
        minimum_annular_ring_mm=0.15,
        minimum_mask_sliver_mm=0.10,
        mask_expansion_mm=0.05,
        paste_area_reduction_percent=0.0,
        minimum_milling_tool_diameter_mm=2.0,
        board_thickness_mm=1.6,
        base_material="FR-4",
        material_tg_c=135.0,
        surface_finish="ENIG",
        insulation_basis="5 V SELV functional insulation; IPC-2221B context retained",
        stackup=(
            StackupLayer(
                layer_id="F.Silkscreen",
                sequence=0,
                kind=StackupLayerKind.SILKSCREEN,
                material="white epoxy ink",
                thickness_um=10.0,
            ),
            StackupLayer(
                layer_id="F.Mask",
                sequence=1,
                kind=StackupLayerKind.SOLDER_MASK,
                material="green LPI",
                thickness_um=20.0,
            ),
            StackupLayer(
                layer_id="F.Cu",
                sequence=2,
                kind=StackupLayerKind.COPPER,
                material="electrodeposited copper",
                thickness_um=35.0,
                copper_weight_oz=1.0,
            ),
            StackupLayer(
                layer_id="FR4.Core",
                sequence=3,
                kind=StackupLayerKind.DIELECTRIC,
                material="FR-4 core",
                thickness_um=1470.0,
                dielectric_constant=4.2,
                loss_tangent=0.02,
            ),
            StackupLayer(
                layer_id="B.Cu",
                sequence=4,
                kind=StackupLayerKind.COPPER,
                material="electrodeposited copper",
                thickness_um=35.0,
                copper_weight_oz=1.0,
            ),
            StackupLayer(
                layer_id="B.Mask",
                sequence=5,
                kind=StackupLayerKind.SOLDER_MASK,
                material="green LPI",
                thickness_um=20.0,
            ),
            StackupLayer(
                layer_id="B.Silkscreen",
                sequence=6,
                kind=StackupLayerKind.SILKSCREEN,
                material="white epoxy ink",
                thickness_um=10.0,
            ),
        ),
        impedance_requirements=(),
        ipc2152_context=Ipc2152Context(
            authority_id="aerosense-2f-ipc2152-context-v1",
            ambient_c=40.0,
            allowed_temperature_rise_c=20.0,
            copper_environment="external",
            current_waveform="mixed",
            duty_cycle=1.0,
            altitude_m=1000.0,
            enclosure_context="prototype enclosure and airflow not yet correlated",
            limitations=(
                "No IPC-2152 correlated coupon or thermal measurement is retained.",
                "Fan startup and stall current require bench correlation.",
            ),
        ),
    )


def _unverified_current_path(
    *,
    path_id: str,
    nets: tuple[str, ...],
    board_sha256: str,
    profile: FabricationElectricalProfile,
    parallel_sharing_applicable: bool,
) -> CurrentPathRecord:
    coverages: list[CurrentPathCoverage] = []
    for kind in CurrentPathElementKind:
        not_applicable = (
            kind is CurrentPathElementKind.ZONE_OR_PLANE
            or (
                kind is CurrentPathElementKind.PARALLEL_SHARING
                and not parallel_sharing_applicable
            )
        )
        coverages.append(
            CurrentPathCoverage(
                kind=kind,
                status=(
                    CurrentPathCoverageStatus.NOT_APPLICABLE
                    if not_applicable
                    else CurrentPathCoverageStatus.UNVERIFIED
                ),
                rationale=(
                    "No zone/plane is used as the series current carrier."
                    if kind is CurrentPathElementKind.ZONE_OR_PLANE
                    else (
                        "No parallel current-sharing element is declared."
                        if not_applicable
                        else "Saved copper exists, but IPC-2152/thermal and "
                        "bench-correlated element authority is not yet retained."
                    )
                ),
            )
        )
    return CurrentPathRecord.build(
        path_id=path_id,
        net_ids=nets,
        board_sha256=board_sha256,
        profile_fingerprint=profile.profile_fingerprint,
        coverages=tuple(coverages),
        elements=(),
    )


def _manufacturing_package() -> dict[str, object]:
    manufacturing = PROJECT / "manufacturing"
    manufacturing.mkdir(parents=True, exist_ok=True)
    raw = manufacturing / "neutral-source"
    package = manufacturing / "release-package"
    for target in (raw, package):
        if target.exists():
            shutil.rmtree(target)
    archive = package.with_suffix(".zip")
    archive.unlink(missing_ok=True)

    ibom_evidence = inspect_version_pinned_tool(
        tool_id="interactive-html-bom",
        command=(str(KICAD_PYTHON), str(IBOM), "--version"),
        pinned_version=INTERACTIVE_HTML_BOM_PINNED_VERSION,
    )
    ibom = generate_interactive_html_bom(
        board_file=BOARD,
        output_directory=manufacturing / "interactive-bom",
        profile=InteractiveBomProfile(
            include_front=True,
            include_back=True,
            include_tracks_and_zones=True,
            back_rotation_offset_degrees=0,
        ),
        tool_evidence=ibom_evidence,
        command_prefix=(str(KICAD_PYTHON), str(IBOM)),
    )
    identities = extract_saved_board_manufacturing_identities(BOARD)
    profile = _fabrication_profile()
    sources, kicad_evidence = export_kicad_neutral_sources(
        board_file=BOARD,
        output_directory=raw,
        profile=profile,
        identities=identities,
        interactive_bom_file=ibom,
        kicad_cli=KICAD_CLI,
        kicad_version="10.0.3",
    )
    _enrich_manufacturer_bom(raw / "bom.csv")
    drc_report = DESIGN / ".pcbsmith" / "kicad" / "drc.json"
    dfm_dft = evaluate_baseline_dfm_dft(
        board_file=BOARD,
        drc_report_file=drc_report,
    )
    current_paths = (
        _unverified_current_path(
            path_id="usb-vbus-to-protected-fan-inputs",
            nets=("/VBUS",),
            board_sha256=identities.board_sha256,
            profile=profile,
            parallel_sharing_applicable=True,
        ),
        _unverified_current_path(
            path_id="fan1-protected-output",
            nets=("/FAN1_5V",),
            board_sha256=identities.board_sha256,
            profile=profile,
            parallel_sharing_applicable=False,
        ),
        _unverified_current_path(
            path_id="fan2-protected-output",
            nets=("/FAN2_5V",),
            board_sha256=identities.board_sha256,
            profile=profile,
            parallel_sharing_applicable=False,
        ),
    )
    manifest, archive = assemble_neutral_manufacturing_package(
        output_directory=package,
        project_id="aerosense-2f-r001",
        board_file=BOARD,
        profile=profile,
        identities=identities,
        current_paths=current_paths,
        dfm_dft=dfm_dft,
        source_artifacts=sources,
        tool_evidence=(kicad_evidence, ibom_evidence),
    )
    (manufacturing / "panelization-not-applicable.json").write_text(
        json.dumps(
            {
                "schema": "pcbsmith-not-applicable-v1",
                "scope": "panelization",
                "status": "not_applicable",
                "reason": "The approved authority requests five loose prototypes and "
                "explicitly does not request panelization.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "release_status": manifest.release_status.value,
        "blockers": list(manifest.blockers),
        "artifact_count": len(manifest.artifacts),
        "archive": str(archive),
        "package_fingerprint": manifest.package_fingerprint,
        "dfm_dft_ready": dfm_dft.ready,
    }


def _enrich_manufacturer_bom(bom_file: Path) -> None:
    selection = json.loads(
        (PROJECT / "intake" / "exact-part-selection.json").read_text(encoding="utf-8")
    )
    selected: dict[str, dict[str, object]] = {}
    for part in selection["parts"]:
        for reference in part["references"]:
            selected[reference] = part
    with bom_file.open("r", encoding="utf-8", newline="") as handle:
        rows = tuple(csv.DictReader(handle))
    with bom_file.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = (
            "Ref",
            "Value",
            "Footprint",
            "Manufacturer",
            "MPN",
            "Lifecycle",
            "SelectionStatus",
            "Authority",
            "StableId",
        )
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            reference = row["Ref"]
            part = selected.get(reference)
            non_assembled = reference.startswith(("H", "TP"))
            writer.writerow(
                {
                    **row,
                    "Manufacturer": "" if part is None else part["manufacturer"],
                    "MPN": "" if part is None else part["mpn"],
                    "Lifecycle": "" if part is None else part["lifecycle"],
                    "SelectionStatus": (
                        "not_assembled_pcb_feature"
                        if non_assembled
                        else ("exact_selected" if part is not None else "specification_only")
                    ),
                    "Authority": "" if part is None else part["authority"],
                }
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--skip-placement-review",
        action="store_true",
        help="Reuse an already generated placement package.",
    )
    args = parser.parse_args()
    for required in (BOARD, PLACEMENT_BOARD, KICAD_CLI, KICAD_PYTHON, IBOM):
        if not required.is_file():
            raise FileNotFoundError(required)

    review_root = PROJECT / "review"
    review_root.mkdir(parents=True, exist_ok=True)
    results: dict[str, object] = {}
    if not args.skip_placement_review:
        results["placement_review"] = _generate_review(
            board=PLACEMENT_BOARD,
            stage="placement",
            destination=review_root / "placement",
        )
    overlays = _net_class_overlays(BOARD)
    results["final_review"] = _generate_review(
        board=BOARD,
        stage="final",
        destination=review_root / "final",
        overlays=overlays,
    )
    schematic = DESIGN / "review" / "schematic" / "schematic.png"
    if schematic.is_file():
        schematic_destination = review_root / "schematic"
        schematic_destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(schematic, schematic_destination / schematic.name)
    results["manufacturing"] = _manufacturing_package()
    (PROJECT / "finalization-summary.json").write_text(
        json.dumps(results, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(results, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
