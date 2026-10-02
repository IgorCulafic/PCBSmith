from __future__ import annotations

import json
from pathlib import Path

from tools.run_phase17_copper_topology_pilot import (
    _required_escape_counts,
    _semantic_unconnected_signatures,
)


def test_required_escape_counts_ignore_already_connected_through_hole() -> None:
    assert _required_escape_counts(
        {
            "through-hole": {"required": False, "satisfied": True},
            "legal": {"required": True, "satisfied": True},
            "blocked": {"required": True, "satisfied": False},
        }
    ) == (2, 1, 1)


def test_semantic_signatures_ignore_generated_uuid_changes(tmp_path: Path) -> None:
    reports = []
    for index, uuid in enumerate(("generated-a", "generated-b")):
        report = tmp_path / f"drc-{index}.json"
        report.write_text(
            json.dumps(
                {
                    "unconnected_items": [
                        {
                            "description": "Missing connection between items",
                            "items": [
                                {
                                    "description": "Zone 'POWER' [VIN] on F.Cu",
                                    "pos": {"x": 10, "y": 20},
                                    "uuid": uuid,
                                },
                                {
                                    "description": "Pad 1 [VIN] of J1 on F.Cu",
                                    "pos": {"x": 12.5, "y": 20},
                                    "uuid": "stable-pad",
                                },
                            ],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        reports.append(report)

    assert _semantic_unconnected_signatures(reports[0]) == _semantic_unconnected_signatures(
        reports[1]
    )
