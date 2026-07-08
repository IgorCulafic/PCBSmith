"""Golden-board regression: every topology regenerates fully clean.

Runs the LIVE pipeline (kicad-cli ERC/DRC, ngspice) for all topologies
into a temp directory and asserts the terminal-clean state: ERC passed,
simulation passed, DRC zero violations and zero unconnected items, and
the bundle at needs_human_review. Protects routers, calculators, the
footprint library, and the virtual DRC from silent cross-topology
breakage (hardening plan 4.1).

Slow (~10 min) and environment-dependent; opt in with:

    PCBSMITH_GOLDEN=1 pytest tests/golden

Run it before any commit touching kicad/ or calculators/.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from pcbsmith.cli import main as cli_main
from pcbsmith.kicad.cli import find_kicad_cli
from pcbsmith.simulation.ngspice import find_ngspice

TOPOLOGIES: tuple[tuple[str, str, list[str]], ...] = (
    (
        "divider",
        "design-divider-highpass-led-authority",
        ["--request", "A voltage divider with a high-pass filter and an LED indicator"],
    ),
    (
        "buck",
        "design-lm2596-buck-authority",
        [
            "--request", "An LM2596 buck converter from 12V to 5V at 1A",
            "--evidence-manifest", "ai_assets/evidence/lm2596-buck.manifest.json",
        ],
    ),
    (
        "led-art",
        "design-led-art-authority",
        ["--request", "An LED matrix spelling out IGOR C. for a 12V system"],
    ),
    (
        "mpu6050",
        "design-mpu6050-authority",
        [
            "--request", "Make an MPU6050 gyroscope breakout module",
            "--evidence-manifest", "ai_assets/evidence/mpu6050.manifest.json",
        ],
    ),
    (
        "clover",
        "design-clover-authority",
        [
            "--request", "Make a board in the shape of a 4 leaf clover with tilt LEDs",
            "--evidence-manifest", "ai_assets/evidence/mpu6050.manifest.json",
        ],
    ),
    (
        "pear",
        "design-pear-authority",
        [
            "--request",
            "A pear shaped board with LEDs around the edges in 3 layers, "
            "12V drive, and a worm silkscreen in the middle",
        ],
    ),
    (
        "detector",
        "design-metal-detector-authority",
        [
            "--request",
            "Create a metal detector board that uses exposed traces on the "
            "board as the detector coil",
        ],
    ),
    (
        "flyback",
        "design-flyback-authority",
        ["--request", "120 VAC to 3.3 V flyback converter"],
    ),
    (
        "servo555",
        "design-servo555-authority",
        [
            "--request",
            "Design a compact PCB for a 555-timer-based RC servo driver "
            "tester with forward and reverse buttons",
        ],
    ),
)


requires_live_tools = pytest.mark.skipif(
    not os.environ.get("PCBSMITH_GOLDEN")
    or find_kicad_cli() is None
    or find_ngspice() is None,
    reason="golden regeneration is gated by PCBSMITH_GOLDEN=1 and needs "
    "kicad-cli and ngspice",
)


@pytest.mark.golden
@requires_live_tools
@pytest.mark.parametrize(
    ("name", "command", "extra"),
    TOPOLOGIES,
    ids=[name for name, _c, _e in TOPOLOGIES],
)
def test_topology_regenerates_clean(
    name: str, command: str, extra: list[str], tmp_path: Path
) -> None:
    output_dir = tmp_path / name
    exit_code = cli_main(
        [
            command,
            str(output_dir),
            "--name",
            f"Golden {name}",
            *extra,
        ]
    )
    assert exit_code == 0

    bundle = json.loads(
        (output_dir / "review-bundle-v2.json").read_text(encoding="utf-8")
    )
    assert bundle["status"] == "needs_human_review", bundle["status"]
    assert bundle["board"]["status"] == "needs_human_review"

    drc = json.loads(
        (output_dir / ".pcbsmith" / "kicad" / "drc.json").read_text(
            encoding="utf-8"
        )
    )
    assert drc.get("violations", []) == []
    assert drc.get("unconnected_items", []) == []
