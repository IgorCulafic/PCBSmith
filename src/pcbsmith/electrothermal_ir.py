"""Deterministic passive electrothermal-network authority.

The initial solver accepts point-valued, source-bound thermal networks. It
fails closed for unresolved or interval-valued inputs rather than presenting a
nominal solve as a tolerance bound. Interval/corner propagation is a later,
separately validated model version.
"""

from __future__ import annotations

from decimal import Decimal, localcontext
from enum import StrEnum
from typing import Literal, Self

from pydantic import model_validator

from pcbsmith.engineering_quantity_ir import (
    BoundedQuantity,
    QuantityKnowledge,
    canonical_engineering_identities,
    require_engineering_identity,
)
from pcbsmith.semantic_ir import SemanticIrModel


class ThermalNodeKind(StrEnum):
    JUNCTION = "junction"
    CASE = "case"
    PACKAGE_SURFACE = "package_surface"
    TIM = "tim"
    CONTACT = "contact"
    SPREADER = "spreader"
    HEATSINK = "heatsink"
    PCB_TERRITORY = "pcb_territory"
    LOCAL_AMBIENT = "local_ambient"


class ThermalNode(SemanticIrModel):
    schema_id: Literal["pcbsmith-thermal-node"] = "pcbsmith-thermal-node"
    schema_version: Literal[1] = 1
    node_id: str
    kind: ThermalNodeKind
    subject_ids: tuple[str, ...]
    fixed_temperature: BoundedQuantity | None = None

    @model_validator(mode="after")
    def node_is_coherent(self) -> Self:
        require_engineering_identity(self.node_id, "node_id")
        subjects = canonical_engineering_identities(self.subject_ids, "subject_ids")
        if not subjects:
            raise ValueError("thermal nodes require physical subjects")
        if self.fixed_temperature is not None and self.fixed_temperature.unit not in {
            "degC",
            "K",
        }:
            raise ValueError("fixed thermal-node temperature must use degC or K")
        object.__setattr__(self, "subject_ids", subjects)
        return self


class ThermalLink(SemanticIrModel):
    schema_id: Literal["pcbsmith-thermal-link"] = "pcbsmith-thermal-link"
    schema_version: Literal[1] = 1
    link_id: str
    node_a_id: str
    node_b_id: str
    thermal_resistance: BoundedQuantity
    source_binding_ids: tuple[str, ...]
    applicability_notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def link_is_coherent(self) -> Self:
        for field_name in ("link_id", "node_a_id", "node_b_id"):
            require_engineering_identity(getattr(self, field_name), field_name)
        if self.node_a_id == self.node_b_id:
            raise ValueError("thermal links cannot connect a node to itself")
        if self.thermal_resistance.unit not in {"K/W", "degC/W"}:
            raise ValueError("thermal resistance must use K/W or degC/W")
        bindings = canonical_engineering_identities(
            self.source_binding_ids,
            "source_binding_ids",
        )
        if not bindings:
            raise ValueError("thermal links require source or assumption bindings")
        notes = tuple(
            require_engineering_identity(note, "applicability_notes")
            for note in self.applicability_notes
        )
        object.__setattr__(self, "source_binding_ids", bindings)
        object.__setattr__(self, "applicability_notes", notes)
        return self


class ThermalHeatInjection(SemanticIrModel):
    schema_id: Literal["pcbsmith-thermal-heat-injection"] = "pcbsmith-thermal-heat-injection"
    schema_version: Literal[1] = 1
    injection_id: str
    node_id: str
    power: BoundedQuantity
    loss_identity_ids: tuple[str, ...]

    @model_validator(mode="after")
    def injection_is_coherent(self) -> Self:
        require_engineering_identity(self.injection_id, "injection_id")
        require_engineering_identity(self.node_id, "node_id")
        if self.power.unit != "W":
            raise ValueError("thermal heat injection must use watts")
        identities = canonical_engineering_identities(
            self.loss_identity_ids,
            "loss_identity_ids",
        )
        if not identities:
            raise ValueError("heat injection must reference physical loss identities")
        object.__setattr__(self, "loss_identity_ids", identities)
        return self


