from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from pcbsmith.services.ai_context import write_ai_context
from pcbsmith.services.circuit_examples import (
    Timer555PwmDimmerCircuit,
    export_timer_555_pwm_dimmer_kicad_project,
)
from pcbsmith.services.kicad_preview import (
    format_kicad_preview_report,
    run_kicad_preview,
)
from pcbsmith.services.kicad_validate import (
    format_kicad_validation_report,
    run_kicad_validation,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a schematic-backed KiCad NE555 PWM LED dimmer bundle."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".tmp/555-pwm-dimmer-demo-20260511-01"),
        help="Output directory containing pcbs-project and kicad-review folders.",
    )
    parser.add_argument("--name", default="555 PWM Dimmer")
    parser.add_argument("--supply-voltage", default="5-12V")
    parser.add_argument("--potentiometer", default="100k")
    parser.add_argument("--timing-capacitor", default="10nF")
    parser.add_argument("--decoupling-capacitor", default="100nF")
    parser.add_argument("--control-capacitor", default="10nF")
    parser.add_argument("--gate-resistor", default="100")
    parser.add_argument("--gate-pulldown", default="100k")
    parser.add_argument("--diode", default="1N4148")
    parser.add_argument("--mosfet", default="Logic N-MOSFET")
    parser.add_argument("--load-label", default="LED OUT")
    args = parser.parse_args()

    output_dir = args.output
    _reset_output_dir(output_dir)
    source_project_dir = output_dir / "pcbs-project"
    review_dir = output_dir / "kicad-review"

    export_timer_555_pwm_dimmer_kicad_project(
        source_project_dir,
        review_dir,
        Timer555PwmDimmerCircuit(
            name=args.name,
            supply_voltage=args.supply_voltage,
            potentiometer_value=args.potentiometer,
            timing_capacitor=args.timing_capacitor,
            decoupling_capacitor=args.decoupling_capacitor,
            control_capacitor=args.control_capacitor,
            gate_resistor=args.gate_resistor,
            gate_pulldown=args.gate_pulldown,
            steering_diode=args.diode,
            mosfet_value=args.mosfet,
            load_label=args.load_label,
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
