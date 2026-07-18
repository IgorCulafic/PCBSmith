"""Replay-bound aggregate exact checking over one materialized board.

This is deliberately a small predecessor to a project-specific R5 acceptance
checker.  The two in-process checks are recomputed on replay.  Checks executed
by another process are retained as exact, input-bound artifact records; no
runtime callbacks or callables are serialized.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from enum import StrEnum
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from pcbsmith.circuit.models import CircuitObject, KiCadReport, SimulationReport
from pcbsmith.kicad.board import (
    BoardGenerationError,
    BoardLayout,
    BoardNetlist,
    canonical_kicad_netlist_xml_text,
    parse_board_netlist,
)
from pcbsmith.kicad.board_serialization import (
    board_layout_snapshot_fingerprint,
    board_netlist_snapshot_fingerprint,
    canonical_board_layout_snapshot_json,
    canonical_board_netlist_snapshot_json,
    parse_canonical_board_layout_snapshot,
    parse_canonical_board_netlist_snapshot,
)
from pcbsmith.kicad.design_checks import DesignChecksSpec, run_design_checks
from pcbsmith.kicad.negotiated_board import ExactRouteCheckResult
from pcbsmith.kicad.placement_readback import PlacementKiCadSaveRoundtripAuthority
from pcbsmith.kicad.reader_schematic import compare_netlists
from pcbsmith.kicad.validate import (
    canonical_kicad_erc_json_text,
    kicad_erc_findings_from_json_text,
)
from pcbsmith.kicad.virtual_drc import run_virtual_drc
from pcbsmith.rule_profiles import PcbRuleProfile
from pcbsmith.simulation.ngspice_buck import parse_ngspice_meas_results
from pcbsmith.simulation.ngspice_thermometer import (
    MODEL_NOTE as THERMOMETER_SIMULATION_MODEL_NOTE,
)
from pcbsmith.simulation.ngspice_thermometer import (
    SUPPORTED_TOPOLOGY_ID as THERMOMETER_SIMULATION_TOPOLOGY_ID,
)
from pcbsmith.simulation.ngspice_thermometer import (
    evaluate_thermometer_measurements,
    render_thermometer_netlist,
)

KICAD_SAVE_ROUNDTRIP_ADAPTER_ID: Literal[
    "pcbsmith.kicad.placement-save-roundtrip-adapter"
] = "pcbsmith.kicad.placement-save-roundtrip-adapter"

READER_NETLIST_EQUALITY_ADAPTER_ID: Literal[
    "pcbsmith.kicad.reader-netlist-equality-adapter"
] = "pcbsmith.kicad.reader-netlist-equality-adapter"

THERMOMETER_NGSPICE_ADAPTER_ID: Literal[
    "pcbsmith.simulation.thermometer-ngspice-adapter"
] = "pcbsmith.simulation.thermometer-ngspice-adapter"

THERMOMETER_LED_BRANCH_MODEL_SCOPE_ID: Literal[
    "pcbsmith.simulation.thermometer-led-branches-only-v1"
] = "pcbsmith.simulation.thermometer-led-branches-only-v1"


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _require_identity(value: str, field_name: str) -> str:
    if not value or value.strip() != value:
        raise ValueError(f"{field_name} must be a non-empty trimmed identity")
    return value


def _require_sha256(value: str, field_name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256")
    return value


def _canonical_json_text(value: str, field_name: str) -> str:
    try:
        loaded = json.loads(
            value,
            parse_constant=lambda item: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON value {item}")
            ),
        )
    except (json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"{field_name} must contain valid JSON: {error}") from error
    if value != _canonical_json(loaded):
        raise ValueError(f"{field_name} must be canonical JSON")
    return value


class AggregateCheckStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    UNVERIFIED = "unverified"
    NOT_APPLICABLE = "not_applicable"


class AggregateSubcheckKind(StrEnum):
    VIRTUAL_DRC = "virtual_drc"
    DESIGN_CHECKS = "design_checks"
    EXTERNAL_ARTIFACT = "external_artifact"


class AggregateSubcheckApplicability(StrEnum):
    REQUIRED = "required"
    NOT_APPLICABLE = "not_applicable"


class AggregateSubcheckRequirement(BaseModel):
    """One versioned check required (or explicitly excluded) by policy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    subcheck_id: str = Field(min_length=1)
    subcheck_version: str = Field(min_length=1)
    kind: AggregateSubcheckKind
    applicability: AggregateSubcheckApplicability = AggregateSubcheckApplicability.REQUIRED
    producer_id: str | None = None

    @model_validator(mode="after")
    def identities_are_trimmed(self) -> Self:
        _require_identity(self.subcheck_id, "subcheck_id")
        _require_identity(self.subcheck_version, "subcheck_version")
        if self.producer_id is not None:
            _require_identity(self.producer_id, "producer_id")
            if self.kind is not AggregateSubcheckKind.EXTERNAL_ARTIFACT:
                raise ValueError("only external aggregate requirements may name a producer")
        if (
            self.kind in {AggregateSubcheckKind.VIRTUAL_DRC, AggregateSubcheckKind.DESIGN_CHECKS}
            and self.applicability is not AggregateSubcheckApplicability.REQUIRED
        ):
            raise ValueError("in-process aggregate checks cannot be declared not applicable")
        return self


_SPEC_ADAPTER = TypeAdapter(DesignChecksSpec)


