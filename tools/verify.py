"""Run the maintained local/CI quality gate with retained diagnostics."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def pytest_worker(arguments: list[str]) -> int:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    if os.environ.get("PCBSMITH_GOLDEN") == "1":
        from pcbsmith.kicad.cli import find_kicad_cli
        from pcbsmith.simulation.ngspice import find_ngspice

        if find_kicad_cli() is None or find_ngspice() is None:
            raise RuntimeError("Native verification requires KiCad CLI and ngspice")
    from PySide6.QtGui import QFont, QFontDatabase
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    if not isinstance(app, QApplication):
        raise RuntimeError("Qt widget tests require QApplication")
    explicit = os.environ.get("PCBSMITH_TEST_FONT")
    candidates = (
        [Path(explicit)]
        if explicit
        else [
            Path("C:/Windows/Fonts/segoeui.ttf"),
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
        ]
    )
    font_file = next((path for path in candidates if path.is_file()), None)
    if font_file is None:
        raise RuntimeError("No reproducible test font found; set PCBSMITH_TEST_FONT to a TTF file")
    font_id = QFontDatabase.addApplicationFont(str(font_file))
    if font_id < 0:
        raise RuntimeError(f"Cannot load test font: {font_file}")
    families = QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        raise RuntimeError("Font registration returned no usable family")
    app.setFont(QFont(families[0], 9))
    app.setStyle("Fusion")
    print(
        json.dumps(
            {"qt_backend": app.platformName(), "font": families[0], "font_file": str(font_file)}
        ),
        flush=True,
    )
    import pytest

    return pytest.main(
        ["-p", "pytestqt.plugin", "-p", "_hypothesis_pytestplugin",
         "-p", "no:cacheprovider", "-W", "error", *arguments]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="A new diagnostics directory")
    parser.add_argument("--profile", choices=("quick", "standard", "deep"), default="standard")
    parser.add_argument(
        "--checks",
        nargs="+",
        choices=("lock", "lint", "types", "imports", "tests"),
        help="Run selected checks for diagnosis; omit for the complete gate matrix",
    )
    parser.add_argument("--native", action="store_true", help="Alias for --profile deep")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    os.chdir(ROOT)
    sys.path.insert(0, str(ROOT / "src"))
    from pcbsmith.execution import (
        EXECUTION_PROFILES,
        SubprocessGateRunner,
        VerificationOrchestrator,
        standard_verification_gates,
    )

    profile_name = "deep" if args.native else args.profile
    gates = standard_verification_gates(
        profile_name=profile_name,
        python_executable=sys.executable,
        output_dir=output,
    )
    aliases = {"lock": "lock", "lint": "ruff", "types": "mypy", "imports": "imports"}
    if args.checks:
        selected = {aliases.get(check, "pytest") for check in args.checks}
        if "lint" in args.checks:
            selected.add("board-workflow-audit")
        gates = tuple(
            g
            for g in gates
            if g.gate_id in selected or ("pytest" in selected and g.gate_id.startswith("pytest-"))
        )
    versions = {}
    for package in ("pydantic", "PySide6", "pytest", "pytest-qt", "mypy", "ruff", "import-linter"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "missing"
    metadata = {
        "schema": "pcbsmith-development-environment-v1",
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "versions": versions,
        "profile": profile_name,
        "selected_checks": args.checks,
        "full_gate_matrix": args.checks is None,
    }
    (output / "environment.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Running {profile_name} verification; logs and heartbeats: {output}", flush=True)
    run = VerificationOrchestrator(
        runner=SubprocessGateRunner(),
        wall_clock=lambda: datetime.now(UTC).isoformat(),
    ).run(gates=gates, profile=EXECUTION_PROFILES[profile_name], output_dir=output)
    print(f"Verification {run.status}; {len(run.gates)} gates completed", flush=True)
    return 0 if run.status == "passed" else 1


if __name__ == "__main__":
    if sys.argv[1:2] == ["--pytest-worker"]:
        raise SystemExit(pytest_worker(sys.argv[2:]))
    raise SystemExit(main())