class ElectrothermalNetwork(SemanticIrModel):
    schema_id: Literal["pcbsmith-electrothermal-network"] = "pcbsmith-electrothermal-network"
    schema_version: Literal[1] = 1
    network_id: str
    scenario_id: str
    mission_profile_fingerprint: str
    loss_ledger_fingerprint: str
    nodes: tuple[ThermalNode, ...]
    links: tuple[ThermalLink, ...]
    heat_injections: tuple[ThermalHeatInjection, ...]
    source_context_ids: tuple[str, ...]

    @model_validator(mode="after")
    def network_is_canonical(self) -> Self:
        require_engineering_identity(self.network_id, "network_id")
        require_engineering_identity(self.scenario_id, "scenario_id")
        for field_name in ("mission_profile_fingerprint", "loss_ledger_fingerprint"):
            value = getattr(self, field_name)
            if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
                raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")
        nodes = tuple(sorted(self.nodes, key=lambda item: item.node_id))
        links = tuple(sorted(self.links, key=lambda item: item.link_id))
        injections = tuple(sorted(self.heat_injections, key=lambda item: item.injection_id))
        if len(nodes) != len({item.node_id for item in nodes}):
            raise ValueError("thermal node identities must be unique")
        if len(links) != len({item.link_id for item in links}):
            raise ValueError("thermal link identities must be unique")
        if len(injections) != len({item.injection_id for item in injections}):
            raise ValueError("thermal injection identities must be unique")
        node_ids = {item.node_id for item in nodes}
        if any(link.node_a_id not in node_ids or link.node_b_id not in node_ids for link in links):
            raise ValueError("thermal link references an unknown node")
        if any(item.node_id not in node_ids for item in injections):
            raise ValueError("heat injection references an unknown node")
        if not any(item.fixed_temperature is not None for item in nodes):
            raise ValueError("thermal network requires at least one temperature boundary")
        contexts = canonical_engineering_identities(
            self.source_context_ids,
            "source_context_ids",
        )
        if not contexts:
            raise ValueError("electrothermal network requires source context")
        object.__setattr__(self, "nodes", nodes)
        object.__setattr__(self, "links", links)
        object.__setattr__(self, "heat_injections", injections)
        object.__setattr__(self, "source_context_ids", contexts)
        return self


class ThermalNodeResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-thermal-node-result"] = "pcbsmith-thermal-node-result"
    schema_version: Literal[1] = 1
    node_id: str
    temperature: BoundedQuantity


class ElectrothermalSolveResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-electrothermal-solve-result"] = (
        "pcbsmith-electrothermal-solve-result"
    )
    schema_version: Literal[1] = 1
    network_id: str
    network_fingerprint: str
    solver_id: Literal["pcbsmith.thermal-dc-point-nodal"] = "pcbsmith.thermal-dc-point-nodal"
    solver_version: Literal[1] = 1
    disposition: Literal["solved", "indeterminate"]
    node_results: tuple[ThermalNodeResult, ...]
    missing_input_ids: tuple[str, ...]
    findings: tuple[str, ...]


class CoupledElectrothermalPointModel(SemanticIrModel):
    """Single-subject screening model with temperature-dependent conduction loss."""

    schema_id: Literal["pcbsmith-coupled-electrothermal-point-model"] = (
        "pcbsmith-coupled-electrothermal-point-model"
    )
    schema_version: Literal[1] = 1
    model_id: str
    scenario_id: str
    subject_id: str
    ambient_temperature: BoundedQuantity
    current_rms: BoundedQuantity
    conduction_fraction: BoundedQuantity
    resistance_reference: BoundedQuantity
    resistance_reference_temperature: BoundedQuantity
    resistance_temperature_coefficient: BoundedQuantity
    fixed_loss: BoundedQuantity
    junction_to_ambient_rth: BoundedQuantity
    convergence_tolerance: BoundedQuantity
    max_iterations: int = 100
    source_context_ids: tuple[str, ...]

    @model_validator(mode="after")
    def model_is_coherent(self) -> Self:
        for field_name in ("model_id", "scenario_id", "subject_id"):
            require_engineering_identity(getattr(self, field_name), field_name)
        expected_units = (
            (self.ambient_temperature, "degC"),
            (self.current_rms, "A"),
            (self.conduction_fraction, "1"),
            (self.resistance_reference, "ohm"),
            (self.resistance_reference_temperature, "degC"),
            (self.resistance_temperature_coefficient, "1/K"),
            (self.fixed_loss, "W"),
            (self.junction_to_ambient_rth, "K/W"),
            (self.convergence_tolerance, "K"),
        )
        for quantity, expected in expected_units:
            if quantity.unit != expected:
                raise ValueError(f"{quantity.quantity_id} must use explicit {expected} units")
        if self.max_iterations < 1:
            raise ValueError("coupled electrothermal max_iterations must be positive")
        contexts = canonical_engineering_identities(
            self.source_context_ids,
            "source_context_ids",
        )
        if not contexts:
            raise ValueError("coupled electrothermal models require source context")
        object.__setattr__(self, "source_context_ids", contexts)
        return self


class CoupledElectrothermalPointResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-coupled-electrothermal-point-result"] = (
        "pcbsmith-coupled-electrothermal-point-result"
    )
    schema_version: Literal[1] = 1
    model_id: str
    model_fingerprint: str
    solver_id: Literal["pcbsmith.coupled-electrothermal-point"] = (
        "pcbsmith.coupled-electrothermal-point"
    )
    solver_version: Literal[1] = 1
    disposition: Literal["solved", "indeterminate", "nonconvergent"]
    junction_temperature: BoundedQuantity
    conduction_loss: BoundedQuantity
    total_loss: BoundedQuantity
    iterations: int
    residual: BoundedQuantity
    missing_input_ids: tuple[str, ...]
    findings: tuple[str, ...]


class TransientThermalBranch(SemanticIrModel):
    schema_id: Literal["pcbsmith-transient-thermal-branch"] = "pcbsmith-transient-thermal-branch"
    schema_version: Literal[1] = 1
    branch_id: str
    thermal_resistance: BoundedQuantity
    time_constant: BoundedQuantity
    source_binding_ids: tuple[str, ...]

    @model_validator(mode="after")
    def branch_is_coherent(self) -> Self:
        require_engineering_identity(self.branch_id, "branch_id")
        if self.thermal_resistance.unit not in {"K/W", "degC/W"}:
            raise ValueError("transient branch resistance must use K/W or degC/W")
        if self.time_constant.unit != "s":
            raise ValueError("transient branch time constant must use seconds")
        bindings = canonical_engineering_identities(
            self.source_binding_ids,
            "source_binding_ids",
        )
        if not bindings:
            raise ValueError("transient thermal branches require source context")
        object.__setattr__(self, "source_binding_ids", bindings)
        return self


class TransientThermalModel(SemanticIrModel):
    schema_id: Literal["pcbsmith-transient-thermal-model"] = "pcbsmith-transient-thermal-model"
    schema_version: Literal[1] = 1
    model_id: str
    scenario_id: str
    subject_id: str
    steady_network_fingerprint: str
    ambient_temperature: BoundedQuantity
    step_power: BoundedQuantity
    duration: BoundedQuantity
    branches: tuple[TransientThermalBranch, ...]
    source_context_ids: tuple[str, ...]

    @model_validator(mode="after")
    def model_is_coherent(self) -> Self:
        for field_name in ("model_id", "scenario_id", "subject_id"):
            require_engineering_identity(getattr(self, field_name), field_name)
        if len(self.steady_network_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in self.steady_network_fingerprint
        ):
            raise ValueError("steady network fingerprint must be lowercase SHA-256")
        if self.ambient_temperature.unit not in {"degC", "K"}:
            raise ValueError("transient ambient must use degC or K")
        if self.step_power.unit != "W" or self.duration.unit != "s":
            raise ValueError("transient model requires power in W and duration in s")
        branches = tuple(sorted(self.branches, key=lambda item: item.branch_id))
        if not branches:
            raise ValueError("transient model requires at least one impedance branch")
        if len(branches) != len({item.branch_id for item in branches}):
            raise ValueError("transient branch identities must be unique")
        contexts = canonical_engineering_identities(
            self.source_context_ids,
            "source_context_ids",
        )
        if not contexts:
            raise ValueError("transient thermal model requires source context")
        object.__setattr__(self, "branches", branches)
        object.__setattr__(self, "source_context_ids", contexts)
        return self


class TransientThermalResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-transient-thermal-result"] = "pcbsmith-transient-thermal-result"
    schema_version: Literal[1] = 1
    model_id: str
    model_fingerprint: str
    solver_id: Literal["pcbsmith.thermal-foster-step-point"] = "pcbsmith.thermal-foster-step-point"
    solver_version: Literal[1] = 1
    disposition: Literal["solved", "indeterminate"]
    endpoint_temperature: BoundedQuantity
    temperature_rise: BoundedQuantity
    missing_input_ids: tuple[str, ...]
    findings: tuple[str, ...]


def _is_point(quantity: BoundedQuantity) -> bool:
    return (
        quantity.is_known
        and quantity.lower == quantity.nominal
        and quantity.nominal == quantity.upper
    )


def _solve_linear(matrix: list[list[Decimal]], vector: list[Decimal]) -> list[Decimal]:
    """Deterministic Decimal Gaussian elimination with partial pivoting."""

    count = len(vector)
    augmented = [row[:] + [vector[index]] for index, row in enumerate(matrix)]
    with localcontext() as context:
        context.prec = 50
        for column in range(count):
            pivot = max(range(column, count), key=lambda row: abs(augmented[row][column]))
            if augmented[pivot][column] == 0:
                raise ValueError("thermal conductance matrix is singular")
            augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
            divisor = augmented[column][column]
            augmented[column] = [value / divisor for value in augmented[column]]
            for row in range(count):
                if row == column:
                    continue
                factor = augmented[row][column]
                if factor == 0:
                    continue
                augmented[row] = [
                    value - factor * pivot_value
                    for value, pivot_value in zip(augmented[row], augmented[column], strict=True)
                ]
        values = [augmented[index][-1] for index in range(count)]
        cleaned: list[Decimal] = []
        for value in values:
            nearest_integer = value.to_integral_value()
            cleaned.append(
                nearest_integer if abs(value - nearest_integer) < Decimal("1e-24") else value
            )
        return cleaned


