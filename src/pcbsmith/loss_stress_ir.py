"""Source-bound component/path loss ledger and conservative stress comparison."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import Field, model_validator

from pcbsmith.engineering_quantity_ir import (
    BoundedQuantity,
    QuantityKnowledge,
    canonical_engineering_identities,
    require_engineering_identity,
)
from pcbsmith.semantic_ir import SemanticIrModel


class LossMechanism(StrEnum):
    CONDUCTION_I2R = "conduction_i2r"
    SWITCHING = "switching"
    GATE_DRIVE = "gate_drive"
    BODY_DIODE_DEAD_TIME = "body_diode_dead_time"
    QUIESCENT = "quiescent"
    CAPACITOR_ESR = "capacitor_esr"
    MAGNETIC_CORE = "magnetic_core"
    MAGNETIC_COPPER = "magnetic_copper"
    CONNECTOR_CONTACT = "connector_contact"
    PCB_COPPER = "pcb_copper"
    CLAMP_OR_TVS = "clamp_or_tvs"


class LossCalculationState(StrEnum):
    COMPUTED = "computed"
    UNRESOLVED = "unresolved"
    OUT_OF_SCOPE = "out_of_scope"
    VALIDATION_REQUIRED = "validation_required"


class LossEntry(SemanticIrModel):
    schema_id: Literal["pcbsmith-loss-entry"] = "pcbsmith-loss-entry"
    schema_version: Literal[1] = 1
    entry_id: str
    loss_identity_id: str
    scenario_id: str
    subject_ids: tuple[str, ...]
    mechanism: LossMechanism
    model_id: str
    model_version: int = Field(ge=1)
    state: LossCalculationState
    inputs: tuple[BoundedQuantity, ...]
    output_power: BoundedQuantity
    source_binding_ids: tuple[str, ...]
    applicability_condition_ids: tuple[str, ...] = ()
    missing_input_ids: tuple[str, ...] = ()
    findings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def loss_is_coherent(self) -> Self:
        for field_name in ("entry_id", "loss_identity_id", "scenario_id", "model_id"):
            require_engineering_identity(getattr(self, field_name), field_name)
        inputs = tuple(sorted(self.inputs, key=lambda item: item.quantity_id))
        if len(inputs) != len({item.quantity_id for item in inputs}):
            raise ValueError("loss input quantity identities must be unique")
        object.__setattr__(self, "inputs", inputs)
        for field_name in (
            "subject_ids",
            "source_binding_ids",
            "applicability_condition_ids",
            "missing_input_ids",
        ):
            values = canonical_engineering_identities(getattr(self, field_name), field_name)
            object.__setattr__(self, field_name, values)
        if not self.subject_ids:
            raise ValueError("loss entries require at least one physical subject")
        if self.output_power.unit != "W":
            raise ValueError("loss outputs must use watts")
        if self.state is LossCalculationState.COMPUTED:
            if not self.output_power.is_known or self.missing_input_ids:
                raise ValueError("computed loss requires known output and no missing inputs")
            if any(not item.is_known for item in inputs):
                raise ValueError("computed loss cannot consume unresolved inputs")
            assert self.output_power.lower is not None
            if self.output_power.lower < 0:
                raise ValueError("computed loss cannot be negative")
            if not self.source_binding_ids:
                raise ValueError("computed loss requires model/source bindings")
        elif self.state is LossCalculationState.UNRESOLVED:
            if self.output_power.is_known or not self.missing_input_ids:
                raise ValueError("unresolved loss requires unknown output and missing inputs")
        elif self.state is LossCalculationState.VALIDATION_REQUIRED:
            if not self.output_power.is_known or self.missing_input_ids:
                raise ValueError(
                    "validation-required screening requires numeric output and no missing inputs"
                )
            if not self.source_binding_ids or not self.findings:
                raise ValueError(
                    "validation-required screening requires bindings and limitations"
                )
            if not self.applicability_condition_ids:
                raise ValueError(
                    "validation-required screening requires explicit applicability conditions"
                )
        return self


class LossStressLedger(SemanticIrModel):
    schema_id: Literal["pcbsmith-loss-stress-ledger"] = "pcbsmith-loss-stress-ledger"
    schema_version: Literal[1] = 1
    ledger_id: str
    mission_profile_id: str
    mission_profile_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    losses: tuple[LossEntry, ...]
    stress_limits: tuple[StressLimit, ...] = ()
    stress_results: tuple[StressResult, ...] = ()
    source_context_ids: tuple[str, ...]

    @model_validator(mode="after")
    def ledger_is_canonical(self) -> Self:
        require_engineering_identity(self.ledger_id, "ledger_id")
        require_engineering_identity(self.mission_profile_id, "mission_profile_id")
        losses = tuple(sorted(self.losses, key=lambda item: item.entry_id))
        if len(losses) != len({item.entry_id for item in losses}):
            raise ValueError("loss entry identities must be unique")
        if len(losses) != len({item.loss_identity_id for item in losses}):
            raise ValueError("physical loss identities must be unique to prevent double counting")
        limits = tuple(sorted(self.stress_limits, key=lambda item: item.limit_id))
        if len(limits) != len({item.limit_id for item in limits}):
            raise ValueError("stress limit identities must be unique")
        results = tuple(sorted(self.stress_results, key=lambda item: item.result_id))
        if len(results) != len({item.result_id for item in results}):
            raise ValueError("stress result identities must be unique")
        known_limits = {item.limit_id for item in limits}
        if any(item.limit_id not in known_limits for item in results):
            raise ValueError("stress result references a limit absent from the ledger")
        contexts = canonical_engineering_identities(
            self.source_context_ids,
            "source_context_ids",
        )
        if not contexts:
            raise ValueError("loss/stress ledger requires source context")
        object.__setattr__(self, "losses", losses)
        object.__setattr__(self, "stress_limits", limits)
        object.__setattr__(self, "stress_results", results)
        object.__setattr__(self, "source_context_ids", contexts)
        return self


class StressLimit(SemanticIrModel):
    schema_id: Literal["pcbsmith-stress-limit"] = "pcbsmith-stress-limit"
    schema_version: Literal[1] = 1
    limit_id: str
    subject_id: str
    parameter_id: str
    maximum_allowed: BoundedQuantity
    derating_policy_id: str
    evidence_binding_ids: tuple[str, ...]

    @model_validator(mode="after")
    def limit_is_source_bound(self) -> Self:
        for field_name in ("limit_id", "subject_id", "parameter_id", "derating_policy_id"):
            require_engineering_identity(getattr(self, field_name), field_name)
        if not self.maximum_allowed.is_known:
            raise ValueError("stress limit must be a known conservative interval")
        evidence = canonical_engineering_identities(
            self.evidence_binding_ids,
            "evidence_binding_ids",
        )
        if not evidence:
            raise ValueError("stress limits require evidence bindings")
        object.__setattr__(self, "evidence_binding_ids", evidence)
        return self


class StressResult(SemanticIrModel):
    schema_id: Literal["pcbsmith-stress-result"] = "pcbsmith-stress-result"
    schema_version: Literal[1] = 1
    result_id: str
    scenario_id: str
    subject_id: str
    parameter_id: str
    observed: BoundedQuantity
    limit_id: str
    disposition: Literal["pass", "fail", "indeterminate"]
    conservative_margin: BoundedQuantity
    findings: tuple[str, ...] = ()


class LossCoverageRequirement(SemanticIrModel):
    schema_id: Literal["pcbsmith-loss-coverage-requirement"] = "pcbsmith-loss-coverage-requirement"
    schema_version: Literal[1] = 1
    requirement_id: str
    scenario_id: str
    subject_id: str
    required_mechanisms: tuple[LossMechanism, ...]
    rationale: str

    @model_validator(mode="after")
    def requirement_is_canonical(self) -> Self:
        for field_name in ("requirement_id", "scenario_id", "subject_id", "rationale"):
            require_engineering_identity(getattr(self, field_name), field_name)
        mechanisms = tuple(sorted(set(self.required_mechanisms), key=lambda item: item.value))
        if not mechanisms:
            raise ValueError("loss coverage requirement needs at least one mechanism")
        if len(mechanisms) != len(self.required_mechanisms):
            raise ValueError("required loss mechanisms must be unique")
        object.__setattr__(self, "required_mechanisms", mechanisms)
        return self


class LossCoverageEvaluation(SemanticIrModel):
    schema_id: Literal["pcbsmith-loss-coverage-evaluation"] = "pcbsmith-loss-coverage-evaluation"
    schema_version: Literal[1] = 1
    requirement_id: str
    disposition: Literal["complete", "incomplete"]
    computed_entry_ids: tuple[str, ...]
    unresolved_mechanisms: tuple[LossMechanism, ...]
    findings: tuple[str, ...] = ()


class LossCoverageReport(SemanticIrModel):
    schema_id: Literal["pcbsmith-loss-coverage-report"] = "pcbsmith-loss-coverage-report"
    schema_version: Literal[1] = 1
    ledger_id: str
    ledger_fingerprint: str
    disposition: Literal["complete", "incomplete"]
    evaluations: tuple[LossCoverageEvaluation, ...]


def calculate_i2r_loss(
    *,
    entry_id: str,
    loss_identity_id: str,
    scenario_id: str,
    subject_ids: tuple[str, ...],
    mechanism: LossMechanism,
    current: BoundedQuantity,
    resistance: BoundedQuantity,
    source_binding_ids: tuple[str, ...],
) -> LossEntry:
    if current.unit != "A" or resistance.unit != "ohm":
        raise ValueError("I^2R loss requires current in A and resistance in ohm")
    missing = tuple(
        quantity.quantity_id for quantity in (current, resistance) if not quantity.is_known
    )
    if missing:
        return LossEntry(
            entry_id=entry_id,
            loss_identity_id=loss_identity_id,
            scenario_id=scenario_id,
            subject_ids=subject_ids,
            mechanism=mechanism,
            model_id="pcbsmith.i2r.interval",
            model_version=1,
            state=LossCalculationState.UNRESOLVED,
            inputs=(current, resistance),
            output_power=BoundedQuantity(
                quantity_id="power_loss",
                unit="W",
                knowledge=QuantityKnowledge.UNRESOLVED,
                rationale="I^2R inputs are unresolved: " + ", ".join(missing),
            ),
            source_binding_ids=source_binding_ids,
            missing_input_ids=missing,
            findings=("No numeric loss is emitted until every interval input is known.",),
        )
    assert current.lower is not None and current.nominal is not None and current.upper is not None
    assert resistance.lower is not None
    assert resistance.nominal is not None
    assert resistance.upper is not None
    if current.lower < 0 or resistance.lower < 0:
        raise ValueError("I^2R interval inputs must be non-negative")
    evidence = tuple(
        sorted(
            {
                *source_binding_ids,
                *current.evidence_binding_ids,
                *resistance.evidence_binding_ids,
            }
        )
    )
    return LossEntry(
        entry_id=entry_id,
        loss_identity_id=loss_identity_id,
        scenario_id=scenario_id,
        subject_ids=subject_ids,
        mechanism=mechanism,
        model_id="pcbsmith.i2r.interval",
        model_version=1,
        state=LossCalculationState.COMPUTED,
        inputs=(current, resistance),
        output_power=BoundedQuantity(
            quantity_id="power_loss",
            unit="W",
            knowledge=QuantityKnowledge.DERIVED_BOUNDED,
            lower=current.lower**2 * resistance.lower,
            nominal=current.nominal**2 * resistance.nominal,
            upper=current.upper**2 * resistance.upper,
            evidence_binding_ids=evidence,
            rationale="Conservative monotonic interval evaluation of P = I_rms^2 R.",
        ),
        source_binding_ids=evidence,
    )


def unresolved_loss_entry(
    *,
    entry_id: str,
    loss_identity_id: str,
    scenario_id: str,
    subject_ids: tuple[str, ...],
    mechanism: LossMechanism,
    missing_input_ids: tuple[str, ...],
    source_binding_ids: tuple[str, ...],
    rationale: str,
) -> LossEntry:
    """Create a non-numeric loss entry without disguising missing inputs as zero."""

    require_engineering_identity(rationale, "rationale")
    return LossEntry(
        entry_id=entry_id,
        loss_identity_id=loss_identity_id,
        scenario_id=scenario_id,
        subject_ids=subject_ids,
        mechanism=mechanism,
        model_id="pcbsmith.unresolved.explicit",
        model_version=1,
        state=LossCalculationState.UNRESOLVED,
        inputs=(),
        output_power=BoundedQuantity(
            quantity_id="power_loss",
            unit="W",
            knowledge=QuantityKnowledge.UNRESOLVED,
            rationale=rationale,
        ),
        source_binding_ids=source_binding_ids,
        missing_input_ids=missing_input_ids,
        findings=(rationale,),
    )


def calculate_i2r_duty_screening(
    *,
    entry_id: str,
    loss_identity_id: str,
    scenario_id: str,
    subject_ids: tuple[str, ...],
    current: BoundedQuantity,
    resistance: BoundedQuantity,
    conduction_fraction: BoundedQuantity,
    source_binding_ids: tuple[str, ...],
    applicability_condition_ids: tuple[str, ...],
    findings: tuple[str, ...],
) -> LossEntry:
    """Calculate an assumption-bearing I^2 R duty screen that cannot satisfy coverage."""

    if current.unit != "A" or resistance.unit != "ohm":
        raise ValueError("I^2R duty screening requires current in A and resistance in ohm")
    if conduction_fraction.unit != "ratio":
        raise ValueError("conduction fraction must use the dimensionless ratio unit")
    missing = tuple(
        item.quantity_id
        for item in (current, resistance, conduction_fraction)
        if not item.is_known
    )
    if missing:
        return unresolved_loss_entry(
            entry_id=entry_id,
            loss_identity_id=loss_identity_id,
            scenario_id=scenario_id,
            subject_ids=subject_ids,
            mechanism=LossMechanism.CONDUCTION_I2R,
            missing_input_ids=missing,
            source_binding_ids=source_binding_ids,
            rationale="I^2R duty-screening inputs are unresolved: " + ", ".join(missing),
        )
    assert current.lower is not None and current.nominal is not None and current.upper is not None
    assert resistance.lower is not None
    assert resistance.nominal is not None
    assert resistance.upper is not None
    assert conduction_fraction.lower is not None
    assert conduction_fraction.nominal is not None
    assert conduction_fraction.upper is not None
    if current.lower < 0 or resistance.lower < 0:
        raise ValueError("I^2R duty-screening inputs must be non-negative")
    if not Decimal("0") <= conduction_fraction.lower <= conduction_fraction.upper <= Decimal(
        "1"
    ):
        raise ValueError("conduction fraction must remain between zero and one")
    evidence = tuple(
        sorted(
            {
                *source_binding_ids,
                *current.evidence_binding_ids,
                *resistance.evidence_binding_ids,
                *conduction_fraction.evidence_binding_ids,
            }
        )
    )
    return LossEntry(
        entry_id=entry_id,
        loss_identity_id=loss_identity_id,
        scenario_id=scenario_id,
        subject_ids=subject_ids,
        mechanism=LossMechanism.CONDUCTION_I2R,
        model_id="pcbsmith.i2r-duty.screening",
        model_version=1,
        state=LossCalculationState.VALIDATION_REQUIRED,
        inputs=(current, resistance, conduction_fraction),
        output_power=BoundedQuantity(
            quantity_id="power_loss_screening",
            unit="W",
            knowledge=QuantityKnowledge.DERIVED_BOUNDED,
            lower=current.lower**2 * resistance.lower * conduction_fraction.lower,
            nominal=(
                current.nominal**2
                * resistance.nominal
                * conduction_fraction.nominal
            ),
            upper=current.upper**2 * resistance.upper * conduction_fraction.upper,
            evidence_binding_ids=evidence,
            rationale=(
                "Screening-only monotonic interval evaluation of P = I_rms^2 R duty."
            ),
        ),
        source_binding_ids=evidence,
        applicability_condition_ids=applicability_condition_ids,
        findings=findings,
    )


def compare_maximum_stress(
    *,
    result_id: str,
    scenario_id: str,
    observed: BoundedQuantity,
    limit: StressLimit,
) -> StressResult:
    maximum = limit.maximum_allowed
    findings: tuple[str, ...]
    if observed.unit != maximum.unit:
        raise ValueError("stress observation and limit units must match exactly")
    if not observed.is_known:
        margin = BoundedQuantity(
            quantity_id="stress_margin",
            unit=observed.unit,
            knowledge=QuantityKnowledge.UNRESOLVED,
            rationale="Observed stress is unresolved.",
        )
        disposition: Literal["pass", "fail", "indeterminate"] = "indeterminate"
        findings = ("No pass/fail claim is possible without a bounded observation.",)
    else:
        assert observed.lower is not None and observed.nominal is not None
        assert observed.upper is not None
        assert maximum.lower is not None and maximum.nominal is not None
        assert maximum.upper is not None
        lower_margin = maximum.lower - observed.upper
        nominal_margin = maximum.nominal - observed.nominal
        upper_margin = maximum.upper - observed.lower
        if observed.upper <= maximum.lower:
            disposition = "pass"
        elif observed.lower > maximum.upper:
            disposition = "fail"
        else:
            disposition = "indeterminate"
        margin = BoundedQuantity(
            quantity_id="stress_margin",
            unit=observed.unit,
            knowledge=QuantityKnowledge.DERIVED_BOUNDED,
            lower=lower_margin,
            nominal=nominal_margin,
            upper=upper_margin,
            evidence_binding_ids=limit.evidence_binding_ids,
            rationale="Guaranteed-limit interval minus observed-stress interval.",
        )
        findings = ()
    return StressResult(
        result_id=result_id,
        scenario_id=scenario_id,
        subject_id=limit.subject_id,
        parameter_id=limit.parameter_id,
        observed=observed,
        limit_id=limit.limit_id,
        disposition=disposition,
        conservative_margin=margin,
        findings=findings,
    )


def evaluate_loss_coverage(
    ledger: LossStressLedger,
    requirements: tuple[LossCoverageRequirement, ...],
) -> LossCoverageReport:
    ordered = tuple(sorted(requirements, key=lambda item: item.requirement_id))
    if len(ordered) != len({item.requirement_id for item in ordered}):
        raise ValueError("loss coverage requirement identities must be unique")
    evaluations: list[LossCoverageEvaluation] = []
    for requirement in ordered:
        candidates = tuple(
            item
            for item in ledger.losses
            if item.scenario_id == requirement.scenario_id
            and requirement.subject_id in item.subject_ids
        )
        computed: list[str] = []
        unresolved: list[LossMechanism] = []
        for mechanism in requirement.required_mechanisms:
            matching = tuple(item for item in candidates if item.mechanism is mechanism)
            if any(item.state is LossCalculationState.COMPUTED for item in matching):
                computed.extend(
                    item.entry_id
                    for item in matching
                    if item.state is LossCalculationState.COMPUTED
                )
            else:
                unresolved.append(mechanism)
        evaluations.append(
            LossCoverageEvaluation(
                requirement_id=requirement.requirement_id,
                disposition="incomplete" if unresolved else "complete",
                computed_entry_ids=tuple(sorted(computed)),
                unresolved_mechanisms=tuple(unresolved),
                findings=(
                    ()
                    if not unresolved
                    else (
                        "Required mechanisms unresolved: "
                        + ", ".join(item.value for item in unresolved),
                    )
                ),
            )
        )
    disposition: Literal["complete", "incomplete"] = (
        "complete" if all(item.disposition == "complete" for item in evaluations) else "incomplete"
    )
    return LossCoverageReport(
        ledger_id=ledger.ledger_id,
        ledger_fingerprint=ledger.semantic_fingerprint(),
        disposition=disposition,
        evaluations=tuple(evaluations),
    )
