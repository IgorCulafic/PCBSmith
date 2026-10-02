"""Small source-bound circuit screens consumed by production readiness.

These are declared operating contracts, not a synthesis engine or stability proof.
All source interpretations and physical qualification still require review.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.calculators.passive import (
    led_current_limit_bounds,
    parse_capacitance_farads,
    parse_resistance_ohms,
    parse_resistance_value,
)
from pcbsmith.kicad.board import parse_board_netlist
from pcbsmith.semantic_ir import SemanticIrModel

if TYPE_CHECKING:
    from pcbsmith.design_readiness import DesignReadinessReport
    from pcbsmith.production_readiness import ReadinessEvidenceFile

PATTERN_EVIDENCE_ID = "circuit-patterns"


class PatternPart(SemanticIrModel):
    reference: str = Field(min_length=1)
    value: str = Field(min_length=1)
    footprint: str = Field(min_length=1)
    mpn: str = Field(min_length=1)
    pins: dict[str, str] = Field(min_length=2)


class PatternLimit(SemanticIrModel):
    """Source-interpreted interval, including derating over the stated conditions."""

    minimum: float = Field(ge=0)
    maximum: float = Field(ge=0)
    allowed_minimum: float = Field(ge=0)
    allowed_maximum: float = Field(gt=0)
    units: str = Field(min_length=1)
    evidence_scope: Literal["operating_envelope", "single_frequency_only", "unverified"]

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.minimum > self.maximum or self.allowed_minimum > self.allowed_maximum:
            raise ValueError("circuit-pattern interval is reversed")
        return self


class IndicatorCalculation(SemanticIrModel):
    supply_min_v: float = Field(gt=0)
    supply_max_v: float = Field(gt=0)
    forward_min_v: float = Field(ge=0)
    forward_max_v: float = Field(ge=0)
    resistance_ohms: float = Field(gt=0)
    resistance_tolerance: float = Field(ge=0, lt=1)


class CircuitPattern(SemanticIrModel):
    pattern_id: str = Field(min_length=1)
    kind: Literal["supply_bypass", "connector", "indicator"]
    parts: dict[str, PatternPart]
    rail_high: str = Field(min_length=1)
    rail_low: str = Field(min_length=1)
    # Every fact is reviewable at a precise page/section of a retained source.
    source_locators: dict[str, str] = Field(min_length=1)
    operating_conditions: str = Field(min_length=1)
    placement_requirements: str = Field(min_length=1)
    protection_assumptions: str = Field(min_length=1)
    physical_tests: tuple[str, ...] = Field(min_length=1)
    support_requirement_ids: tuple[str, ...] = Field(min_length=1)
    limits: dict[str, PatternLimit]
    indicator: IndicatorCalculation | None = None

    @model_validator(mode="after")
    def complete(self) -> Self:
        roles, quantities = {
            "connector": ({"connector"}, {"voltage": "V", "current": "A"}),
            "supply_bypass": (
                {"device", "capacitor"},
                {"voltage": "V", "capacitance": "F", "esr": "ohm"},
            ),
            "indicator": (
                {"led", "resistor"},
                {"current": "A", "resistor_power": "W"},
            ),
        }[self.kind]
        if set(self.parts) != roles or set(self.limits) != set(quantities):
            raise ValueError("circuit pattern lacks exact required roles or operating limits")
        if any(self.limits[key].units != unit for key, unit in quantities.items()):
            raise ValueError("circuit-pattern units differ from the supported contract")
        if (self.kind == "indicator") != (self.indicator is not None):
            raise ValueError("only indicator patterns require an indicator calculation")
        rails = {self.rail_high, self.rail_low}
        if len(rails) != 2:
            raise ValueError("circuit-pattern supply and return must differ")
        if self.kind == "connector":
            if not rails <= set(self.parts["connector"].pins.values()):
                raise ValueError("connector lacks its declared supply or return")
        elif self.kind == "supply_bypass":
            capacitor = self.parts["capacitor"]
            if len(capacitor.pins) != 2 or set(capacitor.pins.values()) != rails:
                raise ValueError("bypass capacitor must bridge the declared supply and return")
            nominal = parse_capacitance_farads(capacitor.value)
            envelope = self.limits["capacitance"]
            if not envelope.minimum <= nominal <= envelope.maximum:
                raise ValueError("capacitance envelope must conservatively include native nominal")
            if not rails <= set(self.parts["device"].pins.values()):
                raise ValueError("bypass device lacks the declared supply or return")
        else:
            led, resistor = self.parts["led"], self.parts["resistor"]
            led_nets, resistor_nets = set(led.pins.values()), set(resistor.pins.values())
            shared = led_nets & resistor_nets
            if (
                len(led.pins) != 2
                or len(resistor.pins) != 2
                or len(led_nets) != 2
                or len(resistor_nets) != 2
                or len(shared) != 1
                or shared & rails
                or (led_nets | resistor_nets) - shared != rails
            ):
                raise ValueError("indicator must be one series resistor and LED between rails")
            if self.indicator is not None and not math.isclose(
                parse_resistance_ohms(resistor.value),
                self.indicator.resistance_ohms,
                rel_tol=1e-12,
                abs_tol=0,
            ):
                raise ValueError("indicator calculation resistance differs from native value")
            _, tolerance = parse_resistance_value(resistor.value)
            if (
                self.indicator is not None
                and tolerance is not None
                and self.indicator.resistance_tolerance < tolerance
            ):
                raise ValueError("indicator calculation understates native resistor tolerance")
        if len({p.reference for p in self.parts.values()}) != len(self.parts):
            raise ValueError("circuit-pattern roles must use distinct components")
        texts = [
            self.pattern_id,
            self.operating_conditions,
            self.placement_requirements,
            self.protection_assumptions,
            *self.physical_tests,
            *self.source_locators.keys(),
            *self.source_locators.values(),
            *self.support_requirement_ids,
        ]
        if any(not s.strip() for s in texts):
            raise ValueError("circuit-pattern declarations must be nonblank")
        if len(set(self.support_requirement_ids)) != len(self.support_requirement_ids):
            raise ValueError("duplicate circuit-pattern support obligation")
        return self


class CircuitPatternSet(SemanticIrModel):
    schema_id: Literal["pcbsmith-circuit-patterns-v1"] = "pcbsmith-circuit-patterns-v1"
    native_netlist_evidence_id: str = Field(min_length=1)
    patterns: tuple[CircuitPattern, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique(self) -> Self:
        if len({p.pattern_id for p in self.patterns}) != len(self.patterns):
            raise ValueError("duplicate circuit-pattern identity")
        return self


def inspect_circuit_patterns(patterns: CircuitPatternSet, native_xml: Path) -> dict[str, Any]:
    """Read actual XML; never write review decisions or change project files."""
    native = parse_board_netlist(native_xml.read_text(encoding="utf-8"))
    components = {p.reference: p for p in native.components}
    if len(components) != len(native.components):
        raise ValueError("duplicate native component in circuit-pattern input")
    pins: dict[tuple[str, str], str] = {}
    names: set[str] = set()
    for net in native.nets:
        if net.name in names:
            raise ValueError("duplicate native net in circuit-pattern input")
        names.add(net.name)
        for terminal in net.nodes:
            if terminal in pins:
                raise ValueError("duplicate native terminal in circuit-pattern input")
            pins[terminal] = net.name
    blockers: list[str] = []
    calculations: dict[str, dict[str, float]] = {}
    for pattern in patterns.patterns:
        prefix = pattern.pattern_id + ":"
        for part in pattern.parts.values():
            actual = components.get(part.reference)
            if actual is None:
                blockers.append(prefix + part.reference + ":missing_component")
                continue
            if (actual.value, actual.footprint, dict(actual.fields).get("MPN")) != (
                part.value,
                part.footprint,
                part.mpn,
            ):
                blockers.append(prefix + part.reference + ":component_identity_mismatch")
            actual_pins = {pin: net for (ref, pin), net in pins.items() if ref == part.reference}
            if actual_pins != part.pins:
                blockers.append(prefix + part.reference + ":pin_or_polarity_mismatch")
        for name, limit in pattern.limits.items():
            if limit.evidence_scope != "operating_envelope":
                blockers.append(prefix + name + ":operating_envelope_unverified")
            if limit.minimum < limit.allowed_minimum or limit.maximum > limit.allowed_maximum:
                blockers.append(prefix + name + ":outside_supported_rating")
        if pattern.indicator is not None:
            calculated = led_current_limit_bounds(**pattern.indicator.model_dump())
            calculations[pattern.pattern_id] = calculated
            for name, low, high in (
                ("current", calculated["current_min_a"], calculated["current_max_a"]),
                ("resistor_power", calculated["power_min_w"], calculated["power_max_w"]),
            ):
                declared = pattern.limits[name]
                if low < declared.minimum or high > declared.maximum:
                    blockers.append(prefix + name + ":calculation_outside_declared_envelope")
    return {
        "authority": "declared_contract_screen_only",
        "approval_granted": False,
        "blockers": blockers,
        "calculations": calculations,
        "physical_tests": {p.pattern_id: list(p.physical_tests) for p in patterns.patterns},
    }


def require_bound_circuit_patterns(
    report: DesignReadinessReport,
    evidence_files: Mapping[str, ReadinessEvidenceFile],
    artifact_root: Path,
) -> dict[str, Any] | None:
    """Replay through the existing readiness owner; preserve historical no-pattern bundles.

    The caller validates confinement and SHA-256 for every evidence file first.
    Native inventory is independently replayed by the preparation/publication owners.
    """
    if PATTERN_EVIDENCE_ID not in evidence_files:
        return None
    patterns = CircuitPatternSet.model_validate_json(
        (artifact_root / evidence_files[PATTERN_EVIDENCE_ID].relative_path).read_bytes()
    )
    needed = {patterns.native_netlist_evidence_id}
    needed.update(key for p in patterns.patterns for key in p.source_locators)
    if not needed <= evidence_files.keys():
        raise ValueError("circuit-pattern sources lack retained evidence")
    # Before approval this is the preparation snapshot; afterward its retained binding.
    inventory_binding = evidence_files.get("component-readiness")
    inventory_path = artifact_root / (
        inventory_binding.relative_path if inventory_binding else "component-readiness.json"
    )
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    native_binding = evidence_files[patterns.native_netlist_evidence_id]
    native_hashes = {
        digest for path, digest in inventory["source_inputs"].items() if path.endswith(".net.xml")
    }
    if native_hashes != {native_binding.sha256}:
        raise ValueError("circuit-pattern netlist differs from current native inventory")
    requirements = {r.requirement_id: r for r in report.support_review.requirements}
    observations = {o.requirement_id: o for o in report.support_review.observations}
    for pattern in patterns.patterns:
        covered: set[str] = set()
        for requirement_id in pattern.support_requirement_ids:
            requirement = requirements.get(requirement_id)
            if requirement is None or not requirement.mandatory:
                raise ValueError("circuit-pattern support obligation omitted or optional")
            if requirement.subject_reference not in {p.reference for p in pattern.parts.values()}:
                raise ValueError("circuit-pattern support subject differs from its parts")
            observation = observations.get(requirement_id)
            if observation is not None:
                covered.update(observation.supporting_references)
            if PATTERN_EVIDENCE_ID not in requirement.source_ids:
                raise ValueError("circuit-pattern obligation lacks its source binding")
        support_role = {
            "supply_bypass": "capacitor",
            "indicator": "resistor",
            "connector": "connector",
        }[pattern.kind]
        if pattern.parts[support_role].reference not in covered:
            raise ValueError("circuit-pattern supporting component is not observed")
    result = inspect_circuit_patterns(patterns, artifact_root / native_binding.relative_path)
    if result["blockers"]:
        raise ValueError("circuit-pattern checks failed: " + ", ".join(result["blockers"]))
    return result