def solve_steady_state_point_network(
    network: ElectrothermalNetwork,
) -> ElectrothermalSolveResult:
    """Solve a fully specified point network or return explicit missing inputs."""

    missing: list[str] = []
    for node in network.nodes:
        if node.fixed_temperature is not None and not _is_point(node.fixed_temperature):
            missing.append(f"node:{node.node_id}:fixed_temperature_point")
    for link in network.links:
        resistance = link.thermal_resistance
        if not _is_point(resistance):
            missing.append(f"link:{link.link_id}:thermal_resistance_point")
        elif resistance.nominal is not None and resistance.nominal <= 0:
            missing.append(f"link:{link.link_id}:positive_thermal_resistance")
    for injection in network.heat_injections:
        if not _is_point(injection.power):
            missing.append(f"injection:{injection.injection_id}:power_point")
        elif injection.power.nominal is not None and injection.power.nominal < 0:
            missing.append(f"injection:{injection.injection_id}:nonnegative_power")
    if missing:
        return ElectrothermalSolveResult(
            network_id=network.network_id,
            network_fingerprint=network.semantic_fingerprint(),
            disposition="indeterminate",
            node_results=(),
            missing_input_ids=tuple(sorted(missing)),
            findings=(
                "Version 1 solves only fully known point inputs; intervals and unknowns "
                "are not collapsed to nominal values.",
            ),
        )

    fixed = {
        item.node_id: item.fixed_temperature.nominal
        for item in network.nodes
        if item.fixed_temperature is not None
    }
    assert all(value is not None for value in fixed.values())
    unknown_ids = tuple(item.node_id for item in network.nodes if item.node_id not in fixed)
    if not unknown_ids:
        results = tuple(
            ThermalNodeResult(node_id=node_id, temperature=quantity)
            for node_id, quantity in sorted(
                (
                    (item.node_id, item.fixed_temperature)
                    for item in network.nodes
                    if item.fixed_temperature is not None
                ),
                key=lambda pair: pair[0],
            )
        )
        return ElectrothermalSolveResult(
            network_id=network.network_id,
            network_fingerprint=network.semantic_fingerprint(),
            disposition="solved",
            node_results=results,
            missing_input_ids=(),
            findings=(),
        )

    index = {node_id: offset for offset, node_id in enumerate(unknown_ids)}
    matrix = [[Decimal("0") for _ in unknown_ids] for _ in unknown_ids]
    vector = [Decimal("0") for _ in unknown_ids]
    for injection in network.heat_injections:
        if injection.node_id in index:
            assert injection.power.nominal is not None
            vector[index[injection.node_id]] += injection.power.nominal
    for link in network.links:
        assert link.thermal_resistance.nominal is not None
        conductance = Decimal("1") / link.thermal_resistance.nominal
        a_unknown = link.node_a_id in index
        b_unknown = link.node_b_id in index
        if a_unknown:
            a = index[link.node_a_id]
            matrix[a][a] += conductance
            if b_unknown:
                matrix[a][index[link.node_b_id]] -= conductance
            else:
                vector[a] += conductance * fixed[link.node_b_id]  # type: ignore[operator]
        if b_unknown:
            b = index[link.node_b_id]
            matrix[b][b] += conductance
            if a_unknown:
                matrix[b][index[link.node_a_id]] -= conductance
            else:
                vector[b] += conductance * fixed[link.node_a_id]  # type: ignore[operator]
    try:
        temperatures = _solve_linear(matrix, vector)
    except ValueError as exc:
        return ElectrothermalSolveResult(
            network_id=network.network_id,
            network_fingerprint=network.semantic_fingerprint(),
            disposition="indeterminate",
            node_results=(),
            missing_input_ids=("network:connected_path_to_fixed_boundary",),
            findings=(str(exc),),
        )
    bindings = tuple(
        sorted(
            {
                *network.source_context_ids,
                *(binding for link in network.links for binding in link.source_binding_ids),
                *(
                    binding
                    for injection in network.heat_injections
                    for binding in injection.power.evidence_binding_ids
                ),
            }
        )
    )
    result_by_node = {**fixed, **dict(zip(unknown_ids, temperatures, strict=True))}
    results = tuple(
        ThermalNodeResult(
            node_id=node_id,
            temperature=BoundedQuantity(
                quantity_id="steady_state_temperature",
                unit="degC",
                knowledge=QuantityKnowledge.DERIVED_BOUNDED,
                lower=value,
                nominal=value,
                upper=value,
                evidence_binding_ids=bindings,
                rationale="Point-input DC thermal nodal solve.",
            ),
        )
        for node_id, value in sorted(result_by_node.items())
    )
    return ElectrothermalSolveResult(
        network_id=network.network_id,
        network_fingerprint=network.semantic_fingerprint(),
        disposition="solved",
        node_results=results,
        missing_input_ids=(),
        findings=(
            "This point solve is not an interval, transient, CFD, or correlated thermal claim.",
        ),
    )