class StableAggregateExactCheckerPolicy(BaseModel):
    """Immutable, complete policy for the narrow aggregate checker."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["pcbsmith-stable-aggregate-exact-checker-policy"] = (
        "pcbsmith-stable-aggregate-exact-checker-policy"
    )
    schema_version: Literal[1] = 1
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    profile: PcbRuleProfile
    design_checks_spec: DesignChecksSpec
    subchecks: tuple[AggregateSubcheckRequirement, ...] = Field(min_length=2)
    policy_fingerprint: str

    def fingerprint_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"policy_fingerprint"})

    @model_validator(mode="after")
    def policy_is_complete_and_fresh(self) -> Self:
        _require_identity(self.policy_id, "policy_id")
        _require_identity(self.policy_version, "policy_version")
        _require_sha256(self.policy_fingerprint, "policy_fingerprint")
        keys = tuple((item.subcheck_id, item.subcheck_version) for item in self.subchecks)
        if len(keys) != len(set(keys)):
            raise ValueError("aggregate policy subcheck identities must be unique")
        canonical = tuple(
            sorted(
                self.subchecks,
                key=lambda item: (item.subcheck_id, item.subcheck_version),
            )
        )
        if canonical != self.subchecks:
            raise ValueError("aggregate policy subchecks must be canonically ordered")
        kinds = tuple(item.kind for item in self.subchecks)
        if kinds.count(AggregateSubcheckKind.VIRTUAL_DRC) != 1:
            raise ValueError("aggregate policy requires exactly one virtual DRC subcheck")
        if kinds.count(AggregateSubcheckKind.DESIGN_CHECKS) != 1:
            raise ValueError("aggregate policy requires exactly one design-check subcheck")
        if self.policy_fingerprint != _fingerprint(self.fingerprint_payload()):
            raise ValueError("aggregate policy fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        policy_id: str,
        policy_version: str,
        profile: PcbRuleProfile,
        design_checks_spec: DesignChecksSpec,
        subchecks: tuple[AggregateSubcheckRequirement, ...],
    ) -> Self:
        canonical = tuple(
            sorted(
                subchecks,
                key=lambda item: (item.subcheck_id, item.subcheck_version),
            )
        )
        fields: dict[str, Any] = {
            "policy_id": policy_id,
            "policy_version": policy_version,
            "profile": profile,
            "design_checks_spec": design_checks_spec,
            "subchecks": canonical,
        }
        provisional = cls.model_construct(**fields, policy_fingerprint="0" * 64)
        return cls(**fields, policy_fingerprint=_fingerprint(provisional.fingerprint_payload()))


class ExternalSubcheckFinding(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    finding_id: str = Field(min_length=1)
    message: str = Field(min_length=1)
    finding_fingerprint: str

    @model_validator(mode="after")
    def finding_is_fresh(self) -> Self:
        _require_identity(self.finding_id, "finding_id")
        _require_identity(self.message, "message")
        _require_sha256(self.finding_fingerprint, "finding_fingerprint")
        expected = _fingerprint({"finding_id": self.finding_id, "message": self.message})
        if self.finding_fingerprint != expected:
            raise ValueError("external subcheck finding fingerprint is stale")
        return self

    @classmethod
    def build(cls, finding_id: str, message: str) -> Self:
        return cls(
            finding_id=finding_id,
            message=message,
            finding_fingerprint=_fingerprint({"finding_id": finding_id, "message": message}),
        )


class ExternalArtifactSubcheckEvidence(BaseModel):
    """Complete result record for a check that ran outside this process."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_kind: Literal["external_artifact"] = "external_artifact"
    subcheck_id: str
    subcheck_version: str
    status: AggregateCheckStatus
    findings: tuple[ExternalSubcheckFinding, ...] = ()
    layout_snapshot_fingerprint: str
    netlist_snapshot_fingerprint: str
    policy_fingerprint: str
    source_artifact_id: str
    source_artifact_sha256: str
    tool_id: str
    tool_version: str
    config_json: str
    config_sha256: str
    result_identity: str
    result_json: str
    result_sha256: str

    def result_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"result_json", "result_sha256"})

    @model_validator(mode="after")
    def external_result_is_complete_and_fresh(self) -> Self:
        for field_name in (
            "subcheck_id",
            "subcheck_version",
            "source_artifact_id",
            "tool_id",
            "tool_version",
            "result_identity",
        ):
            _require_identity(getattr(self, field_name), field_name)
        for field_name in (
            "layout_snapshot_fingerprint",
            "netlist_snapshot_fingerprint",
            "policy_fingerprint",
            "source_artifact_sha256",
            "config_sha256",
            "result_sha256",
        ):
            _require_sha256(getattr(self, field_name), field_name)
        _canonical_json_text(self.config_json, "config_json")
        if self.config_sha256 != hashlib.sha256(self.config_json.encode("utf-8")).hexdigest():
            raise ValueError("external subcheck config checksum is stale")
        canonical_findings = tuple(sorted(self.findings, key=lambda item: item.finding_fingerprint))
        finding_ids = {item.finding_fingerprint for item in self.findings}
        if canonical_findings != self.findings or len(finding_ids) != len(self.findings):
            raise ValueError("external subcheck findings must be canonical and unique")
        if len({item.finding_id for item in self.findings}) != len(self.findings):
            raise ValueError("external subcheck finding identities must be unique")
        if self.status in {AggregateCheckStatus.FAIL, AggregateCheckStatus.UNVERIFIED}:
            if not self.findings:
                raise ValueError("failed or unverified external evidence requires findings")
        elif self.findings:
            raise ValueError("passing or inapplicable external evidence cannot retain findings")
        expected_json = _canonical_json(self.result_payload())
        if self.result_json != expected_json:
            raise ValueError("external subcheck result JSON is noncanonical or stale")
        if self.result_sha256 != hashlib.sha256(expected_json.encode("utf-8")).hexdigest():
            raise ValueError("external subcheck result checksum is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        subcheck_id: str,
        subcheck_version: str,
        status: AggregateCheckStatus,
        findings: tuple[ExternalSubcheckFinding, ...],
        layout_snapshot_fingerprint: str,
        netlist_snapshot_fingerprint: str,
        policy_fingerprint: str,
        source_artifact_id: str,
        source_artifact_sha256: str,
        tool_id: str,
        tool_version: str,
        config: Any,
        result_identity: str,
    ) -> Self:
        config_json = _canonical_json(config)
        canonical_findings = tuple(sorted(findings, key=lambda item: item.finding_fingerprint))
        fields: dict[str, Any] = {
            "subcheck_id": subcheck_id,
            "subcheck_version": subcheck_version,
            "status": status,
            "findings": canonical_findings,
            "layout_snapshot_fingerprint": layout_snapshot_fingerprint,
            "netlist_snapshot_fingerprint": netlist_snapshot_fingerprint,
            "policy_fingerprint": policy_fingerprint,
            "source_artifact_id": source_artifact_id,
            "source_artifact_sha256": source_artifact_sha256,
            "tool_id": tool_id,
            "tool_version": tool_version,
            "config_json": config_json,
            "config_sha256": hashlib.sha256(config_json.encode("utf-8")).hexdigest(),
            "result_identity": result_identity,
        }
        provisional = cls.model_construct(**fields, result_json="{}", result_sha256="0" * 64)
        result_json = _canonical_json(provisional.result_payload())
        return cls(
            **fields,
            result_json=result_json,
            result_sha256=hashlib.sha256(result_json.encode("utf-8")).hexdigest(),
        )


def _derive_kicad_roundtrip_result(
    authority: PlacementKiCadSaveRoundtripAuthority,
) -> tuple[AggregateCheckStatus, tuple[ExternalSubcheckFinding, ...]]:
    findings: list[ExternalSubcheckFinding] = []
    if authority.drc_status != "passed":
        findings.append(
            ExternalSubcheckFinding.build(
                "kicad-drc-status",
                f"KiCad DRC status is {authority.drc_status!r}, expected 'passed'",
            )
        )
    if authority.drc_findings:
        canonical_findings = tuple(sorted(authority.drc_findings))
        findings.append(
            ExternalSubcheckFinding.build(
                "kicad-drc-findings",
                "KiCad DRC retained blocking findings: " + _canonical_json(canonical_findings),
            )
        )
    if authority.initial_snapshot != authority.saved_snapshot:
        findings.append(
            ExternalSubcheckFinding.build(
                "kicad-readback-mismatch",
                "KiCad save changed the retained semantic readback snapshot",
            )
        )
    if authority.saved_board_sha256 != authority.repeated_saved_board_sha256:
        findings.append(
            ExternalSubcheckFinding.build(
                "kicad-repeat-save-mismatch",
                "Repeated KiCad saves are not byte-identical",
            )
        )
    if findings:
        return (
            AggregateCheckStatus.FAIL,
            tuple(sorted(findings, key=lambda item: item.finding_fingerprint)),
        )
    if not authority.require_drc_pass:
        finding = ExternalSubcheckFinding.build(
            "kicad-required-gate-disabled",
            "The retained KiCad authority did not require its DRC pass gate",
        )
        return AggregateCheckStatus.UNVERIFIED, (finding,)
    return AggregateCheckStatus.PASS, ()


