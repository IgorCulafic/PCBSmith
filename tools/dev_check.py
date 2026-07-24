from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


def run_openai_compatible_smoke(
    python: str,
    planner_package_path: Path,
    output_path: Path,
    *,
    project_dir: Path,
    request_path: Path,
    review_output_dir: Path,
) -> None:
    response_content = {
        "version": 1,
        "description": "Dev-check OpenAI-compatible resistor plan",
        "schematic": "schematics/main.sch.json",
        "commands": [
            {
                "type": "place_symbol",
                "symbol_id": "stdlib:R",
                "value": "1k",
                "position": {"x": 0, "y": 0},
                "footprint_id": "stdlib:R_0603",
            }
        ],
    }

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers["Content-Length"])
            self.rfile.read(length)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(
                json.dumps(
                    {
                        "choices": [
                            {"message": {"content": json.dumps(response_content)}}
                        ]
                    }
                ).encode("utf-8")
            )

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        run_step(
            "AI OpenAI-compatible planner smoke",
            [
                python,
                "-m",
                "pcbsmith.cli",
                "ai-openai-plan",
                str(planner_package_path),
                str(output_path),
                "--base-url",
                f"http://127.0.0.1:{server.server_port}",
                "--model",
                "dev-check-local",
            ],
        )
        run_step(
            "AI OpenAI-compatible review smoke",
            [
                python,
                "-m",
                "pcbsmith.cli",
                "ai-openai-review",
                str(project_dir),
                str(request_path),
                str(review_output_dir),
                "--base-url",
                f"http://127.0.0.1:{server.server_port}",
                "--model",
                "dev-check-local",
            ],
        )
    finally:
        server.shutdown()
        server.server_close()


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
        "fixture board check",
        [python, "-m", "pcbsmith.cli", "board-check", "tests/fixtures/voltage_divider"],
    )
    library_smoke_dir = tmp_dir / "kicad-library-index-smoke"
    if library_smoke_dir.exists():
        if not library_smoke_dir.resolve().is_relative_to(tmp_dir.resolve()):
            raise RuntimeError(f"Refusing to remove path outside .tmp: {library_smoke_dir}")
        shutil.rmtree(library_smoke_dir)
    symbols_dir = library_smoke_dir / "symbols"
    footprints_dir = library_smoke_dir / "footprints"
    footprint_library_dir = footprints_dir / "Resistor_SMD.pretty"
    symbols_dir.mkdir(parents=True)
    footprint_library_dir.mkdir(parents=True)
    (symbols_dir / "Device.kicad_sym").write_text(
        '(kicad_symbol_lib\n\t(symbol "R")\n)\n',
        encoding="utf-8",
    )
    (footprint_library_dir / "R_0603_1608Metric.kicad_mod").write_text(
        '(footprint "R_0603_1608Metric")\n',
        encoding="utf-8",
    )
    run_step(
        "KiCad library index smoke",
        [
            python,
            "-m",
            "pcbsmith.cli",
            "kicad-library-index",
            str(tmp_dir / "dev-check-kicad-library-index.json"),
            "--symbols-dir",
            str(symbols_dir),
            "--footprints-dir",
            str(footprints_dir),
            "--symbol-library",
            "Device",
            "--footprint-library",
            "Resistor_SMD",
        ],
    )
    run_step(
        "KiCad part resolver smoke",
        [
            python,
            "-m",
            "pcbsmith.cli",
            "kicad-part-resolve",
            "pcbs:resistor_0603",
            str(tmp_dir / "dev-check-kicad-library-index.json"),
        ],
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
    request_path.write_text(
        "Create a complete LED circuit with a current-limiting resistor\n",
        encoding="utf-8",
    )
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
    run_step(
        "AI demo plan smoke",
        [
            python,
            "-m",
            "pcbsmith.cli",
            "ai-demo-plan",
            str(tmp_dir / "dev-check-ai-planner-package.json"),
            str(candidate_plan_path),
        ],
    )
    run_openai_compatible_smoke(
        python,
        tmp_dir / "dev-check-ai-planner-package.json",
        tmp_dir / "dev-check-openai-compatible-plan.json",
        project_dir=Path("tests/fixtures/led_series_circuit"),
        request_path=request_path,
        review_output_dir=tmp_dir / "dev-check-openai-compatible-review",
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
    run_step(
        "AI plan review smoke",
        [
            python,
            "-m",
            "pcbsmith.cli",
            "ai-plan-review",
            "tests/fixtures/led_series_circuit",
            str(tmp_dir / "dev-check-ai-planner-package.json"),
            str(candidate_plan_path),
        ],
    )
    proposal_bundle_dir = tmp_dir / "dev-check-ai-proposal-bundle"
    if proposal_bundle_dir.exists():
        if not proposal_bundle_dir.resolve().is_relative_to(tmp_dir.resolve()):
            raise RuntimeError(f"Refusing to remove path outside .tmp: {proposal_bundle_dir}")
        shutil.rmtree(proposal_bundle_dir)
    run_step(
        "AI proposal bundle smoke",
        [
            python,
            "-m",
            "pcbsmith.cli",
            "ai-proposal-bundle",
            "tests/fixtures/led_series_circuit",
            str(tmp_dir / "dev-check-ai-planner-package.json"),
            str(candidate_plan_path),
            str(proposal_bundle_dir),
            "--skip-execution",
        ],
        extra_env={"PCBSMITH_KICAD_CLI": "C:/Tools/KiCad/bin/kicad-cli.exe"},
    )
    print("\nDev check completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
