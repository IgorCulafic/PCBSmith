"""Evidence-bound per-component schematic review coverage.

Preparation builds a bounded electrical neighborhood and typed obligations.
Completion fails closed unless every obligation has one coherent outcome.

The coverage-and-neighborhood concepts were informed by the public AGPL-3.0
Pinscope project, but this implementation is native to PCBSmith's replay-bound
IR and exact BoardNetlist snapshots.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.circuit.models import EvidenceRef
from pcbsmith.evidence.component_pin_evidence import ComponentPinEvidence
from pcbsmith.kicad.board import BoardNetlist
from pcbsmith.kicad.board_serialization import (
    board_netlist_snapshot_fingerprint,
    canonical_board_netlist_snapshot_json,
)
from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticDisposition, SemanticIrModel


class ReviewArea(StrEnum):
    PIN_MAPPING = "pin_mapping"
    POWER_DECOUPLING = "power_decoupling"
    INTERFACE = "interface"
    ABSOLUTE_MAXIMUM = "absolute_maximum"
    CONFIGURATION = "configuration"
    CLOCK = "clock"
    REQUIRED_EXTERNALS = "required_external_components"
    UNUSED_PINS = "unused_pins"


class ReviewApplicability(StrEnum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNRESOLVED = "unresolved"


class ReviewRunOutcome(StrEnum):
    BLOCKED = "blocked"
    UNVERIFIED = "unverified"
    REVIEW = "review"
    COMPLETE = "complete"


class ReviewNeighborConnection(SemanticIrModel):
    schema_id: Literal["pcbsmith-review-neighbor-connection"] = (
        "pcbsmith-review-neighbor-connection"
    )
    schema_version: Literal[1] = 1
    component_reference: str
    component_value: str
    pin_number: str

    @model_validator(mode="after")
    def identity_is_valid(self) -> Self:
        require_identity(self.component_reference, "component_reference")
        require_identity(self.component_value, "component_value")
        require_identity(self.pin_number, "pin_number")
        return self


class ReviewPinNeighborhood(SemanticIrModel):
    schema_id: Literal["pcbsmith-review-pin-neighborhood"] = (
        "pcbsmith-review-pin-neighborhood"
    )
    schema_version: Literal[1] = 1
    pin_number: str
    pin_name: str
    electrical_role: str
    functions: tuple[str, ...]
    net_name: str | None
    inferred_net_class: Literal["power", "ground", "signal", "unknown"]
    neighbors: tuple[ReviewNeighborConnection, ...]


class ReviewBridge(SemanticIrModel):
    schema_id: Literal["pcbsmith-review-bridge"] = "pcbsmith-review-bridge"
    schema_version: Literal[1] = 1
    component_reference: str
    component_value: str
    net_names: tuple[str, ...] = Field(min_length=2)


class ComponentReviewNeighborhood(SemanticIrModel):
    schema_id: Literal["pcbsmith-component-review-neighborhood"] = (
        "pcbsmith-component-review-neighborhood"
    )
    schema_version: Literal[1] = 1
    component_reference: str
    component_value: str
    exact_part_number: str
    package_name: str
    board_netlist_snapshot_fingerprint: str
    pin_evidence_fingerprint: str
    pins: tuple[ReviewPinNeighborhood, ...]
    missing_datasheet_pin_numbers: tuple[str, ...]
    orphan_schematic_pin_numbers: tuple[str, ...]
    bridges: tuple[ReviewBridge, ...]

    @model_validator(mode="after")
    def context_is_canonical(self) -> Self:
        require_identity(self.component_reference, "component_reference")
        require_identity(self.component_value, "component_value")
        require_identity(self.exact_part_number, "exact_part_number")
        require_identity(self.package_name, "package_name")
        require_sha256(
            self.board_netlist_snapshot_fingerprint,
            "board_netlist_snapshot_fingerprint",
        )
        require_sha256(self.pin_evidence_fingerprint, "pin_evidence_fingerprint")
        pins = tuple(sorted(self.pins, key=lambda item: _pin_sort_key(item.pin_number)))
        if len(pins) != len({item.pin_number for item in pins}):
            raise ValueError("review neighborhood pin numbers must be unique")
        object.__setattr__(self, "pins", pins)
        object.__setattr__(
            self,
            "missing_datasheet_pin_numbers",
            _canonical_pin_numbers(self.missing_datasheet_pin_numbers),
        )
        object.__setattr__(
            self,
            "orphan_schematic_pin_numbers",
            _canonical_pin_numbers(self.orphan_schematic_pin_numbers),
        )
        bridges = tuple(sorted(self.bridges, key=lambda item: item.component_reference))
        if len(bridges) != len({item.component_reference for item in bridges}):
            raise ValueError("review bridge component references must be unique")
        object.__setattr__(self, "bridges", bridges)
        return self


class ComponentReviewObligation(SemanticIrModel):
    schema_id: Literal["pcbsmith-component-review-obligation"] = (
        "pcbsmith-component-review-obligation"
    )
    schema_version: Literal[1] = 1
    obligation_id: str
    component_reference: str
    area: ReviewArea
    applicability: ReviewApplicability
    rationale: str
    pin_numbers: tuple[str, ...] = ()
    net_names: tuple[str, ...] = ()
    neighbor_component_references: tuple[str, ...] = ()
    required_evidence_topics: tuple[str, ...] = ()

    @model_validator(mode="after")
    def obligation_is_canonical(self) -> Self:
        for field_name in ("obligation_id", "component_reference", "rationale"):
            require_identity(getattr(self, field_name), field_name)
        object.__setattr__(self, "pin_numbers", _canonical_pin_numbers(self.pin_numbers))
        for field_name in (
            "net_names",
            "neighbor_component_references",
            "required_evidence_topics",
        ):
            values = tuple(
                sorted(
                    require_identity(item, field_name)
                    for item in getattr(self, field_name)
                )
            )
            if len(values) != len(set(values)):
                raise ValueError(f"{field_name} must contain unique values")
            object.__setattr__(self, field_name, values)
        return self


class ComponentReviewResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-component-review-result"] = (
        "pcbsmith-component-review-result"
    )
    schema_version: Literal[1] = 1
    obligation_id: str
    disposition: SemanticDisposition
    rationale: str
    finding_ids: tuple[str, ...] = ()
    check_ids: tuple[str, ...] = ()
    evidence: tuple[EvidenceRef, ...] = ()
    evidence_query_count: int = Field(ge=0)
    evidence_query_budget: int = Field(ge=0)

    @model_validator(mode="after")
    def result_is_coherent(self) -> Self:
        require_identity(self.obligation_id, "obligation_id")
        require_identity(self.rationale, "rationale")
        if self.evidence_query_count > self.evidence_query_budget:
            raise ValueError("review evidence query count exceeds its declared budget")
        finding_ids = _canonical_identities(self.finding_ids, "finding_ids")
        check_ids = _canonical_identities(self.check_ids, "check_ids")
        if self.disposition is SemanticDisposition.FAIL and not finding_ids:
            raise ValueError("failed review obligations require at least one finding")
        if self.disposition is SemanticDisposition.PASS and not (check_ids or self.evidence):
            raise ValueError("passed review obligations require evidence or a deterministic check")
        if self.disposition is SemanticDisposition.NOT_APPLICABLE and (
            finding_ids or check_ids or self.evidence
        ):
            raise ValueError("not-applicable review results cannot retain findings or evidence")
        object.__setattr__(self, "finding_ids", finding_ids)
        object.__setattr__(self, "check_ids", check_ids)
        return self


class ComponentReviewManifest(SemanticIrModel):
    schema_id: Literal["pcbsmith-component-review-manifest"] = (
        "pcbsmith-component-review-manifest"
    )
    schema_version: Literal[1] = 1
    project_id: str
    board_revision: str
    board_netlist_snapshot_json: str
    board_netlist_snapshot_fingerprint: str
    neighborhood: ComponentReviewNeighborhood
    obligations: tuple[ComponentReviewObligation, ...]
    results: tuple[ComponentReviewResult, ...]
    trace_ids: tuple[str, ...]
    outcome: ReviewRunOutcome
    manifest_fingerprint: str

    @model_validator(mode="after")
    def manifest_has_exact_coverage_and_is_replay_bound(self) -> Self:
        require_identity(self.project_id, "project_id")
        require_identity(self.board_revision, "board_revision")
        require_sha256(
            self.board_netlist_snapshot_fingerprint,
            "board_netlist_snapshot_fingerprint",
        )
        if (
            board_netlist_snapshot_fingerprint(self.board_netlist_snapshot_json)
            != self.board_netlist_snapshot_fingerprint
        ):
            raise ValueError("component review BoardNetlist fingerprint is stale")
        if (
            self.neighborhood.board_netlist_snapshot_fingerprint
            != self.board_netlist_snapshot_fingerprint
        ):
            raise ValueError("component review neighborhood belongs to another netlist")

        obligations = tuple(sorted(self.obligations, key=lambda item: item.obligation_id))
        results = tuple(sorted(self.results, key=lambda item: item.obligation_id))
        obligation_ids = tuple(item.obligation_id for item in obligations)
        result_ids = tuple(item.obligation_id for item in results)
        if len(obligation_ids) != len(set(obligation_ids)):
            raise ValueError("component review obligation identities must be unique")
        if len(result_ids) != len(set(result_ids)):
            raise ValueError("component review result identities must be unique")
        if set(obligation_ids) != set(result_ids):
            missing = sorted(set(obligation_ids) - set(result_ids))
            extra = sorted(set(result_ids) - set(obligation_ids))
            raise ValueError(
                f"component review coverage is not closed; missing={missing}, extra={extra}"
            )
        by_id = {item.obligation_id: item for item in obligations}
        for result in results:
            applicability = by_id[result.obligation_id].applicability
            if (
                applicability is ReviewApplicability.APPLICABLE
                and result.disposition is SemanticDisposition.NOT_APPLICABLE
            ):
                raise ValueError("applicable review obligation cannot be not-applicable")
            if (
                applicability is ReviewApplicability.NOT_APPLICABLE
                and result.disposition is not SemanticDisposition.NOT_APPLICABLE
            ):
                raise ValueError("not-applicable obligation requires a not-applicable result")
            if (
                applicability is ReviewApplicability.UNRESOLVED
                and result.disposition
                not in {SemanticDisposition.UNVERIFIED, SemanticDisposition.ADVISORY}
            ):
                raise ValueError("unresolved obligation cannot produce a hard pass or failure")

        expected_outcome = _derive_outcome(results)
        if self.outcome is not expected_outcome:
            raise ValueError("component review outcome is stale")
        object.__setattr__(self, "obligations", obligations)
        object.__setattr__(self, "results", results)
        object.__setattr__(
            self,
            "trace_ids",
            _canonical_identities(self.trace_ids, "trace_ids"),
        )
        require_sha256(self.manifest_fingerprint, "manifest_fingerprint")
        payload = self.model_dump(mode="json", exclude={"manifest_fingerprint"})
        if fingerprint(payload) != self.manifest_fingerprint:
            raise ValueError("component review manifest fingerprint is stale")
        return self


def build_component_review_neighborhood(
    netlist: BoardNetlist,
    pin_evidence: ComponentPinEvidence,
    component_reference: str,
) -> ComponentReviewNeighborhood:
    """Build the target IC's bounded net/pin/neighbor/bridge context."""

    component_by_ref = {item.reference: item for item in netlist.components}
    target = component_by_ref.get(component_reference)
    if target is None:
        raise ValueError(f"component {component_reference} is absent from BoardNetlist")
    nodes_by_ref_pin: dict[tuple[str, str], str] = {}
    net_by_name = {item.name: item for item in netlist.nets}
    for net in netlist.nets:
        for reference, pin_number in net.nodes:
            key = (reference, pin_number)
            if key in nodes_by_ref_pin:
                raise ValueError(f"pin {reference}.{pin_number} appears on multiple nets")
            nodes_by_ref_pin[key] = net.name

    pin_numbers = {item.number for item in pin_evidence.pins}
    target_nodes = {
        pin: net
        for (reference, pin), net in nodes_by_ref_pin.items()
        if reference == component_reference
    }
    pin_contexts: list[ReviewPinNeighborhood] = []
    for pin in pin_evidence.pins:
        net_name = target_nodes.get(pin.number)
        neighbors: list[ReviewNeighborConnection] = []
        if net_name is not None:
            net = net_by_name[net_name]
            for reference, pin_number in net.nodes:
                if reference == component_reference:
                    continue
                component = component_by_ref.get(reference)
                if component is None:
                    raise ValueError(f"net {net_name} references unknown component {reference}")
                neighbors.append(
                    ReviewNeighborConnection(
                        component_reference=reference,
                        component_value=component.value,
                        pin_number=pin_number,
                    )
                )
        pin_contexts.append(
            ReviewPinNeighborhood(
                pin_number=pin.number,
                pin_name=pin.name,
                electrical_role=pin.electrical_role,
                functions=pin.functions,
                net_name=net_name,
                inferred_net_class=_infer_net_class(net_name),
                neighbors=tuple(
                    sorted(
                        neighbors,
                        key=lambda item: (
                            item.component_reference,
                            _pin_sort_key(item.pin_number),
                        ),
                    )
                ),
            )
        )

    target_net_names = set(target_nodes.values())
    bridges: list[ReviewBridge] = []
    for component in netlist.components:
        if component.reference == component_reference:
            continue
        touched = {
            net
            for (reference, _pin), net in nodes_by_ref_pin.items()
            if reference == component.reference and net in target_net_names
        }
        if len(touched) >= 2:
            bridges.append(
                ReviewBridge(
                    component_reference=component.reference,
                    component_value=component.value,
                    net_names=tuple(sorted(touched)),
                )
            )

    snapshot_json = canonical_board_netlist_snapshot_json(netlist)
    return ComponentReviewNeighborhood(
        component_reference=component_reference,
        component_value=target.value,
        exact_part_number=pin_evidence.part_number,
        package_name=pin_evidence.package.package_name,
        board_netlist_snapshot_fingerprint=board_netlist_snapshot_fingerprint(
            snapshot_json
        ),
        pin_evidence_fingerprint=pin_evidence.semantic_fingerprint(),
        pins=tuple(pin_contexts),
        missing_datasheet_pin_numbers=tuple(
            pin.number for pin in pin_evidence.pins if pin.number not in target_nodes
        ),
        orphan_schematic_pin_numbers=tuple(
            pin for pin in target_nodes if pin not in pin_numbers
        ),
        bridges=tuple(bridges),
    )