class KiCadSaveRoundtripSubcheckEvidence(BaseModel):
    """Specialized aggregate evidence derived from the complete R5 KiCad authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_kind: Literal["kicad_save_roundtrip"] = "kicad_save_roundtrip"
    producer_id: Literal["pcbsmith.kicad.placement-save-roundtrip-adapter"] = (
        KICAD_SAVE_ROUNDTRIP_ADAPTER_ID
    )
    adapter_version: Literal[1] = 1
    subcheck_id: str
    subcheck_version: str
    layout_snapshot_fingerprint: str
    netlist_snapshot_fingerprint: str
    policy_fingerprint: str
    roundtrip_authority: PlacementKiCadSaveRoundtripAuthority
    status: AggregateCheckStatus
    findings: tuple[ExternalSubcheckFinding, ...]
    evidence_fingerprint: str

    def fingerprint_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"evidence_fingerprint"})

    @model_validator(mode="after")
    def adapter_result_replays_exactly(self) -> Self:
        _require_identity(self.subcheck_id, "subcheck_id")
        _require_identity(self.subcheck_version, "subcheck_version")
        for field_name in (
            "layout_snapshot_fingerprint",
            "netlist_snapshot_fingerprint",
            "policy_fingerprint",
            "evidence_fingerprint",
        ):
            _require_sha256(getattr(self, field_name), field_name)
        authority = PlacementKiCadSaveRoundtripAuthority.model_validate_json(
            self.roundtrip_authority.model_dump_json()
        )
        if authority != self.roundtrip_authority:
            raise ValueError("KiCad roundtrip authority failed exact reconstruction")
        serialization = authority.serialization_authority
        if self.layout_snapshot_fingerprint != board_layout_snapshot_fingerprint(
            serialization.final_layout_snapshot_json
        ):
            raise ValueError("KiCad roundtrip adapter layout binding is stale")
        if self.netlist_snapshot_fingerprint != board_netlist_snapshot_fingerprint(
            serialization.source_netlist_snapshot_json
        ):
            raise ValueError("KiCad roundtrip adapter netlist binding is stale")
        expected_status, expected_findings = _derive_kicad_roundtrip_result(authority)
        if self.status != expected_status or self.findings != expected_findings:
            raise ValueError("KiCad roundtrip adapter status or findings differ from replay")
        if self.evidence_fingerprint != _fingerprint(self.fingerprint_payload()):
            raise ValueError("KiCad roundtrip adapter evidence fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        subcheck_id: str,
        subcheck_version: str,
        layout: BoardLayout,
        netlist: BoardNetlist,
        policy: StableAggregateExactCheckerPolicy,
        roundtrip_authority: PlacementKiCadSaveRoundtripAuthority,
    ) -> Self:
        retained_authority = PlacementKiCadSaveRoundtripAuthority.model_validate_json(
            roundtrip_authority.model_dump_json()
        )
        layout_json = canonical_board_layout_snapshot_json(layout)
        netlist_json = canonical_board_netlist_snapshot_json(netlist)
        if retained_authority.serialization_authority.final_layout_snapshot_json != layout_json:
            raise ValueError("KiCad roundtrip authority final layout differs from aggregate layout")
        if (
            retained_authority.serialization_authority.source_netlist_snapshot_json
            != netlist_json
        ):
            raise ValueError("KiCad roundtrip authority netlist differs from aggregate netlist")
        status, findings = _derive_kicad_roundtrip_result(retained_authority)
        fields: dict[str, Any] = {
            "subcheck_id": subcheck_id,
            "subcheck_version": subcheck_version,
            "layout_snapshot_fingerprint": board_layout_snapshot_fingerprint(layout_json),
            "netlist_snapshot_fingerprint": board_netlist_snapshot_fingerprint(netlist_json),
            "policy_fingerprint": policy.policy_fingerprint,
            "roundtrip_authority": retained_authority,
            "status": status,
            "findings": findings,
        }
        provisional = cls.model_construct(**fields, evidence_fingerprint="0" * 64)
        return cls(**fields, evidence_fingerprint=_fingerprint(provisional.fingerprint_payload()))


def _parse_retained_netlist_xml(xml_text: str, field_name: str) -> BoardNetlist:
    try:
        return parse_board_netlist(xml_text)
    except BoardGenerationError as error:
        raise ValueError(
            f"{field_name} does not contain a parseable KiCad netlist: {error}"
        ) from error


def _derive_reader_netlist_equality_result(
    machine_netlist: BoardNetlist,
    reader_netlist: BoardNetlist,
    machine_erc_report: KiCadReport,
    reader_erc_report: KiCadReport,
) -> tuple[
    tuple[str, ...],
    AggregateCheckStatus,
    tuple[ExternalSubcheckFinding, ...],
]:
    comparison_findings = tuple(sorted(compare_netlists(machine_netlist, reader_netlist)))
    findings: list[ExternalSubcheckFinding] = []
    for side, report in (
        ("machine", machine_erc_report),
        ("reader", reader_erc_report),
    ):
        if report.status != "passed":
            findings.append(
                ExternalSubcheckFinding.build(
                    f"{side}-erc-status",
                    f"{side.capitalize()} KiCad ERC status is {report.status!r}, expected 'passed'",
                )
            )
        if report.findings:
            findings.append(
                ExternalSubcheckFinding.build(
                    f"{side}-erc-findings",
                    f"{side.capitalize()} KiCad ERC retained findings: "
                    + _canonical_json(tuple(sorted(report.findings))),
                )
            )
    if comparison_findings:
        findings.append(
            ExternalSubcheckFinding.build(
                "reader-netlist-equality-findings",
                "Machine/reader exported netlists differ: "
                + _canonical_json(comparison_findings),
            )
        )

    reports = (machine_erc_report, reader_erc_report)
    established_failure = bool(comparison_findings) or any(
        report.status == "failed"
        or (report.status == "passed" and bool(report.findings))
        for report in reports
    )
    if established_failure:
        status = AggregateCheckStatus.FAIL
    elif all(
        report.status == "passed" and not report.findings
        for report in reports
    ):
        status = AggregateCheckStatus.PASS
    else:
        status = AggregateCheckStatus.UNVERIFIED
    return (
        comparison_findings,
        status,
        tuple(sorted(findings, key=lambda item: item.finding_fingerprint)),
    )


def _erc_report_from_retained_json(report_json: str) -> KiCadReport:
    canonical = canonical_kicad_erc_json_text(report_json)
    if canonical != report_json:
        raise ValueError("retained ERC report JSON is noncanonical")
    findings = kicad_erc_findings_from_json_text(canonical)
    return KiCadReport(status="failed" if findings else "passed", findings=findings)


class ReaderNetlistEqualitySubcheckEvidence(BaseModel):
    """Replay-derived equality gate over machine and reader KiCad netlists.

    The layout fingerprint is retained only as aggregate context.  This adapter
    establishes schematic-netlist equality and two ERC gates; it does not make
    any board-layout claim.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_kind: Literal["reader_netlist_equality"] = "reader_netlist_equality"
    producer_id: Literal["pcbsmith.kicad.reader-netlist-equality-adapter"] = (
        READER_NETLIST_EQUALITY_ADAPTER_ID
    )
    adapter_version: Literal[1] = 1
    subcheck_id: str
    subcheck_version: str
    layout_snapshot_fingerprint: str
    netlist_snapshot_fingerprint: str
    policy_fingerprint: str
    machine_schematic_artifact_id: str
    machine_schematic_text: str
    machine_schematic_artifact_sha256: str
    reader_schematic_artifact_id: str
    reader_schematic_text: str
    reader_schematic_artifact_sha256: str
    machine_netlist_xml_text: str
    machine_netlist_xml_sha256: str
    reader_netlist_xml_text: str
    reader_netlist_xml_sha256: str
    machine_netlist_snapshot_json: str
    machine_netlist_snapshot_fingerprint: str
    reader_netlist_snapshot_json: str
    reader_netlist_snapshot_fingerprint: str
    tool_id: str
    tool_version: str
    config_identity: str
    config_json: str
    config_sha256: str
    machine_erc_report_json: str
    machine_erc_report_sha256: str
    reader_erc_report_json: str
    reader_erc_report_sha256: str
    machine_erc_report: KiCadReport
    reader_erc_report: KiCadReport
    comparison_findings: tuple[str, ...]
    status: AggregateCheckStatus
    findings: tuple[ExternalSubcheckFinding, ...]
    evidence_fingerprint: str

    def fingerprint_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"evidence_fingerprint"})

    @model_validator(mode="after")
    def adapter_result_replays_exactly(self) -> Self:
        for field_name in (
            "subcheck_id",
            "subcheck_version",
            "machine_schematic_artifact_id",
            "reader_schematic_artifact_id",
            "tool_id",
            "tool_version",
            "config_identity",
        ):
            _require_identity(getattr(self, field_name), field_name)
        for field_name in (
            "layout_snapshot_fingerprint",
            "netlist_snapshot_fingerprint",
            "policy_fingerprint",
            "machine_schematic_artifact_sha256",
            "reader_schematic_artifact_sha256",
            "machine_netlist_xml_sha256",
            "reader_netlist_xml_sha256",
            "machine_netlist_snapshot_fingerprint",
            "reader_netlist_snapshot_fingerprint",
            "config_sha256",
            "machine_erc_report_sha256",
            "reader_erc_report_sha256",
            "evidence_fingerprint",
        ):
            _require_sha256(getattr(self, field_name), field_name)
        if self.machine_schematic_artifact_sha256 != hashlib.sha256(
            self.machine_schematic_text.encode("utf-8")
        ).hexdigest():
            raise ValueError("machine schematic artifact checksum is stale")
        if self.reader_schematic_artifact_sha256 != hashlib.sha256(
            self.reader_schematic_text.encode("utf-8")
        ).hexdigest():
            raise ValueError("reader schematic artifact checksum is stale")
        if self.machine_netlist_xml_sha256 != hashlib.sha256(
            self.machine_netlist_xml_text.encode("utf-8")
        ).hexdigest():
            raise ValueError("machine netlist XML checksum is stale")
        if self.reader_netlist_xml_sha256 != hashlib.sha256(
            self.reader_netlist_xml_text.encode("utf-8")
        ).hexdigest():
            raise ValueError("reader netlist XML checksum is stale")
        _canonical_json_text(self.config_json, "config_json")
        if self.config_sha256 != hashlib.sha256(self.config_json.encode("utf-8")).hexdigest():
            raise ValueError("reader-netlist adapter config checksum is stale")
        for side in ("machine", "reader"):
            report_json = getattr(self, f"{side}_erc_report_json")
            report_sha256 = getattr(self, f"{side}_erc_report_sha256")
            if report_sha256 != hashlib.sha256(report_json.encode("utf-8")).hexdigest():
                raise ValueError(f"{side} ERC report checksum is stale")
            if canonical_kicad_erc_json_text(report_json) != report_json:
                raise ValueError(f"{side} ERC report JSON is noncanonical")

        if canonical_kicad_netlist_xml_text(self.machine_netlist_xml_text) != (
            self.machine_netlist_xml_text
        ):
            raise ValueError("machine netlist XML is noncanonical")
        if canonical_kicad_netlist_xml_text(self.reader_netlist_xml_text) != (
            self.reader_netlist_xml_text
        ):
            raise ValueError("reader netlist XML is noncanonical")
        machine_from_xml = _parse_retained_netlist_xml(
            self.machine_netlist_xml_text, "machine_netlist_xml_text"
        )
        reader_from_xml = _parse_retained_netlist_xml(
            self.reader_netlist_xml_text, "reader_netlist_xml_text"
        )
        machine_from_snapshot = parse_canonical_board_netlist_snapshot(
            self.machine_netlist_snapshot_json
        )
        reader_from_snapshot = parse_canonical_board_netlist_snapshot(
            self.reader_netlist_snapshot_json
        )
        if machine_from_xml != machine_from_snapshot:
            raise ValueError("machine netlist XML differs from its retained parsed snapshot")
        if reader_from_xml != reader_from_snapshot:
            raise ValueError("reader netlist XML differs from its retained parsed snapshot")
        if self.machine_netlist_snapshot_fingerprint != board_netlist_snapshot_fingerprint(
            self.machine_netlist_snapshot_json
        ):
            raise ValueError("machine parsed netlist snapshot fingerprint is stale")
        if self.reader_netlist_snapshot_fingerprint != board_netlist_snapshot_fingerprint(
            self.reader_netlist_snapshot_json
        ):
            raise ValueError("reader parsed netlist snapshot fingerprint is stale")
        if self.netlist_snapshot_fingerprint != self.machine_netlist_snapshot_fingerprint:
            raise ValueError("machine parsed netlist is not bound to the aggregate netlist")

        machine_report = _erc_report_from_retained_json(self.machine_erc_report_json)
        reader_report = _erc_report_from_retained_json(self.reader_erc_report_json)
        if self.machine_erc_report != machine_report or self.reader_erc_report != reader_report:
            raise ValueError("retained ERC status or findings differ from report JSON replay")
        expected_comparison, expected_status, expected_findings = (
            _derive_reader_netlist_equality_result(
                machine_from_xml,
                reader_from_xml,
                machine_report,
                reader_report,
            )
        )
        if self.comparison_findings != expected_comparison:
            raise ValueError("reader-netlist comparison findings differ from replay")
        if self.status != expected_status or self.findings != expected_findings:
            raise ValueError("reader-netlist adapter status or findings differ from replay")
        if self.evidence_fingerprint != _fingerprint(self.fingerprint_payload()):
            raise ValueError("reader-netlist adapter evidence fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        subcheck_id: str,
        subcheck_version: str,
        layout: BoardLayout,
        netlist: BoardNetlist,
        policy: StableAggregateExactCheckerPolicy,
        machine_schematic_artifact_id: str,
        machine_schematic_text: str,
        machine_schematic_artifact_sha256: str,
        reader_schematic_artifact_id: str,
        reader_schematic_text: str,
        reader_schematic_artifact_sha256: str,
        machine_netlist_xml_text: str,
        reader_netlist_xml_text: str,
        tool_id: str,
        tool_version: str,
        config_identity: str,
        config: Any,
        machine_erc_report_json: str,
        reader_erc_report_json: str,
        machine_erc_report: KiCadReport,
        reader_erc_report: KiCadReport,
    ) -> Self:
        retained_machine_xml = canonical_kicad_netlist_xml_text(machine_netlist_xml_text)
        retained_reader_xml = canonical_kicad_netlist_xml_text(reader_netlist_xml_text)
        if retained_machine_xml != machine_netlist_xml_text:
            raise ValueError("machine netlist XML must be canonicalized before adapter build")
        if retained_reader_xml != reader_netlist_xml_text:
            raise ValueError("reader netlist XML must be canonicalized before adapter build")
        machine_parsed = _parse_retained_netlist_xml(
            retained_machine_xml, "machine_netlist_xml_text"
        )
        reader_parsed = _parse_retained_netlist_xml(
            retained_reader_xml, "reader_netlist_xml_text"
        )
        aggregate_netlist_json = canonical_board_netlist_snapshot_json(netlist)
        machine_snapshot_json = canonical_board_netlist_snapshot_json(machine_parsed)
        if machine_parsed != netlist or machine_snapshot_json != aggregate_netlist_json:
            raise ValueError("machine parsed netlist differs from aggregate netlist")
        requirement = next(
            (
                item
                for item in policy.subchecks
                if (item.subcheck_id, item.subcheck_version)
                == (subcheck_id, subcheck_version)
            ),
            None,
        )
        if (
            requirement is None
            or requirement.kind is not AggregateSubcheckKind.EXTERNAL_ARTIFACT
            or requirement.applicability is not AggregateSubcheckApplicability.REQUIRED
            or requirement.producer_id != READER_NETLIST_EQUALITY_ADAPTER_ID
        ):
            raise ValueError(
                "reader-netlist evidence requires its explicit policy producer identity"
            )
        retained_machine_erc_json = canonical_kicad_erc_json_text(machine_erc_report_json)
        retained_reader_erc_json = canonical_kicad_erc_json_text(reader_erc_report_json)
        if retained_machine_erc_json != machine_erc_report_json:
            raise ValueError("machine ERC report JSON must be canonicalized before adapter build")
        if retained_reader_erc_json != reader_erc_report_json:
            raise ValueError("reader ERC report JSON must be canonicalized before adapter build")
        retained_machine_report = _erc_report_from_retained_json(retained_machine_erc_json)
        retained_reader_report = _erc_report_from_retained_json(retained_reader_erc_json)
        supplied_machine_report = KiCadReport.model_validate_json(
            machine_erc_report.model_dump_json()
        )
        supplied_reader_report = KiCadReport.model_validate_json(
            reader_erc_report.model_dump_json()
        )
        for side, supplied, replayed in (
            ("machine", supplied_machine_report, retained_machine_report),
            ("reader", supplied_reader_report, retained_reader_report),
        ):
            if supplied.status != replayed.status or supplied.findings != replayed.findings:
                raise ValueError(f"{side} ERC status or findings differ from report JSON replay")
        comparison, status, findings = _derive_reader_netlist_equality_result(
            machine_parsed,
            reader_parsed,
            retained_machine_report,
            retained_reader_report,
        )
        reader_snapshot_json = canonical_board_netlist_snapshot_json(reader_parsed)
        layout_json = canonical_board_layout_snapshot_json(layout)
        config_json = _canonical_json(config)
        fields: dict[str, Any] = {
            "subcheck_id": subcheck_id,
            "subcheck_version": subcheck_version,
            "layout_snapshot_fingerprint": board_layout_snapshot_fingerprint(layout_json),
            "netlist_snapshot_fingerprint": board_netlist_snapshot_fingerprint(
                aggregate_netlist_json
            ),
            "policy_fingerprint": policy.policy_fingerprint,
            "machine_schematic_artifact_id": machine_schematic_artifact_id,
            "machine_schematic_text": machine_schematic_text,
            "machine_schematic_artifact_sha256": machine_schematic_artifact_sha256,
            "reader_schematic_artifact_id": reader_schematic_artifact_id,
            "reader_schematic_text": reader_schematic_text,
            "reader_schematic_artifact_sha256": reader_schematic_artifact_sha256,
            "machine_netlist_xml_text": retained_machine_xml,
            "machine_netlist_xml_sha256": hashlib.sha256(
                retained_machine_xml.encode("utf-8")
            ).hexdigest(),
            "reader_netlist_xml_text": retained_reader_xml,
            "reader_netlist_xml_sha256": hashlib.sha256(
                retained_reader_xml.encode("utf-8")
            ).hexdigest(),
            "machine_netlist_snapshot_json": machine_snapshot_json,
            "machine_netlist_snapshot_fingerprint": board_netlist_snapshot_fingerprint(
                machine_snapshot_json
            ),
            "reader_netlist_snapshot_json": reader_snapshot_json,
            "reader_netlist_snapshot_fingerprint": board_netlist_snapshot_fingerprint(
                reader_snapshot_json
            ),
            "tool_id": tool_id,
            "tool_version": tool_version,
            "config_identity": config_identity,
            "config_json": config_json,
            "config_sha256": hashlib.sha256(config_json.encode("utf-8")).hexdigest(),
            "machine_erc_report_json": retained_machine_erc_json,
            "machine_erc_report_sha256": hashlib.sha256(
                retained_machine_erc_json.encode("utf-8")
            ).hexdigest(),
            "reader_erc_report_json": retained_reader_erc_json,
            "reader_erc_report_sha256": hashlib.sha256(
                retained_reader_erc_json.encode("utf-8")
            ).hexdigest(),
            "machine_erc_report": retained_machine_report,
            "reader_erc_report": retained_reader_report,
            "comparison_findings": comparison,
            "status": status,
            "findings": findings,
        }
        provisional = cls.model_construct(**fields, evidence_fingerprint="0" * 64)
        return cls(**fields, evidence_fingerprint=_fingerprint(provisional.fingerprint_payload()))


