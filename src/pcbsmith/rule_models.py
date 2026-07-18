"""Evidence-aware executable rule records.

This module keeps four questions separate: what a source says, whether the
statement applies, what policy PCBSmith adopts, and whether that policy is
implemented and fixture-tested. A verified number is not automatically a
universal blocker.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pcbsmith.circuit.models import EvidenceRef

PolicySeverity = Literal["information", "advisory", "review", "blocker"]
ImplementationStatus = Literal["candidate", "proposed", "implemented", "tested"]


class RuleApplicability(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    required_conditions: tuple[str, ...] = ()
    exclusions: tuple[str, ...] = ()
    status: Literal["confirmed", "conditional", "inferred", "unknown"] = "unknown"


class RulePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    check: str
    severity: PolicySeverity
    override_requires: tuple[str, ...] = ()


class RuleImplementation(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: ImplementationStatus = "candidate"
    tests: tuple[str, ...] = ()

    @model_validator(mode="after")
    def tested_rules_name_their_fixtures(self) -> Self:
        if self.status == "tested" and not self.tests:
            raise ValueError("tested rules must name at least one fixture test")
        return self


class RuleRecord(BaseModel):
    """Versioned rule with authority, applicability and policy gates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["pcbsmith-rule-v1"] = "pcbsmith-rule-v1"
    rule_id: str = Field(min_length=1)
    source_statement: str = Field(min_length=1)
    source: EvidenceRef
    applicability: RuleApplicability
    project_policy: RulePolicy
    implementation: RuleImplementation = RuleImplementation()
    supersedes: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def blockers_require_closed_evidence_and_applicability(self) -> Self:
        if self.source.source_status == "pinned":
            digest = self.source.local_sha256 or ""
            if len(digest) != 64 or any(char not in "0123456789abcdefABCDEF" for char in digest):
                raise ValueError("pinned rule sources require a 64-character SHA-256")
        if self.project_policy.severity != "blocker":
            return self
        if self.source.source_status != "pinned":
            raise ValueError("blocker rules require a pinned source")
        if self.source.locator_status not in {"text_verified", "figure_verified"}:
            raise ValueError("blocker rules require a verified source locator")
        if self.applicability.status != "confirmed":
            raise ValueError("blocker rules require confirmed applicability")
        return self

    def semantic_hash(self) -> str:
        """Hash the rule semantics independently of implementation progress."""
        payload = {
            "schema": self.schema_id,
            "rule_id": self.rule_id,
            "source_statement": self.source_statement,
            "source": self.source.model_dump(mode="json"),
            "applicability": self.applicability.model_dump(mode="json"),
            "project_policy": self.project_policy.model_dump(mode="json"),
            "supersedes": self.supersedes,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

