"""Manufacturer-neutral package assembly and optional Phase 18 adapters."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from enum import StrEnum
from pathlib import Path, PurePosixPath
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.manufacturing_ir import (
    CurrentPathAuthority,
    CurrentPathRecord,
    DfmDftCategory,
    DfmDftDisposition,
    DfmDftEvidence,
    DfmDftReport,
    FabricationElectricalProfile,
    ManufacturingApproval,
    ManufacturingIdentity,
    ManufacturingIdentityKind,
    ManufacturingIdentityRegistry,
    ManufacturingReleaseStatus,
    derive_release_status,
)
from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel

KIKIT_PINNED_VERSION = "1.8.0"
INTERACTIVE_HTML_BOM_PINNED_VERSION = "2.11.2"


class ManufacturingToolStatus(StrEnum):
    AVAILABLE = "available"
    VERSION_MISMATCH = "version_mismatch"
    UNAVAILABLE = "unavailable"
    FAILED = "failed"


class ManufacturingToolEvidence(SemanticIrModel):
    tool_id: str
    pinned_version: str
    observed_version: str | None
    status: ManufacturingToolStatus
    command: tuple[str, ...]
    stdout_sha256: str | None
    stderr_sha256: str | None
    limitations: tuple[str, ...] = ()
    evidence_fingerprint: str

    @model_validator(mode="after")
    def evidence_is_replay_bound(self) -> Self:
        require_identity(self.tool_id, "tool_id")
        require_identity(self.pinned_version, "pinned_version")
        if not self.command:
            raise ValueError("tool evidence requires the exact command")
        if self.observed_version is not None:
            require_identity(self.observed_version, "observed_version")
        for name in ("stdout_sha256", "stderr_sha256"):
            digest = getattr(self, name)
            if digest is not None:
                require_sha256(digest, name)
        if self.status is ManufacturingToolStatus.AVAILABLE:
            if self.observed_version != self.pinned_version:
                raise ValueError("available tool does not match the pinned version")
        require_sha256(self.evidence_fingerprint, "evidence_fingerprint")
        payload = self.model_dump(mode="json", exclude={"evidence_fingerprint"})
        if self.evidence_fingerprint != fingerprint(payload):
            raise ValueError("manufacturing tool evidence fingerprint is stale")
        return self


def inspect_version_pinned_tool(
    *,
    tool_id: str,
    command: Sequence[str],
    pinned_version: str,
    environment: Mapping[str, str] | None = None,
) -> ManufacturingToolEvidence:
    """Inspect a tool without installing or silently substituting it."""

    observed: str | None = None
    stdout = b""
    stderr = b""
    status = ManufacturingToolStatus.UNAVAILABLE
    limitations: tuple[str, ...] = ()
    process_environment = None
    if environment is not None:
        process_environment = os.environ.copy()
        process_environment.update(environment)
    try:
        completed = subprocess.run(
            list(command),
            capture_output=True,
            check=False,
            env=process_environment,
        )
        stdout = completed.stdout
        stderr = completed.stderr
        combined = (stdout + b"\n" + stderr).decode("utf-8", errors="replace")
        observed = _extract_version(combined)
        if completed.returncode != 0:
            status = ManufacturingToolStatus.FAILED
        elif observed == pinned_version:
            status = ManufacturingToolStatus.AVAILABLE
        else:
            status = ManufacturingToolStatus.VERSION_MISMATCH
    except FileNotFoundError:
        limitations = ("tool executable is not installed or not on PATH",)
    fields: dict[str, Any] = {
        "tool_id": tool_id,
        "pinned_version": pinned_version,
        "observed_version": observed,
        "status": status,
        "command": tuple(command),
        "stdout_sha256": _bytes_sha256(stdout) if stdout else None,
        "stderr_sha256": _bytes_sha256(stderr) if stderr else None,
        "limitations": limitations,
    }
    provisional = ManufacturingToolEvidence.model_construct(**fields, evidence_fingerprint="0" * 64)
    return ManufacturingToolEvidence(
        **fields,
        evidence_fingerprint=fingerprint(
            provisional.model_dump(mode="json", exclude={"evidence_fingerprint"})
        ),
    )


def _extract_version(value: str) -> str | None:
    import re

    match = re.search(r"(?<!\d)(\d+\.\d+\.\d+)(?!\d)", value)
    return match.group(1) if match else None


def _bytes_sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def extract_saved_board_manufacturing_identities(
    board_file: Path,
) -> ManufacturingIdentityRegistry:
    """Derive replay-stable manufacturing identities from a saved KiCad board."""

    board_payload = board_file.read_bytes()
    text = board_payload.decode("utf-8")
    board_sha256 = _bytes_sha256(board_payload)
    identities: list[ManufacturingIdentity] = []
    for footprint_index, footprint_block in enumerate(
        _sexpr_blocks(text, "footprint"),
        start=1,
    ):
        library_match = re.match(r'\(footprint\s+"([^"]+)"', footprint_block)
        reference_match = re.search(
            r'\(property\s+"Reference"\s+"([^"]+)"',
            footprint_block,
        ) or re.search(r'\(fp_text\s+reference\s+"([^"]+)"', footprint_block)
        value_match = re.search(
            r'\(property\s+"Value"\s+"([^"]*)"',
            footprint_block,
        )
        uuid_match = re.search(
            r'\((?:uuid|tstamp)\s+"?([0-9a-fA-F-]{8,})"?\)',
            footprint_block,
        )
        at_match = re.search(
            r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)(?:\s+(-?[\d.]+))?",
            footprint_block,
        )
        layer_match = re.search(r'\(layer\s+"([^"]+)"\)', footprint_block)
        library_id = library_match.group(1) if library_match else "unknown-footprint"
        reference = reference_match.group(1) if reference_match else f"UNREF-{footprint_index}"
        value = value_match.group(1) if value_match else ""
        footprint_uuid = (
            uuid_match.group(1).lower()
            if uuid_match
            else fingerprint(
                {
                    "reference": reference,
                    "library_id": library_id,
                    "occurrence": footprint_index,
                }
            )[:32]
        )
        footprint_id = f"footprint:{footprint_uuid}"
        common_keys = (
            f"reference={reference}",
            f"library_id={library_id}",
            f"uuid={footprint_uuid}",
        )
        identities.append(
            ManufacturingIdentity.build(
                kind=ManufacturingIdentityKind.FOOTPRINT,
                stable_id=footprint_id,
                board_sha256=board_sha256,
                source_keys=common_keys,
            )
        )
        identities.append(
            ManufacturingIdentity.build(
                kind=ManufacturingIdentityKind.COMPONENT,
                stable_id=f"component:{footprint_uuid}",
                board_sha256=board_sha256,
                source_keys=common_keys + (f"value={value}",),
            )
        )
        identities.append(
            ManufacturingIdentity.build(
                kind=ManufacturingIdentityKind.BOM_ROW,
                stable_id=f"bom:{footprint_uuid}",
                board_sha256=board_sha256,
                source_keys=common_keys + (f"value={value}",),
            )
        )
        placement_keys = common_keys + (
            f"at={at_match.group(0) if at_match else 'unknown'}",
            f"layer={layer_match.group(1) if layer_match else 'unknown'}",
        )
        identities.append(
            ManufacturingIdentity.build(
                kind=ManufacturingIdentityKind.PLACEMENT_ROW,
                stable_id=f"placement:{footprint_uuid}",
                board_sha256=board_sha256,
                source_keys=placement_keys,
            )
        )
        for pad_index, pad_block in enumerate(
            _sexpr_blocks(footprint_block, "pad"),
            start=1,
        ):
            pad_match = re.match(r'\(pad\s+"([^"]*)"\s+(\S+)\s+(\S+)', pad_block)
            if pad_match is None:
                continue
            pad_name, pad_type, pad_shape = pad_match.groups()
            pad_uuid_match = re.search(
                r'\((?:uuid|tstamp)\s+"?([0-9a-fA-F-]{8,})"?\)',
                pad_block,
            )
            pad_key = (
                pad_uuid_match.group(1).lower()
                if pad_uuid_match
                else f"{pad_name or 'unnamed'}:{pad_index}"
            )
            pad_id = f"{footprint_id}/pad:{pad_key}"
            pad_keys = common_keys + (
                f"pad_name={pad_name}",
                f"pad_type={pad_type}",
                f"pad_shape={pad_shape}",
                f"pad_occurrence={pad_index}",
            )
            identities.append(
                ManufacturingIdentity.build(
                    kind=ManufacturingIdentityKind.PAD,
                    stable_id=pad_id,
                    board_sha256=board_sha256,
                    source_keys=pad_keys,
                )
            )
            drill_match = re.search(
                r"\(drill\s+(?:oval\s+)?([\d.]+)(?:\s+([\d.]+))?",
                pad_block,
            )
            if drill_match:
                identities.append(
                    ManufacturingIdentity.build(
                        kind=ManufacturingIdentityKind.HOLE,
                        stable_id=f"{pad_id}/hole",
                        board_sha256=board_sha256,
                        source_keys=pad_keys + (f"drill={drill_match.group(0)}",),
                    )
                )
            layers_match = re.search(r"\(layers\s+([^)]+)\)", pad_block)
            layers = layers_match.group(1) if layers_match else ""
            for aperture_layer in ("F.Mask", "B.Mask", "F.Paste", "B.Paste"):
                wildcard = "*.Mask" if aperture_layer.endswith(".Mask") else "*.Paste"
                if aperture_layer in layers or wildcard in layers:
                    identities.append(
                        ManufacturingIdentity.build(
                            kind=ManufacturingIdentityKind.APERTURE,
                            stable_id=f"{pad_id}/aperture:{aperture_layer}",
                            board_sha256=board_sha256,
                            source_keys=pad_keys + (f"layer={aperture_layer}",),
                        )
                    )
    if not identities:
        raise ValueError("saved KiCad board contains no manufacturing identities")
    return ManufacturingIdentityRegistry.build(
        board_sha256=board_sha256,
        identities=tuple(identities),
    )


def _sexpr_blocks(text: str, head: str) -> tuple[str, ...]:
    blocks: list[str] = []
    pattern = re.compile(rf"\({re.escape(head)}(?:\s|\))")
    for match in pattern.finditer(text):
        depth = 0
        index = match.start()
        quoted = False
        escaped = False
        while index < len(text):
            character = text[index]
            if quoted:
                if escaped:
                    escaped = False
                elif character == "\\":
                    escaped = True
                elif character == '"':
                    quoted = False
            elif character == '"':
                quoted = True
            elif character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    blocks.append(text[match.start() : index + 1])
                    break
            index += 1
    return tuple(blocks)


class BoardOutlineClass(StrEnum):
    REGULAR_RECTANGULAR = "regular_rectangular"
    IRREGULAR = "irregular"
    CUTOUT = "cutout"


class PanelCutMethod(StrEnum):
    MOUSE_BITES = "mouse_bites"
    V_CUTS = "v_cuts"


class PanelFrameKind(StrEnum):
    TOP_BOTTOM_RAILS = "top_bottom_rails"
    LEFT_RIGHT_RAILS = "left_right_rails"
    FULL_FRAME = "full_frame"


class PanelizationProfile(SemanticIrModel):
    schema_id: Literal["pcbsmith-panelization-profile"] = "pcbsmith-panelization-profile"
    schema_version: Literal[1] = 1
    outline_class: BoardOutlineClass
    rows: int = Field(gt=0)
    columns: int = Field(gt=0)
    horizontal_spacing_mm: float = Field(ge=0)
    vertical_spacing_mm: float = Field(ge=0)
    tabs_width_mm: float = Field(gt=0)
    cut_method: PanelCutMethod
    mouse_bite_drill_mm: float | None = Field(default=None, gt=0)
    mouse_bite_spacing_mm: float | None = Field(default=None, gt=0)
    frame_kind: PanelFrameKind
    rail_width_mm: float = Field(gt=0)
    fiducial_count: int = Field(ge=0)
    tooling_hole_count: int = Field(ge=0)
    impedance_coupon_ids: tuple[str, ...] = ()
    panel_drc_required: Literal[True] = True

    @model_validator(mode="after")
    def profile_is_manufacturable_in_scope(self) -> Self:
        if self.cut_method is PanelCutMethod.MOUSE_BITES:
            if self.mouse_bite_drill_mm is None or self.mouse_bite_spacing_mm is None:
                raise ValueError("mouse-bite panel requires drill and spacing")
        elif self.mouse_bite_drill_mm is not None or self.mouse_bite_spacing_mm is not None:
            raise ValueError("V-cut panel cannot declare mouse-bite geometry")
        if (
            self.cut_method is PanelCutMethod.V_CUTS
            and self.outline_class is not BoardOutlineClass.REGULAR_RECTANGULAR
        ):
            raise ValueError("irregular/cutout boards require routed tabs, not V-cuts")
        if self.rows * self.columns > 1:
            if self.fiducial_count < 3:
                raise ValueError("multi-board panel requires at least three fiducials")
            if self.tooling_hole_count < 3:
                raise ValueError("multi-board panel requires at least three tooling holes")
        coupons = tuple(sorted(self.impedance_coupon_ids))
        if len(coupons) != len(set(coupons)):
            raise ValueError("panel coupon identities must be unique")
        object.__setattr__(self, "impedance_coupon_ids", coupons)
        return self

    def kikit_configuration(self) -> dict[str, object]:
        cuts: dict[str, object]
        if self.cut_method is PanelCutMethod.MOUSE_BITES:
            cuts = {
                "type": "mousebites",
                "drill": f"{self.mouse_bite_drill_mm:g}mm",
                "spacing": f"{self.mouse_bite_spacing_mm:g}mm",
            }
        else:
            cuts = {"type": "vcuts"}
        frame_type = {
            PanelFrameKind.TOP_BOTTOM_RAILS: "railstb",
            PanelFrameKind.LEFT_RIGHT_RAILS: "railslr",
            PanelFrameKind.FULL_FRAME: "frame",
        }[self.frame_kind]
        return {
            "layout": {
                "type": "grid",
                "rows": self.rows,
                "cols": self.columns,
                "hspace": f"{self.horizontal_spacing_mm:g}mm",
                "vspace": f"{self.vertical_spacing_mm:g}mm",
            },
            "source": {"type": "auto", "tolerance": "1mm"},
            "tabs": (
                {"type": "full"}
                if self.cut_method is PanelCutMethod.V_CUTS
                else {"type": "spacing", "width": f"{self.tabs_width_mm:g}mm"}
            ),
            "cuts": cuts,
            "framing": {"type": frame_type, "width": f"{self.rail_width_mm:g}mm"},
            "tooling": {"type": "3hole" if self.tooling_hole_count >= 3 else "none"},
            "fiducials": {"type": "3fid" if self.fiducial_count >= 3 else "none"},
            "post": {"type": "auto", "dimensions": True},
        }


class InteractiveBomProfile(SemanticIrModel):
    include_front: bool = True
    include_back: bool = True
    include_tracks_and_zones: bool = False
    variant_ids: tuple[str, ...] = ()
    dnp_reference_ids: tuple[str, ...] = ()
    bom_group_fields: tuple[str, ...] = ("Value", "Footprint")
    back_rotation_offset_degrees: Literal[0, 180] = 0

    @model_validator(mode="after")
    def profile_is_canonical(self) -> Self:
        if not self.include_front and not self.include_back:
            raise ValueError("interactive BOM must include at least one side")
        for name in ("variant_ids", "dnp_reference_ids", "bom_group_fields"):
            values = tuple(sorted(getattr(self, name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{name} must be unique")
            object.__setattr__(self, name, values)
        return self


def generate_kikit_panel(
    *,
    board_file: Path,
    panel_file: Path,
    profile: PanelizationProfile,
    tool_evidence: ManufacturingToolEvidence,
    executable: str = "kikit",
    command_prefix: Sequence[str] | None = None,
) -> Path:
    """Run the pinned KiKit CLI and retain its resolved configuration."""

    if (
        tool_evidence.tool_id != "kikit"
        or tool_evidence.pinned_version != KIKIT_PINNED_VERSION
        or tool_evidence.status is not ManufacturingToolStatus.AVAILABLE
    ):
        raise ValueError("panelization requires available pinned KiKit evidence")
    panel_file.parent.mkdir(parents=True, exist_ok=True)
    configuration = panel_file.with_suffix(".kikit.json")
    configuration.write_text(
        json.dumps(profile.kikit_configuration(), indent=2) + "\n",
        encoding="utf-8",
    )
    prefix = tuple(command_prefix) if command_prefix is not None else (executable,)
    command = (
        *prefix,
        "panelize",
        "-p",
        str(configuration),
        "-d",
        str(panel_file.with_suffix(".resolved-kikit.json")),
        str(board_file),
        str(panel_file),
    )
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    if completed.returncode != 0 or not panel_file.is_file():
        raise RuntimeError(
            "KiKit panelization failed: " + (completed.stderr.strip() or completed.stdout.strip())
        )
    return panel_file


def generate_interactive_html_bom(
    *,
    board_file: Path,
    output_directory: Path,
    profile: InteractiveBomProfile,
    tool_evidence: ManufacturingToolEvidence,
    executable: str = "generate_interactive_bom",
    command_prefix: Sequence[str] | None = None,
) -> Path:
    """Generate one self-contained assembly BOM with explicit side/variant data."""

    if (
        tool_evidence.tool_id != "interactive-html-bom"
        or tool_evidence.pinned_version != INTERACTIVE_HTML_BOM_PINNED_VERSION
        or tool_evidence.status is not ManufacturingToolStatus.AVAILABLE
    ):
        raise ValueError("interactive BOM requires available pinned InteractiveHtmlBom evidence")
    output_directory.mkdir(parents=True, exist_ok=True)
    side = (
        "FB"
        if profile.include_front and profile.include_back
        else ("F" if profile.include_front else "B")
    )
    prefix = tuple(command_prefix) if command_prefix is not None else (executable,)
    command: list[str] = [
        *prefix,
        "--no-browser",
        "--dest-dir",
        str(output_directory),
        "--layer-view",
        side,
        "--group-fields",
        ",".join(profile.bom_group_fields),
        "--dnp-field",
        "DNP",
    ]
    if profile.include_tracks_and_zones:
        command.extend(("--include-tracks", "--include-nets"))
    if profile.back_rotation_offset_degrees == 180:
        command.append("--offset-back-rotation")
    if profile.variant_ids:
        command.extend(("--variants-whitelist", ",".join(profile.variant_ids)))
    if profile.dnp_reference_ids:
        command.extend(("--blacklist", ",".join(profile.dnp_reference_ids)))
    command.append(str(board_file))
    before = set(output_directory.glob("*.html"))
    environment = os.environ.copy()
    environment["INTERACTIVE_HTML_BOM_NO_DISPLAY"] = "1"
    environment["INTERACTIVE_HTML_BOM_CLI_MODE"] = "1"
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        check=False,
        env=environment,
    )
    produced = tuple(sorted(set(output_directory.glob("*.html")) - before))
    if completed.returncode != 0 or len(produced) != 1:
        raise RuntimeError(
            "InteractiveHtmlBom generation failed or was ambiguous: "
            + (completed.stderr.strip() or completed.stdout.strip())
        )
    return produced[0]


class ManufacturingArtifactRole(StrEnum):
    GERBER = "gerber"
    DRILL = "drill"
    DRILL_MAP = "drill_map"
    NETLIST = "netlist"
    STACKUP_NOTES = "stackup_notes"
    FABRICATION_DRAWING = "fabrication_drawing"
    ASSEMBLY_DRAWING_FRONT = "assembly_drawing_front"
    ASSEMBLY_DRAWING_BACK = "assembly_drawing_back"
    BOM = "bom"
    PLACEMENT = "placement"
    PASTE = "paste"
    INTERACTIVE_BOM = "interactive_bom"
    README = "readme"
    PANEL_BOARD = "panel_board"
    PANEL_DRC = "panel_drc"
    OTHER = "other"


MANDATORY_NEUTRAL_ROLES = frozenset(
    {
        ManufacturingArtifactRole.GERBER,
        ManufacturingArtifactRole.DRILL,
        ManufacturingArtifactRole.DRILL_MAP,
        ManufacturingArtifactRole.NETLIST,
        ManufacturingArtifactRole.STACKUP_NOTES,
        ManufacturingArtifactRole.FABRICATION_DRAWING,
        ManufacturingArtifactRole.ASSEMBLY_DRAWING_FRONT,
        ManufacturingArtifactRole.ASSEMBLY_DRAWING_BACK,
        ManufacturingArtifactRole.BOM,
        ManufacturingArtifactRole.PLACEMENT,
        ManufacturingArtifactRole.PASTE,
        ManufacturingArtifactRole.INTERACTIVE_BOM,
        ManufacturingArtifactRole.README,
    }
)


class ManufacturingArtifact(SemanticIrModel):
    artifact_id: str
    role: ManufacturingArtifactRole
    relative_path: str
    content_sha256: str
    source_board_sha256: str

    @model_validator(mode="after")
    def artifact_is_safe(self) -> Self:
        require_identity(self.artifact_id, "artifact_id")
        path = PurePosixPath(self.relative_path)
        if path.is_absolute() or ".." in path.parts or path.as_posix() in {"", "."}:
            raise ValueError("manufacturing artifact path escapes package")
        require_sha256(self.content_sha256, "content_sha256")
        require_sha256(self.source_board_sha256, "source_board_sha256")
        return self


class NeutralManufacturingPackage(SemanticIrModel):
    schema_id: Literal["pcbsmith-neutral-manufacturing-package"] = (
        "pcbsmith-neutral-manufacturing-package"
    )
    schema_version: Literal[1] = 1
    project_id: str
    board_sha256: str
    fabrication_profile_fingerprint: str
    identity_registry_fingerprint: str
    current_path_record_fingerprints: tuple[str, ...]
    dfm_dft_report_fingerprint: str
    artifacts: tuple[ManufacturingArtifact, ...]
    tool_evidence: tuple[ManufacturingToolEvidence, ...]
    approvals: tuple[ManufacturingApproval, ...] = ()
    release_status: ManufacturingReleaseStatus
    blockers: tuple[str, ...]
    package_fingerprint: str

    @model_validator(mode="after")
    def package_is_complete_and_release_language_is_guarded(self) -> Self:
        require_identity(self.project_id, "project_id")
        for name in (
            "board_sha256",
            "fabrication_profile_fingerprint",
            "identity_registry_fingerprint",
            "dfm_dft_report_fingerprint",
        ):
            require_sha256(getattr(self, name), name)
        artifacts = tuple(
            sorted(self.artifacts, key=lambda item: (item.role.value, item.relative_path))
        )
        if len({item.relative_path for item in artifacts}) != len(artifacts):
            raise ValueError("manufacturing artifact paths must be unique")
        if any(item.source_board_sha256 != self.board_sha256 for item in artifacts):
            raise ValueError("manufacturing package mixes board revisions")
        missing = MANDATORY_NEUTRAL_ROLES - {item.role for item in artifacts}
        if missing:
            raise ValueError(
                "neutral manufacturing package is missing roles: "
                + ", ".join(sorted(item.value for item in missing))
            )
        approvals = tuple(sorted(self.approvals, key=lambda item: item.role.value))
        if len({item.role for item in approvals}) != len(approvals):
            raise ValueError("manufacturing approvals must be unique by role")
        if approvals and any(item.package_sha256 != self.package_fingerprint for item in approvals):
            raise ValueError("manufacturing approval targets another package")
        expected_status = derive_release_status(approvals)
        if self.blockers:
            expected_status = ManufacturingReleaseStatus.BLOCKED
        if self.release_status is not expected_status:
            raise ValueError("manufacturing release status is stale")
        object.__setattr__(self, "artifacts", artifacts)
        object.__setattr__(self, "approvals", approvals)
        require_sha256(self.package_fingerprint, "package_fingerprint")
        payload = self.model_dump(
            mode="json",
            exclude={"package_fingerprint", "approvals", "release_status"},
        )
        if self.package_fingerprint != fingerprint(payload):
            raise ValueError("neutral manufacturing package fingerprint is stale")
        return self


def assemble_neutral_manufacturing_package(
    *,
    output_directory: Path,
    project_id: str,
    board_file: Path,
    profile: FabricationElectricalProfile,
    identities: ManufacturingIdentityRegistry,
    current_paths: tuple[CurrentPathRecord, ...],
    dfm_dft: DfmDftReport,
    source_artifacts: Mapping[ManufacturingArtifactRole, tuple[Path, ...]],
    tool_evidence: tuple[ManufacturingToolEvidence, ...],
) -> tuple[NeutralManufacturingPackage, Path]:
    """Atomically assemble exact exporter outputs into one neutral package."""

    board_sha256 = _bytes_sha256(board_file.read_bytes())
    if identities.board_sha256 != board_sha256:
        raise ValueError("manufacturing identities target another board")
    if dfm_dft.board_sha256 != board_sha256:
        raise ValueError("DFM/DFT report targets another board")
    if not current_paths:
        raise ValueError("manufacturing package requires current-path records")
    blockers: list[str] = []
    if any(item.board_sha256 != board_sha256 for item in current_paths):
        raise ValueError("current-path records target another board")
    if any(item.profile_fingerprint != profile.profile_fingerprint for item in current_paths):
        raise ValueError("current-path records use another fabrication profile")
    if any(item.authority is not CurrentPathAuthority.VERIFIED for item in current_paths):
        blockers.append("one or more current paths remain unverified")
    if not dfm_dft.ready:
        blockers.append("DFM/DFT report is not ready")
    unavailable_tools = tuple(
        item.tool_id
        for item in tool_evidence
        if item.status is not ManufacturingToolStatus.AVAILABLE
    )
    if unavailable_tools:
        blockers.append(
            "required manufacturing tools unavailable or version-mismatched: "
            + ", ".join(sorted(unavailable_tools))
        )
    supplied_roles = set(source_artifacts)
    missing = MANDATORY_NEUTRAL_ROLES - supplied_roles
    if missing:
        raise ValueError(
            "source artifacts omit mandatory roles: "
            + ", ".join(sorted(item.value for item in missing))
        )

    target = output_directory.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{target.name}-", dir=target.parent) as temporary:
        staging = Path(temporary) / "package"
        staging.mkdir()
        artifacts: list[ManufacturingArtifact] = []
        artifact_index = 0
        for role in sorted(source_artifacts, key=lambda item: item.value):
            paths = source_artifacts[role]
            if not paths:
                raise ValueError(f"artifact role {role.value} has no files")
            for source in sorted(paths, key=lambda item: item.name):
                if not source.is_file():
                    raise ValueError(f"manufacturing source artifact is missing: {source}")
                payload = source.read_bytes()
                _validate_manufacturing_artifact(role, source, payload)
                artifact_index += 1
                relative = PurePosixPath("files") / role.value / source.name
                destination = staging / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(payload)
                artifacts.append(
                    ManufacturingArtifact(
                        artifact_id=f"mfg-{artifact_index:04d}",
                        role=role,
                        relative_path=relative.as_posix(),
                        content_sha256=_bytes_sha256(destination.read_bytes()),
                        source_board_sha256=board_sha256,
                    )
                )
        current_fingerprints = tuple(sorted(item.record_fingerprint for item in current_paths))
        fields: dict[str, Any] = {
            "project_id": project_id,
            "board_sha256": board_sha256,
            "fabrication_profile_fingerprint": profile.profile_fingerprint,
            "identity_registry_fingerprint": identities.registry_fingerprint,
            "current_path_record_fingerprints": current_fingerprints,
            "dfm_dft_report_fingerprint": dfm_dft.report_fingerprint,
            "artifacts": tuple(artifacts),
            "tool_evidence": tuple(sorted(tool_evidence, key=lambda item: item.tool_id)),
            "blockers": tuple(blockers),
        }
        provisional = NeutralManufacturingPackage.model_construct(
            **fields,
            approvals=(),
            release_status=ManufacturingReleaseStatus.BLOCKED,
            package_fingerprint="0" * 64,
        )
        package_fingerprint = fingerprint(
            provisional.model_dump(
                mode="json",
                exclude={"package_fingerprint", "approvals", "release_status"},
            )
        )
        status = (
            ManufacturingReleaseStatus.BLOCKED
            if blockers
            else ManufacturingReleaseStatus.PACKAGE_GENERATED
        )
        manifest = NeutralManufacturingPackage(
            **fields,
            approvals=(),
            release_status=status,
            package_fingerprint=package_fingerprint,
        )
        (staging / "manifest.json").write_text(
            json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n",
            encoding="utf-8",
        )
        hashes = "\n".join(
            f"{item.content_sha256}  {item.relative_path}" for item in manifest.artifacts
        )
        (staging / "SHA256SUMS").write_text(hashes + "\n", encoding="utf-8")
        if target.exists():
            raise ValueError(f"manufacturing package target already exists: {target}")
        os.replace(staging, target)
    archive = Path(
        shutil.make_archive(
            str(target),
            "zip",
            root_dir=target.parent,
            base_dir=target.name,
        )
    )
    return manifest, archive


def export_kicad_neutral_sources(
    *,
    board_file: Path,
    output_directory: Path,
    profile: FabricationElectricalProfile,
    identities: ManufacturingIdentityRegistry,
    interactive_bom_file: Path,
    kicad_cli: Path,
    kicad_version: str,
) -> tuple[
    dict[ManufacturingArtifactRole, tuple[Path, ...]],
    ManufacturingToolEvidence,
]:
    """Export the canonical neutral source set with KiCad's headless CLI."""

    if output_directory.exists():
        raise ValueError(f"neutral export target already exists: {output_directory}")
    output_directory.mkdir(parents=True)
    tool = inspect_version_pinned_tool(
        tool_id="kicad-cli",
        command=(str(kicad_cli), "version"),
        pinned_version=kicad_version,
    )
    if tool.status is not ManufacturingToolStatus.AVAILABLE:
        raise ValueError("KiCad CLI version does not match the manufacturing pin")
    gerber_dir = output_directory / "gerber"
    drill_dir = output_directory / "drill"
    drawing_dir = output_directory / "drawings"
    gerber_dir.mkdir()
    drill_dir.mkdir()
    drawing_dir.mkdir()
    commands = (
        (
            str(kicad_cli),
            "pcb",
            "export",
            "gerbers",
            "--layers",
            "F.Cu,B.Cu,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,Edge.Cuts,F.Paste,B.Paste",
            "--check-zones",
            "--output",
            str(gerber_dir) + os.sep,
            str(board_file),
        ),
        (
            str(kicad_cli),
            "pcb",
            "export",
            "drill",
            "--format",
            "excellon",
            "--generate-map",
            "--map-format",
            "gerberx2",
            "--output",
            str(drill_dir) + os.sep,
            str(board_file),
        ),
        (
            str(kicad_cli),
            "pcb",
            "export",
            "ipcd356",
            "--output",
            str(output_directory / "netlist.ipc"),
            str(board_file),
        ),
        (
            str(kicad_cli),
            "pcb",
            "export",
            "pos",
            "--format",
            "csv",
            "--units",
            "mm",
            "--side",
            "both",
            "--exclude-dnp",
            "--output",
            str(output_directory / "placement.csv"),
            str(board_file),
        ),
        _pdf_export_command(
            kicad_cli=kicad_cli,
            board_file=board_file,
            output=drawing_dir / "fabrication.pdf",
            layers="F.Fab,B.Fab,Edge.Cuts",
            mirror=False,
        ),
        _pdf_export_command(
            kicad_cli=kicad_cli,
            board_file=board_file,
            output=drawing_dir / "assembly-front.pdf",
            layers="F.Silkscreen,F.Fab,Edge.Cuts",
            mirror=False,
        ),
        _pdf_export_command(
            kicad_cli=kicad_cli,
            board_file=board_file,
            output=drawing_dir / "assembly-back.pdf",
            layers="B.Silkscreen,B.Fab,Edge.Cuts",
            mirror=True,
        ),
    )
    for command in commands:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "KiCad neutral export failed: "
                + (completed.stderr.strip() or completed.stdout.strip())
            )
    bom_file = output_directory / "bom.csv"
    _write_identity_bom(bom_file, identities)
    stackup_file = output_directory / "stackup-notes.md"
    _write_stackup_notes(stackup_file, profile)
    readme_file = output_directory / "README.md"
    readme_file.write_text(
        "# Manufacturer-neutral outputs\n\n"
        "These files are generated evidence, not fabrication or assembly "
        "approval. Read the package manifest, DFM/DFT report, current-path "
        "records, limitations, and approval records before release.\n",
        encoding="utf-8",
    )
    retained_ibom = output_directory / "interactive-bom.html"
    shutil.copy2(interactive_bom_file, retained_ibom)
    gerbers = tuple(sorted(gerber_dir.glob("*")))
    paste = tuple(
        path
        for path in gerbers
        if "paste" in path.name.casefold() or path.suffix.casefold() in {".gtp", ".gbp"}
    )
    ordinary_gerbers = tuple(path for path in gerbers if path not in paste)
    drill_files = tuple(
        path for path in drill_dir.glob("*") if path.suffix.casefold() in {".drl", ".xln"}
    )
    drill_maps = tuple(path for path in drill_dir.glob("*") if path not in drill_files)
    sources = {
        ManufacturingArtifactRole.GERBER: ordinary_gerbers,
        ManufacturingArtifactRole.DRILL: drill_files,
        ManufacturingArtifactRole.DRILL_MAP: drill_maps,
        ManufacturingArtifactRole.NETLIST: (output_directory / "netlist.ipc",),
        ManufacturingArtifactRole.STACKUP_NOTES: (stackup_file,),
        ManufacturingArtifactRole.FABRICATION_DRAWING: (drawing_dir / "fabrication.pdf",),
        ManufacturingArtifactRole.ASSEMBLY_DRAWING_FRONT: (drawing_dir / "assembly-front.pdf",),
        ManufacturingArtifactRole.ASSEMBLY_DRAWING_BACK: (drawing_dir / "assembly-back.pdf",),
        ManufacturingArtifactRole.BOM: (bom_file,),
        ManufacturingArtifactRole.PLACEMENT: (output_directory / "placement.csv",),
        ManufacturingArtifactRole.PASTE: paste,
        ManufacturingArtifactRole.INTERACTIVE_BOM: (retained_ibom,),
        ManufacturingArtifactRole.README: (readme_file,),
    }
    missing_files = tuple(
        role.value
        for role, paths in sources.items()
        if not paths or any(not path.is_file() for path in paths)
    )
    if missing_files:
        raise RuntimeError("KiCad neutral export omitted roles: " + ", ".join(missing_files))
    return sources, tool