def _canonical_circuit_snapshot_json(circuit: CircuitObject) -> str:
    return _canonical_json(circuit.model_dump(mode="json"))


def _parse_canonical_circuit_snapshot(snapshot_json: str) -> CircuitObject:
    _canonical_json_text(snapshot_json, "circuit_snapshot_json")
    try:
        circuit = CircuitObject.model_validate_json(snapshot_json)
    except ValueError as error:
        raise ValueError(f"circuit snapshot does not match CircuitObject: {error}") from error
    if _canonical_circuit_snapshot_json(circuit) != snapshot_json:
        raise ValueError("circuit snapshot differs from canonical CircuitObject serialization")
    return circuit


def _simulation_report_authority_missing(report: SimulationReport) -> tuple[str, ...]:
    command_is_present = bool(report.command) and all(
        bool(item) and item.strip() == item for item in report.command
    ) and "ngspice" in report.command[0].lower()
    raw_path_is_present = (
        report.raw_output_path is not None
        and bool(report.raw_output_path)
        and report.raw_output_path.strip() == report.raw_output_path
    )
    return tuple(
        field_name
        for field_name, present in (
            ("command", command_is_present),
            ("raw_output_path", raw_path_is_present),
        )
        if not present
    )


def _derive_thermometer_simulation_result(
    *,
    circuit: CircuitObject,
    raw_output_text: str,
    report: SimulationReport,
) -> tuple[
    dict[str, float],
    AggregateCheckStatus,
    tuple[ExternalSubcheckFinding, ...],
]:
    parsed = parse_ngspice_meas_results(raw_output_text)
    if report.measurements != parsed:
        raise ValueError("simulation report measurements differ from parsed raw ngspice output")
    evaluation_status, evaluation_findings, evaluation_measurements = (
        evaluate_thermometer_measurements(dict(parsed), circuit)
    )
    if evaluation_measurements != parsed:
        raise ValueError("thermometer evaluator changed the parsed measurement values")

    has_replayable_results = bool(parsed)
    if has_replayable_results and (
        report.status != evaluation_status or report.findings != evaluation_findings
    ):
        raise ValueError(
            "completed simulation report status or findings differ from measurement replay"
        )

    authority_missing = _simulation_report_authority_missing(report)
    findings: list[ExternalSubcheckFinding] = []
    if not has_replayable_results:
        findings.append(
            ExternalSubcheckFinding.build(
                "thermometer-ngspice-results-missing",
                "Retained ngspice output contains no replayable .meas results",
            )
        )
    if authority_missing:
        findings.append(
            ExternalSubcheckFinding.build(
                "thermometer-ngspice-authority-incomplete",
                "Simulation authority is missing required fields: "
                + ", ".join(authority_missing),
            )
        )
    if report.status != "passed":
        findings.append(
            ExternalSubcheckFinding.build(
                "thermometer-ngspice-report-status",
                f"Retained SimulationReport status is {report.status!r}, expected 'passed'",
            )
        )
    if report.findings and report.findings != (THERMOMETER_SIMULATION_MODEL_NOTE,):
        findings.append(
            ExternalSubcheckFinding.build(
                "thermometer-ngspice-report-findings",
                "Retained SimulationReport findings: "
                + _canonical_json(tuple(sorted(report.findings))),
            )
        )

    if has_replayable_results and evaluation_status == "failed":
        status = AggregateCheckStatus.FAIL
    elif (
        has_replayable_results
        and evaluation_status == "passed"
        and report.status == "passed"
        and not authority_missing
    ):
        status = AggregateCheckStatus.PASS
        findings = []
    else:
        status = AggregateCheckStatus.UNVERIFIED
    return (
        dict(sorted(parsed.items())),
        status,
        tuple(sorted(findings, key=lambda item: item.finding_fingerprint)),
    )


