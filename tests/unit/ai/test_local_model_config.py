from __future__ import annotations

import json
from pathlib import Path

import pytest

from pcbsmith.ai.local_model_config import (
    DEFAULT_LOCAL_MODEL_CONFIG_PATH,
    LOCAL_AI_ASSET_DIRS,
    LocalModelConfig,
    format_local_model_config,
    load_local_model_config,
    local_model_tool_contract,
    write_local_model_config_template,
)


def test_load_local_model_config_uses_local_endpoint_defaults() -> None:
    config = load_local_model_config(env={})

    assert config.base_url == "http://127.0.0.1:5001"
    assert config.model == "local-model"
    assert config.use_json_mode is False
    assert config.supports_multimodal is False
    assert config.timeout_seconds == 120


def test_load_local_model_config_reads_environment_overrides() -> None:
    config = load_local_model_config(
        env={
            "PCBSMITH_LOCAL_AI_BASE_URL": "http://127.0.0.1:8080/v1/chat/completions",
            "PCBSMITH_LOCAL_AI_MODEL": "qwen3.6-35b",
            "PCBSMITH_LOCAL_AI_API_KEY": "secret",
            "PCBSMITH_LOCAL_AI_TIMEOUT_SECONDS": "240",
            "PCBSMITH_LOCAL_AI_JSON_MODE": "yes",
            "PCBSMITH_LOCAL_AI_MULTIMODAL": "1",
            "PCBSMITH_LOCAL_AI_MODEL_PATH": "ai_assets/models/model.gguf",
            "PCBSMITH_LOCAL_AI_CONTEXT_TOKENS": "32768",
        }
    )

    assert config.base_url == "http://127.0.0.1:8080/v1/chat/completions"
    assert config.model == "qwen3.6-35b"
    assert config.api_key == "secret"
    assert config.timeout_seconds == 240
    assert config.use_json_mode is True
    assert config.supports_multimodal is True
    assert config.model_path == "ai_assets/models/model.gguf"
    assert config.context_window_tokens == 32768


def test_load_local_model_config_rejects_invalid_boolean_env() -> None:
    with pytest.raises(ValueError, match="PCBSMITH_LOCAL_AI_JSON_MODE"):
        load_local_model_config(env={"PCBSMITH_LOCAL_AI_JSON_MODE": "sometimes"})


def test_load_local_model_config_file_is_source_of_truth(tmp_path: Path) -> None:
    path = tmp_path / "local-ai.json"
    path.write_text(
        json.dumps(
            {
                "schema": "pcbsmith-local-model-config-v1",
                "provider": "openai-compatible",
                "base_url": "http://127.0.0.1:1234",
                "model": "configured-model",
                "timeout_seconds": 90,
                "use_json_mode": False,
                "supports_multimodal": False,
                "model_path": "ai_assets/models/configured.gguf",
                "context_window_tokens": 16384,
            }
        ),
        encoding="utf-8",
    )

    config = load_local_model_config(
        path,
        env={"PCBSMITH_LOCAL_AI_MODEL": "ignored-env-model"},
    )

    assert config.model == "configured-model"
    assert config.model_path == "ai_assets/models/configured.gguf"


def test_write_local_model_config_template_creates_safe_editable_json(
    tmp_path: Path,
) -> None:
    path = tmp_path / "local-ai-template.json"

    config = write_local_model_config_template(path)

    assert isinstance(config, LocalModelConfig)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["schema"] == "pcbsmith-local-model-config-v1"
    assert data["base_url"] == "http://127.0.0.1:5001"
    assert data["api_key"] is None
    assert data["use_json_mode"] is False


def test_format_local_model_config_hides_secret_values() -> None:
    config = LocalModelConfig(
        base_url="http://127.0.0.1:5001",
        model="qwen-local",
        api_key="secret",
        model_path="ai_assets/models/qwen.gguf",
    )

    assert format_local_model_config(config) == (
        "Local AI provider: openai-compatible",
        "Endpoint: http://127.0.0.1:5001",
        "Model: qwen-local",
        "API key: configured",
        "Timeout: 120.0 seconds",
        "JSON mode: off",
        "Multimodal: no",
        "Model path: ai_assets/models/qwen.gguf",
        "Context window: unspecified",
    )


def test_local_model_tool_contract_documents_endpoint_and_assets() -> None:
    contract = local_model_tool_contract()

    assert contract["schema"] == "pcbsmith-local-ai-tool-v1"
    assert contract["default_config_path"] == str(DEFAULT_LOCAL_MODEL_CONFIG_PATH)
    assert contract["endpoint_contract"] == "OpenAI-compatible chat completions"
    assert contract["asset_directories"] == LOCAL_AI_ASSET_DIRS
    assert "PCBSMITH_LOCAL_AI_BASE_URL" in contract["environment_variables"]
    assert "approval loop" in " ".join(contract["planner_rules"])