def evaluate_baseline_dfm_dft(
    *,
    board_file: Path,
    drc_report_file: Path,
    supplemental_evidence: Mapping[DfmDftCategory, DfmDftEvidence] | None = None,
) -> DfmDftReport:
    """Run deterministic baseline checks and expose unsupported scopes."""

    from pcbsmith.kicad.routing_evidence import inspect_kicad_drc_report

    board_sha256 = _bytes_sha256(board_file.read_bytes())
    identities = extract_saved_board_manufacturing_identities(board_file)
    drc = inspect_kicad_drc_report(drc_report_file)
    supplied = {} if supplemental_evidence is None else dict(supplemental_evidence)
    evidence: list[DfmDftEvidence] = []

    footprint_count = sum(
        item.kind is ManufacturingIdentityKind.FOOTPRINT for item in identities.identities
    )
    evidence.append(
        _dfm_evidence(
            category=DfmDftCategory.COURTYARD_PROCESS_CLEARANCE,
            board_sha256=board_sha256,
            disposition=(DfmDftDisposition.PASS if drc.clean else DfmDftDisposition.FAIL),
            count=max(1, footprint_count),
            findings=(
                ()
                if drc.clean
                else (
                    "KiCad DRC contains violations/unconnected/parity findings; "
                    "courtyard/process clearance is not accepted.",
                )
            ),
            source_sha256=drc.report_sha256,
        )
    )
    pad_identities = tuple(
        item for item in identities.identities if item.kind is ManufacturingIdentityKind.PAD
    )
    smd_pads = tuple(item for item in pad_identities if "pad_type=smd" in item.source_keys)
    paste_apertures = tuple(
        item
        for item in identities.identities
        if item.kind is ManufacturingIdentityKind.APERTURE
        and any(key in {"layer=F.Paste", "layer=B.Paste"} for key in item.source_keys)
    )
    paste_findings: tuple[str, ...]
    if not smd_pads:
        paste_disposition = DfmDftDisposition.NOT_APPLICABLE
        paste_findings = ("saved board contains no SMD pads",)
        paste_count = 0
    elif len(paste_apertures) >= len(smd_pads):
        paste_disposition = DfmDftDisposition.PASS
        paste_findings = ()
        paste_count = len(smd_pads)
    else:
        paste_disposition = DfmDftDisposition.FAIL
        paste_findings = (
            f"{len(smd_pads)} SMD pads but only {len(paste_apertures)} "
            "front/back paste apertures were identified",
        )
        paste_count = len(smd_pads)
    evidence.append(
        _dfm_evidence(
            category=DfmDftCategory.PASTE_STRATEGY,
            board_sha256=board_sha256,
            disposition=paste_disposition,
            count=paste_count,
            findings=paste_findings,
            source_sha256=identities.registry_fingerprint,
        )
    )
    reference_keys = tuple(
        key.removeprefix("reference=")
        for item in identities.identities
        if item.kind is ManufacturingIdentityKind.COMPONENT
        for key in item.source_keys
        if key.startswith("reference=")
    )
    test_points = tuple(ref for ref in reference_keys if ref.upper().startswith("TP"))
    evidence.append(
        _dfm_evidence(
            category=DfmDftCategory.TEST_POINTS,
            board_sha256=board_sha256,
            disposition=(DfmDftDisposition.PASS if test_points else DfmDftDisposition.UNVERIFIED),
            count=len(test_points),
            findings=(() if test_points else ("no explicit TP reference identities were found",)),
            source_sha256=identities.registry_fingerprint,
        )
    )
    automatic_categories = {item.category for item in evidence}
    for category in DfmDftCategory:
        if category in automatic_categories:
            if category in supplied:
                raise ValueError(f"supplemental evidence conflicts with automatic {category.value}")
            continue
        if category in supplied:
            item = supplied[category]
            if board_sha256 not in item.exact_input_sha256s:
                raise ValueError(f"supplemental {category.value} evidence targets another board")
            evidence.append(item)
        else:
            evidence.append(
                _dfm_evidence(
                    category=category,
                    board_sha256=board_sha256,
                    disposition=DfmDftDisposition.UNVERIFIED,
                    count=0,
                    findings=("no retained qualified evidence was supplied for this scope",),
                    source_sha256=identities.registry_fingerprint,
                )
            )
    return DfmDftReport.build(
        board_sha256=board_sha256,
        evidence=tuple(evidence),
    )