class ThermometerNgspiceSubcheckEvidence(BaseModel):
    """Replay-derived ngspice evidence for thermometer LED branches only."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_kind: Literal["thermometer_ngspice"] = "thermometer_ngspice"
    producer_id: Literal["pcbsmith.simulation.thermometer-ngspice-adapter"] = (
        THERMOMETER_NGSPICE_ADAPTER_ID
    )
    adapter_version: Literal[1] = 1
    subcheck_id: str
    subcheck_version: str
    layout_snapshot_fingerprint: str
    netlist_snapshot_fingerprint: str
    policy_fingerprint: str
    circuit_snapshot_json: str
    circuit_snapshot_sha256: str
    circuit_artifact_id: str
    circuit_artifact_sha256: str
    supported_topology_id: Literal["thermometer_env_display"] = "thermometer_env_display"
    model_scope_id: Literal["pcbsmith.simulation.thermometer-led-branches-only-v1"] = (
        THERMOMETER_LED_BRANCH_MODEL_SCOPE_ID
    )
    model_scope_note: str = THERMOMETER_SIMULATION_MODEL_NOTE
    spice_netlist_text: str
    spice_netlist_sha256: str
    raw_output_text: str
    raw_output_sha256: str
    raw_output_artifact_id: str
    raw_output_artifact_sha256: str
    simulation_report: SimulationReport
    tool_id: Literal["ngspice"] = "ngspice"
    tool_version: str
    config_json: str
    config_sha256: str
    parsed_measurements: dict[str, float]
    status: AggregateCheckStatus
    findings: tuple[ExternalSubcheckFinding, ...]
    evidence_fingerprint: str

    def fingerprint_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"evidence_fingerprint"})

    @model_validator(mode="after")
    def adapter_result_replays_exactly(self) -> Self:
        for field_name in (
            "subcheck_id",
            "subcheck_version",
            "circuit_artifact_id",
            "raw_output_artifact_id",
            "tool_version",
        ):
            _require_identity(getattr(self, field_name), field_name)
        for field_name in (
            "layout_snapshot_fingerprint",
            "netlist_snapshot_fingerprint",
            "policy_fingerprint",
            "circuit_snapshot_sha256",
            "circuit_artifact_sha256",
            "spice_netlist_sha256",
            "raw_output_sha256",
            "raw_output_artifact_sha256",
            "config_sha256",
            "evidence_fingerprint",
        ):
            _require_sha256(getattr(self, field_name), field_name)
        circuit = _parse_canonical_circuit_snapshot(self.circuit_snapshot_json)
        if self.circuit_snapshot_sha256 != hashlib.sha256(
            self.circuit_snapshot_json.encode("utf-8")
        ).hexdigest():
            raise ValueError("CircuitObject snapshot checksum is stale")
        if (
            circuit.intent.intent_id != THERMOMETER_SIMULATION_TOPOLOGY_ID
            or circuit.topology.topology_id != THERMOMETER_SIMULATION_TOPOLOGY_ID
        ):
            raise ValueError("thermometer simulation circuit has unsupported topology identity")
        if self.model_scope_note != THERMOMETER_SIMULATION_MODEL_NOTE:
            raise ValueError("thermometer simulation model-scope note is stale")
        expected_netlist = render_thermometer_netlist(circuit)
        if self.spice_netlist_text != expected_netlist:
            raise ValueError("retained thermometer SPICE netlist differs from circuit replay")
        if self.spice_netlist_sha256 != hashlib.sha256(
            self.spice_netlist_text.encode("utf-8")
        ).hexdigest():
            raise ValueError("thermometer SPICE netlist checksum is stale")
        expected_raw_sha256 = hashlib.sha256(self.raw_output_text.encode("utf-8")).hexdigest()
        if self.raw_output_sha256 != expected_raw_sha256:
            raise ValueError("raw ngspice output checksum is stale")
        if self.raw_output_artifact_sha256 != expected_raw_sha256:
            raise ValueError("raw ngspice artifact checksum differs from retained output")
        _canonical_json_text(self.config_json, "config_json")
        if self.config_sha256 != hashlib.sha256(self.config_json.encode("utf-8")).hexdigest():
            raise ValueError("thermometer ngspice config checksum is stale")
        retained_report = SimulationReport.model_validate_json(
            self.simulation_report.model_dump_json()
        )
        expected_measurements, expected_status, expected_findings = (
            _derive_thermometer_simulation_result(
                circuit=circuit,
                raw_output_text=self.raw_output_text,
                report=retained_report,
            )
        )
        if self.parsed_measurements != expected_measurements:
            raise ValueError("retained parsed measurements differ from raw-output replay")
        if self.status != expected_status or self.findings != expected_findings:
            raise ValueError("thermometer ngspice status or findings differ from replay")
        if self.evidence_fingerprint != _fingerprint(self.fingerprint_payload()):
            raise ValueError("thermometer ngspice evidence fingerprint is stale")
        return self

    @classmethod
    def build(
        cls,
        *,
        subcheck_id: str,
        subcheck_version: str,
        layout: BoardLayout,
        netlist: BoardNetlist,
        policy: StableAggregateExactCheckerPolicy,
        circuit: CircuitObject,
        circuit_artifact_id: str,
        circuit_artifact_sha256: str,
        raw_output_text: str,
        raw_output_artifact_id: str,
        simulation_report: SimulationReport,
        tool_version: str,
        config: Any,
    ) -> Self:
        requirement = next(
            (
                item
                for item in policy.subchecks
                if (item.subcheck_id, item.subcheck_version)
                == (subcheck_id, subcheck_version)
            ),
            None,
        )
        if (
            requirement is None
            or requirement.kind is not AggregateSubcheckKind.EXTERNAL_ARTIFACT
            or requirement.applicability is not AggregateSubcheckApplicability.REQUIRED
            or requirement.producer_id != THERMOMETER_NGSPICE_ADAPTER_ID
        ):
            raise ValueError(
                "thermometer ngspice evidence requires its explicit policy producer identity"
            )
        retained_circuit = CircuitObject.model_validate_json(circuit.model_dump_json())
        if (
            retained_circuit.intent.intent_id != THERMOMETER_SIMULATION_TOPOLOGY_ID
            or retained_circuit.topology.topology_id != THERMOMETER_SIMULATION_TOPOLOGY_ID
        ):
            raise ValueError("thermometer simulation circuit has unsupported topology identity")
        circuit_snapshot_json = _canonical_circuit_snapshot_json(retained_circuit)
        spice_netlist_text = render_thermometer_netlist(retained_circuit)
        raw_sha256 = hashlib.sha256(raw_output_text.encode("utf-8")).hexdigest()
        retained_report = SimulationReport.model_validate_json(
            simulation_report.model_dump_json()
        )
        parsed, status, findings = _derive_thermometer_simulation_result(
            circuit=retained_circuit,
            raw_output_text=raw_output_text,
            report=retained_report,
        )
        layout_json = canonical_board_layout_snapshot_json(layout)
        netlist_json = canonical_board_netlist_snapshot_json(netlist)
        config_json = _canonical_json(config)
        fields: dict[str, Any] = {
            "subcheck_id": subcheck_id,
            "subcheck_version": subcheck_version,
            "layout_snapshot_fingerprint": board_layout_snapshot_fingerprint(layout_json),
            "netlist_snapshot_fingerprint": board_netlist_snapshot_fingerprint(netlist_json),
            "policy_fingerprint": policy.policy_fingerprint,
            "circuit_snapshot_json": circuit_snapshot_json,
            "circuit_snapshot_sha256": hashlib.sha256(
                circuit_snapshot_json.encode("utf-8")
            ).hexdigest(),
            "circuit_artifact_id": circuit_artifact_id,
            "circuit_artifact_sha256": circuit_artifact_sha256,
            "model_scope_note": THERMOMETER_SIMULATION_MODEL_NOTE,
            "spice_netlist_text": spice_netlist_text,
            "spice_netlist_sha256": hashlib.sha256(
                spice_netlist_text.encode("utf-8")
            ).hexdigest(),
            "raw_output_text": raw_output_text,
            "raw_output_sha256": raw_sha256,
            "raw_output_artifact_id": raw_output_artifact_id,
            "raw_output_artifact_sha256": raw_sha256,
            "simulation_report": retained_report,
            "tool_version": tool_version,
            "config_json": config_json,
            "config_sha256": hashlib.sha256(config_json.encode("utf-8")).hexdigest(),
            "parsed_measurements": parsed,
            "status": status,
            "findings": findings,
        }
        provisional = cls.model_construct(**fields, evidence_fingerprint="0" * 64)
        return cls(**fields, evidence_fingerprint=_fingerprint(provisional.fingerprint_payload()))


class InProcessSubcheckEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_kind: Literal["in_process"] = "in_process"
    subcheck_id: str
    subcheck_version: str
    kind: Literal[AggregateSubcheckKind.VIRTUAL_DRC, AggregateSubcheckKind.DESIGN_CHECKS]
    status: AggregateCheckStatus
    finding_fingerprints: tuple[str, ...]
    result_json: str
    result_sha256: str

    @model_validator(mode="after")
    def result_is_canonical(self) -> Self:
        _require_identity(self.subcheck_id, "subcheck_id")
        _require_identity(self.subcheck_version, "subcheck_version")
        canonical = tuple(sorted(self.finding_fingerprints))
        if canonical != self.finding_fingerprints or len(set(canonical)) != len(canonical):
            raise ValueError("in-process finding fingerprints must be canonical and unique")
        for value in canonical:
            _require_sha256(value, "finding_fingerprint")
        _canonical_json_text(self.result_json, "result_json")
        _require_sha256(self.result_sha256, "result_sha256")
        if self.result_sha256 != hashlib.sha256(self.result_json.encode("utf-8")).hexdigest():
            raise ValueError("in-process result checksum is stale")
        if self.status is AggregateCheckStatus.PASS and canonical:
            raise ValueError("passing in-process evidence cannot retain findings")
        if self.status is not AggregateCheckStatus.PASS and not canonical:
            raise ValueError("blocked in-process evidence requires findings")
        return self


class MissingSubcheckEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    evidence_kind: Literal["missing"] = "missing"
    subcheck_id: str
    subcheck_version: str
    status: Literal[AggregateCheckStatus.UNVERIFIED, AggregateCheckStatus.NOT_APPLICABLE]
    reason: str
    finding_fingerprint: str | None

    @model_validator(mode="after")
    def missing_record_is_coherent(self) -> Self:
        _require_identity(self.subcheck_id, "subcheck_id")
        _require_identity(self.subcheck_version, "subcheck_version")
        _require_identity(self.reason, "reason")
        expected = _fingerprint(
            {
                "subcheck_id": self.subcheck_id,
                "subcheck_version": self.subcheck_version,
                "status": self.status,
                "reason": self.reason,
            }
        )
        if self.status is AggregateCheckStatus.UNVERIFIED:
            if self.finding_fingerprint != expected:
                raise ValueError("missing required subcheck fingerprint is stale")
        elif self.finding_fingerprint is not None:
            raise ValueError("not-applicable subcheck cannot carry a blocking fingerprint")
        return self


AggregateSubcheckEvidence = Annotated[
    InProcessSubcheckEvidence
    | ExternalArtifactSubcheckEvidence
    | KiCadSaveRoundtripSubcheckEvidence
    | ReaderNetlistEqualitySubcheckEvidence
    | ThermometerNgspiceSubcheckEvidence
    | MissingSubcheckEvidence,
    Field(discriminator="evidence_kind"),
]

SuppliedAggregateSubcheckEvidence = Annotated[
    ExternalArtifactSubcheckEvidence
    | KiCadSaveRoundtripSubcheckEvidence
    | ReaderNetlistEqualitySubcheckEvidence
    | ThermometerNgspiceSubcheckEvidence,
    Field(discriminator="evidence_kind"),
]
_SUPPLIED_EVIDENCE_ADAPTER: TypeAdapter[SuppliedAggregateSubcheckEvidence] = TypeAdapter(
    SuppliedAggregateSubcheckEvidence
)


class StableAggregateExactCheckEvidence(BaseModel):
    """Replay-checkable full-input envelope and existing exact-check verdict."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["pcbsmith-stable-aggregate-exact-check-evidence"] = (
        "pcbsmith-stable-aggregate-exact-check-evidence"
    )
    schema_version: Literal[1] = 1
    layout_snapshot_json: str
    netlist_snapshot_json: str
    layout_snapshot_fingerprint: str
    netlist_snapshot_fingerprint: str
    policy: StableAggregateExactCheckerPolicy
    subchecks: tuple[AggregateSubcheckEvidence, ...]
    aggregate_result: ExactRouteCheckResult
    evidence_fingerprint: str

    @model_validator(mode="after")
    def envelope_replays_exactly(self) -> Self:
        parse_canonical_board_layout_snapshot(self.layout_snapshot_json)
        parse_canonical_board_netlist_snapshot(self.netlist_snapshot_json)
        if self.layout_snapshot_fingerprint != board_layout_snapshot_fingerprint(
            self.layout_snapshot_json
        ):
            raise ValueError("aggregate layout snapshot fingerprint is stale")
        if self.netlist_snapshot_fingerprint != board_netlist_snapshot_fingerprint(
            self.netlist_snapshot_json
        ):
            raise ValueError("aggregate netlist snapshot fingerprint is stale")
        supplied_external = tuple(
            item
            for item in self.subchecks
            if isinstance(
                item,
                (
                    ExternalArtifactSubcheckEvidence,
                    KiCadSaveRoundtripSubcheckEvidence,
                    ReaderNetlistEqualitySubcheckEvidence,
                    ThermometerNgspiceSubcheckEvidence,
                ),
            )
        )
        expected_subchecks, expected_result = _derive_aggregate(
            self.layout_snapshot_json,
            self.netlist_snapshot_json,
            self.policy,
            supplied_external,
        )
        if self.subchecks != expected_subchecks:
            raise ValueError("aggregate subcheck evidence differs from deterministic replay")
        if self.aggregate_result != expected_result:
            raise ValueError("aggregate exact result differs from deterministic replay")
        payload = self.model_dump(mode="json", exclude={"evidence_fingerprint"})
        if self.evidence_fingerprint != _fingerprint(payload):
            raise ValueError("aggregate evidence fingerprint is stale")
        return self


