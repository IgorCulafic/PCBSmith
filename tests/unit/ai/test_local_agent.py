from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from pcbsmith.ai.local_agent import (
    local_agent_instructions,
    local_agent_tool_contract,
    run_local_agent_review,
)
from pcbsmith.operations.project_io import create_project


def _config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "pcbsmith-local-model-config-v1",
                "provider": "openai-compatible",
                "base_url": "http://127.0.0.1:5001",
                "model": "qwen-local",
                "timeout_seconds": 120,
                "use_json_mode": False,
                "supports_multimodal": True,
            }
        ),
        encoding="utf-8",
    )


def _candidate_plan() -> dict[str, object]:
    return {
        "version": 1,
        "description": "Agent resistor plan",
        "schematic": "schematics/main.sch.json",
        "commands": [
            {
                "type": "place_symbol",
                "symbol_id": "stdlib:R",
                "value": "1k",
                "position": {"x": 10_000_000, "y": 10_000_000},
                "footprint_id": "stdlib:R_0603",
            }
        ],
    }


def test_local_agent_instructions_forbid_direct_filesystem_edits() -> None:
    instructions = local_agent_instructions()

    assert "Do not read, write, rename, delete, or inspect raw files directly." in instructions
    assert "Return only JSON" in instructions
    assert "final_plan" in instructions


def test_local_agent_tool_contract_lists_safe_pcbs_tool_surface() -> None:
    contract = local_agent_tool_contract()

    assert contract["schema"] == "pcbsmith-local-agent-tool-v1"
    assert [tool["name"] for tool in contract["tools"]] == [
        "project_context",
        "circuit_topologies",
        "calculator",
    ]


def test_run_local_agent_review_allows_tool_call_then_final_plan(tmp_path: Path) -> None:
    project_dir = tmp_path / "project"
    request_path = tmp_path / "request.txt"
    output_dir = tmp_path / "agent-run"
    config_path = tmp_path / "local-ai.json"
    create_project(project_dir, "Agent Demo")
    request_path.write_text("Add a 1k resistor after checking tools.\n", encoding="utf-8")
    _config(config_path)
    responses = [
        {
            "version": 1,
            "action": "tool_call",
            "tool": "calculator",
            "arguments": {
                "calculator": "lc-resonance",
                "parameters": {
                    "inductance_uH": "35.56",
                    "capacitance_nF": "10",
                },
            },
        },
        {
            "version": 1,
            "action": "final_plan",
            "candidate_plan": _candidate_plan(),
        },
    ]
    seen_bodies: list[dict[str, object]] = []

    def runner(request: urllib.request.Request, _timeout: float) -> bytes:
        seen_bodies.append(json.loads(request.data.decode("utf-8")))
        response = responses.pop(0)
        return json.dumps(
            {"choices": [{"message": {"content": json.dumps(response)}}]}
        ).encode("utf-8")

    result = run_local_agent_review(
        project_dir,
        request_path,
        output_dir,
        config_path=config_path,
        runner=runner,
    )

    assert result.exit_code == 0
    assert result.applied is False
    assert len(seen_bodies) == 2
    assert seen_bodies[0]["model"] == "qwen-local"
    assert result.lines[:7] == (
        f"AI local agent review bundle: {output_dir}",
        "Local model: qwen-local (openai-compatible, http://127.0.0.1:5001)",
        f"Brief: {output_dir / 'ai-brief.json'}",
        f"Planner package: {output_dir / 'ai-planner-package.json'}",
        f"Transcript: {output_dir / 'agent-transcript.json'}",
        f"Candidate plan: {output_dir / 'candidate-plan.json'}",
        "Agent steps: 2",
    )
    assert "Tool calls: 1" in result.lines
    transcript = json.loads((output_dir / "agent-transcript.json").read_text(encoding="utf-8"))
    assert transcript["steps"][0]["tool_result"]["calculator"] == "lc-resonance"
    assert transcript["steps"][1]["action"]["action"] == "final_plan"
    candidate = json.loads((output_dir / "candidate-plan.json").read_text(encoding="utf-8"))
    assert candidate["description"] == "Agent resistor plan"


def test_run_local_agent_review_accepts_plain_candidate_plan_response(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    request_path = tmp_path / "request.txt"
    output_dir = tmp_path / "agent-run"
    config_path = tmp_path / "local-ai.json"
    create_project(project_dir, "Agent Demo")
    request_path.write_text("Add a 1k resistor.\n", encoding="utf-8")
    _config(config_path)

    def runner(_request: urllib.request.Request, _timeout: float) -> bytes:
        return json.dumps(
            {"choices": [{"message": {"content": json.dumps(_candidate_plan())}}]}
        ).encode("utf-8")

    result = run_local_agent_review(
        project_dir,
        request_path,
        output_dir,
        config_path=config_path,
        runner=runner,
    )

    assert result.exit_code == 0
    assert "Agent steps: 1" in result.lines
    assert "Tool calls: 0" in result.lines
    transcript = json.loads((output_dir / "agent-transcript.json").read_text(encoding="utf-8"))
    assert transcript["steps"][0]["action"]["action"] == "final_plan"