def _dfm_evidence(
    *,
    category: DfmDftCategory,
    board_sha256: str,
    disposition: DfmDftDisposition,
    count: int,
    findings: tuple[str, ...],
    source_sha256: str,
) -> DfmDftEvidence:
    payload = {
        "category": category.value,
        "board_sha256": board_sha256,
        "disposition": disposition.value,
        "count": count,
        "findings": findings,
        "source_sha256": source_sha256,
    }
    return DfmDftEvidence(
        category=category,
        disposition=disposition,
        producer_id="pcbsmith.phase18.baseline-dfm-dft",
        tool_version="1",
        exact_input_sha256s=tuple(sorted({board_sha256, source_sha256})),
        evaluated_object_count=count,
        findings=findings,
        evidence_sha256=fingerprint(payload),
    )


def _pdf_export_command(
    *,
    kicad_cli: Path,
    board_file: Path,
    output: Path,
    layers: str,
    mirror: bool,
) -> tuple[str, ...]:
    command = [
        str(kicad_cli),
        "pcb",
        "export",
        "pdf",
        "--mode-single",
        "--black-and-white",
        "--sketch-pads-on-fab-layers",
        "--layers",
        layers,
        "--output",
        str(output),
    ]
    if mirror:
        command.append("--mirror")
    command.append(str(board_file))
    return tuple(command)


