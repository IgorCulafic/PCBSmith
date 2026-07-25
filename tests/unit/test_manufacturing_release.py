from __future__ import annotations

import hashlib
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from pcbsmith.manufacturing_ir import (
    CurrentPathCoverage,
    CurrentPathCoverageStatus,
    CurrentPathElement,
    CurrentPathElementKind,
    CurrentPathRecord,
    DfmDftCategory,
    DfmDftDisposition,
    DfmDftEvidence,
    DfmDftReport,
    FabricationElectricalProfile,
    Ipc2152Context,
    ManufacturingApproval,
    ManufacturingApprovalRole,
    ManufacturingReleaseStatus,
    StackupLayer,
    StackupLayerKind,
)
from pcbsmith.manufacturing_release import (
    INTERACTIVE_HTML_BOM_PINNED_VERSION,
    MANDATORY_NEUTRAL_ROLES,
    BoardOutlineClass,
    InteractiveBomProfile,
    ManufacturingArtifactRole,
    ManufacturingToolStatus,
    NeutralManufacturingPackage,
    PanelCutMethod,
    PanelFrameKind,
    PanelizationProfile,
    assemble_neutral_manufacturing_package,
    evaluate_baseline_dfm_dft,
    extract_saved_board_manufacturing_identities,
    generate_interactive_html_bom,
    inspect_version_pinned_tool,
)


def _sha(value: str | bytes) -> str:
    payload = value if isinstance(value, bytes) else value.encode()
    return hashlib.sha256(payload).hexdigest()


def _profile() -> FabricationElectricalProfile:
    return FabricationElectricalProfile.build(
        profile_id="prototype-2layer",
        minimum_trace_width_mm=0.15,
        minimum_copper_clearance_mm=0.15,
        minimum_finished_drill_mm=0.3,
        minimum_annular_ring_mm=0.13,
        minimum_mask_sliver_mm=0.1,
        mask_expansion_mm=0.05,
        paste_area_reduction_percent=5,
        minimum_milling_tool_diameter_mm=1.0,
        board_thickness_mm=1.6,
        base_material="FR-4",
        material_tg_c=150,
        surface_finish="lead-free HASL",
        insulation_basis="functional insulation only; no safety rating",
        stackup=(
            StackupLayer(
                layer_id="F.Mask",
                sequence=0,
                kind=StackupLayerKind.SOLDER_MASK,
                material="epoxy mask",
                thickness_um=20,
            ),
            StackupLayer(
                layer_id="F.Cu",
                sequence=1,
                kind=StackupLayerKind.COPPER,
                material="copper",
                thickness_um=35,
                copper_weight_oz=1,
            ),
            StackupLayer(
                layer_id="dielectric",
                sequence=2,
                kind=StackupLayerKind.DIELECTRIC,
                material="FR-4",
                thickness_um=1490,
                dielectric_constant=4.2,
                loss_tangent=0.02,
            ),
            StackupLayer(
                layer_id="B.Cu",
                sequence=3,
                kind=StackupLayerKind.COPPER,
                material="copper",
                thickness_um=35,
                copper_weight_oz=1,
            ),
            StackupLayer(
                layer_id="B.Mask",
                sequence=4,
                kind=StackupLayerKind.SOLDER_MASK,
                material="epoxy mask",
                thickness_um=20,
            ),
        ),
        impedance_requirements=(),
        ipc2152_context=Ipc2152Context(
            authority_id="ipc2152.prototype-context",
            ambient_c=25,
            allowed_temperature_rise_c=20,
            copper_environment="external",
            current_waveform="dc",
            duty_cycle=1,
            altitude_m=0,
            enclosure_context="open bench prototype",
            limitations=("requires correlation before current-rating claim",),
        ),
    )


def _board(path: Path) -> Path:
    path.write_text(
        """(kicad_pcb
  (version 20250101)
  (footprint "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
    (layer "F.Cu")
    (uuid "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    (at 10 20 90)
    (property "Reference" "U1")
    (property "Value" "TEST")
    (pad "1" smd rect
      (at -1 0)
      (size 1 2)
      (layers "F.Cu" "F.Paste" "F.Mask")
      (uuid "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"))
    (pad "2" thru_hole circle
      (at 1 0)
      (size 2 2)
      (drill 1)
      (layers "*.Cu" "*.Mask")
      (uuid "cccccccc-cccc-cccc-cccc-cccccccccccc"))
  )
)""",
        encoding="utf-8",
    )
    return path


