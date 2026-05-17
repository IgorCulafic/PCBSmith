from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from pcbsmith.ai.local_ai_review import run_local_ai_review
from pcbsmith.operations.project_io import create_project


def _model_response() -> dict[str, object]:
    return {
        "version": 1,
        "description": "Local AI resistor plan",
        "schematic": "schematics/main.sch.json",
        "commands": [
            {
                "type": "place_symbol",
                "symbol_id": "stdlib:R",
                "value": "1k",
                "position": {"x": 15_240_000, "y": 0},
                "footprint_id": "stdlib:R_0603",
            }
        ],
    }


def test_run_local_ai_review_uses_configured_endpoint_and_review_pipeline(
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "project"
    request_path = tmp_path / "request.txt"
    output_dir = tmp_path / "local-ai-run"
    config_path = tmp_path / "local-ai.json"
    create_project(project_dir, "Local AI Demo")
    request_path.write_text("Add a resistor to the circuit\n", encoding="utf-8")
    config_path.write_text(
        json.dumps(
            {
                "schema": "pcbsmith-local-model-config-v1",
                "provider": "openai-compatible",
                "base_url": "http://127.0.0.1:5001",
                "model": "qwen-local",
                "timeout_seconds": 180,
                "use_json_mode": False,
                "supports_multimodal": False,
            }
        ),
        encoding="utf-8",
    )
    seen: dict[str, object] = {}

    def runner(request: urllib.request.Request, timeout: float) -> bytes:
        seen["url"] = request.full_url
        seen["timeout"] = timeout
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return json.dumps(
            {"choices": [{"message": {"content": json.dumps(_model_response())}}]}
        ).encode("utf-8")

    result = run_local_ai_review(
        project_dir,
        request_path,
        output_dir,
        config_path=config_path,
        runner=runner,
    )

    assert result.exit_code == 0
    assert result.applied is False
    assert seen["url"] == "http://127.0.0.1:5001/v1/chat/completions"
    assert seen["timeout"] == 180
    assert seen["body"]["model"] == "qwen-local"
    assert "response_format" not in seen["body"]
    assert result.lines[0] == f"AI local review bundle: {output_dir}"
    assert result.lines[1].startswith("Local model: qwen-local")
    assert (output_dir / "candidate-plan.json").exists()