def derive_component_review_obligations(
    neighborhood: ComponentReviewNeighborhood,
) -> tuple[ComponentReviewObligation, ...]:
    """Derive a conservative per-IC review checklist from the actual context."""

    ref = neighborhood.component_reference
    obligations: list[ComponentReviewObligation] = []

    def add(
        suffix: str,
        area: ReviewArea,
        applicability: ReviewApplicability,
        rationale: str,
        *,
        pins: tuple[str, ...] = (),
        nets: tuple[str, ...] = (),
        neighbors: tuple[str, ...] = (),
        topics: tuple[str, ...] = (),
    ) -> None:
        obligations.append(
            ComponentReviewObligation(
                obligation_id=f"schematic-review:{ref}:{suffix}",
                component_reference=ref,
                area=area,
                applicability=applicability,
                rationale=rationale,
                pin_numbers=pins,
                net_names=nets,
                neighbor_component_references=neighbors,
                required_evidence_topics=topics,
            )
        )

    add(
        "pin-mapping",
        ReviewArea.PIN_MAPPING,
        ReviewApplicability.APPLICABLE,
        "The exact-package datasheet pin table must reconcile with schematic pins.",
        pins=tuple(pin.pin_number for pin in neighborhood.pins),
        topics=("package_information", "pin_configuration"),
    )
    power_pins = tuple(
        pin
        for pin in neighborhood.pins
        if pin.electrical_role in {"supply", "ground"}
        or pin.inferred_net_class in {"power", "ground"}
    )
    add(
        "power-decoupling",
        ReviewArea.POWER_DECOUPLING,
        (
            ReviewApplicability.APPLICABLE
            if power_pins
            else ReviewApplicability.UNRESOLVED
        ),
        (
            "Supply/ground pins exist and require rail, bypass, and return review."
            if power_pins
            else "No supply/ground role was extracted; power applicability is unresolved."
        ),
        pins=tuple(pin.pin_number for pin in power_pins),
        nets=tuple(pin.net_name for pin in power_pins if pin.net_name is not None),
        topics=("decoupling", "power_supply", "recommended_operating_conditions"),
    )

    connected_nets = tuple(
        sorted({pin.net_name for pin in neighborhood.pins if pin.net_name is not None})
    )
    add(
        "absolute-maximum",
        ReviewArea.ABSOLUTE_MAXIMUM,
        (
            ReviewApplicability.APPLICABLE
            if connected_nets
            else ReviewApplicability.UNRESOLVED
        ),
        (
            "Connected pins require pin-matched stress and operating-range review."
            if connected_nets
            else "No connected pins were found, so actual stress cannot be established."
        ),
        nets=connected_nets,
        topics=("absolute_maximum", "recommended_operating_conditions"),
    )

    configuration_pins = tuple(
        pin
        for pin in neighborhood.pins
        if pin.electrical_role == "configuration"
        or _has_token(
            pin.pin_name,
            ("RESET", "RST", "ENABLE", "EN", "BOOT", "MODE", "STRAP"),
        )
    )
    add(
        "configuration",
        ReviewArea.CONFIGURATION,
        (
            ReviewApplicability.APPLICABLE
            if configuration_pins
            else ReviewApplicability.NOT_APPLICABLE
        ),
        (
            "Reset/enable/boot/mode pins were identified."
            if configuration_pins
            else "The exact-package pin table contains no identified configuration pins."
        ),
        pins=tuple(pin.pin_number for pin in configuration_pins),
        nets=tuple(pin.net_name for pin in configuration_pins if pin.net_name is not None),
        topics=("pin_descriptions", "startup_configuration"),
    )

    clock_pins = tuple(
        pin
        for pin in neighborhood.pins
        if pin.electrical_role == "clock"
        or _has_token(pin.pin_name, ("XTAL", "OSC", "CLK", "CLOCK"))
    )
    add(
        "clock",
        ReviewArea.CLOCK,
        (
            ReviewApplicability.APPLICABLE
            if clock_pins
            else ReviewApplicability.NOT_APPLICABLE
        ),
        (
            "Clock/crystal pins were identified."
            if clock_pins
            else "The exact-package pin table contains no identified clock pins."
        ),
        pins=tuple(pin.pin_number for pin in clock_pins),
        nets=tuple(pin.net_name for pin in clock_pins if pin.net_name is not None),
        topics=("clock", "crystal", "oscillator"),
    )

    ic_neighbors: dict[str, set[str]] = {}
    for pin in neighborhood.pins:
        if pin.inferred_net_class in {"power", "ground"} or pin.net_name is None:
            continue
        for neighbor in pin.neighbors:
            if neighbor.component_reference.upper().startswith("U"):
                ic_neighbors.setdefault(neighbor.component_reference, set()).add(pin.net_name)
    for neighbor_ref, nets in sorted(ic_neighbors.items()):
        add(
            f"interface:{neighbor_ref}",
            ReviewArea.INTERFACE,
            ReviewApplicability.APPLICABLE,
            "A signal-bearing cross-component interface requires both endpoints' evidence.",
            nets=tuple(nets),
            neighbors=(neighbor_ref,),
            topics=(
                "absolute_maximum",
                "electrical_characteristics",
                "pin_voltage_levels",
            ),
        )

    add(
        "required-externals",
        ReviewArea.REQUIRED_EXTERNALS,
        ReviewApplicability.APPLICABLE,
        "Required support parts must be resolved by circuit role, not example designator.",
        nets=connected_nets,
        topics=("application_circuit", "required_external_components"),
    )
    add(
        "unused-pins",
        ReviewArea.UNUSED_PINS,
        (
            ReviewApplicability.APPLICABLE
            if neighborhood.missing_datasheet_pin_numbers
            else ReviewApplicability.NOT_APPLICABLE
        ),
        (
            "Datasheet pins absent from the netlist require no-connect/use review."
            if neighborhood.missing_datasheet_pin_numbers
            else "Every exact-package datasheet pin appears in the netlist."
        ),
        pins=neighborhood.missing_datasheet_pin_numbers,
        topics=("pin_descriptions", "unused_pins"),
    )
    return tuple(sorted(obligations, key=lambda item: item.obligation_id))