def _current_path(board_sha256: str, profile: FabricationElectricalProfile) -> CurrentPathRecord:
    elements = tuple(
        CurrentPathElement(
            element_id=f"element.{kind.value}",
            kind=kind,
            source_identity_id=f"source.{kind.value}",
            current_a_rms=0.5,
            current_a_peak=0.5,
            duty_cycle=1,
            waveform="dc",
            resistance_ohm=0.01,
            voltage_drop_v=0.005,
            power_loss_w=0.0025,
            geometry_fingerprint=_sha(f"geometry.{kind.value}"),
            thermal_context_id=profile.ipc2152_context.authority_id,
        )
        for kind in CurrentPathElementKind
    )
    coverages = tuple(
        CurrentPathCoverage(
            kind=kind,
            status=CurrentPathCoverageStatus.VERIFIED,
            rationale="Exact saved geometry and selected process are available.",
        )
        for kind in CurrentPathElementKind
    )
    return CurrentPathRecord.build(
        path_id="path.5v",
        net_ids=("5V", "GND"),
        board_sha256=board_sha256,
        profile_fingerprint=profile.profile_fingerprint,
        coverages=coverages,
        elements=elements,
    )


def _dfm(board_sha256: str) -> DfmDftReport:
    return DfmDftReport.build(
        board_sha256=board_sha256,
        evidence=tuple(
            DfmDftEvidence(
                category=category,
                disposition=DfmDftDisposition.PASS,
                producer_id=f"test.{category.value}",
                tool_version="1.0",
                exact_input_sha256s=(board_sha256,),
                evaluated_object_count=1,
                evidence_sha256=_sha(f"evidence.{category.value}"),
            )
            for category in DfmDftCategory
        ),
    )


def _tool():
    return inspect_version_pinned_tool(
        tool_id="fixture-exporter",
        command=(sys.executable, "-c", "print('1.2.3')"),
        pinned_version="1.2.3",
    )


def _artifact_payload(role: ManufacturingArtifactRole) -> bytes:
    if role in {
        ManufacturingArtifactRole.GERBER,
        ManufacturingArtifactRole.DRILL_MAP,
        ManufacturingArtifactRole.PASTE,
    }:
        return b"G04 generated fixture*\n%FSLAX46Y46*%\nM02*\n"
    if role is ManufacturingArtifactRole.DRILL:
        return b"M48\nMETRIC\n%\nM30\n"
    if role is ManufacturingArtifactRole.NETLIST:
        return b"C  IPC-D-356 fixture\nP  JOB fixture\n"
    if role in {
        ManufacturingArtifactRole.FABRICATION_DRAWING,
        ManufacturingArtifactRole.ASSEMBLY_DRAWING_FRONT,
        ManufacturingArtifactRole.ASSEMBLY_DRAWING_BACK,
    }:
        return b"%PDF-1.4\n% fixture\n"
    if role in {
        ManufacturingArtifactRole.BOM,
        ManufacturingArtifactRole.PLACEMENT,
    }:
        return b"Ref,Value,Footprint\nU1,TEST,SOIC-8\n"
    if role is ManufacturingArtifactRole.INTERACTIVE_BOM:
        return b"<!doctype html><html><body>fixture</body></html>\n"
    return f"# {role.value}\n".encode()


def test_saved_board_identities_cover_manufacturing_rows_and_apertures(
    tmp_path: Path,
) -> None:
    registry = extract_saved_board_manufacturing_identities(_board(tmp_path / "board.kicad_pcb"))
    kinds = {item.kind.value for item in registry.identities}

    assert {
        "footprint",
        "component",
        "pad",
        "hole",
        "aperture",
        "bom_row",
        "placement_row",
    }.issubset(kinds)
    assert (
        extract_saved_board_manufacturing_identities(
            tmp_path / "board.kicad_pcb"
        ).registry_fingerprint
        == registry.registry_fingerprint
    )


