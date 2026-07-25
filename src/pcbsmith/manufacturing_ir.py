"""Typed manufacturing, assembly, DFM/DFT, and release authority."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel


class StackupLayerKind(StrEnum):
    COPPER = "copper"
    DIELECTRIC = "dielectric"
    SOLDER_MASK = "solder_mask"
    SILKSCREEN = "silkscreen"


class StackupLayer(SemanticIrModel):
    layer_id: str
    sequence: int = Field(ge=0)
    kind: StackupLayerKind
    material: str
    thickness_um: float = Field(gt=0)
    copper_weight_oz: float | None = Field(default=None, gt=0)
    dielectric_constant: float | None = Field(default=None, gt=0)
    loss_tangent: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def layer_is_coherent(self) -> Self:
        require_identity(self.layer_id, "layer_id")
        require_identity(self.material, "material")
        if self.kind is StackupLayerKind.COPPER:
            if self.copper_weight_oz is None:
                raise ValueError("copper stack-up layer requires copper weight")
            if self.dielectric_constant is not None or self.loss_tangent is not None:
                raise ValueError("copper layer cannot declare dielectric properties")
        elif self.copper_weight_oz is not None:
            raise ValueError("only copper layers may declare copper weight")
        return self


class ImpedanceRequirement(SemanticIrModel):
    interface_id: str
    mode: Literal["single_ended", "differential"]
    target_ohm: float = Field(gt=0)
    tolerance_percent: float = Field(gt=0, le=100)
    reference_layer_ids: tuple[str, ...] = Field(min_length=1)
    coupon_required: bool

    @model_validator(mode="after")
    def requirement_is_canonical(self) -> Self:
        require_identity(self.interface_id, "interface_id")
        layers = tuple(sorted(self.reference_layer_ids))
        if len(layers) != len(set(layers)):
            raise ValueError("impedance reference layers must be unique")
        for layer in layers:
            require_identity(layer, "reference_layer_id")
        object.__setattr__(self, "reference_layer_ids", layers)
        return self


class Ipc2152Context(SemanticIrModel):
    authority_id: str
    ambient_c: float
    allowed_temperature_rise_c: float = Field(gt=0)
    copper_environment: Literal["external", "internal", "mixed"]
    current_waveform: Literal["dc", "rms", "pulsed", "mixed"]
    duty_cycle: float = Field(gt=0, le=1)
    altitude_m: float = Field(ge=0)
    enclosure_context: str
    limitations: tuple[str, ...] = ()

    @model_validator(mode="after")
    def context_is_canonical(self) -> Self:
        require_identity(self.authority_id, "authority_id")
        require_identity(self.enclosure_context, "enclosure_context")
        for limitation in self.limitations:
            require_identity(limitation, "limitation")
        if len(self.limitations) != len(set(self.limitations)):
            raise ValueError("IPC-2152 limitations must be unique")
        object.__setattr__(self, "limitations", tuple(sorted(self.limitations)))
        return self


class FabricationElectricalProfile(SemanticIrModel):
    """Selected process contract; values are requirements, not fab capability."""

    schema_id: Literal["pcbsmith-fabrication-electrical-profile"] = (
        "pcbsmith-fabrication-electrical-profile"
    )
    schema_version: Literal[1] = 1
    profile_id: str
    minimum_trace_width_mm: float = Field(gt=0)
    minimum_copper_clearance_mm: float = Field(gt=0)
    minimum_finished_drill_mm: float = Field(gt=0)
    minimum_annular_ring_mm: float = Field(gt=0)
    minimum_mask_sliver_mm: float = Field(gt=0)
    mask_expansion_mm: float = Field(ge=0)
    paste_area_reduction_percent: float = Field(ge=0, lt=100)
    minimum_milling_tool_diameter_mm: float = Field(gt=0)
    board_thickness_mm: float = Field(gt=0)
    base_material: str
    material_tg_c: float
    surface_finish: str
    insulation_basis: str
    stackup: tuple[StackupLayer, ...] = Field(min_length=3)
    impedance_requirements: tuple[ImpedanceRequirement, ...] = ()
    ipc2152_context: Ipc2152Context
    profile_fingerprint: str

    @model_validator(mode="after")
    def profile_is_complete_and_replay_bound(self) -> Self:
        for name in (
            "profile_id",
            "base_material",
            "surface_finish",
            "insulation_basis",
        ):
            require_identity(getattr(self, name), name)
        stackup = tuple(sorted(self.stackup, key=lambda item: item.sequence))
        if tuple(layer.sequence for layer in stackup) != tuple(range(len(stackup))):
            raise ValueError("stack-up sequence must be contiguous from zero")
        if len({layer.layer_id for layer in stackup}) != len(stackup):
            raise ValueError("stack-up layer identities must be unique")
        if sum(layer.thickness_um for layer in stackup) > self.board_thickness_mm * 1000 * 1.05:
            raise ValueError("declared stack-up exceeds board thickness tolerance")
        impedance = tuple(sorted(self.impedance_requirements, key=lambda item: item.interface_id))
        if len({item.interface_id for item in impedance}) != len(impedance):
            raise ValueError("impedance requirement identities must be unique")
        layer_ids = {layer.layer_id for layer in stackup}
        if any(not set(item.reference_layer_ids).issubset(layer_ids) for item in impedance):
            raise ValueError("impedance requirement references an unknown stack-up layer")
        object.__setattr__(self, "stackup", stackup)
        object.__setattr__(self, "impedance_requirements", impedance)
        require_sha256(self.profile_fingerprint, "profile_fingerprint")
        payload = self.model_dump(mode="json", exclude={"profile_fingerprint"})
        if self.profile_fingerprint != fingerprint(payload):
            raise ValueError("fabrication/electrical profile fingerprint is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> FabricationElectricalProfile:
        values["stackup"] = tuple(sorted(values["stackup"], key=lambda item: item.sequence))
        values["impedance_requirements"] = tuple(
            sorted(
                values.get("impedance_requirements", ()),
                key=lambda item: item.interface_id,
            )
        )
        provisional = cls.model_construct(**values, profile_fingerprint="0" * 64)
        return cls(
            **values,
            profile_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"profile_fingerprint"})
            ),
        )


class CurrentPathElementKind(StrEnum):
    TRACK = "track"
    ZONE_OR_PLANE = "zone_or_plane"
    VIA = "via"
    PAD = "pad"
    NECK_DOWN = "neck_down"
    PARALLEL_SHARING = "parallel_sharing"
    CONNECTOR = "connector"


class CurrentPathCoverageStatus(StrEnum):
    VERIFIED = "verified"
    NOT_APPLICABLE = "not_applicable"
    UNVERIFIED = "unverified"


class CurrentPathCoverage(SemanticIrModel):
    kind: CurrentPathElementKind
    status: CurrentPathCoverageStatus
    rationale: str

    @model_validator(mode="after")
    def rationale_is_present(self) -> Self:
        require_identity(self.rationale, "rationale")
        return self


class CurrentPathElement(SemanticIrModel):
    element_id: str
    kind: CurrentPathElementKind
    source_identity_id: str
    current_a_rms: float = Field(ge=0)
    current_a_peak: float = Field(ge=0)
    duty_cycle: float = Field(gt=0, le=1)
    waveform: Literal["dc", "rms", "pulsed", "mixed"]
    resistance_ohm: float = Field(ge=0)
    voltage_drop_v: float = Field(ge=0)
    power_loss_w: float = Field(ge=0)
    geometry_fingerprint: str
    thermal_context_id: str
    parallel_group_id: str | None = None

    @model_validator(mode="after")
    def element_is_complete(self) -> Self:
        for name in ("element_id", "source_identity_id", "thermal_context_id"):
            require_identity(getattr(self, name), name)
        if self.parallel_group_id is not None:
            require_identity(self.parallel_group_id, "parallel_group_id")
        if self.current_a_peak < self.current_a_rms:
            raise ValueError("peak current cannot be below RMS current")
        require_sha256(self.geometry_fingerprint, "geometry_fingerprint")
        return self


class CurrentPathAuthority(StrEnum):
    VERIFIED = "verified"
    UNVERIFIED = "unverified"


class CurrentPathRecord(SemanticIrModel):
    schema_id: Literal["pcbsmith-current-path-record"] = "pcbsmith-current-path-record"
    schema_version: Literal[1] = 1
    path_id: str
    net_ids: tuple[str, ...] = Field(min_length=1)
    board_sha256: str
    profile_fingerprint: str
    coverages: tuple[CurrentPathCoverage, ...]
    elements: tuple[CurrentPathElement, ...]
    total_voltage_drop_v: float = Field(ge=0)
    total_power_loss_w: float = Field(ge=0)
    authority: CurrentPathAuthority
    blockers: tuple[str, ...]
    record_fingerprint: str

    @model_validator(mode="after")
    def record_is_complete_and_replay_bound(self) -> Self:
        require_identity(self.path_id, "path_id")
        require_sha256(self.board_sha256, "board_sha256")
        require_sha256(self.profile_fingerprint, "profile_fingerprint")
        nets = tuple(sorted(self.net_ids))
        if len(nets) != len(set(nets)):
            raise ValueError("current-path net identities must be unique")
        coverages = tuple(sorted(self.coverages, key=lambda item: item.kind.value))
        if {item.kind for item in coverages} != set(CurrentPathElementKind):
            raise ValueError("current-path record must classify every conductor kind")
        elements = tuple(sorted(self.elements, key=lambda item: item.element_id))
        if len({item.element_id for item in elements}) != len(elements):
            raise ValueError("current-path element identities must be unique")
        blockers: list[str] = []
        for coverage in coverages:
            matching = tuple(item for item in elements if item.kind is coverage.kind)
            if coverage.status is CurrentPathCoverageStatus.VERIFIED and not matching:
                blockers.append(f"{coverage.kind.value}: verified coverage has no elements")
            if coverage.status is CurrentPathCoverageStatus.NOT_APPLICABLE and matching:
                blockers.append(f"{coverage.kind.value}: not-applicable coverage has elements")
            if coverage.status is CurrentPathCoverageStatus.UNVERIFIED:
                blockers.append(f"{coverage.kind.value}: conductor geometry is unverified")
        calculated_drop = sum(item.voltage_drop_v for item in elements)
        calculated_loss = sum(item.power_loss_w for item in elements)
        if abs(calculated_drop - self.total_voltage_drop_v) > 1e-9:
            raise ValueError("current-path total voltage drop is stale")
        if abs(calculated_loss - self.total_power_loss_w) > 1e-9:
            raise ValueError("current-path total power loss is stale")
        expected_blockers = tuple(blockers)
        if self.blockers != expected_blockers:
            raise ValueError("current-path blockers are stale")
        expected_authority = (
            CurrentPathAuthority.VERIFIED if not blockers else CurrentPathAuthority.UNVERIFIED
        )
        if self.authority is not expected_authority:
            raise ValueError("current-path authority is stale")
        object.__setattr__(self, "net_ids", nets)
        object.__setattr__(self, "coverages", coverages)
        object.__setattr__(self, "elements", elements)
        require_sha256(self.record_fingerprint, "record_fingerprint")
        payload = self.model_dump(mode="json", exclude={"record_fingerprint"})
        if self.record_fingerprint != fingerprint(payload):
            raise ValueError("current-path record fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        path_id: str,
        net_ids: tuple[str, ...],
        board_sha256: str,
        profile_fingerprint: str,
        coverages: tuple[CurrentPathCoverage, ...],
        elements: tuple[CurrentPathElement, ...],
    ) -> CurrentPathRecord:
        canonical_coverages = tuple(sorted(coverages, key=lambda item: item.kind.value))
        canonical_elements = tuple(sorted(elements, key=lambda item: item.element_id))
        blockers: list[str] = []
        for coverage in canonical_coverages:
            matching = tuple(item for item in canonical_elements if item.kind is coverage.kind)
            if coverage.status is CurrentPathCoverageStatus.VERIFIED and not matching:
                blockers.append(f"{coverage.kind.value}: verified coverage has no elements")
            if coverage.status is CurrentPathCoverageStatus.NOT_APPLICABLE and matching:
                blockers.append(f"{coverage.kind.value}: not-applicable coverage has elements")
            if coverage.status is CurrentPathCoverageStatus.UNVERIFIED:
                blockers.append(f"{coverage.kind.value}: conductor geometry is unverified")
        fields: dict[str, Any] = {
            "path_id": path_id,
            "net_ids": tuple(sorted(net_ids)),
            "board_sha256": board_sha256,
            "profile_fingerprint": profile_fingerprint,
            "coverages": canonical_coverages,
            "elements": canonical_elements,
            "total_voltage_drop_v": sum(item.voltage_drop_v for item in canonical_elements),
            "total_power_loss_w": sum(item.power_loss_w for item in canonical_elements),
            "authority": (
                CurrentPathAuthority.VERIFIED if not blockers else CurrentPathAuthority.UNVERIFIED
            ),
            "blockers": tuple(blockers),
        }
        provisional = cls.model_construct(**fields, record_fingerprint="0" * 64)
        return cls(
            **fields,
            record_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"record_fingerprint"})
            ),
        )


class ManufacturingIdentityKind(StrEnum):
    FOOTPRINT = "footprint"
    PAD = "pad"
    HOLE = "hole"
    APERTURE = "aperture"
    COMPONENT = "component"
    BOM_ROW = "bom_row"
    PLACEMENT_ROW = "placement_row"


class ManufacturingIdentity(SemanticIrModel):
    kind: ManufacturingIdentityKind
    stable_id: str
    board_sha256: str
    source_keys: tuple[str, ...] = Field(min_length=1)
    identity_fingerprint: str

    @model_validator(mode="after")
    def identity_is_stable(self) -> Self:
        require_identity(self.stable_id, "stable_id")
        require_sha256(self.board_sha256, "board_sha256")
        keys = tuple(sorted(self.source_keys))
        if len(keys) != len(set(keys)):
            raise ValueError("manufacturing identity source keys must be unique")
        for key in keys:
            require_identity(key, "source_key")
        object.__setattr__(self, "source_keys", keys)
        require_sha256(self.identity_fingerprint, "identity_fingerprint")
        payload = self.model_dump(mode="json", exclude={"identity_fingerprint"})
        if self.identity_fingerprint != fingerprint(payload):
            raise ValueError("manufacturing identity fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        kind: ManufacturingIdentityKind,
        stable_id: str,
        board_sha256: str,
        source_keys: tuple[str, ...],
    ) -> ManufacturingIdentity:
        fields: dict[str, Any] = {
            "kind": kind,
            "stable_id": stable_id,
            "board_sha256": board_sha256,
            "source_keys": tuple(sorted(source_keys)),
        }
        provisional = cls.model_construct(**fields, identity_fingerprint="0" * 64)
        return cls(
            **fields,
            identity_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"identity_fingerprint"})
            ),
        )


class ManufacturingIdentityRegistry(SemanticIrModel):
    board_sha256: str
    identities: tuple[ManufacturingIdentity, ...] = Field(min_length=1)
    registry_fingerprint: str

    @model_validator(mode="after")
    def registry_is_exact(self) -> Self:
        require_sha256(self.board_sha256, "board_sha256")
        identities = tuple(
            sorted(self.identities, key=lambda item: (item.kind.value, item.stable_id))
        )
        keys = {(item.kind, item.stable_id) for item in identities}
        if len(keys) != len(identities):
            raise ValueError("manufacturing identities must be unique by kind and ID")
        if any(item.board_sha256 != self.board_sha256 for item in identities):
            raise ValueError("manufacturing identities target different boards")
        object.__setattr__(self, "identities", identities)
        require_sha256(self.registry_fingerprint, "registry_fingerprint")
        payload = self.model_dump(mode="json", exclude={"registry_fingerprint"})
        if self.registry_fingerprint != fingerprint(payload):
            raise ValueError("manufacturing identity registry fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        board_sha256: str,
        identities: tuple[ManufacturingIdentity, ...],
    ) -> ManufacturingIdentityRegistry:
        canonical = tuple(sorted(identities, key=lambda item: (item.kind.value, item.stable_id)))
        fields: dict[str, Any] = {
            "board_sha256": board_sha256,
            "identities": canonical,
        }
        provisional = cls.model_construct(**fields, registry_fingerprint="0" * 64)
        return cls(
            **fields,
            registry_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"registry_fingerprint"})
            ),
        )


class DfmDftCategory(StrEnum):
    COURTYARD_PROCESS_CLEARANCE = "courtyard_process_clearance"
    PASTE_STRATEGY = "paste_strategy"
    EXPOSED_PAD_THERMAL_VIAS = "exposed_pad_thermal_vias"
    FIDUCIALS = "fiducials"
    TOOLING = "tooling"
    TEST_POINTS = "test_points"
    PROBE_ACCESS = "probe_access"
    POLARITY_ORIENTATION = "polarity_orientation"
    ASSEMBLY_SEQUENCE = "assembly_sequence"
    REWORK_ACCESS = "rework_access"


class DfmDftDisposition(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NOT_APPLICABLE = "not_applicable"
    UNVERIFIED = "unverified"


class DfmDftEvidence(SemanticIrModel):
    category: DfmDftCategory
    disposition: DfmDftDisposition
    producer_id: str
    tool_version: str
    exact_input_sha256s: tuple[str, ...] = Field(min_length=1)
    evaluated_object_count: int = Field(ge=0)
    findings: tuple[str, ...] = ()
    evidence_sha256: str

    @model_validator(mode="after")
    def evidence_is_complete(self) -> Self:
        require_identity(self.producer_id, "producer_id")
        require_identity(self.tool_version, "tool_version")
        for digest in self.exact_input_sha256s:
            require_sha256(digest, "exact_input_sha256")
        if len(self.exact_input_sha256s) != len(set(self.exact_input_sha256s)):
            raise ValueError("DFM/DFT exact inputs must be unique")
        if (
            self.disposition in {DfmDftDisposition.PASS, DfmDftDisposition.FAIL}
            and self.evaluated_object_count < 1
        ):
            raise ValueError("executed DFM/DFT evidence must evaluate an object")
        if self.disposition is DfmDftDisposition.NOT_APPLICABLE and not self.findings:
            raise ValueError("not-applicable DFM/DFT evidence requires rationale")
        require_sha256(self.evidence_sha256, "evidence_sha256")
        return self


class DfmDftReport(SemanticIrModel):
    board_sha256: str
    evidence: tuple[DfmDftEvidence, ...]
    ready: bool
    blockers: tuple[str, ...]
    report_fingerprint: str

    @model_validator(mode="after")
    def report_is_complete(self) -> Self:
        require_sha256(self.board_sha256, "board_sha256")
        evidence = tuple(sorted(self.evidence, key=lambda item: item.category.value))
        if {item.category for item in evidence} != set(DfmDftCategory):
            raise ValueError("DFM/DFT report must classify every required category")
        blockers = tuple(
            f"{item.category.value}: {item.disposition.value}"
            for item in evidence
            if item.disposition in {DfmDftDisposition.FAIL, DfmDftDisposition.UNVERIFIED}
        )
        if self.blockers != blockers or self.ready != (not blockers):
            raise ValueError("DFM/DFT report disposition is stale")
        object.__setattr__(self, "evidence", evidence)
        require_sha256(self.report_fingerprint, "report_fingerprint")
        payload = self.model_dump(mode="json", exclude={"report_fingerprint"})
        if self.report_fingerprint != fingerprint(payload):
            raise ValueError("DFM/DFT report fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        board_sha256: str,
        evidence: tuple[DfmDftEvidence, ...],
    ) -> DfmDftReport:
        canonical = tuple(sorted(evidence, key=lambda item: item.category.value))
        blockers = tuple(
            f"{item.category.value}: {item.disposition.value}"
            for item in canonical
            if item.disposition in {DfmDftDisposition.FAIL, DfmDftDisposition.UNVERIFIED}
        )
        fields: dict[str, Any] = {
            "board_sha256": board_sha256,
            "evidence": canonical,
            "ready": not blockers,
            "blockers": blockers,
        }
        provisional = cls.model_construct(**fields, report_fingerprint="0" * 64)
        return cls(
            **fields,
            report_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"report_fingerprint"})
            ),
        )


class ManufacturingApprovalRole(StrEnum):
    HUMAN_ENGINEERING = "human_engineering"
    FABRICATOR = "fabricator"
    ASSEMBLER = "assembler"


class ManufacturingApproval(SemanticIrModel):
    role: ManufacturingApprovalRole
    approver_id: str
    package_sha256: str
    decision: Literal["approved", "rejected"]
    conditions: tuple[str, ...] = ()
    approval_record_sha256: str

    @model_validator(mode="after")
    def approval_is_exact(self) -> Self:
        require_identity(self.approver_id, "approver_id")
        require_sha256(self.package_sha256, "package_sha256")
        require_sha256(self.approval_record_sha256, "approval_record_sha256")
        return self


class ManufacturingReleaseStatus(StrEnum):
    BLOCKED = "blocked"
    PACKAGE_GENERATED = "package_generated"
    FABRICATION_READY = "fabrication_ready"
    ASSEMBLY_READY = "assembly_ready"


def derive_release_status(
    approvals: tuple[ManufacturingApproval, ...],
) -> ManufacturingReleaseStatus:
    approved = {item.role for item in approvals if item.decision == "approved"}
    if ManufacturingApprovalRole.HUMAN_ENGINEERING not in approved:
        return ManufacturingReleaseStatus.PACKAGE_GENERATED
    if ManufacturingApprovalRole.FABRICATOR not in approved:
        return ManufacturingReleaseStatus.PACKAGE_GENERATED
    if ManufacturingApprovalRole.ASSEMBLER not in approved:
        return ManufacturingReleaseStatus.FABRICATION_READY
    return ManufacturingReleaseStatus.ASSEMBLY_READY
