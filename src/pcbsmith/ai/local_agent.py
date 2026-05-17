from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from pcbsmith.ai.ai_brief import write_ai_brief
from pcbsmith.ai.ai_context import build_ai_context
from pcbsmith.ai.ai_openai_compatible_plan import (
    OpenAICompatibleRunner,
    _default_runner,
    _parse_candidate_json,
    _post_chat_completion,
)
from pcbsmith.ai.ai_plan_review import run_ai_plan_review
from pcbsmith.ai.ai_planner_package import write_ai_planner_package
from pcbsmith.ai.local_model_config import load_local_model_config
from pcbsmith.calculators.electronics import run_calculator
from pcbsmith.knowledge.circuit_topologies import select_topologies_for_intent

LOCAL_AGENT_TOOL_SCHEMA = "pcbsmith-local-agent-tool-v1"
LOCAL_AGENT_TRANSCRIPT_SCHEMA = "pcbsmith-local-agent-transcript-v1"


class LocalAgentReviewResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    applied: bool
    exit_code: int
    brief_path: str
    planner_package_path: str
    transcript_path: str
    candidate_plan_path: str
    lines: tuple[str, ...]


def local_agent_instructions() -> str:
    return (
        "You are the PCBSmith local planning agent. Return only JSON. "
        "Do not read, write, rename, delete, or inspect raw files directly. "
        "Use only the safe tool_call actions listed in the agent package. "
        "When enough evidence exists, return action final_plan with candidate_plan. "
        "PCBSmith validates every final_plan before anything can be applied."
    )


def local_agent_tool_contract() -> dict[str, Any]:
    return {
        "schema": LOCAL_AGENT_TOOL_SCHEMA,
        "actions": ["tool_call", "final_plan"],
        "tools": [
            {
                "name": "project_context",
                "arguments": {},
                "description": "Return the current PCBSmith project context package.",
            },
            {
                "name": "circuit_topologies",
                "arguments": {"intent": "metal-detector"},
                "description": "Return supported topology guidance for an intent.",
            },
            {
                "name": "calculator",
                "arguments": {
                    "calculator": "lc-resonance",
                    "parameters": {"inductance_uH": "35.56", "capacitance_nF": "10"},
                },
                "description": "Run deterministic PCBSmith engineering math.",
            },
        ],
        "final_plan_shape": {
            "version": 1,
            "action": "final_plan",
            "candidate_plan": {
                "version": 1,
                "description": "<short summary>",
                "schematic": "schematics/main.sch.json",
                "commands": [],
            },
        },
    }


def run_local_agent_review(
    project_dir: Path,
    request_path: Path,
    output_dir: Path,
    *,
    config_path: Path | None = None,
    kicad_project_dir: Path | None = None,
    apply: bool = False,
    max_steps: int = 4,
    runner: OpenAICompatibleRunner | None = None,
) -> LocalAgentReviewResult:
    if max_steps < 1:
        raise ValueError("max_steps must be at least 1")

    config = load_local_model_config(config_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    brief_path = output_dir / "ai-brief.json"
    planner_package_path = output_dir / "ai-planner-package.json"
    transcript_path = output_dir / "agent-transcript.json"
    candidate_plan_path = output_dir / "candidate-plan.json"

    request_text = request_path.read_text(encoding="utf-8")
    write_ai_brief(
        project_dir,
        request_text,
        brief_path,
        kicad_project_dir=kicad_project_dir,
    )
    write_ai_planner_package(brief_path, planner_package_path)
    planner_package = _command_capable_planner_package(
        _read_json_object(planner_package_path)
    )
    _write_json(planner_package_path, planner_package)

    tool_results: list[dict[str, Any]] = []
    steps: list[dict[str, Any]] = []
    for step in range(1, max_steps + 1):
        action = _request_agent_action(
            agent_package=_agent_package(
                planner_package=planner_package,
                tool_results=tool_results,
                step=step,
                max_steps=max_steps,
            ),
            base_url=config.base_url,
            model=config.model,
            api_key=config.api_key,
            timeout_seconds=config.timeout_seconds,
            use_json_mode=config.use_json_mode,
            runner=runner,
        )
        if action["action"] == "tool_call":
            tool_result = _run_agent_tool(
                action,
                project_dir=project_dir,
                kicad_project_dir=kicad_project_dir,
            )
            tool_results.append(tool_result)
            steps.append({"step": step, "action": action, "tool_result": tool_result})
            continue

        candidate_plan = _candidate_plan_from_action(action)
        _write_json(candidate_plan_path, candidate_plan)
        steps.append({"step": step, "action": action})
        _write_json(
            transcript_path,
            {
                "schema": LOCAL_AGENT_TRANSCRIPT_SCHEMA,
                "steps": steps,
            },
        )
        review = run_ai_plan_review(
            project_dir,
            planner_package_path,
            candidate_plan_path,
            apply=apply,
        )
        return LocalAgentReviewResult(
            applied=review.applied,
            exit_code=review.exit_code,
            brief_path=str(brief_path),
            planner_package_path=str(planner_package_path),
            transcript_path=str(transcript_path),
            candidate_plan_path=str(candidate_plan_path),
            lines=(
                f"AI local agent review bundle: {output_dir}",
                f"Local model: {config.model} ({config.provider}, {config.base_url})",
                f"Brief: {brief_path}",
                f"Planner package: {planner_package_path}",
                f"Transcript: {transcript_path}",
                f"Candidate plan: {candidate_plan_path}",
                f"Agent steps: {len(steps)}",
                f"Tool calls: {len(tool_results)}",
                *review.lines,
            ),
        )

    _write_json(
        transcript_path,
        {
            "schema": LOCAL_AGENT_TRANSCRIPT_SCHEMA,
            "steps": steps,
        },
    )
    raise ValueError(f"Local agent did not return final_plan within {max_steps} steps")


def _agent_package(
    *,
    planner_package: dict[str, Any],
    tool_results: list[dict[str, Any]],
    step: int,
    max_steps: int,
) -> dict[str, Any]:
    return {
        "schema": "pcbsmith-local-agent-package-v1",
        "instructions": local_agent_instructions(),
        "tool_contract": local_agent_tool_contract(),
        "planner_package": planner_package,
        "tool_results": tool_results,
        "step": step,
        "max_steps": max_steps,
    }


def _command_capable_planner_package(planner_package: dict[str, Any]) -> dict[str, Any]:
    if planner_package.get("planner_mode") != "review_response":
        return planner_package
    updated = dict(planner_package)
    updated["planner_mode"] = "structured_command_proposal"
    updated["allowed_command_types"] = [
        "place_symbol",
        "add_wire",
        "add_label",
        "route_segment",
        "place_text",
    ]
    updated["target_plan_schema"] = {
        "version": 1,
        "description": "<short human-readable summary>",
        "schematic": _first_schematic_path(updated),
        "commands": [],
    }
    updated["planner_rules"] = [
        "Return only JSON matching target_plan_schema.",
        "Do not invent unknown symbols, footprints, pins, or KiCad capabilities.",
        "Do not mutate files directly; propose commands for the approval loop.",
        "Use approved PCBSmith tools before proposing unfamiliar circuitry.",
    ]
    return updated


def _first_schematic_path(planner_package: dict[str, Any]) -> str:
    brief = planner_package.get("brief", {})
    if not isinstance(brief, dict):
        return "schematics/main.sch.json"
    context = brief.get("context", {})
    if not isinstance(context, dict):
        return "schematics/main.sch.json"
    project = context.get("project", {})
    if not isinstance(project, dict):
        return "schematics/main.sch.json"
    schematics = project.get("schematics", [])
    if not isinstance(schematics, list) or not schematics:
        return "schematics/main.sch.json"
    first = schematics[0]
    return first if isinstance(first, str) else "schematics/main.sch.json"


def _request_agent_action(
    *,
    agent_package: dict[str, Any],
    base_url: str,
    model: str,
    api_key: str | None,
    timeout_seconds: float,
    use_json_mode: bool,
    runner: OpenAICompatibleRunner | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": local_agent_instructions(),
            },
            {
                "role": "user",
                "content": (
                    "Return the next PCBSmith local-agent action JSON for this "
                    "agent package:\n"
                    + json.dumps(agent_package, indent=2, sort_keys=True)
                ),
            },
        ],
        "temperature": 0,
    }
    if use_json_mode:
        body["response_format"] = {"type": "json_object"}
    response = _post_chat_completion(
        base_url=base_url,
        request_body=body,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        runner=runner or _default_runner,
    )
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("Local agent response has no choices")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise ValueError("Local agent response choice has no message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Local agent response message has no content")
    return _validate_agent_action(_parse_candidate_json(content))