def test_current_path_unknown_geometry_remains_unverified() -> None:
    profile = _profile()
    board_sha256 = _sha("board")
    path = CurrentPathRecord.build(
        path_id="path.power",
        net_ids=("VBUS",),
        board_sha256=board_sha256,
        profile_fingerprint=profile.profile_fingerprint,
        coverages=tuple(
            CurrentPathCoverage(
                kind=kind,
                status=(
                    CurrentPathCoverageStatus.UNVERIFIED
                    if kind is CurrentPathElementKind.NECK_DOWN
                    else CurrentPathCoverageStatus.NOT_APPLICABLE
                ),
                rationale="Geometry is unknown."
                if kind is CurrentPathElementKind.NECK_DOWN
                else "Not used by this fixture.",
            )
            for kind in CurrentPathElementKind
        ),
        elements=(),
    )

    assert path.authority.value == "unverified"
    assert "neck_down: conductor geometry is unverified" in path.blockers


def test_panelization_rejects_vcuts_for_irregular_or_cutout_boards() -> None:
    with pytest.raises(ValidationError, match="require routed tabs"):
        PanelizationProfile(
            outline_class=BoardOutlineClass.IRREGULAR,
            rows=2,
            columns=2,
            horizontal_spacing_mm=2,
            vertical_spacing_mm=2,
            tabs_width_mm=3,
            cut_method=PanelCutMethod.V_CUTS,
            frame_kind=PanelFrameKind.FULL_FRAME,
            rail_width_mm=5,
            fiducial_count=3,
            tooling_hole_count=3,
        )


def test_version_pin_is_machine_checked() -> None:
    available = _tool()
    mismatch = inspect_version_pinned_tool(
        tool_id="fixture-exporter",
        command=(sys.executable, "-c", "print('1.2.4')"),
        pinned_version="1.2.3",
    )

    assert available.status is ManufacturingToolStatus.AVAILABLE
    assert mismatch.status is ManufacturingToolStatus.VERSION_MISMATCH


def test_interactive_bom_launcher_forces_cli_mode_without_plugin_registration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    board = _board(tmp_path / "board.kicad_pcb")
    output = tmp_path / "ibom"
    evidence = inspect_version_pinned_tool(
        tool_id="interactive-html-bom",
        command=(
            sys.executable,
            "-c",
            f"print('{INTERACTIVE_HTML_BOM_PINNED_VERSION}')",
        ),
        pinned_version=INTERACTIVE_HTML_BOM_PINNED_VERSION,
    )
    retained_environment: dict[str, str] = {}

    def fake_run(*args, **kwargs):
        retained_environment.update(kwargs["env"])
        output.mkdir(parents=True, exist_ok=True)
        (output / "interactive.html").write_text(
            "<html><body>fixture</body></html>",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args[0], 0, "", "")

    monkeypatch.setattr(subprocess, "run", fake_run)
    generated = generate_interactive_html_bom(
        board_file=board,
        output_directory=output,
        profile=InteractiveBomProfile(),
        tool_evidence=evidence,
        command_prefix=("fixture-python", "fixture-launcher"),
    )

    assert generated.name == "interactive.html"
    assert retained_environment["INTERACTIVE_HTML_BOM_NO_DISPLAY"] == "1"
    assert retained_environment["INTERACTIVE_HTML_BOM_CLI_MODE"] == "1"


def test_baseline_dfm_dft_runs_supported_checks_and_exposes_missing_authority(
    tmp_path: Path,
) -> None:
    board = _board(tmp_path / "board.kicad_pcb")
    drc = tmp_path / "drc.json"
    drc.write_text(
        '{"violations": [], "unconnected_items": [], "schematic_parity": []}',
        encoding="utf-8",
    )

    report = evaluate_baseline_dfm_dft(
        board_file=board,
        drc_report_file=drc,
    )
    by_category = {item.category: item for item in report.evidence}

    assert (
        by_category[DfmDftCategory.COURTYARD_PROCESS_CLEARANCE].disposition
        is DfmDftDisposition.PASS
    )
    assert by_category[DfmDftCategory.PASTE_STRATEGY].disposition is DfmDftDisposition.PASS
    assert by_category[DfmDftCategory.REWORK_ACCESS].disposition is DfmDftDisposition.UNVERIFIED
    assert not report.ready


