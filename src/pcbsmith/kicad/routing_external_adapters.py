"""Research adapters for pinned, otherwise-unmodified external routers.

These adapters are intentionally thin process boundaries. They never accept an
external engine's own DRC as release evidence; candidate transactions still
require independent KiCad and PCBSmith validation.
"""

from __future__ import annotations

import hashlib
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, fields
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import model_validator

from pcbsmith.kicad.board import BoardLayout
from pcbsmith.kicad.routing_candidate_adapter import native_layout_route_deltas
from pcbsmith.routed_copper_graph_ir import fingerprint, require_identity, require_sha256
from pcbsmith.routing_ir import (
    ConstraintConsumption,
    PartialCandidateStatus,
    RouteCandidateResult,
    RouteConstraintDisposition,
    RouteFailureEvidence,
    RouteFailureKind,
    RouteRequest,
    RouteTerminationEvidence,
    RouteTerminationState,
    RoutingEngineIdentity,
    validate_route_candidate_result,
)
from pcbsmith.semantic_ir import SemanticIrModel

_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class ExternalRouterFamily(StrEnum):
    KICAD_ROUTING_TOOLS = "kicad_routing_tools"
    FREEROUTING = "freerouting"


class ExternalInterchangeKind(StrEnum):
    KICAD_BOARD = "kicad_board"
    SPECCTRA_DSN_SES = "specctra_dsn_ses"


class ExternalRouterRole(StrEnum):
    RESEARCH_CANDIDATE = "research_candidate"
    LEGACY_ORACLE = "legacy_oracle"
    EXPERIMENTAL = "experimental"


class PinnedExternalRouterSpec(SemanticIrModel):
    """Audited source identity and intended use for one untouched engine."""

    schema_id: Literal["pcbsmith-pinned-external-router"] = "pcbsmith-pinned-external-router"
    schema_version: Literal[1] = 1
    engine_id: str
    family: ExternalRouterFamily
    version: str
    source_revision: str
    interchange: ExternalInterchangeKind
    role: ExternalRouterRole
    headless: bool
    limitations: tuple[str, ...]
    spec_fingerprint: str

    @model_validator(mode="after")
    def spec_is_pinned(self) -> Self:
        for field_name in ("engine_id", "version", "source_revision"):
            require_identity(getattr(self, field_name), field_name)
        if not self.limitations:
            raise ValueError("external research router requires explicit limitations")
        require_sha256(self.spec_fingerprint, "spec_fingerprint")
        payload = self.model_dump(mode="json", exclude={"spec_fingerprint"})
        if self.spec_fingerprint != fingerprint(payload):
            raise ValueError("external router specification fingerprint is stale")
        return self

    @classmethod
    def build(cls, **values: Any) -> PinnedExternalRouterSpec:
        fields = dict(values)
        fields["limitations"] = tuple(sorted(fields["limitations"]))
        provisional = cls.model_construct(**fields, spec_fingerprint="0" * 64)
        return cls(
            **fields,
            spec_fingerprint=fingerprint(
                provisional.model_dump(mode="json", exclude={"spec_fingerprint"})
            ),
        )


KRT_V0_19_0 = PinnedExternalRouterSpec.build(
    engine_id="kicad-routing-tools-v0.19.0",
    family=ExternalRouterFamily.KICAD_ROUTING_TOOLS,
    version="0.19.0",
    source_revision="9f0bf5025a03c6856a93f13f68ae6f667f3ba060",
    interchange=ExternalInterchangeKind.KICAD_BOARD,
    role=ExternalRouterRole.RESEARCH_CANDIDATE,
    headless=True,
    limitations=(
        "direct KiCad rewrite requires immutable read-back comparison",
        "external expansion budgets are not mapped exactly",
        "only generic single-ended routing is in H0 scope",
    ),
)

