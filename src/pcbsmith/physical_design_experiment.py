"""Replay-bound physical-design experiment identity and comparison gates.

This module prevents locally valid routing, placement, or copper checks from
being aggregated into a whole-board success rate when they were produced from
different boards, fabrication authorities, or acceptance predicates.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel


class ExperimentTermination(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    CANCELLED = "cancelled"
    CRASHED = "crashed"


class GeometryComparison(StrEnum):
    EXACT_EQUAL = "exact_equal"
    SEMANTIC_EQUAL = "semantic_equal"
    DIFFERENT = "different"
    NOT_COMPARED = "not_compared"


class ExperimentComparisonScope(StrEnum):
    SAME_INPUT_AND_GATE = "same_input_and_gate"
    CROSS_COHORT = "cross_cohort"


class SoftwareIdentity(SemanticIrModel):
    """One executable/runtime identity used by a retained experiment."""

    software_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    executable_sha256: str | None = None
    source_commit: str | None = None

    @model_validator(mode="after")
    def identity_is_complete(self) -> Self:
        require_identity(self.software_id, "software_id")
        require_identity(self.version, "version")
        if self.executable_sha256 is not None:
            require_sha256(self.executable_sha256, "executable_sha256")
        if self.source_commit is not None:
            require_identity(self.source_commit, "source_commit")
        return self


class PhysicalDesignAuthorityIdentity(SemanticIrModel):
    """Immutable board and rule authorities consumed by one experiment."""

    source_board_sha256: str
    schematic_sha256: str
    netlist_sha256: str
    exact_part_authority_sha256: str
    footprint_library_sha256: str
    fabrication_profile_sha256: str
    translated_constraints_sha256: str
    zone_intent_sha256: str
    acceptance_predicate_id: str = Field(min_length=1)
    acceptance_predicate_version: str = Field(min_length=1)
    acceptance_predicate_sha256: str
    active_copper_layers: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def authority_is_canonical(self) -> Self:
        for field_name in (
            "source_board_sha256",
            "schematic_sha256",
            "netlist_sha256",
            "exact_part_authority_sha256",
            "footprint_library_sha256",
            "fabrication_profile_sha256",
            "translated_constraints_sha256",
            "zone_intent_sha256",
            "acceptance_predicate_sha256",
        ):
            require_sha256(getattr(self, field_name), field_name)
        require_identity(self.acceptance_predicate_id, "acceptance_predicate_id")
        require_identity(
            self.acceptance_predicate_version,
            "acceptance_predicate_version",
        )
        layers = tuple(sorted(self.active_copper_layers))
        if len(layers) != len(set(layers)):
            raise ValueError("active_copper_layers must contain unique layers")
        for layer in layers:
            require_identity(layer, "active_copper_layers")
        object.__setattr__(self, "active_copper_layers", layers)
        return self


class PhysicalDesignExperimentIdentity(SemanticIrModel):
    """Complete identity of one retained physical-design experiment run."""

    schema_id: Literal["pcbsmith-physical-design-experiment-identity"] = (
        "pcbsmith-physical-design-experiment-identity"
    )
    schema_version: Literal[1] = 1
    experiment_id: str = Field(min_length=1)
    cohort_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    authorities: PhysicalDesignAuthorityIdentity
    generator: SoftwareIdentity
    kicad: SoftwareIdentity
    router: SoftwareIdentity
    adapter: SoftwareIdentity
    java: SoftwareIdentity
    python: SoftwareIdentity
    router_seed: int | str
    router_configuration_sha256: str
    final_filled_board_sha256: str
    started_at_utc: datetime
    ended_at_utc: datetime
    termination: ExperimentTermination
    time_budget_seconds: float = Field(gt=0.0)
    memory_budget_bytes: int = Field(gt=0)
    elapsed_seconds: float = Field(ge=0.0)
    peak_memory_bytes: int = Field(ge=0)
    identity_fingerprint: str

    @model_validator(mode="after")
    def identity_is_replay_bound(self) -> Self:
        for field_name in ("experiment_id", "cohort_id", "case_id"):
            require_identity(getattr(self, field_name), field_name)
        if isinstance(self.router_seed, str):
            require_identity(self.router_seed, "router_seed")
        require_sha256(self.router_configuration_sha256, "router_configuration_sha256")
        require_sha256(self.final_filled_board_sha256, "final_filled_board_sha256")
        if self.started_at_utc.tzinfo is None or self.started_at_utc.utcoffset() != UTC.utcoffset(
            self.started_at_utc
        ):
            raise ValueError("started_at_utc must be timezone-aware UTC")
        if self.ended_at_utc.tzinfo is None or self.ended_at_utc.utcoffset() != UTC.utcoffset(
            self.ended_at_utc
        ):
            raise ValueError("ended_at_utc must be timezone-aware UTC")
        if self.ended_at_utc < self.started_at_utc:
            raise ValueError("ended_at_utc cannot precede started_at_utc")
        for field_name in ("time_budget_seconds", "elapsed_seconds"):
            if not math.isfinite(getattr(self, field_name)):
                raise ValueError(f"{field_name} must be finite")
        if (
            self.termination is ExperimentTermination.COMPLETED
            and self.elapsed_seconds > self.time_budget_seconds * 1.05
        ):
            raise ValueError("a completed run cannot exceed its retained time budget")
        if (
            self.termination is ExperimentTermination.COMPLETED
            and self.peak_memory_bytes > self.memory_budget_bytes
        ):
            raise ValueError("a completed run cannot exceed its retained memory budget")
        require_sha256(self.identity_fingerprint, "identity_fingerprint")
        expected = fingerprint(
            self.model_dump(mode="json", exclude={"identity_fingerprint"})
        )
        if self.identity_fingerprint != expected:
            raise ValueError("physical-design experiment identity fingerprint is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> PhysicalDesignExperimentIdentity:
        provisional = cls.model_construct(**values, identity_fingerprint="0" * 64)
        return cls(
            **values,
            identity_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"identity_fingerprint"})
            ),
        )

    def input_gate_fingerprint(self) -> str:
        """Fingerprint only the board/rule authorities required for comparison."""

        return fingerprint(self.authorities.model_dump(mode="json"))


class PhysicalDesignExperimentResult(SemanticIrModel):
    """Whole-board result; local checks may be evidence but cannot set accepted."""

    schema_id: Literal["pcbsmith-physical-design-experiment-result"] = (
        "pcbsmith-physical-design-experiment-result"
    )
    schema_version: Literal[1] = 1
    identity: PhysicalDesignExperimentIdentity
    semantic_geometry_sha256: str
    acceptance_result_sha256: str
    whole_board_accepted: bool
    local_check_pass_count: int = Field(ge=0)
    local_check_fail_count: int = Field(ge=0)
    whole_board_gate_complete: bool
    result_fingerprint: str

    @model_validator(mode="after")
    def result_is_replay_bound(self) -> Self:
        require_sha256(self.semantic_geometry_sha256, "semantic_geometry_sha256")
        require_sha256(self.acceptance_result_sha256, "acceptance_result_sha256")
        if self.whole_board_accepted and not self.whole_board_gate_complete:
            raise ValueError("local checks cannot establish whole-board acceptance")
        if self.identity.termination is not ExperimentTermination.COMPLETED:
            if self.whole_board_accepted:
                raise ValueError("an incomplete experiment cannot be accepted")
        require_sha256(self.result_fingerprint, "result_fingerprint")
        expected = fingerprint(self.model_dump(mode="json", exclude={"result_fingerprint"}))
        if self.result_fingerprint != expected:
            raise ValueError("physical-design experiment result fingerprint is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> PhysicalDesignExperimentResult:
        provisional = cls.model_construct(**values, result_fingerprint="0" * 64)
        return cls(
            **values,
            result_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"result_fingerprint"})
            ),
        )


class PhysicalDesignComparison(SemanticIrModel):
    schema_id: Literal["pcbsmith-physical-design-comparison"] = (
        "pcbsmith-physical-design-comparison"
    )
    schema_version: Literal[1] = 1
    left_experiment_id: str
    right_experiment_id: str
    scope: ExperimentComparisonScope
    input_gate_equal: bool
    geometry_comparison: GeometryComparison
    aggregate_success_rate_allowed: bool
    label: str

    @model_validator(mode="after")
    def comparison_is_coherent(self) -> Self:
        require_identity(self.left_experiment_id, "left_experiment_id")
        require_identity(self.right_experiment_id, "right_experiment_id")
        require_identity(self.label, "label")
        if self.scope is ExperimentComparisonScope.CROSS_COHORT:
            if self.geometry_comparison is not GeometryComparison.NOT_COMPARED:
                raise ValueError("cross-cohort geometry cannot be reported as directly equal")
            if self.aggregate_success_rate_allowed:
                raise ValueError("cross-cohort results cannot share a success rate")
        else:
            if not self.input_gate_equal:
                raise ValueError("same-cohort comparison requires equal input and gate identity")
            if self.geometry_comparison is GeometryComparison.NOT_COMPARED:
                raise ValueError("same-cohort repeat must report geometry equality")
            if not self.aggregate_success_rate_allowed:
                raise ValueError("same-cohort comparison must allow direct aggregation")
        return self


def compare_physical_design_results(
    left: PhysicalDesignExperimentResult,
    right: PhysicalDesignExperimentResult,
    *,
    cross_cohort: bool = False,
    cross_cohort_label: str | None = None,
) -> PhysicalDesignComparison:
    """Compare retained results without silently weakening experiment identity."""

    input_gate_equal = (
        left.identity.input_gate_fingerprint()
        == right.identity.input_gate_fingerprint()
    )
    if not input_gate_equal and not cross_cohort:
        raise ValueError(
            "physical-design results use different input boards or gate definitions; "
            "declare a labeled cross-cohort comparison"
        )
    if cross_cohort:
        if cross_cohort_label is None:
            raise ValueError("cross-cohort comparisons require an explicit label")
        require_identity(cross_cohort_label, "cross_cohort_label")
        geometry = GeometryComparison.NOT_COMPARED
        scope = ExperimentComparisonScope.CROSS_COHORT
        aggregate_allowed = False
        label = cross_cohort_label
    else:
        exact_equal = (
            left.identity.final_filled_board_sha256
            == right.identity.final_filled_board_sha256
        )
        semantic_equal = left.semantic_geometry_sha256 == right.semantic_geometry_sha256
        geometry = (
            GeometryComparison.EXACT_EQUAL
            if exact_equal
            else GeometryComparison.SEMANTIC_EQUAL
            if semantic_equal
            else GeometryComparison.DIFFERENT
        )
        scope = ExperimentComparisonScope.SAME_INPUT_AND_GATE
        aggregate_allowed = True
        label = "same input board and acceptance gate"
    return PhysicalDesignComparison(
        left_experiment_id=left.identity.experiment_id,
        right_experiment_id=right.identity.experiment_id,
        scope=scope,
        input_gate_equal=input_gate_equal,
        geometry_comparison=geometry,
        aggregate_success_rate_allowed=aggregate_allowed,
        label=label,
    )


class PhysicalDesignExperimentSummary(SemanticIrModel):
    schema_id: Literal["pcbsmith-physical-design-experiment-summary"] = (
        "pcbsmith-physical-design-experiment-summary"
    )
    schema_version: Literal[1] = 1
    scope: ExperimentComparisonScope
    label: str
    result_count: int = Field(gt=0)
    accepted_count: int = Field(ge=0)
    success_rate: float | None
    input_gate_fingerprints: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def summary_is_coherent(self) -> Self:
        require_identity(self.label, "label")
        if self.accepted_count > self.result_count:
            raise ValueError("accepted_count cannot exceed result_count")
        fingerprints = tuple(sorted(self.input_gate_fingerprints))
        if len(fingerprints) != len(set(fingerprints)):
            raise ValueError("input_gate_fingerprints must contain unique digests")
        for digest in fingerprints:
            require_sha256(digest, "input_gate_fingerprints")
        object.__setattr__(self, "input_gate_fingerprints", fingerprints)
        if self.scope is ExperimentComparisonScope.CROSS_COHORT:
            if self.success_rate is not None:
                raise ValueError("cross-cohort summary cannot publish a success rate")
        else:
            expected = self.accepted_count / self.result_count
            if self.success_rate != expected:
                raise ValueError("same-cohort success rate is stale")
            if len(fingerprints) != 1:
                raise ValueError("same-cohort summary requires one input/gate fingerprint")
        return self


def summarize_physical_design_results(
    results: tuple[PhysicalDesignExperimentResult, ...],
    *,
    cross_cohort: bool = False,
    cross_cohort_label: str | None = None,
) -> PhysicalDesignExperimentSummary:
    """Aggregate only one input/gate cohort; cross-cohort output has no success rate."""

    if not results:
        raise ValueError("at least one physical-design result is required")
    fingerprints = tuple(
        sorted({result.identity.input_gate_fingerprint() for result in results})
    )
    if len(fingerprints) > 1 and not cross_cohort:
        raise ValueError(
            "cannot aggregate different input boards or gate definitions into one success rate"
        )
    if cross_cohort:
        if cross_cohort_label is None:
            raise ValueError("cross-cohort summaries require an explicit label")
        require_identity(cross_cohort_label, "cross_cohort_label")
        scope = ExperimentComparisonScope.CROSS_COHORT
        label = cross_cohort_label
        rate = None
    else:
        scope = ExperimentComparisonScope.SAME_INPUT_AND_GATE
        label = "same input board and acceptance gate"
        rate = sum(result.whole_board_accepted for result in results) / len(results)
    return PhysicalDesignExperimentSummary(
        scope=scope,
        label=label,
        result_count=len(results),
        accepted_count=sum(result.whole_board_accepted for result in results),
        success_rate=rate,
        input_gate_fingerprints=fingerprints,
    )


__all__ = [
    "ExperimentComparisonScope",
    "ExperimentTermination",
    "GeometryComparison",
    "PhysicalDesignAuthorityIdentity",
    "PhysicalDesignComparison",
    "PhysicalDesignExperimentIdentity",
    "PhysicalDesignExperimentResult",
    "PhysicalDesignExperimentSummary",
    "SoftwareIdentity",
    "compare_physical_design_results",
    "summarize_physical_design_results",
]