def solve_coupled_electrothermal_point(
    model: CoupledElectrothermalPointModel,
) -> CoupledElectrothermalPointResult:
    """Iterate R(T), I^2R loss, and junction temperature for point inputs."""

    inputs = (
        ("ambient_temperature", model.ambient_temperature),
        ("current_rms", model.current_rms),
        ("conduction_fraction", model.conduction_fraction),
        ("resistance_reference", model.resistance_reference),
        ("resistance_reference_temperature", model.resistance_reference_temperature),
        (
            "resistance_temperature_coefficient",
            model.resistance_temperature_coefficient,
        ),
        ("fixed_loss", model.fixed_loss),
        ("junction_to_ambient_rth", model.junction_to_ambient_rth),
        ("convergence_tolerance", model.convergence_tolerance),
    )
    missing = tuple(sorted(identity for identity, quantity in inputs if not _is_point(quantity)))

    def unknown(quantity_id: str, unit: str, rationale: str) -> BoundedQuantity:
        return BoundedQuantity(
            quantity_id=quantity_id,
            unit=unit,
            knowledge=QuantityKnowledge.UNRESOLVED,
            rationale=rationale,
        )

    unknown_temperature = unknown(
        "coupled_junction_temperature",
        "degC",
        "Coupled electrothermal point inputs are unresolved or interval-valued.",
    )
    unknown_conduction = unknown(
        "coupled_conduction_loss",
        "W",
        "Coupled electrothermal point inputs are unresolved or interval-valued.",
    )
    unknown_total = unknown(
        "coupled_total_loss",
        "W",
        "Coupled electrothermal point inputs are unresolved or interval-valued.",
    )
    unknown_residual = unknown(
        "coupled_temperature_residual",
        "K",
        "No converged temperature residual is available.",
    )
    if missing:
        return CoupledElectrothermalPointResult(
            model_id=model.model_id,
            model_fingerprint=model.semantic_fingerprint(),
            disposition="indeterminate",
            junction_temperature=unknown_temperature,
            conduction_loss=unknown_conduction,
            total_loss=unknown_total,
            iterations=0,
            residual=unknown_residual,
            missing_input_ids=missing,
            findings=(
                "The solver accepts only point inputs and never collapses bounds to nominal.",
            ),
        )
    values = [quantity.nominal for _, quantity in inputs]
    assert all(value is not None for value in values)
    (
        ambient,
        current,
        fraction,
        resistance,
        reference_temperature,
        coefficient,
        fixed_loss,
        thermal_resistance,
        tolerance,
    ) = values
    assert ambient is not None
    assert current is not None
    assert fraction is not None
    assert resistance is not None
    assert reference_temperature is not None
    assert coefficient is not None
    assert fixed_loss is not None
    assert thermal_resistance is not None
    assert tolerance is not None
    if (
        current < 0
        or fraction < 0
        or fraction > 1
        or resistance <= 0
        or coefficient < 0
        or fixed_loss < 0
        or thermal_resistance <= 0
        or tolerance <= 0
    ):
        raise ValueError("coupled electrothermal point inputs violate physical bounds")
    loop_gain = thermal_resistance * current * current * fraction * resistance * coefficient
    if loop_gain >= 1:
        return CoupledElectrothermalPointResult(
            model_id=model.model_id,
            model_fingerprint=model.semantic_fingerprint(),
            disposition="nonconvergent",
            junction_temperature=unknown_temperature,
            conduction_loss=unknown_conduction,
            total_loss=unknown_total,
            iterations=0,
            residual=unknown_residual,
            missing_input_ids=("model:stable_electrothermal_loop_gain",),
            findings=(
                f"Linearized electrothermal loop gain is {loop_gain}; it must be below 1.",
            ),
        )
    temperature = ambient
    conduction = Decimal("0")
    total = fixed_loss
    residual_value = Decimal("Infinity")
    iteration = 0
    with localcontext() as context:
        context.prec = 50
        for _iteration in range(1, model.max_iterations + 1):
            iteration = _iteration
            multiplier = Decimal("1") + coefficient * (
                temperature - reference_temperature
            )
            if multiplier <= 0:
                raise ValueError("temperature-adjusted resistance became non-positive")
            conduction = current * current * fraction * resistance * multiplier
            total = conduction + fixed_loss
            updated = ambient + thermal_resistance * total
            residual_value = abs(updated - temperature)
            temperature = updated
            if residual_value <= tolerance:
                break
        else:
            return CoupledElectrothermalPointResult(
                model_id=model.model_id,
                model_fingerprint=model.semantic_fingerprint(),
                disposition="nonconvergent",
                junction_temperature=unknown_temperature,
                conduction_loss=unknown_conduction,
                total_loss=unknown_total,
                iterations=model.max_iterations,
                residual=unknown_residual,
                missing_input_ids=("model:iteration_convergence",),
                findings=("Iteration limit reached before the requested tolerance.",),
            )
    bindings = tuple(
        sorted(
            {
                *model.source_context_ids,
                *(binding for _, quantity in inputs for binding in quantity.evidence_binding_ids),
            }
        )
    )

    def derived(quantity_id: str, unit: str, value: Decimal, rationale: str) -> BoundedQuantity:
        return BoundedQuantity(
            quantity_id=quantity_id,
            unit=unit,
            knowledge=QuantityKnowledge.DERIVED_BOUNDED,
            lower=value,
            nominal=value,
            upper=value,
            evidence_binding_ids=bindings,
            rationale=rationale,
        )

    return CoupledElectrothermalPointResult(
        model_id=model.model_id,
        model_fingerprint=model.semantic_fingerprint(),
        disposition="solved",
        junction_temperature=derived(
            "coupled_junction_temperature",
            "degC",
            temperature,
            "Converged point-input temperature-dependent resistance screening.",
        ),
        conduction_loss=derived(
            "coupled_conduction_loss",
            "W",
            conduction,
            "I^2R conduction loss at the converged junction temperature.",
        ),
        total_loss=derived(
            "coupled_total_loss",
            "W",
            total,
            "Conduction plus fixed point-valued loss at convergence.",
        ),
        iterations=iteration,
        residual=derived(
            "coupled_temperature_residual",
            "K",
            residual_value,
            "Absolute temperature change in the final fixed-point iteration.",
        ),
        missing_input_ids=(),
        findings=(
            "This is a single-subject point screening model, not an interval, CFD, "
            "commutation, or correlated assembly claim.",
        ),
    )


