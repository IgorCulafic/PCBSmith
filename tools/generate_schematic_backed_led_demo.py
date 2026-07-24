from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from pcbsmith.ai.ai_context import write_ai_context
from pcbsmith.generators.circuit_examples import (
    CurrentLimitedLedCircuit,
    export_current_limited_led_kicad_project,
)
from pcbsmith.kicad.kicad_preview import (
    format_kicad_preview_report,
    run_kicad_preview,
)
from pcbsmith.kicad.kicad_validate import (
    format_kicad_validation_report,
    run_kicad_validation,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a schematic-backed KiCad 5V LED demo bundle."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".tmp/schematic-backed-led-demo-20260511-01"),
        help="Output directory containing pcbs-project and kicad-review folders.",
    )
    parser.add_argument("--name", default="Schematic Backed LED Demo")
    parser.add_argument("--supply-voltage", default="5V")
    parser.add_argument("--resistor", default="680")
    parser.add_argument("--led", default="Red LED")
    parser.add_argument(
        "--no-polarity-marks",
        action="store_true",
        help="omit educational anode + marks from the board silkscreen",
    )
    args = parser.parse_args()

    output_dir = args.output
    _reset_output_dir(output_dir)
    source_project_dir = output_dir / "pcbs-project"
    review_dir = output_dir / "kicad-review"

    export_current_limited_led_kicad_project(
        source_project_dir,
        review_dir,
        CurrentLimitedLedCircuit(
            name=args.name,
            supply_voltage=args.supply_voltage,
            resistor_value=args.resistor,
            led_value=args.led,
            show_polarity_marks=not args.no_polarity_marks,
        ),
    )
    validation_report = run_kicad_validation(review_dir)
    preview_report = run_kicad_preview(review_dir)
    context_file = review_dir / "ai-context.json"
    write_ai_context(
        source_project_dir,
        context_file,
        kicad_project_dir=review_dir,
    )
    print(f"Review bundle: {review_dir}")
    print(f"Exported KiCad handoff: {review_dir}")
    print("\n".join(format_kicad_validation_report(validation_report)))
    print("\n".join(format_kicad_preview_report(preview_report)))
    print(f"AI context: {context_file}")
    exit_code = max(validation_report.exit_code, preview_report.exit_code)
    if exit_code:
        raise SystemExit(exit_code)


def _reset_output_dir(output_dir: Path) -> None:
    resolved = output_dir.resolve()
    workspace = Path.cwd().resolve()
    if not resolved.is_relative_to(workspace):
        raise ValueError(f"Output must be inside the workspace: {output_dir}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


if __name__ == "__main__":
    main()