def _write_identity_bom(
    path: Path,
    identities: ManufacturingIdentityRegistry,
) -> None:
    import csv

    rows = tuple(
        item for item in identities.identities if item.kind is ManufacturingIdentityKind.BOM_ROW
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("Ref", "Value", "Footprint", "StableId"))
        for item in rows:
            keys = dict(key.split("=", 1) for key in item.source_keys if "=" in key)
            writer.writerow(
                (
                    keys.get("reference", ""),
                    keys.get("value", ""),
                    keys.get("library_id", ""),
                    item.stable_id,
                )
            )


def _write_stackup_notes(
    path: Path,
    profile: FabricationElectricalProfile,
) -> None:
    lines = [
        f"# Stack-up and process profile: {profile.profile_id}",
        "",
        f"- Board thickness: {profile.board_thickness_mm:g} mm",
        f"- Base material: {profile.base_material}",
        f"- Material Tg: {profile.material_tg_c:g} °C",
        f"- Surface finish: {profile.surface_finish}",
        f"- Insulation basis: {profile.insulation_basis}",
        "",
        "| Sequence | Layer | Kind | Material | Thickness | Copper weight |",
        "| ---: | --- | --- | --- | ---: | ---: |",
    ]
    for layer in profile.stackup:
        copper = f"{layer.copper_weight_oz:g} oz" if layer.copper_weight_oz is not None else "n/a"
        lines.append(
            f"| {layer.sequence} | {layer.layer_id} | {layer.kind.value} | "
            f"{layer.material} | {layer.thickness_um:g} µm | {copper} |"
        )
    lines.extend(
        (
            "",
            "This selected profile is a design requirement. The fabricator "
            "must confirm its achievable process and tolerances.",
            "",
        )
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _validate_manufacturing_artifact(
    role: ManufacturingArtifactRole,
    source: Path,
    payload: bytes,
) -> None:
    if not payload:
        raise ValueError(f"manufacturing artifact is empty: {source}")
    text = payload[:8192].decode("utf-8", errors="replace")
    if role in {
        ManufacturingArtifactRole.GERBER,
        ManufacturingArtifactRole.DRILL_MAP,
        ManufacturingArtifactRole.PASTE,
    } and not any(marker in text for marker in ("G04", "%FS", "%TF.")):
        raise ValueError(f"{role.value} artifact is not recognizable Gerber: {source}")
    if role is ManufacturingArtifactRole.DRILL and "M48" not in text:
        raise ValueError(f"drill artifact is not recognizable Excellon: {source}")
    if role is ManufacturingArtifactRole.NETLIST and not any(
        marker in text for marker in ("IPC-D-356", "P  JOB", "C  ")
    ):
        raise ValueError(f"netlist artifact is not recognizable IPC-D-356: {source}")
    if role in {
        ManufacturingArtifactRole.FABRICATION_DRAWING,
        ManufacturingArtifactRole.ASSEMBLY_DRAWING_FRONT,
        ManufacturingArtifactRole.ASSEMBLY_DRAWING_BACK,
    } and not payload.startswith(b"%PDF"):
        raise ValueError(f"{role.value} artifact is not a PDF: {source}")
    if role in {
        ManufacturingArtifactRole.BOM,
        ManufacturingArtifactRole.PLACEMENT,
    } and ("," not in text or "ref" not in text.casefold()):
        raise ValueError(f"{role.value} artifact is not recognizable CSV: {source}")
    if role is ManufacturingArtifactRole.INTERACTIVE_BOM and "<html" not in text.casefold():
        raise ValueError(f"interactive BOM artifact is not self-contained HTML: {source}")