def _in_process_evidence(
    requirement: AggregateSubcheckRequirement,
    layout: BoardLayout,
    netlist: BoardNetlist,
    policy: StableAggregateExactCheckerPolicy,
) -> InProcessSubcheckEvidence:
    if requirement.kind is AggregateSubcheckKind.VIRTUAL_DRC:
        findings = tuple(
            sorted(
                (asdict(item) for item in run_virtual_drc(layout, netlist, policy.profile)),
                key=_canonical_json,
            )
        )
        payload = {
            "schema_id": "pcbsmith-aggregate-virtual-drc-result",
            "schema_version": 1,
            "findings": findings,
        }
    elif requirement.kind is AggregateSubcheckKind.DESIGN_CHECKS:
        report = run_design_checks(layout, netlist, policy.design_checks_spec, policy.profile)
        finding_values = tuple(
            sorted(
                (item.model_dump(mode="json") for item in report.findings),
                key=_canonical_json,
            )
        )
        payload = {
            "schema_id": "pcbsmith-aggregate-design-check-result",
            "schema_version": 1,
            "status": report.status,
            "checks_run": tuple(report.checks_run),
            "findings": finding_values,
        }
        findings = finding_values
    else:  # pragma: no cover - guarded by the caller and policy model
        raise ValueError("external subcheck cannot run in-process")
    result_json = _canonical_json(payload)
    finding_fingerprints = tuple(
        sorted(
            _fingerprint(
                {
                    "subcheck_id": requirement.subcheck_id,
                    "subcheck_version": requirement.subcheck_version,
                    "finding": item,
                }
            )
            for item in findings
        )
    )
    return InProcessSubcheckEvidence(
        subcheck_id=requirement.subcheck_id,
        subcheck_version=requirement.subcheck_version,
        kind=requirement.kind,
        status=(AggregateCheckStatus.PASS if not findings else AggregateCheckStatus.FAIL),
        finding_fingerprints=finding_fingerprints,
        result_json=result_json,
        result_sha256=hashlib.sha256(result_json.encode("utf-8")).hexdigest(),
    )