def build_component_review_manifest(
    *,
    project_id: str,
    board_revision: str,
    netlist: BoardNetlist,
    neighborhood: ComponentReviewNeighborhood,
    obligations: tuple[ComponentReviewObligation, ...],
    results: tuple[ComponentReviewResult, ...],
    trace_ids: tuple[str, ...],
) -> ComponentReviewManifest:
    snapshot_json = canonical_board_netlist_snapshot_json(netlist)
    fields: dict[str, Any] = {
        "project_id": project_id,
        "board_revision": board_revision,
        "board_netlist_snapshot_json": snapshot_json,
        "board_netlist_snapshot_fingerprint": board_netlist_snapshot_fingerprint(
            snapshot_json
        ),
        "neighborhood": neighborhood,
        "obligations": obligations,
        "results": results,
        "trace_ids": trace_ids,
        "outcome": _derive_outcome(results),
    }
    provisional = ComponentReviewManifest.model_construct(
        **fields,
        manifest_fingerprint="0" * 64,
    )
    payload = provisional.model_dump(mode="json", exclude={"manifest_fingerprint"})
    return ComponentReviewManifest(**fields, manifest_fingerprint=fingerprint(payload))


def _derive_outcome(results: tuple[ComponentReviewResult, ...]) -> ReviewRunOutcome:
    dispositions = {item.disposition for item in results}
    if SemanticDisposition.FAIL in dispositions:
        return ReviewRunOutcome.BLOCKED
    if SemanticDisposition.UNVERIFIED in dispositions:
        return ReviewRunOutcome.UNVERIFIED
    if dispositions & {
        SemanticDisposition.ADVISORY,
        SemanticDisposition.VALIDATION_PENDING,
    }:
        return ReviewRunOutcome.REVIEW
    return ReviewRunOutcome.COMPLETE


