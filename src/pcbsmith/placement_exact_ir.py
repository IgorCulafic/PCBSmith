"""Typed R5.5 exact-check authority and final result honesty."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from pcbsmith.placement_detail_ir import (
    PlacementCandidateDetailRecord,
    PlacementDetailRunResult,
)
from pcbsmith.placement_ir import PlacementIrModel


def _sha(value: str, name: str) -> str:
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _ids(values: tuple[str, ...], name: str) -> tuple[str, ...]:
    out = tuple(sorted(values))
    if len(set(out)) != len(out) or any(not x or x != x.strip() for x in out):
        raise ValueError(f"{name} must contain unique canonical identities")
    return out


def _fp(payload: object) -> str:
    text = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )
    return hashlib.sha256(text.encode()).hexdigest()


def exact_checker_report_fingerprint(
    accepted: bool,
    checker_id: str,
    finding_fingerprints: tuple[str, ...],
) -> str:
    return _fp(
        {
            "accepted": accepted,
            "checker_id": checker_id,
            "finding_fingerprints": finding_fingerprints,
        }
    )


def exact_candidate_input_fingerprint(
    candidate_fingerprint: str,
    detail_record_fingerprint: str,
    routing_run_fingerprint: str,
    route_geometry_fingerprint: str,
    materialized_layout_fingerprint: str,
    netlist_fingerprint: str,
) -> str:
    return _fp(
        {
            "schema_id": "pcbsmith-placement-exact-candidate-input",
            "schema_version": 1,
            "candidate_fingerprint": candidate_fingerprint,
            "detail_record_fingerprint": detail_record_fingerprint,
            "routing_run_fingerprint": routing_run_fingerprint,
            "route_geometry_fingerprint": route_geometry_fingerprint,
            "materialized_layout_fingerprint": materialized_layout_fingerprint,
            "netlist_fingerprint": netlist_fingerprint,
        }
    )


def exact_invocation_input_fingerprint(
    candidate_input_fingerprint: str,
    exact_policy_fingerprint: str,
    checker_id: str,
    call_index: int,
) -> str:
    return _fp(
        {
            "schema_id": "pcbsmith-placement-exact-invocation-input",
            "schema_version": 1,
            "candidate_input_fingerprint": candidate_input_fingerprint,
            "exact_policy_fingerprint": exact_policy_fingerprint,
            "checker_id": checker_id,
            "call_index": call_index,
        }
    )


class PlacementExactDisposition(StrEnum):
    NOT_ELIGIBLE = "not_eligible"
    CHECKER_UNAVAILABLE = "checker_unavailable"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CHECKER_ERROR = "checker_error"
    EXACT_REJECTED = "exact_rejected"
    EXACT_ACCEPTED = "exact_accepted"


class PlacementFinalState(StrEnum):
    NOT_SELECTED = "not_selected"
    ROUTING_FAILED = "routing_failed"
    ROUTED_UNCHECKED = "routed_unchecked"
    EXACT_REJECTED = "exact_rejected"
    ACCEPTED = "accepted"


class PlacementExactPolicy(PlacementIrModel):
    policy_id: str = "r5.5-exact-authority-v1"
    checker_id: str

    @model_validator(mode="after")
    def valid(self) -> Self:
        for name in ("policy_id", "checker_id"):
            value = getattr(self, name)
            if not value or value != value.strip():
                raise ValueError(f"{name} must be canonical and non-empty")
        return self


class PlacementExactBudget(PlacementIrModel):
    max_exact_checks: int = Field(ge=0)


class PlacementExactCheckEvidence(PlacementIrModel):
    candidate_fingerprint: str
    detail_record_fingerprint: str
    routing_run_fingerprint: str
    route_geometry_fingerprint: str
    materialized_layout_fingerprint: str
    checker_id: str
    checker_report_fingerprint: str
    accepted: bool
    finding_fingerprints: tuple[str, ...] = ()
    call_index: int = Field(ge=0)

    @model_validator(mode="after")
    def coherent(self) -> Self:
        for name in (
            "candidate_fingerprint",
            "detail_record_fingerprint",
            "routing_run_fingerprint",
            "route_geometry_fingerprint",
            "materialized_layout_fingerprint",
            "checker_report_fingerprint",
        ):
            _sha(getattr(self, name), name)
        if not self.checker_id or self.checker_id != self.checker_id.strip():
            raise ValueError("checker_id must be canonical and non-empty")
        findings = _ids(self.finding_fingerprints, "finding_fingerprints")
        for item in findings:
            _sha(item, "finding fingerprint")
        expected = exact_checker_report_fingerprint(self.accepted, self.checker_id, findings)
        if self.checker_report_fingerprint != expected:
            raise ValueError("checker report fingerprint is stale")
        object.__setattr__(self, "finding_fingerprints", findings)
        return self


class PlacementExactCandidateRecord(PlacementIrModel):
    candidate_fingerprint: str
    detail_record: PlacementCandidateDetailRecord
    detail_record_fingerprint: str
    netlist_fingerprint: str | None = None
    exact_input_fingerprint: str | None = None
    exact_checks_consumed: int = Field(ge=0, le=1)
    checker_call_index: int | None = Field(default=None, ge=0)
    disposition: PlacementExactDisposition
    final_state: PlacementFinalState
    exact_report: PlacementExactCheckEvidence | None = None
    checker_error_fingerprint: str | None = None
    accepted: bool = False

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _sha(self.candidate_fingerprint, "candidate_fingerprint")
        detail = PlacementCandidateDetailRecord.model_validate_json(
            self.detail_record.model_dump_json()
        )
        if detail.candidate_fingerprint != self.candidate_fingerprint:
            raise ValueError("exact record belongs to another detail candidate")
        if self.detail_record_fingerprint != detail.semantic_fingerprint():
            raise ValueError("detail record fingerprint is stale")
        if self.netlist_fingerprint is not None:
            _sha(self.netlist_fingerprint, "netlist_fingerprint")
        if detail.routed_unchecked != (self.netlist_fingerprint is not None):
            raise ValueError("eligible exact candidate must retain its netlist fingerprint")
        if self.exact_input_fingerprint is not None:
            _sha(self.exact_input_fingerprint, "exact_input_fingerprint")
        if self.checker_error_fingerprint is not None:
            _sha(self.checker_error_fingerprint, "checker_error_fingerprint")
        report = (
            None
            if self.exact_report is None
            else PlacementExactCheckEvidence.model_validate_json(
                self.exact_report.model_dump_json()
            )
        )
        if not detail.selected:
            expected_disposition = PlacementExactDisposition.NOT_ELIGIBLE
            expected_state = PlacementFinalState.NOT_SELECTED
        elif not detail.routed_unchecked:
            expected_disposition = PlacementExactDisposition.NOT_ELIGIBLE
            expected_state = PlacementFinalState.ROUTING_FAILED
        elif report is not None:
            expected_disposition = (
                PlacementExactDisposition.EXACT_ACCEPTED
                if report.accepted
                else PlacementExactDisposition.EXACT_REJECTED
            )
            expected_state = (
                PlacementFinalState.ACCEPTED
                if report.accepted
                else PlacementFinalState.EXACT_REJECTED
            )
        else:
            expected_disposition = self.disposition
            expected_state = PlacementFinalState.ROUTED_UNCHECKED
            if expected_disposition not in {
                PlacementExactDisposition.CHECKER_UNAVAILABLE,
                PlacementExactDisposition.BUDGET_EXHAUSTED,
                PlacementExactDisposition.CHECKER_ERROR,
            }:
                raise ValueError("unchecked candidate has an invalid exact disposition")
        if self.disposition is not expected_disposition or self.final_state is not expected_state:
            raise ValueError("exact disposition or final state is stale")
        invoked = self.exact_checks_consumed == 1
        if invoked != (self.checker_call_index is not None):
            raise ValueError("checker call index and consumed work disagree")
        if invoked != (self.exact_input_fingerprint is not None):
            raise ValueError("invoked exact check requires a bound exact input")
        if report is not None:
            if not invoked or self.checker_error_fingerprint is not None:
                raise ValueError("an exact report requires one successful checker call")
            if report.call_index != self.checker_call_index:
                raise ValueError("exact report call index is stale")
            if report.candidate_fingerprint != self.candidate_fingerprint:
                raise ValueError("exact report belongs to another candidate")
            if report.detail_record_fingerprint != self.detail_record_fingerprint:
                raise ValueError("exact report does not bind the detail record")
            if detail.routing_run is None or (
                report.routing_run_fingerprint != detail.routing_run.semantic_fingerprint()
            ):
                raise ValueError("exact report does not bind the R2 run")
            if (
                report.route_geometry_fingerprint != detail.route_geometry_fingerprint
                or report.materialized_layout_fingerprint != detail.materialized_layout_fingerprint
            ):
                raise ValueError("exact report does not bind routed geometry/layout")
        elif self.disposition is PlacementExactDisposition.CHECKER_ERROR:
            if not invoked or self.checker_error_fingerprint is None:
                raise ValueError("checker error requires one call and error fingerprint")
        elif invoked or self.checker_error_fingerprint is not None:
            raise ValueError("non-invoked state cannot consume exact work")
        expected_accepted = (
            detail.algorithmic_success
            and detail.zero_overuse
            and report is not None
            and report.accepted
        )
        if self.accepted != expected_accepted:
            raise ValueError("accepted flag is stale")
        object.__setattr__(self, "detail_record", detail)
        object.__setattr__(self, "exact_report", report)
        return self


class PlacementExactRunResult(PlacementIrModel):
    schema_id: Literal["pcbsmith-placement-exact-run"] = "pcbsmith-placement-exact-run"
    schema_version: Literal[1] = 1
    detail_result: PlacementDetailRunResult
    detail_result_fingerprint: str
    exact_policy: PlacementExactPolicy
    exact_policy_fingerprint: str
    exact_budget: PlacementExactBudget
    exact_budget_fingerprint: str
    exact_input_catalog_fingerprint: str
    input_fingerprint: str
    checker_available: bool
    candidate_records: tuple[PlacementExactCandidateRecord, ...]
    exact_checks_consumed: int = Field(ge=0)
    accepted_candidate_fingerprints: tuple[str, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> Self:
        detail = PlacementDetailRunResult.model_validate_json(self.detail_result.model_dump_json())
        policy = PlacementExactPolicy.model_validate_json(self.exact_policy.model_dump_json())
        budget = PlacementExactBudget.model_validate_json(self.exact_budget.model_dump_json())
        if self.detail_result_fingerprint != detail.semantic_fingerprint():
            raise ValueError("nested R5.4 result fingerprint is stale")
        if self.exact_policy_fingerprint != policy.semantic_fingerprint():
            raise ValueError("exact policy fingerprint is stale")
        if self.exact_budget_fingerprint != budget.semantic_fingerprint():
            raise ValueError("exact budget fingerprint is stale")
        for name in ("exact_input_catalog_fingerprint", "input_fingerprint"):
            _sha(getattr(self, name), name)
        expected_input = _fp(
            {
                "schema_id": "pcbsmith-placement-exact-input",
                "schema_version": 1,
                "detail_result_fingerprint": self.detail_result_fingerprint,
                "exact_policy_fingerprint": self.exact_policy_fingerprint,
                "exact_budget_fingerprint": self.exact_budget_fingerprint,
                "exact_input_catalog_fingerprint": self.exact_input_catalog_fingerprint,
                "checker_available": self.checker_available,
            }
        )
        if self.input_fingerprint != expected_input:
            raise ValueError("exact input fingerprint is stale")
        records = tuple(
            sorted(
                (
                    PlacementExactCandidateRecord.model_validate_json(item.model_dump_json())
                    for item in self.candidate_records
                ),
                key=lambda item: item.candidate_fingerprint,
            )
        )
        record_ids = tuple(item.candidate_fingerprint for item in records)
        detail_ids = tuple(item.candidate_fingerprint for item in detail.candidate_records)
        if len(set(record_ids)) != len(records) or record_ids != detail_ids:
            raise ValueError("exact records must cover every R5.4 candidate exactly once")
        detail_by_id = {item.candidate_fingerprint: item for item in detail.candidate_records}
        if any(item.detail_record != detail_by_id[item.candidate_fingerprint] for item in records):
            raise ValueError("exact records rewrite nested R5.4 evidence")
        eligible = tuple(item for item in records if item.detail_record.routed_unchecked)
        candidate_input_fingerprints = tuple(
            exact_candidate_input_fingerprint(
                item.candidate_fingerprint,
                item.detail_record_fingerprint,
                item.detail_record.routing_run.semantic_fingerprint(),
                item.detail_record.route_geometry_fingerprint,
                item.detail_record.materialized_layout_fingerprint,
                item.netlist_fingerprint,
            )
            for item in eligible
            if item.detail_record.routing_run is not None
            and item.detail_record.route_geometry_fingerprint is not None
            and item.detail_record.materialized_layout_fingerprint is not None
            and item.netlist_fingerprint is not None
        )
        if len(candidate_input_fingerprints) != len(eligible):
            raise ValueError("eligible exact candidate authority is incomplete")
        expected_catalog = _fp(
            {
                "schema_id": "pcbsmith-placement-exact-input-catalog",
                "schema_version": 1,
                "inputs": list(candidate_input_fingerprints),
            }
        )
        if self.exact_input_catalog_fingerprint != expected_catalog:
            raise ValueError("exact input catalog fingerprint is stale")
        consumed = sum(item.exact_checks_consumed for item in records)
        if self.exact_checks_consumed != consumed:
            raise ValueError("exact work count is stale")
        if consumed > budget.max_exact_checks:
            raise ValueError("exact work exceeds the fixed budget")
        if not self.checker_available:
            if consumed != 0 or any(
                item.disposition is not PlacementExactDisposition.CHECKER_UNAVAILABLE
                for item in eligible
            ):
                raise ValueError("checker-unavailable schedule is stale")
        else:
            invocation_limit = min(len(eligible), budget.max_exact_checks)
            for index, item in enumerate(eligible):
                if index < invocation_limit:
                    if item.exact_checks_consumed != 1 or item.checker_call_index != index:
                        raise ValueError("eligible exact candidate was skipped before exhaustion")
                    if item.disposition not in {
                        PlacementExactDisposition.EXACT_ACCEPTED,
                        PlacementExactDisposition.EXACT_REJECTED,
                        PlacementExactDisposition.CHECKER_ERROR,
                    }:
                        raise ValueError("invoked exact candidate has a stale disposition")
                    expected_exact_input = exact_invocation_input_fingerprint(
                        candidate_input_fingerprints[index],
                        self.exact_policy_fingerprint,
                        policy.checker_id,
                        index,
                    )
                    if item.exact_input_fingerprint != expected_exact_input:
                        raise ValueError("invoked exact input fingerprint is stale")
                    if (
                        item.exact_report is not None
                        and item.exact_report.checker_id != policy.checker_id
                    ):
                        raise ValueError("exact report checker ID disagrees with policy")
                elif (
                    item.disposition is not PlacementExactDisposition.BUDGET_EXHAUSTED
                    or item.exact_checks_consumed != 0
                ):
                    raise ValueError("post-budget exact candidate state is stale")
        call_indices = tuple(
            item.checker_call_index for item in records if item.checker_call_index is not None
        )
        if call_indices != tuple(range(consumed)):
            raise ValueError("checker calls must be consecutive in candidate order")
        accepted = _ids(
            self.accepted_candidate_fingerprints,
            "accepted_candidate_fingerprints",
        )
        for accepted_fingerprint in accepted:
            _sha(accepted_fingerprint, "accepted candidate fingerprint")
        if set(accepted) != {item.candidate_fingerprint for item in records if item.accepted}:
            raise ValueError("accepted candidate tuple is stale")
        object.__setattr__(self, "detail_result", detail)
        object.__setattr__(self, "exact_policy", policy)
        object.__setattr__(self, "exact_budget", budget)
        object.__setattr__(self, "candidate_records", records)
        object.__setattr__(self, "accepted_candidate_fingerprints", accepted)
        return self