FREEROUTING_V1_9_0 = PinnedExternalRouterSpec.build(
    engine_id="freerouting-v1.9.0-oracle",
    family=ExternalRouterFamily.FREEROUTING,
    version="1.9.0",
    source_revision="v1.9.0",
    interchange=ExternalInterchangeKind.SPECCTRA_DSN_SES,
    role=ExternalRouterRole.LEGACY_ORACLE,
    headless=False,
    limitations=(
        "legacy oracle is not a qualified headless production adapter",
        "Specctra DSN/SES is lossy",
        "external expansion budgets are not mapped exactly",
    ),
)

FREEROUTING_V2_2_4 = PinnedExternalRouterSpec.build(
    engine_id="freerouting-v2.2.4",
    family=ExternalRouterFamily.FREEROUTING,
    version="2.2.4",
    source_revision="20f1a72e546b9b23c7ba5127086885cfacbdd4be",
    interchange=ExternalInterchangeKind.SPECCTRA_DSN_SES,
    role=ExternalRouterRole.RESEARCH_CANDIDATE,
    headless=True,
    limitations=(
        "Specctra DSN/SES is lossy",
        "external expansion budgets are not mapped exactly",
        "KiCad board-edge clearance requires independent validation",
    ),
)

FREEROUTING_V2_3_0 = PinnedExternalRouterSpec.build(
    engine_id="freerouting-v2.3.0",
    family=ExternalRouterFamily.FREEROUTING,
    version="2.3.0",
    source_revision="v2.3.0",
    interchange=ExternalInterchangeKind.SPECCTRA_DSN_SES,
    role=ExternalRouterRole.RESEARCH_CANDIDATE,
    headless=True,
    limitations=(
        "Specctra DSN/SES is lossy",
        "external expansion budgets are not mapped exactly",
        "plane and filled-zone topology require independent KiCad validation",
    ),
)


FREEROUTING_MASTER_2026_07_09 = PinnedExternalRouterSpec.build(
    engine_id="freerouting-master-4514092",
    family=ExternalRouterFamily.FREEROUTING,
    version="master-2026-07-09",
    source_revision="4514092128a7539d5014f14c13215a0b3f989e33",
    interchange=ExternalInterchangeKind.SPECCTRA_DSN_SES,
    role=ExternalRouterRole.EXPERIMENTAL,
    headless=True,
    limitations=(
        "experimental unreleased revision",
        "KiCad JSON interchange is deliberately excluded from H0",
        "Specctra DSN/SES is lossy",
        "external expansion budgets are not mapped exactly",
    ),
)

PINNED_H0_EXTERNAL_ROUTERS = (
    KRT_V0_19_0,
    FREEROUTING_V1_9_0,
    FREEROUTING_V2_2_4,
    FREEROUTING_V2_3_0,
    FREEROUTING_MASTER_2026_07_09,
)