def _infer_net_class(
    net_name: str | None,
) -> Literal["power", "ground", "signal", "unknown"]:
    if net_name is None:
        return "unknown"
    original = net_name.upper()
    normalized = re.sub(r"[^A-Z0-9]+", "_", original).strip("_")
    if normalized in {"GND", "AGND", "DGND", "PGND", "VSS", "GROUND"}:
        return "ground"
    tokens = set(normalized.split("_"))
    if (
        original.startswith("+")
        or re.fullmatch(
            r"(?:\d+V\d*|VCC|VDD|VBAT|VIN|VOUT|AVDD|DVDD)",
            normalized,
        )
        or tokens & {"VCC", "VDD", "VBAT", "VIN", "VOUT", "AVDD", "DVDD"}
    ):
        return "power"
    return "signal"


def _has_token(value: str, candidates: tuple[str, ...]) -> bool:
    tokens = set(filter(None, re.split(r"[^A-Z0-9]+", value.upper())))
    return bool(tokens.intersection(candidates))


def _canonical_identities(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    canonical = tuple(sorted(require_identity(item, field_name) for item in values))
    if len(canonical) != len(set(canonical)):
        raise ValueError(f"{field_name} must contain unique values")
    return canonical


def _canonical_pin_numbers(values: tuple[str, ...]) -> tuple[str, ...]:
    canonical = tuple(
        sorted(
            (require_identity(item, "pin_numbers") for item in values),
            key=_pin_sort_key,
        )
    )
    if len(canonical) != len(set(canonical)):
        raise ValueError("pin_numbers must contain unique values")
    return canonical


def _pin_sort_key(value: str) -> tuple[int, int | str, str]:
    stripped = value.strip()
    if stripped.isdigit():
        return (0, int(stripped), stripped)
    return (1, stripped.casefold(), stripped)
