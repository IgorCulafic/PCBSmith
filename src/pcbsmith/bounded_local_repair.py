"""W8 contracts for monotonic local repair without implicit board restart."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel


class RepairFindingClass(StrEnum):
    OPEN_ENDPOINT = "open_endpoint"
    DISCONNECTED_ISLAND = "disconnected_island"
    LOCAL_CLEARANCE = "local_clearance"
    SHORT = "short"
    FORBIDDEN_NECKDOWN = "forbidden_neckdown"
    EXCESSIVE_NECKDOWN = "excessive_neckdown"
    STARVED_THERMAL = "starved_thermal"
    REFERENCE_SLOT = "reference_slot"
    MISSING_RETURN_VIA = "missing_return_via"
    LOCAL_CRAFT = "local_craft"
    SILKSCREEN_OVERLAP = "silkscreen_overlap"


class RestartInvalidationReason(StrEnum):
    APPROVED_CONCEPT_CHANGED = "approved_concept_changed"
    OUTLINE_CHANGED = "outline_changed"
    SELECTED_PART_CHANGED = "selected_part_changed"
    FOOTPRINT_CHANGED = "footprint_changed"
    FABRICATION_PROFILE_CHANGED = "fabrication_profile_changed"
    FUNCTIONAL_TOPOLOGY_CHANGED = "functional_topology_changed"
    GLOBAL_CAPACITY_ASSUMPTION_INVALID = "global_capacity_assumption_invalid"


class LocalRepairBudget(SemanticIrModel):
    schema_id: Literal["pcbsmith-local-repair-budget"] = "pcbsmith-local-repair-budget"
    schema_version: Literal[1] = 1
    maximum_displacement_mm: float = Field(ge=0)
    maximum_ripped_segment_count: int = Field(ge=0)
    maximum_ripped_via_count: int = Field(ge=0)
    maximum_added_segment_count: int = Field(ge=0)
    maximum_added_via_count: int = Field(ge=0)
    maximum_attempt_count: int = Field(ge=1)
    maximum_elapsed_seconds: float = Field(gt=0)


class LocalRepairRequest(SemanticIrModel):
    schema_id: Literal["pcbsmith-local-repair-request"] = "pcbsmith-local-repair-request"
    schema_version: Literal[1] = 1
    request_id: str
    source_board_sha256: str
    source_qualification_fingerprint: str
    finding_class: RepairFindingClass
    target_finding_ids: tuple[str, ...] = Field(min_length=1)
    target_region_mm: tuple[float, float, float, float]
    affected_net_names: tuple[str, ...]
    immutable_object_ids: tuple[str, ...]
    movable_component_references: tuple[str, ...]
    rip_authorized_copper_ids: tuple[str, ...]
    budget: LocalRepairBudget
    request_fingerprint: str

    @model_validator(mode="after")
    def request_is_bounded(self) -> Self:
        require_identity(self.request_id, "request_id")
        require_sha256(self.source_board_sha256, "source_board_sha256")
        require_sha256(self.source_qualification_fingerprint, "source_qualification_fingerprint")
        x1, y1, x2, y2 = self.target_region_mm
        if not (x1 < x2 and y1 < y2):
            raise ValueError("target repair region must have positive area")
        for field_name in (
            "target_finding_ids",
            "affected_net_names",
            "immutable_object_ids",
            "movable_component_references",
            "rip_authorized_copper_ids",
        ):
            values = tuple(sorted(getattr(self, field_name)))
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must contain unique identities")
            object.__setattr__(self, field_name, values)
        if set(self.immutable_object_ids) & set(self.rip_authorized_copper_ids):
            raise ValueError("an immutable object cannot also be authorized for rip-up")
        require_sha256(self.request_fingerprint, "request_fingerprint")
        payload = self.model_dump(mode="json", exclude={"request_fingerprint"})
        if self.request_fingerprint != fingerprint(payload):
            raise ValueError("local repair request fingerprint is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> LocalRepairRequest:
        fields = dict(values)
        for name in (
            "target_finding_ids",
            "affected_net_names",
            "immutable_object_ids",
            "movable_component_references",
            "rip_authorized_copper_ids",
        ):
            fields[name] = tuple(sorted(fields.get(name, ())))
        provisional = cls.model_construct(**fields, request_fingerprint="0" * 64)
        return cls(
            **fields,
            request_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"request_fingerprint"})
            ),
        )


class LocalRepairOutcome(StrEnum):
    ACCEPTED = "accepted"
    REJECTED_REGRESSION = "rejected_regression"
    EXHAUSTED = "exhausted"
    INVALIDATED = "invalidated"


class LocalRepairResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-local-repair-result"] = "pcbsmith-local-repair-result"
    schema_version: Literal[1] = 1
    request: LocalRepairRequest
    candidate_board_sha256: str | None
    outcome: LocalRepairOutcome
    attempts_used: int = Field(ge=0)
    elapsed_seconds: float = Field(ge=0)
    target_findings_removed: tuple[str, ...]
    new_finding_ids: tuple[str, ...]
    protected_region_fingerprints_before: dict[str, str]
    protected_region_fingerprints_after: dict[str, str]
    source_unresolved_burden: int = Field(ge=0)
    candidate_unresolved_burden: int | None = Field(default=None, ge=0)
    source_craft_cost: int = Field(ge=0)
    candidate_craft_cost: int | None = Field(default=None, ge=0)
    restart_invalidation_reason: RestartInvalidationReason | None = None
    blocker_ids: tuple[str, ...]
    publish_authorized: bool
    result_fingerprint: str

    @model_validator(mode="after")
    def result_is_monotonic(self) -> Self:
        if self.candidate_board_sha256 is not None:
            require_sha256(self.candidate_board_sha256, "candidate_board_sha256")
        if self.attempts_used > self.request.budget.maximum_attempt_count:
            raise ValueError("repair attempt budget exceeded")
        if (
            self.outcome is LocalRepairOutcome.ACCEPTED
            and self.elapsed_seconds > self.request.budget.maximum_elapsed_seconds
        ):
            raise ValueError("accepted repair exceeded time budget")
        for mapping_name in (
            "protected_region_fingerprints_before",
            "protected_region_fingerprints_after",
        ):
            for value in getattr(self, mapping_name).values():
                require_sha256(value, mapping_name)
        parity = (
            self.protected_region_fingerprints_before == self.protected_region_fingerprints_after
        )
        target_removed = set(self.request.target_finding_ids).issubset(self.target_findings_removed)
        burden_lower = (
            self.candidate_unresolved_burden is not None
            and self.candidate_unresolved_burden < self.source_unresolved_burden
        )
        craft_not_worse = (
            self.candidate_craft_cost is not None
            and self.candidate_craft_cost <= self.source_craft_cost
        )
        expected_publish = (
            self.outcome is LocalRepairOutcome.ACCEPTED
            and self.candidate_board_sha256 is not None
            and parity
            and target_removed
            and not self.new_finding_ids
            and burden_lower
            and craft_not_worse
            and self.restart_invalidation_reason is None
        )
        if self.publish_authorized != expected_publish:
            raise ValueError("repair publication disposition is stale")
        if self.outcome is LocalRepairOutcome.INVALIDATED:
            if self.restart_invalidation_reason is None:
                raise ValueError("full restart requires a typed invalidation reason")
        elif self.restart_invalidation_reason is not None:
            raise ValueError("typed restart reason is only valid for invalidation")
        if self.outcome is not LocalRepairOutcome.ACCEPTED and not self.blocker_ids:
            raise ValueError("unsuccessful repair must retain useful blockers")
        payload = self.model_dump(mode="json", exclude={"result_fingerprint"})
        require_sha256(self.result_fingerprint, "result_fingerprint")
        if self.result_fingerprint != fingerprint(payload):
            raise ValueError("local repair result fingerprint is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> LocalRepairResult:
        fields = dict(values)
        request: LocalRepairRequest = fields["request"]
        parity = (
            fields["protected_region_fingerprints_before"]
            == fields["protected_region_fingerprints_after"]
        )
        fields["publish_authorized"] = (
            fields["outcome"] is LocalRepairOutcome.ACCEPTED
            and fields.get("candidate_board_sha256") is not None
            and parity
            and set(request.target_finding_ids).issubset(fields["target_findings_removed"])
            and not fields["new_finding_ids"]
            and fields.get("candidate_unresolved_burden") is not None
            and fields["candidate_unresolved_burden"] < fields["source_unresolved_burden"]
            and fields.get("candidate_craft_cost") is not None
            and fields["candidate_craft_cost"] <= fields["source_craft_cost"]
            and fields.get("restart_invalidation_reason") is None
        )
        fields["blocker_ids"] = tuple(sorted(fields.get("blocker_ids", ())))
        provisional = cls.model_construct(**fields, result_fingerprint="0" * 64)
        return cls(
            **fields,
            result_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"result_fingerprint"})
            ),
        )


__all__ = [
    "LocalRepairBudget",
    "LocalRepairOutcome",
    "LocalRepairRequest",
    "LocalRepairResult",
    "RepairFindingClass",
    "RestartInvalidationReason",
]
