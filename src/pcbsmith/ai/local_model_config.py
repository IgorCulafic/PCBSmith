from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

LOCAL_MODEL_CONFIG_SCHEMA = "pcbsmith-local-model-config-v1"
LOCAL_AI_TOOL_SCHEMA = "pcbsmith-local-ai-tool-v1"
DEFAULT_LOCAL_MODEL_CONFIG_PATH = Path("ai_assets/local-ai-config.json")
LOCAL_AI_ASSET_DIRS = {
    "models": "ai_assets/models",
    "loras": "ai_assets/loras",
    "rag_indexes": "ai_assets/rag_indexes",
    "koboldcpp": "ai_assets/koboldcpp",
}


class LocalModelConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    schema_id: Literal["pcbsmith-local-model-config-v1"] = Field(
        default=LOCAL_MODEL_CONFIG_SCHEMA,
        alias="schema",
    )
    provider: Literal["openai-compatible"] = "openai-compatible"
    base_url: str = "http://127.0.0.1:5001"
    model: str = "local-model"
    api_key: str | None = None
    timeout_seconds: float = Field(default=120.0, gt=0)
    use_json_mode: bool = False
    supports_multimodal: bool = False
    model_path: str | None = None
    context_window_tokens: int | None = Field(default=None, gt=0)
    notes: tuple[str, ...] = (
        "Run KoboldCPP, llama.cpp server, LM Studio, or another local runtime "
        "that exposes OpenAI-compatible /v1/chat/completions.",
        "GGUF model files remain local assets and are not committed.",
        "PCBSmith validates model output through the planner approval loop.",
    )

    @field_validator("base_url", "model")
    @classmethod
    def _non_empty_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty")
        return stripped

    @field_validator("api_key", "model_path")
    @classmethod
    def _empty_string_to_none(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


def load_local_model_config(
    config_path: Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> LocalModelConfig:
    if config_path is not None:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"Expected local AI config JSON object: {config_path}")
        return LocalModelConfig.model_validate(data)

    source = env if env is not None else os.environ
    return LocalModelConfig(
        base_url=source.get("PCBSMITH_LOCAL_AI_BASE_URL", "http://127.0.0.1:5001"),
        model=source.get("PCBSMITH_LOCAL_AI_MODEL", "local-model"),
        api_key=source.get("PCBSMITH_LOCAL_AI_API_KEY") or None,
        timeout_seconds=_float_env(source, "PCBSMITH_LOCAL_AI_TIMEOUT_SECONDS", 120.0),
        use_json_mode=_bool_env(source, "PCBSMITH_LOCAL_AI_JSON_MODE", False),
        supports_multimodal=_bool_env(source, "PCBSMITH_LOCAL_AI_MULTIMODAL", False),
        model_path=source.get("PCBSMITH_LOCAL_AI_MODEL_PATH") or None,
        context_window_tokens=_int_env(
            source,
            "PCBSMITH_LOCAL_AI_CONTEXT_TOKENS",
            None,
        ),
    )


def write_local_model_config_template(path: Path) -> LocalModelConfig:
    config = LocalModelConfig()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(config.model_dump(by_alias=True), indent=2) + "\n",
        encoding="utf-8",
    )
    return config


def format_local_model_config(config: LocalModelConfig) -> tuple[str, ...]:
    return (
        f"Local AI provider: {config.provider}",
        f"Endpoint: {config.base_url}",
        f"Model: {config.model}",
        f"API key: {'configured' if config.api_key else 'not configured'}",
        f"Timeout: {config.timeout_seconds:.1f} seconds",
        f"JSON mode: {'on' if config.use_json_mode else 'off'}",
        f"Multimodal: {'yes' if config.supports_multimodal else 'no'}",
        f"Model path: {config.model_path or 'unspecified'}",
        "Context window: "
        + (
            f"{config.context_window_tokens} tokens"
            if config.context_window_tokens is not None
            else "unspecified"
        ),
    )


def local_model_tool_contract() -> dict[str, Any]:
    return {
        "schema": LOCAL_AI_TOOL_SCHEMA,
        "provider": "openai-compatible",
        "endpoint_contract": "OpenAI-compatible chat completions",
        "default_config_path": str(DEFAULT_LOCAL_MODEL_CONFIG_PATH),
        "asset_directories": LOCAL_AI_ASSET_DIRS,
        "environment_variables": [
            "PCBSMITH_LOCAL_AI_BASE_URL",
            "PCBSMITH_LOCAL_AI_MODEL",
            "PCBSMITH_LOCAL_AI_API_KEY",
            "PCBSMITH_LOCAL_AI_TIMEOUT_SECONDS",
            "PCBSMITH_LOCAL_AI_JSON_MODE",
            "PCBSMITH_LOCAL_AI_MULTIMODAL",
            "PCBSMITH_LOCAL_AI_MODEL_PATH",
            "PCBSMITH_LOCAL_AI_CONTEXT_TOKENS",
        ],
        "planner_rules": [
            "Use the same planner package, calculators, and approval loop as hosted models.",
            "Keep GGUF model files, LoRAs, and RAG indexes in ignored local asset folders.",
            (
                "Prefer HTTP endpoint integration first; direct in-process inference "
                "is a later adapter."
            ),
            "Do not trust local model output until PCBSmith validation and the approval loop pass.",
        ],
    }


def _bool_env(source: Mapping[str, str], key: str, default: bool) -> bool:
    raw = source.get(key)
    if raw is None or raw == "":
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{key} must be one of true/false, yes/no, on/off, or 1/0")


def _float_env(source: Mapping[str, str], key: str, default: float) -> float:
    raw = source.get(key)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be a number") from exc


def _int_env(source: Mapping[str, str], key: str, default: int | None) -> int | None:
    raw = source.get(key)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{key} must be an integer") from exc


__all__ = [
    "DEFAULT_LOCAL_MODEL_CONFIG_PATH",
    "LOCAL_AI_ASSET_DIRS",
    "LOCAL_AI_TOOL_SCHEMA",
    "LOCAL_MODEL_CONFIG_SCHEMA",
    "LocalModelConfig",
    "format_local_model_config",
    "load_local_model_config",
    "local_model_tool_contract",
    "write_local_model_config_template",
]
