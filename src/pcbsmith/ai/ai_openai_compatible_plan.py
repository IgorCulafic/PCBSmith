from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError

from pcbsmith.ai.ai_planner_package import AI_PLANNER_PACKAGE_SCHEMA
from pcbsmith.kicad.kicad_plan import KiCadPlanPackage

OpenAICompatibleRunner = Callable[[urllib.request.Request, float], bytes]

_PLAN_ADAPTER = TypeAdapter(KiCadPlanPackage)


class OpenAICompatiblePlannerResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    candidate_plan: dict[str, Any]
    request_body: dict[str, Any]


def build_openai_compatible_request_body(
    planner_package: dict[str, Any],
    *,
    model: str,
    use_json_mode: bool = True,
) -> dict[str, Any]:
    _require_command_planner_package(planner_package)
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": _system_prompt(),
            },
            {
                "role": "user",
                "content": _user_prompt(planner_package),
            },
        ],
        "temperature": 0,
    }
    if use_json_mode:
        body["response_format"] = {"type": "json_object"}
    return body


def request_openai_compatible_plan(
    planner_package: dict[str, Any],
    *,
    base_url: str,
    model: str,
    api_key: str | None = None,
    timeout_seconds: float = 60,
    use_json_mode: bool = True,
    runner: OpenAICompatibleRunner | None = None,
) -> OpenAICompatiblePlannerResult:
    request_body = build_openai_compatible_request_body(
        planner_package,
        model=model,
        use_json_mode=use_json_mode,
    )
    response = _post_chat_completion(
        base_url=base_url,
        request_body=request_body,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        runner=runner or _default_runner,
    )
    candidate_plan = _extract_candidate_plan(response)
    _validate_candidate_plan(planner_package, candidate_plan)
    return OpenAICompatiblePlannerResult(
        candidate_plan=candidate_plan,
        request_body=request_body,
    )


def write_openai_compatible_plan(
    planner_package_path: Path,
    output_path: Path,
    *,
    base_url: str,
    model: str,
    api_key: str | None = None,
    timeout_seconds: float = 60,
    use_json_mode: bool = True,
    runner: OpenAICompatibleRunner | None = None,
) -> None:
    planner_package = _read_json_object(planner_package_path)
    result = request_openai_compatible_plan(
        planner_package,
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout_seconds=timeout_seconds,
        use_json_mode=use_json_mode,
        runner=runner,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result.candidate_plan, indent=2) + "\n",
        encoding="utf-8",
    )


def _post_chat_completion(
    *,
    base_url: str,
    request_body: dict[str, Any],
    api_key: str | None,
    timeout_seconds: float,
    runner: OpenAICompatibleRunner,
) -> dict[str, Any]:
    endpoint = _chat_completion_endpoint(base_url)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(request_body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        response_bytes = runner(request, timeout_seconds)
    except urllib.error.URLError as exc:
        raise ValueError(f"OpenAI-compatible planner request failed: {exc}") from exc

    try:
        response = json.loads(response_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("OpenAI-compatible planner response is not valid JSON") from exc
    if not isinstance(response, dict):
        raise ValueError("OpenAI-compatible planner response must be a JSON object")
    return response


def _default_runner(request: urllib.request.Request, timeout: float) -> bytes:
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
    if not isinstance(body, bytes):
        raise TypeError("OpenAI-compatible endpoint returned a non-bytes response")
    return body


def _extract_candidate_plan(response: dict[str, Any]) -> dict[str, Any]:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("OpenAI-compatible planner response has no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise ValueError("OpenAI-compatible planner response choice must be an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise ValueError("OpenAI-compatible planner response choice has no message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ValueError("OpenAI-compatible planner response message has no content")
    return _parse_candidate_json(content)


def _parse_candidate_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("candidate plan is not valid JSON") from exc
    if not isinstance(data, dict):
        raise ValueError("candidate plan must be a JSON object")
    return data


def _validate_candidate_plan(
    planner_package: dict[str, Any],
    candidate_plan: dict[str, Any],
) -> None:
    try:
        candidate = _PLAN_ADAPTER.validate_python(candidate_plan)
    except ValidationError as exc:
        raise ValueError(f"candidate plan schema is invalid: {exc.errors()[0]['msg']}") from exc

    expected_schematic = _expected_schematic(planner_package)
    if expected_schematic is not None and candidate.schematic != expected_schematic:
        raise ValueError(
            f"target schematic does not match planner package: {candidate.schematic}"
        )

    allowed_types = set(_allowed_command_types(planner_package))
    for command in candidate.commands:
        if command.type not in allowed_types:
            raise ValueError(f"command type is not allowed: {command.type}")


def _read_json_object(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return data


def _require_command_planner_package(planner_package: dict[str, Any]) -> None:
    if planner_package.get("schema") != AI_PLANNER_PACKAGE_SCHEMA:
        raise ValueError(
            f"unsupported planner package schema: {planner_package.get('schema')}"
        )
    if planner_package.get("planner_mode") == "review_response":
        raise ValueError("planner package is review-only and does not allow command plans")


def _expected_schematic(planner_package: dict[str, Any]) -> str | None:
    target_plan_schema = planner_package.get("target_plan_schema")
    if not isinstance(target_plan_schema, dict):
        return None
    schematic = target_plan_schema.get("schematic")
    return schematic if isinstance(schematic, str) else None


def _allowed_command_types(planner_package: dict[str, Any]) -> list[str]:
    raw = planner_package.get("allowed_command_types", [])
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, str)]


def _chat_completion_endpoint(base_url: str) -> str:
    stripped = base_url.strip().rstrip("/")
    if not stripped:
        raise ValueError("OpenAI-compatible base URL is required")
    if stripped.endswith("/v1/chat/completions"):
        return stripped
    return f"{stripped}/v1/chat/completions"


def _system_prompt() -> str:
    return (
        "You are PCBSmith's PCB planning model. Return only the candidate plan JSON "
        "object requested by the planner package. Do not include markdown, prose, "
        "tool calls, code fences, or file edits. Use only the allowed command types, "
        "known symbols, known footprints, integer nanometre coordinates, and the "
        "target schematic from the planner package."
    )


def _user_prompt(planner_package: dict[str, Any]) -> str:
    return (
        "Create one PCBSmith candidate plan from this planner package JSON:\n"
        + json.dumps(planner_package, indent=2, sort_keys=True)
    )


__all__ = [
    "OpenAICompatiblePlannerResult",
    "build_openai_compatible_request_body",
    "request_openai_compatible_plan",
    "write_openai_compatible_plan",
]
