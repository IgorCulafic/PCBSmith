from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.unit.ai.test_local_agent import _candidate_plan, _config

from pcbsmith.ai.attempt_journal import AttemptJournal
from pcbsmith.ai.local_agent import run_local_agent_review
from pcbsmith.operations.project_io import create_project


def _setup(tmp_path):
    project = tmp_path / "project"
    create_project(project, "Fault controls")
    request = tmp_path / "request.txt"
    request.write_text("Check context then propose a resistor.", encoding="utf-8")
    config = tmp_path / "config.json"
    _config(config)
    return project, request, tmp_path / "output", config


def _response(action):
    return json.dumps({"choices": [{"message": {"content": json.dumps(action)}}]}).encode()


def _events(output):
    paths = list(output.glob("attempts/*/agent-events.jsonl"))
    assert len(paths) == 1
    return paths[0].parent, [json.loads(line) for line in paths[0].read_text().splitlines()]


def test_bad_second_response_retains_first_tool_and_raw_failure(tmp_path):
    project, request, output, config = _setup(tmp_path)
    responses = iter(
        [
            _response({"action": "tool_call", "tool": "project_context", "arguments": {}}),
            b'{"broken-response":',
        ]
    )
    with pytest.raises(ValueError):
        run_local_agent_review(
            project, request, output, config_path=config, runner=lambda *_: next(responses)
        )
    attempt, events = _events(output)
    assert [e["sequence"] for e in events] == list(range(len(events)))
    assert any(e["event"] == "tool_completed" for e in events)
    assert any(e["event"] == "response" and e["content"] == '{"broken-response":' for e in events)
    assert events[-1]["event"] == "failed"
    transcript = json.loads((attempt / "agent-transcript.json").read_text())
    assert transcript["status"] == "failed"
    assert len(transcript["steps"]) == 1
    assert not (attempt / "candidate-plan.json").exists()


@pytest.mark.parametrize("failure", ["transport", "tool", "invalid_plan"])
def test_failures_are_retained_and_cannot_apply_a_plan(tmp_path, failure):
    project, request, output, config = _setup(tmp_path)
    schematic = project / "schematics/main.sch.json"
    before = schematic.read_bytes()

    def runner(*_):
        if failure == "transport":
            raise TimeoutError("transport fixture timeout")
        if failure == "tool":
            return _response({"action": "tool_call", "tool": "calculator", "arguments": {}})
        return _response({"action": "final_plan", "candidate_plan": "invalid"})

    with pytest.raises((ValueError, TimeoutError)):
        run_local_agent_review(
            project, request, output, config_path=config, runner=runner, apply=True
        )
    _, events = _events(output)
    assert events[-1]["event"] == "failed"
    assert schematic.read_bytes() == before


def test_retry_retains_successful_attempt_and_does_not_reuse_its_plan(tmp_path):
    project, request, output, config = _setup(tmp_path)
    first = run_local_agent_review(
        project, request, output, config_path=config, runner=lambda *_: _response(_candidate_plan())
    )
    first_dir = Path(first.transcript_path).parent
    retained = {p.name: p.read_bytes() for p in first_dir.iterdir() if p.is_file()}
    with pytest.raises(ValueError):
        run_local_agent_review(
            project, request, output, config_path=config, runner=lambda *_: b"invalid"
        )
    assert {p.name: p.read_bytes() for p in first_dir.iterdir() if p.is_file()} == retained
    attempts = list((output / "attempts").iterdir())
    assert len(attempts) == 2
    failed = next(p for p in attempts if p != first_dir)
    assert not (failed / "candidate-plan.json").exists()


def test_credentials_are_redacted_from_raw_response_and_error_history(tmp_path):
    project, request, output, config = _setup(tmp_path)
    payload = json.loads(config.read_text())
    payload["api_key"] = "test-secret-not-a-real-credential"
    config.write_text(json.dumps(payload))
    responses = iter(
        [
            _response({"action": "tool_call", "tool": "project_context", "arguments": {}}),
            ("malformed " + payload["api_key"]).encode(),
        ]
    )
    with pytest.raises(ValueError):
        run_local_agent_review(
            project, request, output, config_path=config, runner=lambda *_: next(responses)
        )
    attempt, _ = _events(output)
    for name in ("agent-events.jsonl", "agent-transcript.json"):
        assert payload["api_key"] not in (attempt / name).read_text()
    assert "[REDACTED]" in (attempt / "agent-events.jsonl").read_text()


def test_transcript_write_failure_preserves_events_and_stops_before_next_call(
    tmp_path, monkeypatch
):
    project, request, output, config = _setup(tmp_path)
    original = AttemptJournal.checkpoint
    calls = []

    def fail_after_tool(self, steps, *, status):
        if steps:
            raise OSError("injected transcript storage failure")
        return original(self, steps, status=status)

    def runner(*_):
        calls.append(1)
        return _response({"action": "tool_call", "tool": "project_context", "arguments": {}})

    monkeypatch.setattr(AttemptJournal, "checkpoint", fail_after_tool)
    with pytest.raises(OSError, match="injected transcript"):
        run_local_agent_review(project, request, output, config_path=config, runner=runner)
    _, events = _events(output)
    assert len(calls) == 1
    assert any(e["event"] == "tool_completed" for e in events)
    assert events[-1]["event"] == "failed"