class ExternalToolBinding(SemanticIrModel):
    """Exact local executable/distribution identity supplied to an adapter."""

    schema_id: Literal["pcbsmith-external-tool-binding"] = "pcbsmith-external-tool-binding"
    schema_version: Literal[1] = 1
    root_path: str
    entrypoint_path: str
    entrypoint_sha256: str
    distribution_sha256: str

    @model_validator(mode="after")
    def binding_is_complete(self) -> Self:
        require_identity(self.root_path, "root_path")
        require_identity(self.entrypoint_path, "entrypoint_path")
        require_sha256(self.entrypoint_sha256, "entrypoint_sha256")
        require_sha256(self.distribution_sha256, "distribution_sha256")
        return self


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def external_distribution_sha256(root: Path) -> str:
    """Hash one file or a complete external-tool tree deterministically."""

    resolved = root.resolve()
    if resolved.is_file():
        return _file_sha256(resolved)
    if not resolved.is_dir():
        raise ValueError(f"external tool root does not exist: {resolved}")
    records = [
        {
            "relative_path": path.relative_to(resolved).as_posix(),
            "content_sha256": _file_sha256(path),
        }
        for path in sorted(resolved.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    ]
    if not records:
        raise ValueError("external tool distribution is empty")
    return hashlib.sha256(
        __import__("json")
        .dumps(
            records,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        .encode("utf-8")
    ).hexdigest()


def verify_external_tool_binding(binding: ExternalToolBinding) -> Path:
    """Resolve and verify the exact untouched executable before launch."""

    root = Path(binding.root_path).resolve()
    entrypoint = Path(binding.entrypoint_path).resolve()
    if root.is_dir():
        try:
            entrypoint.relative_to(root)
        except ValueError as exc:
            raise ValueError("external entrypoint is outside its pinned distribution") from exc
    elif root != entrypoint:
        raise ValueError("single-file external distribution must be its entrypoint")
    if not entrypoint.is_file():
        raise ValueError("external router entrypoint is unavailable")
    if _file_sha256(entrypoint) != binding.entrypoint_sha256:
        raise ValueError("external router entrypoint hash is stale")
    if external_distribution_sha256(root) != binding.distribution_sha256:
        raise ValueError("external router distribution hash is stale")
    return entrypoint


@dataclass(frozen=True)
class ExternalProcessResult:
    exit_code: int
    stdout: bytes
    stderr: bytes
    elapsed_seconds: float


class ExternalProcessCancelled(RuntimeError):
    """Raised by an executor when a parent transaction cancels routing."""


ExternalProcessExecutor = Callable[[Sequence[str], Path], ExternalProcessResult]
ExternalLayoutImporter = Callable[[Path], BoardLayout]


def run_external_process(
    command: Sequence[str],
    working_directory: Path,
    *,
    timeout_seconds: int = 900,
) -> ExternalProcessResult:
    """Run an argument-vector process without a shell and retain exact output."""

    started = time.monotonic()
    completed = subprocess.run(
        list(command),
        cwd=working_directory,
        check=False,
        shell=False,
        capture_output=True,
        timeout=timeout_seconds,
    )
    return ExternalProcessResult(
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        elapsed_seconds=max(0.0, time.monotonic() - started),
    )


def _engine_identity(
    spec: PinnedExternalRouterSpec,
    binding: ExternalToolBinding,
) -> RoutingEngineIdentity:
    return RoutingEngineIdentity(
        engine_id=spec.engine_id,
        engine_version=spec.version,
        adapter_id="pcbsmith.kicad.routing_external_adapters",
        adapter_version="1",
        source_commit=spec.source_revision,
        executable_sha256=binding.distribution_sha256,
    )


def _translation_ledger(
    request: RouteRequest,
) -> tuple[tuple[ConstraintConsumption, ...], tuple[RouteFailureEvidence, ...]]:
    unsupported = {
        *(item.constraint_id for item in request.route_guides),
        *(
            item.constraint_id
            for item in request.topology_constraints
            if item.topology_kind != "any_tree"
        ),
        *request.additional_constraint_ids,
    }
    ledger = tuple(
        ConstraintConsumption(
            constraint_id=constraint_id,
            disposition=(
                RouteConstraintDisposition.UNSUPPORTED
                if constraint_id in unsupported
                else RouteConstraintDisposition.CONSUMED
            ),
            backend_constraint_id=(
                None if constraint_id in unsupported else f"external-interchange:{constraint_id}"
            ),
            detail=(
                "constraint has no proven H0 external-interchange translation"
                if constraint_id in unsupported
                else "constraint delegated through the retained external interchange"
            ),
        )
        for constraint_id in request.constraint_ids
    )
    failures = tuple(
        RouteFailureEvidence(
            failure_id=f"failure:external:unsupported:{constraint_id}",
            kind=RouteFailureKind.UNSUPPORTED_CONSTRAINT,
            message="external research adapter cannot translate this constraint",
            constraint_ids=(constraint_id,),
        )
        for constraint_id in sorted(unsupported)
    )
    return ledger, failures


def _failed_result(
    *,
    request: RouteRequest,
    engine: RoutingEngineIdentity,
    ledger: tuple[ConstraintConsumption, ...],
    failures: tuple[RouteFailureEvidence, ...],
    reason: str,
    stdout: bytes = b"",
    stderr: bytes = b"",
    exit_code: int | None = None,
    elapsed_seconds: float = 0.0,
    state: RouteTerminationState = RouteTerminationState.FAILED,
) -> RouteCandidateResult:
    result = RouteCandidateResult(
        request_fingerprint=request.semantic_fingerprint(),
        source_board_sha256=request.inputs.board_sha256,
        engine=engine,
        termination=RouteTerminationEvidence(
            state=state,
            reason=reason,
            exit_code=exit_code,
            stdout_sha256=hashlib.sha256(stdout).hexdigest(),
            stderr_sha256=hashlib.sha256(stderr).hexdigest(),
            elapsed_seconds=elapsed_seconds,
        ),
        partial_status=PartialCandidateStatus.FAILED_NO_DELTA,
        constraint_consumption=ledger,
        failures=failures,
    )
    validate_route_candidate_result(request, result)
    return result


def _write_process_evidence(
    candidate_directory: Path,
    process: ExternalProcessResult,
) -> None:
    engine_dir = candidate_directory / "engine"
    engine_dir.mkdir(parents=True, exist_ok=True)
    (engine_dir / "stdout.log").write_bytes(process.stdout)
    (engine_dir / "stderr.log").write_bytes(process.stderr)


def _nonroute_layout_differences(
    source: BoardLayout,
    candidate: BoardLayout,
) -> tuple[str, ...]:
    route_fields = {"segments", "vias", "zones"}
    return tuple(
        field.name
        for field in fields(source)
        if field.name not in route_fields
        and getattr(source, field.name) != getattr(candidate, field.name)
    )


def _jvm_fatal_signature(stdout: bytes, stderr: bytes) -> str | None:
    combined = (stdout + b"\n" + stderr).decode("utf-8", errors="replace").lower()
    signatures = (
        "java.lang.stackoverflowerror",
        "a fatal error has been detected by the java runtime environment",
        "exception_access_violation",
        "outofmemoryerror",
    )
    return next((signature for signature in signatures if signature in combined), None)


def _run_pinned_external_candidate(
    *,
    request: RouteRequest,
    source_layout: BoardLayout,
    candidate_directory: Path,
    spec: PinnedExternalRouterSpec,
    binding: ExternalToolBinding,
    command: Sequence[str],
    output_file: Path,
    importer: ExternalLayoutImporter,
    executor: ExternalProcessExecutor,
    completion_verifier: Callable[[], bool] | None = None,
) -> RouteCandidateResult:
    engine = _engine_identity(spec, binding)
    ledger, translation_failures = _translation_ledger(request)
    if translation_failures:
        return _failed_result(
            request=request,
            engine=engine,
            ledger=ledger,
            failures=translation_failures,
            reason="constraint_translation_failed",
        )
    try:
        process = executor(command, candidate_directory)
    except subprocess.TimeoutExpired as exc:
        return _failed_result(
            request=request,
            engine=engine,
            ledger=ledger,
            failures=(
                RouteFailureEvidence(
                    failure_id="failure:external:timeout",
                    kind=RouteFailureKind.BUDGET_EXHAUSTED,
                    message="external router exceeded the process time budget",
                    resource_ids=("budget:process_timeout",),
                    retryable=True,
                ),
            ),
            reason="external_process_timeout",
            stdout=exc.stdout or b"",
            stderr=exc.stderr or b"",
            elapsed_seconds=float(exc.timeout),
            state=RouteTerminationState.TIMEOUT,
        )
    except ExternalProcessCancelled:
        return _failed_result(
            request=request,
            engine=engine,
            ledger=ledger,
            failures=(
                RouteFailureEvidence(
                    failure_id="failure:external:cancelled",
                    kind=RouteFailureKind.CANCELLED,
                    message="external router was cancelled",
                ),
            ),
            reason="external_process_cancelled",
            state=RouteTerminationState.CANCELLED,
        )
    _write_process_evidence(candidate_directory, process)
    fatal_signature = _jvm_fatal_signature(process.stdout, process.stderr)
    if fatal_signature is not None:
        return _failed_result(
            request=request,
            engine=engine,
            ledger=ledger,
            failures=(
                RouteFailureEvidence(
                    failure_id="failure:external:jvm-fatal",
                    kind=RouteFailureKind.ENGINE_FAILURE,
                    message=f"external JVM fatal signature: {fatal_signature}",
                    retryable=False,
                ),
            ),
            reason="external_jvm_fatal",
            stdout=process.stdout,
            stderr=process.stderr,
            exit_code=process.exit_code,
            elapsed_seconds=process.elapsed_seconds,
        )
    if process.exit_code != 0 or not output_file.is_file():
        return _failed_result(
            request=request,
            engine=engine,
            ledger=ledger,
            failures=(
                RouteFailureEvidence(
                    failure_id="failure:external:process",
                    kind=RouteFailureKind.ENGINE_FAILURE,
                    message=(
                        f"external router exited {process.exit_code}"
                        if process.exit_code != 0
                        else "external router did not produce its declared output"
                    ),
                    resource_ids=(str(output_file),),
                    retryable=True,
                ),
            ),
            reason="external_process_failed",
            stdout=process.stdout,
            stderr=process.stderr,
            exit_code=process.exit_code,
            elapsed_seconds=process.elapsed_seconds,
        )
    try:
        final_layout = importer(output_file)
        nonroute_differences = _nonroute_layout_differences(source_layout, final_layout)
        if nonroute_differences:
            raise ValueError(
                "external candidate changed immutable layout fields: "
                + ", ".join(nonroute_differences)
            )
        segments, vias, zones = native_layout_route_deltas(
            request=request,
            source_layout=source_layout,
            final_layout=final_layout,
        )
    except Exception as exc:
        return _failed_result(
            request=request,
            engine=engine,
            ledger=ledger,
            failures=(
                RouteFailureEvidence(
                    failure_id="failure:external:import",
                    kind=RouteFailureKind.INVALID_DELTA,
                    message=f"{type(exc).__name__}: {exc}",
                ),
            ),
            reason="external_output_import_failed",
            stdout=process.stdout,
            stderr=process.stderr,
            exit_code=process.exit_code,
            elapsed_seconds=process.elapsed_seconds,
        )
    has_delta = bool(segments or vias or zones)
    budget_failure = RouteFailureEvidence(
        failure_id="failure:external:unmapped-expansion-budget",
        kind=RouteFailureKind.REJECTED_CONSTRAINT,
        message=(
            "external engine completed, but max_expansions and "
            "max_expansions_per_net were not enforced exactly"
        ),
        resource_ids=(
            "budget:max_expansions",
            "budget:max_expansions_per_net",
        ),
    )
    external_budget = request.budget.external_process_seconds
    verified = (
        external_budget is not None
        and process.elapsed_seconds <= external_budget
        and completion_verifier is not None
        and completion_verifier()
    )
    if external_budget is not None and not verified:
        budget_failure = RouteFailureEvidence(
            failure_id="failure:external:unverified-completion",
            kind=RouteFailureKind.REJECTED_CONSTRAINT,
            message="External time limit or independent native completion checks did not pass",
        )
    result = RouteCandidateResult(
        request_fingerprint=request.semantic_fingerprint(),
        source_board_sha256=request.inputs.board_sha256,
        engine=engine,
        termination=RouteTerminationEvidence(
            state=RouteTerminationState.COMPLETED,
            reason="external_process_completed",
            exit_code=process.exit_code,
            stdout_sha256=hashlib.sha256(process.stdout).hexdigest(),
            stderr_sha256=hashlib.sha256(process.stderr).hexdigest(),
            elapsed_seconds=process.elapsed_seconds,
        ),
        partial_status=(
            PartialCandidateStatus.COMPLETE
            if verified
            else PartialCandidateStatus.BOUNDED_PARTIAL
            if has_delta
            else PartialCandidateStatus.FAILED_NO_DELTA
        ),
        segment_deltas=segments,
        via_deltas=vias,
        zone_deltas=zones,
        constraint_consumption=ledger,
        failures=() if verified else (budget_failure,),
    )
    validate_route_candidate_result(request, result)
    return result


def run_freerouting_dsn_ses_candidate(
    *,
    request: RouteRequest,
    source_layout: BoardLayout,
    candidate_directory: Path,
    spec: PinnedExternalRouterSpec,
    binding: ExternalToolBinding,
    dsn_payload: bytes,
    ses_importer: ExternalLayoutImporter,
    java_executable: str = "java",
    executor: ExternalProcessExecutor = run_external_process,
    completion_verifier: Callable[[], bool] | None = None,
) -> RouteCandidateResult:
    """Run a pinned Freerouting JAR through the retained DSN/SES boundary."""

    if (
        spec.family is not ExternalRouterFamily.FREEROUTING
        or spec.interchange is not ExternalInterchangeKind.SPECCTRA_DSN_SES
    ):
        raise ValueError("Freerouting adapter received an incompatible engine spec")
    engine = _engine_identity(spec, binding)
    ledger, translation_failures = _translation_ledger(request)
    if spec.version == "2.2.4":
        return _failed_result(
            request=request,
            engine=engine,
            ledger=ledger,
            failures=translation_failures
            + (
                RouteFailureEvidence(
                    failure_id="failure:freerouting:2.2.4-retained-wiring",
                    kind=RouteFailureKind.ENGINE_FAILURE,
                    message=(
                        "Freerouting 2.2.4 is blocked before launch because retained "
                        "wiring can trigger PolylineTrace.combine StackOverflowError"
                    ),
                    retryable=False,
                ),
            ),
            reason="known_bad_router_version",
        )
    try:
        entrypoint = verify_external_tool_binding(binding)
    except Exception as exc:
        return _failed_result(
            request=request,
            engine=engine,
            ledger=ledger,
            failures=translation_failures
            + (
                RouteFailureEvidence(
                    failure_id="failure:external:unavailable",
                    kind=RouteFailureKind.ENGINE_FAILURE,
                    message=f"{type(exc).__name__}: {exc}",
                    retryable=True,
                ),
            ),
            reason="external_tool_unavailable",
        )
    if not spec.headless:
        return _failed_result(
            request=request,
            engine=engine,
            ledger=ledger,
            failures=translation_failures
            + (
                RouteFailureEvidence(
                    failure_id="failure:external:headless-unavailable",
                    kind=RouteFailureKind.ENGINE_FAILURE,
                    message="this pinned Freerouting oracle has no qualified headless run",
                ),
            ),
            reason="headless_execution_unavailable",
        )
    input_file = candidate_directory / "interchange" / "input.dsn"
    output_file = candidate_directory / "interchange" / "output.ses"
    input_file.parent.mkdir(parents=True, exist_ok=True)
    input_file.write_bytes(dsn_payload)
    command = (
        java_executable,
        "-jar",
        str(entrypoint),
        "-de",
        str(input_file),
        "-do",
        str(output_file),
        "-mp",
        str(request.budget.max_passes),
        "-mt",
        "1",
        "--gui.enabled=false",
        "--router.fanout.enabled=false",
        "--router.automatic_neckdown=false",
        "-da",
        "--logging.file.enabled=false",
        f"--user_data_path={candidate_directory / 'engine' / 'user-data'}",
    )
    if request.budget.external_process_seconds is not None:
        if executor is not run_external_process:
            raise ValueError("external time policy requires the owned bounded process executor")
        seconds = request.budget.external_process_seconds

        def bounded_executor(command: Sequence[str], cwd: Path) -> ExternalProcessResult:
            return run_external_process(command, cwd, timeout_seconds=seconds)

        executor = bounded_executor
    return _run_pinned_external_candidate(
        request=request,
        source_layout=source_layout,
        candidate_directory=candidate_directory,
        spec=spec,
        binding=binding,
        command=command,
        output_file=output_file,
        importer=ses_importer,
        executor=executor,
        completion_verifier=completion_verifier,
    )


def run_krt_board_candidate(
    *,
    request: RouteRequest,
    source_layout: BoardLayout,
    candidate_directory: Path,
    spec: PinnedExternalRouterSpec,
    binding: ExternalToolBinding,
    source_board_payload: bytes,
    board_importer: ExternalLayoutImporter,
    python_executable: str = "python",
    executor: ExternalProcessExecutor = run_external_process,
) -> RouteCandidateResult:
    """Run pinned KRT generic routing against an isolated KiCad board copy."""

    if (
        spec.family is not ExternalRouterFamily.KICAD_ROUTING_TOOLS
        or spec.interchange is not ExternalInterchangeKind.KICAD_BOARD
    ):
        raise ValueError("KRT adapter received an incompatible engine spec")
    engine = _engine_identity(spec, binding)
    ledger, translation_failures = _translation_ledger(request)

    try:
        entrypoint = verify_external_tool_binding(binding)
    except Exception as exc:
        return _failed_result(
            request=request,
            engine=engine,
            ledger=ledger,
            failures=translation_failures
            + (
                RouteFailureEvidence(
                    failure_id="failure:external:unavailable",
                    kind=RouteFailureKind.ENGINE_FAILURE,
                    message=f"{type(exc).__name__}: {exc}",
                    retryable=True,
                ),
            ),
            reason="external_tool_unavailable",
        )
    input_file = candidate_directory / "interchange" / "input.kicad_pcb"
    output_file = candidate_directory / "interchange" / "output.kicad_pcb"
    input_file.parent.mkdir(parents=True, exist_ok=True)
    input_file.write_bytes(source_board_payload)
    preferred_widths = {item.preferred_width_mm for item in request.width_constraints}
    clearances = {item.minimum_clearance_mm for item in request.clearance_constraints}
    if len(preferred_widths) != 1 or len(clearances) != 1:
        rejected_ids = {
            *(item.constraint_id for item in request.width_constraints),
            *(item.constraint_id for item in request.clearance_constraints),
        }
        rejected_ledger = tuple(
            ConstraintConsumption(
                constraint_id=item.constraint_id,
                disposition=(
                    RouteConstraintDisposition.REJECTED
                    if item.constraint_id in rejected_ids
                    else item.disposition
                ),
                backend_constraint_id=(
                    None if item.constraint_id in rejected_ids else item.backend_constraint_id
                ),
                detail=(
                    "H0 KRT CLI adapter supports one width and clearance only"
                    if item.constraint_id in rejected_ids
                    else item.detail
                ),
            )
            for item in ledger
        )
        return _failed_result(
            request=request,
            engine=engine,
            ledger=rejected_ledger,
            failures=translation_failures
            + (
                RouteFailureEvidence(
                    failure_id="failure:krt:nonuniform-rules",
                    kind=RouteFailureKind.REJECTED_CONSTRAINT,
                    message="H0 KRT CLI adapter supports one width and clearance only",
                    constraint_ids=tuple(
                        sorted(
                            (
                                *(item.constraint_id for item in request.width_constraints),
                                *(item.constraint_id for item in request.clearance_constraints),
                            )
                        )
                    ),
                ),
            ),
            reason="krt_rule_translation_failed",
        )
    command = (
        python_executable,
        str(entrypoint),
        str(input_file),
        str(output_file),
        "--nets",
        *request.deterministic.route_order,
        "--track-width",
        str(next(iter(preferred_widths))),
        "--clearance",
        str(next(iter(clearances))),
    )
    return _run_pinned_external_candidate(
        request=request,
        source_layout=source_layout,
        candidate_directory=candidate_directory,
        spec=spec,
        binding=binding,
        command=command,
        output_file=output_file,
        importer=board_importer,
        executor=executor,
    )