def _missing(requirement: AggregateSubcheckRequirement) -> MissingSubcheckEvidence:
    if requirement.applicability is AggregateSubcheckApplicability.NOT_APPLICABLE:
        return MissingSubcheckEvidence(
            subcheck_id=requirement.subcheck_id,
            subcheck_version=requirement.subcheck_version,
            status=AggregateCheckStatus.NOT_APPLICABLE,
            reason="policy explicitly declares this external subcheck not applicable",
            finding_fingerprint=None,
        )
    reason = "policy-required external subcheck evidence was not supplied"
    payload = {
        "subcheck_id": requirement.subcheck_id,
        "subcheck_version": requirement.subcheck_version,
        "status": AggregateCheckStatus.UNVERIFIED,
        "reason": reason,
    }
    return MissingSubcheckEvidence(
        subcheck_id=requirement.subcheck_id,
        subcheck_version=requirement.subcheck_version,
        status=AggregateCheckStatus.UNVERIFIED,
        reason=reason,
        finding_fingerprint=_fingerprint(payload),
    )


def _derive_aggregate(
    layout_snapshot_json: str,
    netlist_snapshot_json: str,
    policy: StableAggregateExactCheckerPolicy,
    external_evidence: tuple[
        ExternalArtifactSubcheckEvidence
        | KiCadSaveRoundtripSubcheckEvidence
        | ReaderNetlistEqualitySubcheckEvidence
        | ThermometerNgspiceSubcheckEvidence,
        ...,
    ],
) -> tuple[tuple[AggregateSubcheckEvidence, ...], ExactRouteCheckResult]:
    layout = parse_canonical_board_layout_snapshot(layout_snapshot_json)
    netlist = parse_canonical_board_netlist_snapshot(netlist_snapshot_json)
    policy_before = policy.model_dump(mode="json")
    layout_fp = board_layout_snapshot_fingerprint(layout_snapshot_json)
    netlist_fp = board_netlist_snapshot_fingerprint(netlist_snapshot_json)
    external_by_key: dict[
        tuple[str, str],
        ExternalArtifactSubcheckEvidence
        | KiCadSaveRoundtripSubcheckEvidence
        | ReaderNetlistEqualitySubcheckEvidence
        | ThermometerNgspiceSubcheckEvidence,
    ] = {}
    for external_item in external_evidence:
        key = (external_item.subcheck_id, external_item.subcheck_version)
        if key in external_by_key:
            raise ValueError("duplicate external aggregate subcheck evidence")
        external_by_key[key] = external_item
    requirements = {(item.subcheck_id, item.subcheck_version): item for item in policy.subchecks}
    if any(key not in requirements for key in external_by_key):
        raise ValueError("external evidence contains an extra policy-unknown subcheck")

    derived: list[AggregateSubcheckEvidence] = []
    for requirement in policy.subchecks:
        key = (requirement.subcheck_id, requirement.subcheck_version)
        if requirement.kind is not AggregateSubcheckKind.EXTERNAL_ARTIFACT:
            if key in external_by_key:
                raise ValueError("external evidence cannot replace an in-process aggregate check")
            derived.append(_in_process_evidence(requirement, layout, netlist, policy))
            continue
        supplied = external_by_key.get(key)
        if requirement.applicability is AggregateSubcheckApplicability.NOT_APPLICABLE:
            if supplied is not None:
                raise ValueError("evidence supplied for a policy-inapplicable subcheck")
            derived.append(_missing(requirement))
            continue
        if supplied is None:
            derived.append(_missing(requirement))
            continue
        if isinstance(supplied, KiCadSaveRoundtripSubcheckEvidence):
            if requirement.producer_id != KICAD_SAVE_ROUNDTRIP_ADAPTER_ID:
                raise ValueError(
                    "KiCad roundtrip evidence requires its explicit policy producer identity"
                )
            serialization = supplied.roundtrip_authority.serialization_authority
            if serialization.final_layout_snapshot_json != layout_snapshot_json:
                raise ValueError(
                    "KiCad roundtrip authority final layout differs from aggregate layout"
                )
            if serialization.source_netlist_snapshot_json != netlist_snapshot_json:
                raise ValueError("KiCad roundtrip authority netlist differs from aggregate netlist")
        elif isinstance(supplied, ReaderNetlistEqualitySubcheckEvidence):
            if requirement.producer_id != READER_NETLIST_EQUALITY_ADAPTER_ID:
                raise ValueError(
                    "reader-netlist evidence requires its explicit policy producer identity"
                )
            if supplied.machine_netlist_snapshot_json != netlist_snapshot_json:
                raise ValueError("machine parsed netlist differs from aggregate netlist")
        elif isinstance(supplied, ThermometerNgspiceSubcheckEvidence):
            if requirement.producer_id != THERMOMETER_NGSPICE_ADAPTER_ID:
                raise ValueError(
                    "thermometer ngspice evidence requires its explicit policy producer identity"
                )
        elif requirement.producer_id is not None:
            raise ValueError("generic external evidence cannot fulfill a producer-specific check")
        if (
            supplied.layout_snapshot_fingerprint != layout_fp
            or supplied.netlist_snapshot_fingerprint != netlist_fp
            or supplied.policy_fingerprint != policy.policy_fingerprint
        ):
            raise ValueError("external evidence is bound to stale aggregate inputs or policy")
        if supplied.status is AggregateCheckStatus.NOT_APPLICABLE:
            raise ValueError("required external evidence cannot claim not applicable")
        derived.append(supplied)

    if canonical_board_layout_snapshot_json(layout) != layout_snapshot_json:
        raise ValueError("aggregate subcheck mutated its retained BoardLayout")
    if canonical_board_netlist_snapshot_json(netlist) != netlist_snapshot_json:
        raise ValueError("aggregate subcheck mutated its retained BoardNetlist")
    if policy.model_dump(mode="json") != policy_before:
        raise ValueError("aggregate subcheck mutated its retained checker policy")

    canonical = tuple(sorted(derived, key=lambda item: (item.subcheck_id, item.subcheck_version)))
    blocking: list[str] = []
    accepted = True
    for item in canonical:
        if item.status in {AggregateCheckStatus.FAIL, AggregateCheckStatus.UNVERIFIED}:
            accepted = False
            if isinstance(item, InProcessSubcheckEvidence):
                blocking.extend(item.finding_fingerprints)
            elif isinstance(item, ExternalArtifactSubcheckEvidence):
                blocking.extend(
                    _fingerprint(
                        {
                            "subcheck_id": item.subcheck_id,
                            "subcheck_version": item.subcheck_version,
                            "external_finding_fingerprint": finding.finding_fingerprint,
                        }
                    )
                    for finding in item.findings
                )
            elif isinstance(item, KiCadSaveRoundtripSubcheckEvidence):
                blocking.extend(
                    _fingerprint(
                        {
                            "subcheck_id": item.subcheck_id,
                            "subcheck_version": item.subcheck_version,
                            "producer_id": item.producer_id,
                            "adapter_finding_fingerprint": finding.finding_fingerprint,
                        }
                    )
                    for finding in item.findings
                )
            elif isinstance(item, ReaderNetlistEqualitySubcheckEvidence):
                blocking.extend(
                    _fingerprint(
                        {
                            "subcheck_id": item.subcheck_id,
                            "subcheck_version": item.subcheck_version,
                            "producer_id": item.producer_id,
                            "adapter_finding_fingerprint": finding.finding_fingerprint,
                        }
                    )
                    for finding in item.findings
                )
            elif isinstance(item, ThermometerNgspiceSubcheckEvidence):
                blocking.extend(
                    _fingerprint(
                        {
                            "subcheck_id": item.subcheck_id,
                            "subcheck_version": item.subcheck_version,
                            "producer_id": item.producer_id,
                            "adapter_finding_fingerprint": finding.finding_fingerprint,
                        }
                    )
                    for finding in item.findings
                )
            elif item.finding_fingerprint is not None:
                blocking.append(item.finding_fingerprint)
    checker_id = (
        f"{policy.policy_id}@{policy.policy_version}:"
        f"{policy.policy_fingerprint}"
    )
    return canonical, ExactRouteCheckResult(accepted, checker_id, tuple(blocking))


