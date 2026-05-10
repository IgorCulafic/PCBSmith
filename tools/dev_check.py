from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def run_step(label: str, args: list[str]) -> None:
    print(f"\n== {label} ==")
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    result = subprocess.run(args, cwd=REPO_ROOT, env=env, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> int:
    tmp_dir = REPO_ROOT / ".tmp"
    tmp_dir.mkdir(exist_ok=True)

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
    print("\nDev check completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
