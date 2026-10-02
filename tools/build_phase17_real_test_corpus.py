"""Build the frozen 40-board, four-tier Phase 17 real routing test."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from pcbsmith.kicad.routing_real_test_corpus import write_real_test_corpus


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("experiments/phase17-real-test-40-2026-08-16"),
    )
    args = parser.parse_args()
    summary = write_real_test_corpus(args.output.resolve())
    print(
        json.dumps(
            {
                "case_count": summary["case_count"],
                "success_count": summary["success_count"],
                "tier_counts": summary["tier_counts"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
