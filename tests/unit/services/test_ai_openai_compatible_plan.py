from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from pcbsmith.services.ai_openai_compatible_plan import (
    OpenAICompatiblePlannerResult,
    build_openai_compatible_request_body,
    request_openai_compatible_plan,
    write_openai_compatible_plan,
)


def _planner_package() -> dict[str, object]:
    return {
        "schema": "pcbsmith-ai-planner-package-v1",
        "planner_mode": "structured_command_proposal",
        "brief": {"request": {"text": "Add an LED circuit"}},
        "allowed_command_types": ["place_symbol", "add_wire", "add_label"],
        "target_plan_schema": {
            "version": 1,
            "schematic": "schematics/main.sch.json",
            "commands": [],
        },
        "planner_rules": ["Return only JSON matching target_plan_schema."],
    }


def _candidate_plan() -> dict[str, object]:
    return {
        "version": 1,
        "description": "Mock LED plan",
        "schematic": "schematics/main.sch.json",
        "commands": [
            {
                "type": "place_symbol",
                "symbol_id": "stdlib:R",
                "value": "330",
                "position": {"x": 0, "y": 0},
                "footprint_id": "stdlib:R_0603",
            }
        ],
    }


def test_build_request_body_boxes_planner_package_into_json_instruction() -> None:
    body = build_openai_compatible_request_body(
        _planner_package(),
        model="local-model",
        use_json_mode=True,
    )

    assert body["model"] == "local-model"
    assert body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0]["role"] == "system"
    assert "Return only the candidate plan JSON object" in body["messages"][0]["content"]
    assert "pcbsmith-ai-planner-package-v1" in body["messages"][1]["content"]


def test_build_request_body_can_disable_json_mode_for_local_servers() -> None:
    body = build_openai_compatible_request_body(
        _planner_package(),
        model="local-model",
        use_json_mode=False,
    )

    assert "response_format" not in body


def test_request_openai_compatible_plan_posts_to_chat_completions() -> None:
    seen: dict[str, object] = {}

    def runner(request: urllib.request.Request, timeout: float) -> bytes:
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["headers"] = dict(request.header_items())
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return json.dumps(
            {"choices": [{"message": {"content": json.dumps(_candidate_plan())}}]}
        ).encode("utf-8")

    result = request_openai_compatible_plan(
        _planner_package(),
        base_url="http://127.0.0.1:1234/",
        model="local-model",
        api_key="secret",
        timeout_seconds=12,
        runner=runner,
    )

    assert isinstance(result, OpenAICompatiblePlannerResult)
    assert seen["url"] == "http://127.0.0.1:1234/v1/chat/completions"
    assert seen["timeout"] == 12
    assert seen["headers"]["Authorization"] == "Bearer secret"
    assert seen["body"]["model"] == "local-model"
    assert result.candidate_plan["description"] == "Mock LED plan"


def test_request_accepts_fenced_json_model_content() -> None:
    def runner(_request: urllib.request.Request, _timeout: float) -> bytes:
        return json.dumps(
            {
                "choices": [
                    {
                        "message": {
                            "content": "```json\n"
                            + json.dumps(_candidate_plan())
                            + "\n```"
                        }
                    }
                ]
            }
        ).encode("utf-8")

    result = request_openai_compatible_plan(
        _planner_package(),
        base_url="http://127.0.0.1:1234",
        model="local-model",
        runner=runner,
    )

    assert result.candidate_plan["schematic"] == "schematics/main.sch.json"


def test_request_rejects_non_json_model_content() -> None:
    def runner(_request: urllib.request.Request, _timeout: float) -> bytes:
        return json.dumps({"choices": [{"message": {"content": "not json"}}]}).encode(
            "utf-8"
        )

    with pytest.raises(ValueError, match="candidate plan is not valid JSON"):
        request_openai_compatible_plan(
            _planner_package(),
            base_url="http://127.0.0.1:1234",
            model="local-model",
            runner=runner,
        )


def test_request_rejects_disallowed_command_type() -> None:
    candidate = _candidate_plan()
    candidate["commands"] = [{"type": "delete_everything"}]

    def runner(_request: urllib.request.Request, _timeout: float) -> bytes:
        return json.dumps(
            {"choices": [{"message": {"content": json.dumps(candidate)}}]}
        ).encode("utf-8")

    with pytest.raises(ValueError, match="candidate plan schema is invalid"):
        request_openai_compatible_plan(
            _planner_package(),
            base_url="http://127.0.0.1:1234",
            model="local-model",
            runner=runner,
        )


def test_write_openai_compatible_plan_writes_validated_candidate(tmp_path: Path) -> None:
    planner_path = tmp_path / "planner-package.json"
    output_path = tmp_path / "candidate-plan.json"
    planner_path.write_text(json.dumps(_planner_package()), encoding="utf-8")

    def runner(_request: urllib.request.Request, _timeout: float) -> bytes:
        return json.dumps(
            {"choices": [{"message": {"content": json.dumps(_candidate_plan())}}]}
        ).encode("utf-8")

    write_openai_compatible_plan(
        planner_path,
        output_path,
        base_url="http://127.0.0.1:1234",
        model="local-model",
        runner=runner,
    )

    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert data["description"] == "Mock LED plan"
    assert data["commands"][0]["symbol_id"] == "stdlib:R"
