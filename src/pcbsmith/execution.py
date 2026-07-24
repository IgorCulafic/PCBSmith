"""Observable execution profiles and a single reusable verification runner."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

TerminationKind = Literal[
    "passed",
    "failed",
    "unavailable",
    "budget_exhausted",
    "timeout",
    "memory_limit",
    "interrupted",
]


class DeterministicWorkBudget(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    maximum_expansions: int = Field(gt=0)
    maximum_passes: int = Field(gt=0)


class ExecutionProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: Literal["quick", "standard", "deep"]
    heartbeat_seconds: float = Field(gt=0)
    memory_limit_mb: int = Field(gt=0)
    default_gate_timeout_seconds: float = Field(gt=0)
    work_budget: DeterministicWorkBudget
    fail_fast: bool = True

    def with_timeout_scale(self, scale: float) -> ExecutionProfile:
        if not math_is_finite_positive(scale):
            raise ValueError("Timeout scale must be finite and positive.")
        return self.model_copy(
            update={"default_gate_timeout_seconds": self.default_gate_timeout_seconds * scale}
        )


EXECUTION_PROFILES: dict[str, ExecutionProfile] = {
    "quick": ExecutionProfile(
        name="quick",
        heartbeat_seconds=10,
        memory_limit_mb=2048,
        default_gate_timeout_seconds=300,
        work_budget=DeterministicWorkBudget(maximum_expansions=50_000, maximum_passes=25),
    ),
    "standard": ExecutionProfile(
        name="standard",
        heartbeat_seconds=20,
        memory_limit_mb=4096,
        default_gate_timeout_seconds=1800,
        work_budget=DeterministicWorkBudget(maximum_expansions=500_000, maximum_passes=100),
    ),
    "deep": ExecutionProfile(
        name="deep",
        heartbeat_seconds=30,
        memory_limit_mb=8192,
        default_gate_timeout_seconds=7200,
        work_budget=DeterministicWorkBudget(maximum_expansions=5_000_000, maximum_passes=500),
        fail_fast=False,
    ),
}


class VerificationGate(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    command: tuple[str, ...] = Field(min_length=1)
    required: bool = True
    timeout_seconds: float | None = Field(default=None, gt=0)
    environment: dict[str, str] = Field(default_factory=dict)


class GateExecutionResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    gate_id: str
    termination: TerminationKind
    command: tuple[str, ...]
    command_sha256: str
    returncode: int | None = None
    elapsed_seconds: float = Field(ge=0)
    memory_limit_mb: int
    memory_limit_enforced: bool
    peak_job_memory_bytes: int | None = None
    stdout_file: str | None = None
    stderr_file: str | None = None
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None
    findings: tuple[str, ...] = ()


class VerificationRun(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    schema_id: Literal["pcbsmith-verification-run-v1"] = Field(
        validation_alias="schema", serialization_alias="schema"
    )
    profile: ExecutionProfile
    status: Literal["passed", "failed", "attention_required"]
    started_at: str
    finished_at: str
    gates: tuple[GateExecutionResult, ...]
    progress_file: str
    findings: tuple[str, ...] = ()


class GateRunner(Protocol):
    def run(
        self,
        gate: VerificationGate,
        *,
        profile: ExecutionProfile,
        output_dir: Path,
        emit: Callable[[str, Mapping[str, object]], None],
    ) -> GateExecutionResult: ...


class VerificationOrchestrator:
    def __init__(
        self,
        *,
        runner: GateRunner,
        wall_clock: Callable[[], str],
    ) -> None:
        self._runner = runner
        self._wall_clock = wall_clock

    def run(
        self,
        *,
        gates: Sequence[VerificationGate],
        profile: ExecutionProfile,
        output_dir: Path,
    ) -> VerificationRun:
        run_dir = output_dir.resolve()
        run_dir.mkdir(parents=True, exist_ok=True)
        progress_file = run_dir / "progress.jsonl"
        progress_file.write_text("", encoding="utf-8")

        def emit(event: str, fields: Mapping[str, object]) -> None:
            record = {"event": event, "at": self._wall_clock(), **fields}
            with progress_file.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, sort_keys=True) + "\n")

        started = self._wall_clock()
        emit("run_started", {"profile": profile.name, "gate_count": len(gates)})
        results: list[GateExecutionResult] = []
        findings: list[str] = []
        for index, gate in enumerate(gates, start=1):
            emit("gate_started", {"gate": gate.gate_id, "index": index})
            result = self._runner.run(
                gate,
                profile=profile,
                output_dir=run_dir,
                emit=emit,
            )
            results.append(result)
            emit(
                "gate_completed",
                {
                    "gate": gate.gate_id,
                    "termination": result.termination,
                    "elapsed_seconds": result.elapsed_seconds,
                },
            )
            _write_checkpoint(run_dir / "checkpoint.json", profile, results)
            if gate.required and result.termination != "passed":
                findings.append(f"Required gate {gate.gate_id} terminated as {result.termination}.")
                if profile.fail_fast:
                    break
        required_by_id = {gate.gate_id: gate.required for gate in gates}
        required_failures = tuple(
            result
            for result in results
            if required_by_id[result.gate_id] and result.termination != "passed"
        )
        unexecuted_required = tuple(gate.gate_id for gate in gates[len(results) :] if gate.required)
        if unexecuted_required:
            findings.append(f"Required gates not executed: {', '.join(unexecuted_required)}")
        optional_failures = tuple(
            result
            for result in results
            if not required_by_id[result.gate_id] and result.termination != "passed"
        )
        status: Literal["passed", "failed", "attention_required"]
        if required_failures or unexecuted_required:
            status = "failed"
        elif optional_failures:
            status = "attention_required"
        else:
            status = "passed"
        finished = self._wall_clock()
        emit("run_completed", {"status": status})
        run = VerificationRun(
            schema_id="pcbsmith-verification-run-v1",
            profile=profile,
            status=status,
            started_at=started,
            finished_at=finished,
            gates=tuple(results),
            progress_file=str(progress_file),
            findings=tuple(findings),
        )
        (run_dir / "verification-run.json").write_text(
            json.dumps(run.model_dump(mode="json", by_alias=True), indent=2) + "\n",
            encoding="utf-8",
        )
        return run


class SubprocessGateRunner:
    def run(
        self,
        gate: VerificationGate,
        *,
        profile: ExecutionProfile,
        output_dir: Path,
        emit: Callable[[str, Mapping[str, object]], None],
    ) -> GateExecutionResult:
        executable = _resolve_executable(gate.command[0])
        command = (executable, *gate.command[1:]) if executable is not None else gate.command
        command_hash = _command_hash(command, gate.environment)
        if executable is None:
            return GateExecutionResult(
                gate_id=gate.gate_id,
                termination="unavailable",
                command=gate.command,
                command_sha256=command_hash,
                elapsed_seconds=0,
                memory_limit_mb=profile.memory_limit_mb,
                memory_limit_enforced=False,
                findings=(f"Executable not found: {gate.command[0]}",),
            )
        stdout_path = output_dir / "logs" / f"{gate.gate_id}.stdout.txt"
        stderr_path = output_dir / "logs" / f"{gate.gate_id}.stderr.txt"
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        environment = dict(os.environ)
        environment.update(gate.environment)
        timeout = gate.timeout_seconds or profile.default_gate_timeout_seconds
        start = time.monotonic()
        limiter: _ProcessLimiter | None = None
        termination: TerminationKind = "failed"
        returncode: int | None = None
        findings: list[str] = []
        try:
            with (
                stdout_path.open("w", encoding="utf-8") as stdout_handle,
                stderr_path.open("w", encoding="utf-8") as stderr_handle,
            ):
                process, limiter = _spawn_limited_process(
                    command,
                    cwd=Path.cwd(),
                    environment=environment,
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    memory_limit_bytes=profile.memory_limit_mb * 1024 * 1024,
                )
                next_heartbeat = start + profile.heartbeat_seconds
                while process.poll() is None:
                    now = time.monotonic()
                    if now - start >= timeout:
                        termination = "timeout"
                        findings.append(f"Gate exceeded its {timeout:g} second wall-time limit.")
                        _terminate_process_tree(process, limiter)
                        break
                    if now >= next_heartbeat:
                        emit(
                            "heartbeat",
                            {
                                "gate": gate.gate_id,
                                "elapsed_seconds": round(now - start, 3),
                            },
                        )
                        next_heartbeat = now + profile.heartbeat_seconds
                    time.sleep(min(0.2, profile.heartbeat_seconds / 4))
                returncode = process.wait()
                if termination != "timeout":
                    if returncode == 0:
                        termination = "passed"
                    elif limiter is not None and limiter.memory_limit_likely_exceeded():
                        termination = "memory_limit"
                        findings.append("The OS-enforced job memory ceiling was reached.")
                    else:
                        termination = "failed"
        except KeyboardInterrupt:
            termination = "interrupted"
            findings.append("Gate was interrupted by the operator.")
        except OSError as exc:
            termination = "unavailable"
            findings.append(f"Gate could not start: {exc}")
        finally:
            peak = None if limiter is None else limiter.peak_memory_bytes()
            enforced = limiter is not None and limiter.enforced
            if limiter is not None:
                limiter.close()
        elapsed = time.monotonic() - start
        return GateExecutionResult(
            gate_id=gate.gate_id,
            termination=termination,
            command=tuple(command),
            command_sha256=command_hash,
            returncode=returncode,
            elapsed_seconds=elapsed,
            memory_limit_mb=profile.memory_limit_mb,
            memory_limit_enforced=enforced,
            peak_job_memory_bytes=peak,
            stdout_file=str(stdout_path),
            stderr_file=str(stderr_path),
            stdout_sha256=_file_hash(stdout_path),
            stderr_sha256=_file_hash(stderr_path),
            findings=tuple(findings),
        )


class WorkBudgetExhausted(RuntimeError):
    def __init__(self, counter: Literal["expansions", "passes"], limit: int) -> None:
        self.counter = counter
        self.limit = limit
        super().__init__(f"Deterministic {counter} budget exhausted at {limit}.")


@dataclass
class WorkBudgetLedger:
    budget: DeterministicWorkBudget
    expansions: int = 0
    passes: int = 0

    def consume_expansions(self, count: int = 1) -> None:
        if count < 0:
            raise ValueError("Expansion consumption cannot be negative.")
        if self.expansions + count > self.budget.maximum_expansions:
            raise WorkBudgetExhausted("expansions", self.budget.maximum_expansions)
        self.expansions += count

    def consume_pass(self) -> None:
        if self.passes + 1 > self.budget.maximum_passes:
            raise WorkBudgetExhausted("passes", self.budget.maximum_passes)
        self.passes += 1

    def semantic_checkpoint(self, boundary: str, payload_sha256: str) -> dict[str, object]:
        if not boundary.strip():
            raise ValueError("A semantic checkpoint needs a named boundary.")
        if len(payload_sha256) != 64:
            raise ValueError("Checkpoint payload identity must be a SHA-256 digest.")
        return {
            "boundary": boundary,
            "payload_sha256": payload_sha256,
            "expansions": self.expansions,
            "passes": self.passes,
        }


def standard_verification_gates(
    *,
    profile_name: Literal["quick", "standard", "deep"],
    python_executable: str | None = None,
) -> tuple[VerificationGate, ...]:
    python = python_executable or sys.executable
    common = (
        VerificationGate(gate_id="lock", command=("uv", "lock", "--check")),
        VerificationGate(
            gate_id="ruff",
            command=(python, "-m", "ruff", "check", "src", "tests", "tools"),
        ),
        VerificationGate(
            gate_id="mypy",
            command=(python, "-m", "mypy", "src/pcbsmith"),
        ),
    )
    pytest_base = (
        python,
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
        "-W",
        "error",
    )
    if profile_name == "quick":
        tests = (
            "tests/unit/evidence",
            "tests/unit/review",
            "tests/unit/kicad/test_model_preflight.py",
            "tests/unit/kicad/test_raster_artwork.py",
            "tests/unit/kicad/test_asset_install.py",
            "tests/unit/test_execution.py",
        )
        return (
            *common,
            VerificationGate(
                gate_id="pytest-focused",
                command=(*pytest_base, *tests),
                environment={"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
            ),
        )
    environment = {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    if profile_name == "deep":
        environment["PCBSMITH_GOLDEN"] = "1"
    return (
        *common,
        VerificationGate(
            gate_id="pytest-full" if profile_name == "standard" else "pytest-deep",
            command=pytest_base,
            environment=environment,
        ),
    )


class _ProcessLimiter(Protocol):
    enforced: bool

    def terminate(self) -> None: ...

    def peak_memory_bytes(self) -> int | None: ...

    def memory_limit_likely_exceeded(self) -> bool: ...

    def close(self) -> None: ...


def _spawn_limited_process(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    stdout: IO[str],
    stderr: IO[str],
    memory_limit_bytes: int,
) -> tuple[subprocess.Popen[str], _ProcessLimiter | None]:
    if os.name == "nt":
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=dict(environment),
            stdout=stdout,
            stderr=stderr,
            text=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
        )
        try:
            limiter: _ProcessLimiter | None = _WindowsJobLimiter(process, memory_limit_bytes)
        except OSError:
            limiter = None
        return process, limiter

    import resource

    def set_limit() -> None:
        resource.setrlimit(  # type: ignore[attr-defined]
            resource.RLIMIT_AS,  # type: ignore[attr-defined]
            (memory_limit_bytes, memory_limit_bytes),
        )

    process = subprocess.Popen(
        list(command),
        cwd=cwd,
        env=dict(environment),
        stdout=stdout,
        stderr=stderr,
        text=True,
        start_new_session=True,
        preexec_fn=set_limit,
    )
    return process, _PosixLimiter(process)


class _PosixLimiter:
    enforced = True

    def __init__(self, process: subprocess.Popen[str]) -> None:
        self._process = process

    def terminate(self) -> None:
        try:
            os.killpg(  # type: ignore[attr-defined]
                self._process.pid,
                signal.SIGKILL,  # type: ignore[attr-defined]
            )
        except ProcessLookupError:
            pass

    def peak_memory_bytes(self) -> int | None:
        return None

    def memory_limit_likely_exceeded(self) -> bool:
        return False

    def close(self) -> None:
        return None


class _WindowsJobLimiter:
    enforced = True

    _JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
    _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
    _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9

    class _IO_COUNTERS(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_ulonglong),
            ("WriteOperationCount", ctypes.c_ulonglong),
            ("OtherOperationCount", ctypes.c_ulonglong),
            ("ReadTransferCount", ctypes.c_ulonglong),
            ("WriteTransferCount", ctypes.c_ulonglong),
            ("OtherTransferCount", ctypes.c_ulonglong),
        ]

    class _BASIC_LIMIT_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", ctypes.c_uint32),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", ctypes.c_uint32),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", ctypes.c_uint32),
            ("SchedulingClass", ctypes.c_uint32),
        ]

    class _EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
        pass

    _EXTENDED_LIMIT_INFORMATION._fields_ = [
        ("BasicLimitInformation", _BASIC_LIMIT_INFORMATION),
        ("IoInfo", _IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]

    def __init__(self, process: subprocess.Popen[str], limit_bytes: int) -> None:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32 = kernel32
        self._limit_bytes = limit_bytes
        self._handle = kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            raise ctypes.WinError(ctypes.get_last_error())
        info = self._EXTENDED_LIMIT_INFORMATION()
        info.BasicLimitInformation.LimitFlags = (
            self._JOB_OBJECT_LIMIT_JOB_MEMORY | self._JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        info.JobMemoryLimit = limit_bytes
        if not kernel32.SetInformationJobObject(
            self._handle,
            self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())
        process_handle = ctypes.c_void_p(int(process._handle))  # type: ignore[attr-defined]
        if not kernel32.AssignProcessToJobObject(self._handle, process_handle):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def terminate(self) -> None:
        self._kernel32.TerminateJobObject(self._handle, 1)

    def peak_memory_bytes(self) -> int | None:
        info = self._EXTENDED_LIMIT_INFORMATION()
        if not self._kernel32.QueryInformationJobObject(
            self._handle,
            self._JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
            None,
        ):
            return None
        return int(info.PeakJobMemoryUsed)

    def memory_limit_likely_exceeded(self) -> bool:
        peak = self.peak_memory_bytes()
        return peak is not None and peak >= int(self._limit_bytes * 0.98)

    def close(self) -> None:
        if getattr(self, "_handle", None):
            self._kernel32.CloseHandle(self._handle)
            self._handle = None


def _terminate_process_tree(
    process: subprocess.Popen[str], limiter: _ProcessLimiter | None
) -> None:
    if limiter is not None:
        limiter.terminate()
    elif process.poll() is None:
        process.kill()


def _resolve_executable(value: str) -> str | None:
    candidate = Path(value)
    if candidate.parent != Path(".") or candidate.is_absolute():
        return str(candidate.resolve()) if candidate.exists() else None
    return shutil.which(value)


def _command_hash(command: Sequence[str], environment: Mapping[str, str]) -> str:
    payload = json.dumps(
        {"command": tuple(command), "environment": dict(sorted(environment.items()))},
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_hash(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None


def _write_checkpoint(
    path: Path,
    profile: ExecutionProfile,
    results: Sequence[GateExecutionResult],
) -> None:
    payload = {
        "schema": "pcbsmith-verification-checkpoint-v1",
        "semantic_boundary": "completed_verification_gate",
        "profile": profile.model_dump(mode="json"),
        "completed_gates": [result.model_dump(mode="json") for result in results],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def math_is_finite_positive(value: float) -> bool:
    import math

    return math.isfinite(value) and value > 0