def _validate_agent_action(action: dict[str, Any]) -> dict[str, Any]:
    value = action.get("action")
    if value is None and _looks_like_candidate_plan(action):
        return {
            "version": 1,
            "action": "final_plan",
            "candidate_plan": action,
        }
    if value == "tool_call":
        tool = action.get("tool")
        if tool not in {"project_context", "circuit_topologies", "calculator"}:
            raise ValueError(f"Unsupported local agent tool: {tool}")
        arguments = action.get("arguments", {})
        if not isinstance(arguments, dict):
            raise ValueError("Local agent tool_call arguments must be an object")
        return action
    if value == "final_plan":
        _candidate_plan_from_action(action)
        return action
    raise ValueError(f"Unsupported local agent action: {value}")


def _looks_like_candidate_plan(action: dict[str, Any]) -> bool:
    return (
        isinstance(action.get("version"), int)
        and isinstance(action.get("schematic"), str)
        and isinstance(action.get("commands"), list)
    )


def _candidate_plan_from_action(action: dict[str, Any]) -> dict[str, Any]:
    candidate_plan = action.get("candidate_plan")
    if not isinstance(candidate_plan, dict):
        raise ValueError("Local agent final_plan requires candidate_plan object")
    return candidate_plan


def _run_agent_tool(
    action: dict[str, Any],
    *,
    project_dir: Path,
    kicad_project_dir: Path | None,
) -> dict[str, Any]:
    tool = action["tool"]
    arguments = action.get("arguments", {})
    if not isinstance(arguments, dict):
        raise ValueError("Local agent tool_call arguments must be an object")
    if tool == "project_context":
        return build_ai_context(project_dir, kicad_project_dir=kicad_project_dir)
    if tool == "circuit_topologies":
        intent = arguments.get("intent")
        if not isinstance(intent, str):
            raise ValueError("circuit_topologies requires string argument: intent")
        return select_topologies_for_intent(intent)
    if tool == "calculator":
        calculator = arguments.get("calculator")
        parameters = arguments.get("parameters", {})
        if not isinstance(calculator, str):
            raise ValueError("calculator requires string argument: calculator")
        if not isinstance(parameters, dict):
            raise ValueError("calculator parameters must be an object")
        return run_calculator(
            calculator,
            {str(key): str(value) for key, value in parameters.items()},
        )
    raise ValueError(f"Unsupported local agent tool: {tool}")


def _read_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


__all__ = [
    "LOCAL_AGENT_TOOL_SCHEMA",
    "LOCAL_AGENT_TRANSCRIPT_SCHEMA",
    "LocalAgentReviewResult",
    "local_agent_instructions",
    "local_agent_tool_contract",
    "run_local_agent_review",
]