def evaluate_stable_aggregate_exact_check(
    layout: BoardLayout,
    netlist: BoardNetlist,
    policy: StableAggregateExactCheckerPolicy,
    external_evidence: tuple[
        ExternalArtifactSubcheckEvidence
        | KiCadSaveRoundtripSubcheckEvidence
        | ReaderNetlistEqualitySubcheckEvidence
        | ThermometerNgspiceSubcheckEvidence,
        ...,
    ] = (),
) -> StableAggregateExactCheckEvidence:
    """Evaluate and retain the narrow stable aggregate over isolated inputs."""

    caller_layout_before = canonical_board_layout_snapshot_json(layout)
    caller_netlist_before = canonical_board_netlist_snapshot_json(netlist)
    retained_policy = StableAggregateExactCheckerPolicy.model_validate_json(
        policy.model_dump_json()
    )
    retained_external = tuple(
        _SUPPLIED_EVIDENCE_ADAPTER.validate_json(item.model_dump_json())
        for item in external_evidence
    )
    retained_layout = parse_canonical_board_layout_snapshot(caller_layout_before)
    retained_netlist = parse_canonical_board_netlist_snapshot(caller_netlist_before)
    layout_json = canonical_board_layout_snapshot_json(retained_layout)
    netlist_json = canonical_board_netlist_snapshot_json(retained_netlist)
    subchecks, aggregate = _derive_aggregate(
        layout_json,
        netlist_json,
        retained_policy,
        retained_external,
    )
    if canonical_board_layout_snapshot_json(layout) != caller_layout_before:
        raise ValueError("aggregate checker mutated the caller BoardLayout")
    if canonical_board_netlist_snapshot_json(netlist) != caller_netlist_before:
        raise ValueError("aggregate checker mutated the caller BoardNetlist")
    fields: dict[str, Any] = {
        "layout_snapshot_json": layout_json,
        "netlist_snapshot_json": netlist_json,
        "layout_snapshot_fingerprint": board_layout_snapshot_fingerprint(layout_json),
        "netlist_snapshot_fingerprint": board_netlist_snapshot_fingerprint(netlist_json),
        "policy": retained_policy,
        "subchecks": subchecks,
        "aggregate_result": aggregate,
    }
    provisional = StableAggregateExactCheckEvidence.model_construct(
        **fields, evidence_fingerprint="0" * 64
    )
    fingerprint = _fingerprint(
        provisional.model_dump(mode="json", exclude={"evidence_fingerprint"})
    )
    return StableAggregateExactCheckEvidence(**fields, evidence_fingerprint=fingerprint)


def external_subcheck_binding(
    layout: BoardLayout,
    netlist: BoardNetlist,
    policy: StableAggregateExactCheckerPolicy,
) -> tuple[str, str, str]:
    """Return exact fingerprints needed when an external adapter makes evidence."""

    layout_json = canonical_board_layout_snapshot_json(layout)
    netlist_json = canonical_board_netlist_snapshot_json(netlist)
    return (
        board_layout_snapshot_fingerprint(layout_json),
        board_netlist_snapshot_fingerprint(netlist_json),
        policy.policy_fingerprint,
    )