def test_neutral_package_is_atomic_hashed_and_not_release_approved(
    tmp_path: Path,
) -> None:
    board = _board(tmp_path / "board.kicad_pcb")
    board_sha256 = _sha(board.read_bytes())
    profile = _profile()
    identities = extract_saved_board_manufacturing_identities(board)
    sources: dict[ManufacturingArtifactRole, tuple[Path, ...]] = {}
    for role in MANDATORY_NEUTRAL_ROLES:
        artifact = tmp_path / f"{role.value}.dat"
        artifact.write_bytes(_artifact_payload(role))
        sources[role] = (artifact,)

    manifest, archive = assemble_neutral_manufacturing_package(
        output_directory=tmp_path / "release-package",
        project_id="fixture-project",
        board_file=board,
        profile=profile,
        identities=identities,
        current_paths=(_current_path(board_sha256, profile),),
        dfm_dft=_dfm(board_sha256),
        source_artifacts=sources,
        tool_evidence=(_tool(),),
    )

    assert archive.is_file()
    assert (tmp_path / "release-package" / "manifest.json").is_file()
    assert (tmp_path / "release-package" / "SHA256SUMS").is_file()
    assert manifest.release_status is ManufacturingReleaseStatus.PACKAGE_GENERATED
    assert manifest.approvals == ()

    payload = manifest.model_dump(mode="json")
    payload["release_status"] = "fabrication_ready"
    with pytest.raises(ValidationError, match="release status is stale"):
        NeutralManufacturingPackage.model_validate(payload)


def test_release_language_requires_exact_human_fab_and_assembler_approvals(
    tmp_path: Path,
) -> None:
    board = _board(tmp_path / "board.kicad_pcb")
    board_sha256 = _sha(board.read_bytes())
    profile = _profile()
    sources: dict[ManufacturingArtifactRole, tuple[Path, ...]] = {}
    for role in MANDATORY_NEUTRAL_ROLES:
        artifact = tmp_path / f"{role.value}.dat"
        artifact.write_bytes(_artifact_payload(role))
        sources[role] = (artifact,)
    manifest, _ = assemble_neutral_manufacturing_package(
        output_directory=tmp_path / "release-package",
        project_id="fixture-project",
        board_file=board,
        profile=profile,
        identities=extract_saved_board_manufacturing_identities(board),
        current_paths=(_current_path(board_sha256, profile),),
        dfm_dft=_dfm(board_sha256),
        source_artifacts=sources,
        tool_evidence=(_tool(),),
    )

    def approval(role: ManufacturingApprovalRole) -> ManufacturingApproval:
        return ManufacturingApproval(
            role=role,
            approver_id=f"fixture.{role.value}",
            package_sha256=manifest.package_fingerprint,
            decision="approved",
            approval_record_sha256=_sha(f"approval.{role.value}"),
        )

    base = manifest.model_dump(mode="json")
    base["approvals"] = [
        approval(ManufacturingApprovalRole.HUMAN_ENGINEERING).model_dump(mode="json"),
        approval(ManufacturingApprovalRole.FABRICATOR).model_dump(mode="json"),
    ]
    base["release_status"] = "fabrication_ready"
    fabrication_ready = NeutralManufacturingPackage.model_validate(base)
    assert fabrication_ready.release_status is ManufacturingReleaseStatus.FABRICATION_READY

    base["approvals"].append(approval(ManufacturingApprovalRole.ASSEMBLER).model_dump(mode="json"))
    base["release_status"] = "assembly_ready"
    assembly_ready = NeutralManufacturingPackage.model_validate(base)
    assert assembly_ready.release_status is ManufacturingReleaseStatus.ASSEMBLY_READY


def test_neutral_package_rejects_role_labels_on_unrecognizable_content(
    tmp_path: Path,
) -> None:
    board = _board(tmp_path / "board.kicad_pcb")
    board_sha256 = _sha(board.read_bytes())
    profile = _profile()
    sources: dict[ManufacturingArtifactRole, tuple[Path, ...]] = {}
    for role in MANDATORY_NEUTRAL_ROLES:
        artifact = tmp_path / f"{role.value}.dat"
        artifact.write_bytes(
            b"not actually a gerber\n"
            if role is ManufacturingArtifactRole.GERBER
            else _artifact_payload(role)
        )
        sources[role] = (artifact,)

    with pytest.raises(ValueError, match="not recognizable Gerber"):
        assemble_neutral_manufacturing_package(
            output_directory=tmp_path / "release-package",
            project_id="fixture-project",
            board_file=board,
            profile=profile,
            identities=extract_saved_board_manufacturing_identities(board),
            current_paths=(_current_path(board_sha256, profile),),
            dfm_dft=_dfm(board_sha256),
            source_artifacts=sources,
            tool_evidence=(_tool(),),
        )