def solve_transient_foster_step_point(
    model: TransientThermalModel,
) -> TransientThermalResult:
    """Solve a point-valued Foster step response without nominal substitution."""

    inputs = (
        ("ambient_temperature", model.ambient_temperature),
        ("step_power", model.step_power),
        ("duration", model.duration),
        *(
            item
            for branch in model.branches
            for item in (
                (
                    f"branch:{branch.branch_id}:thermal_resistance",
                    branch.thermal_resistance,
                ),
                (f"branch:{branch.branch_id}:time_constant", branch.time_constant),
            )
        ),
    )
    missing = tuple(sorted(identity for identity, value in inputs if not _is_point(value)))
    unknown_temperature = BoundedQuantity(
        quantity_id="transient_endpoint_temperature",
        unit="degC",
        knowledge=QuantityKnowledge.UNRESOLVED,
        rationale="Transient thermal inputs are unresolved or interval-valued.",
    )
    unknown_rise = BoundedQuantity(
        quantity_id="transient_temperature_rise",
        unit="K",
        knowledge=QuantityKnowledge.UNRESOLVED,
        rationale="Transient thermal inputs are unresolved or interval-valued.",
    )
    if missing:
        return TransientThermalResult(
            model_id=model.model_id,
            model_fingerprint=model.semantic_fingerprint(),
            disposition="indeterminate",
            endpoint_temperature=unknown_temperature,
            temperature_rise=unknown_rise,
            missing_input_ids=missing,
            findings=(
                "Version 1 accepts only point-valued Foster parameters and does not "
                "digitize or fit a datasheet graph automatically.",
            ),
        )
    assert model.ambient_temperature.nominal is not None
    assert model.step_power.nominal is not None
    assert model.duration.nominal is not None
    if model.step_power.nominal < 0 or model.duration.nominal < 0:
        raise ValueError("transient power and duration must be non-negative")
    rise = Decimal("0")
    with localcontext() as context:
        context.prec = 50
        for branch in model.branches:
            resistance = branch.thermal_resistance.nominal
            time_constant = branch.time_constant.nominal
            assert resistance is not None and time_constant is not None
            if resistance <= 0 or time_constant <= 0:
                raise ValueError("Foster resistance and time constant must be positive")
            response = Decimal("1") - (-model.duration.nominal / time_constant).exp()
            rise += model.step_power.nominal * resistance * response
    endpoint = model.ambient_temperature.nominal + rise
    bindings = tuple(
        sorted(
            {
                *model.source_context_ids,
                *model.ambient_temperature.evidence_binding_ids,
                *model.step_power.evidence_binding_ids,
                *model.duration.evidence_binding_ids,
                *(binding for branch in model.branches for binding in branch.source_binding_ids),
            }
        )
    )

    def derived(quantity_id: str, unit: str, value: Decimal) -> BoundedQuantity:
        return BoundedQuantity(
            quantity_id=quantity_id,
            unit=unit,
            knowledge=QuantityKnowledge.DERIVED_BOUNDED,
            lower=value,
            nominal=value,
            upper=value,
            evidence_binding_ids=bindings,
            rationale="Point-valued Foster step response.",
        )

    return TransientThermalResult(
        model_id=model.model_id,
        model_fingerprint=model.semantic_fingerprint(),
        disposition="solved",
        endpoint_temperature=derived(
            "transient_endpoint_temperature",
            "degC",
            endpoint,
        ),
        temperature_rise=derived("transient_temperature_rise", "K", rise),
        missing_input_ids=(),
        findings=(
            "The result is a point-input Foster screening result, not a correlated "
            "assembly temperature claim.",
        ),
    )
