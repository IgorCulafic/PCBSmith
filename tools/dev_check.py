from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def run_step(
    label: str, args: list[str], *, extra_env: dict[str, str] | None = None
) -> None:
    print(f"\n== {label} ==")
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    if extra_env is not None:
        env.update(extra_env)
    result = subprocess.run(args, cwd=REPO_ROOT, env=env, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> int:
    tmp_dir = REPO_ROOT / ".tmp"
    tmp_dir.mkdir(exist_ok=True)
    kicad_smoke_dir = tmp_dir / "kicad-dev-check"
    if kicad_smoke_dir.exists():
        if not kicad_smoke_dir.resolve().is_relative_to(tmp_dir.resolve()):
            raise RuntimeError(f"Refusing to remove path outside .tmp: {kicad_smoke_dir}")
        shutil.rmtree(kicad_smoke_dir)

    python = sys.executable
    run_step("ruff", [python, "-m", "ruff", "check", "src", "tests", "tools"])
    run_step(
        "pytest",
        [
            python,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            "--basetemp",
            str(tmp_dir / "pytest-dev-check"),
        ],
    )
    run_step(
        "fixture validate",
        [python, "-m", "pcbsmith.cli", "validate", "tests/fixtures/voltage_divider"],
    )
    run_step(
        "KiCad skeleton smoke",
        [
            python,
            "-m",
            "pcbsmith.cli",
            "kicad-new",
            str(kicad_smoke_dir),
            "--name",
            "Dev Check",
        ],
    )
    run_step(
        "KiCad preview discovery smoke",
        [
            python,
            "-m",
            "pcbsmith.cli",
            "kicad-preview",
            str(kicad_smoke_dir),
            "--skip-execution",
        ],
        extra_env={"PCBSMITH_KICAD_CLI": "C:/Tools/KiCad/bin/kicad-cli.exe"},
    )
    review_bundle_dir = tmp_dir / "review-bundle-dev-check"
    if review_bundle_dir.exists():
        if not review_bundle_dir.resolve().is_relative_to(tmp_dir.resolve()):
            raise RuntimeError(f"Refusing to remove path outside .tmp: {review_bundle_dir}")
        shutil.rmtree(review_bundle_dir)
    run_step(
        "KiCad review bundle smoke",
        [
            python,
            "-m",
            "pcbsmith.cli",
            "kicad-review-bundle",
            "tests/fixtures/led_series_circuit",
            str(review_bundle_dir),
            "--skip-execution",
        ],
        extra_env={"PCBSMITH_KICAD_CLI": "C:/Tools/KiCad/bin/kicad-cli.exe"},
    )
    run_step(
        "AI context smoke",
        [
            python,
            "-m",
            "pcbsmith.cli",
            "kicad-context",
            "tests/fixtures/led_series_circuit",
            str(tmp_dir / "dev-check-ai-context.json"),
        ],
    )
    request_path = tmp_dir / "dev-check-request.txt"
    request_path.write_text("Add a resistor to the LED circuit\n", encoding="utf-8")
    run_step(
        "AI brief smoke",
        [
            python,
            "-m",
            "pcbsmith.cli",
            "ai-brief",
            "tests/fixtures/led_series_circuit",
            str(request_path),
            str(tmp_dir / "dev-check-ai-brief.json"),
            "--kicad-project",
            str(review_bundle_dir),
        ],
    )
    run_step(
        "AI planner package smoke",
        [
            python,
            "-m",
            "pcbsmith.cli",
            "ai-planner-package",
            str(tmp_dir / "dev-check-ai-brief.json"),
            str(tmp_dir / "dev-check-ai-planner-package.json"),
        ],
    )
    candidate_plan_path = tmp_dir / "dev-check-candidate-plan.json"
    candidate_plan_path.write_text(
        """{
  "version": 1,
  "description": "Dev check candidate plan",
  "schematic": "schematics/main.sch.json",
  "commands": [
    {
      "type": "place_symbol",
      "symbol_id": "stdlib:R",
      "value": "330",
      "position": {"x": 0, "y": 0},
      "footprint_id": "stdlib:R_0603"
    }
  ]
}
""",
        encoding="utf-8",
    )
    run_step(
        "AI plan check smoke",
        [
            python,
            "-m",
            "pcbsmith.cli",
            "ai-plan-check",
            str(tmp_dir / "dev-check-ai-planner-package.json"),
            str(candidate_plan_path),
        ],
    )
    print("\nDev check completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
