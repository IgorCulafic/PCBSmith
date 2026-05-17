from __future__ import annotations

from pathlib import Path

from pcbsmith.ai.ai_openai_compatible_plan import OpenAICompatibleRunner
from pcbsmith.ai.ai_openai_compatible_review import (
    OpenAICompatibleReviewResult,
    run_openai_compatible_review,
)
from pcbsmith.ai.local_model_config import load_local_model_config


def run_local_ai_review(
    project_dir: Path,
    request_path: Path,
    output_dir: Path,
    *,
    config_path: Path | None = None,
    kicad_project_dir: Path | None = None,
    apply: bool = False,
    runner: OpenAICompatibleRunner | None = None,
) -> OpenAICompatibleReviewResult:
    config = load_local_model_config(config_path)
    result = run_openai_compatible_review(
        project_dir,
        request_path,
        output_dir,
        base_url=config.base_url,
        model=config.model,
        api_key=config.api_key,
        timeout_seconds=config.timeout_seconds,
        use_json_mode=config.use_json_mode,
        kicad_project_dir=kicad_project_dir,
        apply=apply,
        runner=runner,
    )
    return result.model_copy(
        update={
            "lines": (
                f"AI local review bundle: {output_dir}",
                (
                    f"Local model: {config.model} "
                    f"({config.provider}, {config.base_url})"
                ),
                *result.lines[1:],
            )
        }
    )


__all__ = ["run_local_ai_review"]
