from __future__ import annotations

import json
from pathlib import Path

from pcbsmith.cli import main


def test_design_divider_highpass_led_writes_review_bundle(tmp_path: Path) -> None:
    output_dir = tmp_path / "slice"

    exit_code = main(
        [
            "design-divider-highpass-led",
            str(output_dir),
            "--request",
            "Generate a voltage divider connected to a high-pass filter and LED indicator",
            "--name",
            "Trusted Slice",
        ]
    )

    assert exit_code == 0
    assert (output_dir / "project.pcbsmith.json").exists()
    data = json.loads((output_dir / "review-bundle.json").read_text(encoding="utf-8"))
    assert data["status"] == "needs_human_review"
    assert data["artifacts"]["pcbs_project"] == str(output_dir)
