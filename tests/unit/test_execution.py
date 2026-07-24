from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from pcbsmith.execution import (
    EXECUTION_PROFILES,
    GateExecutionResult,
    VerificationGate,
    VerificationOrchestrator,
    WorkBudgetExhausted,
    WorkBudgetLedger,
    standard_verification_gates,
)


class ScriptedRunner:
    def __init__(self, terminations: dict[str, str]) -> None:
        self.terminations = terminations
        self.calls: list[str] = []

    def run(self, gate, *, profile, output_dir, emit):  # type: ignore[no-untyped-def]
        self.calls.append(gate.gate_id)
        emit("heartbeat", {"gate": gate.gate_id, "elapsed_seconds": 1})
        termination = self.terminations.get(gate.gate_id, "passed")
        return GateExecutionResult(
            gate_id=gate.gate_id,
            termination=termination,
            command=gate.command,
            command_sha256=hashlib.sha256(" ".join(gate.command).encode()).hexdigest(),
            returncode=0 if termination == "passed" else 1,
            elapsed_seconds=1,
            memory_limit_mb=profile.memory_limit_mb,
            memory_limit_enforced=True,
        )


def _clock() -> str:
    return "2026-07-20T12:00:00Z"


def test_orchestrator_reuses_gates_and_checkpoints_only_after_completion(tmp_path: Path) -> None:
    runner = ScriptedRunner({})
    gates = (
        VerificationGate(gate_id="ruff", command=("python", "-m", "ruff")),
        VerificationGate(gate_id="pytest", command=("python", "-m", "pytest")),
    )

    run = VerificationOrchestrator(runner=runner, wall_clock=_clock).run(
        gates=gates,
        profile=EXECUTION_PROFILES["quick"],
        output_dir=tmp_path,
    )
    checkpoint = json.loads((tmp_path / "checkpoint.json").read_text("utf-8"))
    progress = [
        json.loads(line) for line in (tmp_path / "progress.jsonl").read_text("utf-8").splitlines()
    ]

    assert run.status == "passed"
    assert runner.calls == ["ruff", "pytest"]
    assert checkpoint["semantic_boundary"] == "completed_verification_gate"
    assert [item["gate_id"] for item in checkpoint["completed_gates"]] == ["ruff", "pytest"]
    assert any(item["event"] == "heartbeat" for item in progress)


def test_quick_profile_fail_fast_records_unexecuted_required_gate(tmp_path: Path) -> None:
    runner = ScriptedRunner({"ruff": "failed"})
    gates = (
        VerificationGate(gate_id="ruff", command=("ruff",)),
        VerificationGate(gate_id="pytest", command=("pytest",)),
    )

    run = VerificationOrchestrator(runner=runner, wall_clock=_clock).run(
        gates=gates,
        profile=EXECUTION_PROFILES["quick"],
        output_dir=tmp_path,
    )

    assert run.status == "failed"
    assert runner.calls == ["ruff"]
    assert "pytest" in run.findings[-1]


def test_optional_failure_is_attention_required(tmp_path: Path) -> None:
    runner = ScriptedRunner({"advisory": "timeout"})

    run = VerificationOrchestrator(runner=runner, wall_clock=_clock).run(
        gates=(VerificationGate(gate_id="advisory", command=("tool",), required=False),),
        profile=EXECUTION_PROFILES["quick"],
        output_dir=tmp_path,
    )

    assert run.status == "attention_required"


def test_work_budget_has_typed_expansion_and_pass_termination() -> None:
    ledger = WorkBudgetLedger(EXECUTION_PROFILES["quick"].work_budget)
    ledger.consume_expansions(50_000)
    ledger.consume_pass()
    checkpoint = ledger.semantic_checkpoint("routing_group_complete", "0" * 64)

    assert checkpoint["expansions"] == 50_000
    assert checkpoint["passes"] == 1
    with pytest.raises(WorkBudgetExhausted, match="expansions") as error:
        ledger.consume_expansions()
    assert error.value.counter == "expansions"


def test_profile_timeout_escalation_is_explicit_and_validated() -> None:
    standard = EXECUTION_PROFILES["standard"]

    assert standard.with_timeout_scale(2).default_gate_timeout_seconds == 3600
    with pytest.raises(ValueError, match="positive"):
        standard.with_timeout_scale(0)


def test_standard_gate_matrix_uses_existing_tools_and_profile_scopes() -> None:
    quick = standard_verification_gates(profile_name="quick", python_executable="python")
    deep = standard_verification_gates(profile_name="deep", python_executable="python")

    assert [gate.gate_id for gate in quick] == ["lock", "ruff", "mypy", "pytest-focused"]
    assert quick[-1].environment["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"
    assert deep[-1].environment["PCBSMITH_GOLDEN"] == "1"
