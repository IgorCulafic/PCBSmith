"""Independently audit all Phase 17 revision-bound review bundles."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from PIL import Image, ImageStat

from pcbsmith.kicad.routed_review_bundle import (
    fingerprint,
    latest_hash_bound_routed_board,
    sha256_file,
    validate_review_bundle,
)


def audit(root: Path) -> dict[str, object]:
    records: list[dict[str, object]] = []
    low_variance: list[str] = []
    renderer_hashes: Counter[str] = Counter()
    kicad_hashes: Counter[str] = Counter()
    total_bytes = 0
    for case_dir in sorted((root / "boards").iterdir()):
        if not case_dir.is_dir():
            continue
        case_id = case_dir.name.split("-", 1)[0]
        _attempt, board = latest_hash_bound_routed_board(case_dir)
        board_sha = sha256_file(board)
        manifest = (
            root
            / "review"
            / "qualified"
            / case_id
            / f"revision-{board_sha[:12]}"
            / "review-manifest.json"
        )
        bundle = validate_review_bundle(
            manifest, expected_case_id=case_id, expected_board_sha256=board_sha
        )
        renderer_hashes[bundle.renderer_sha256] += 1
        kicad_hashes[bundle.kicad_cli_sha256] += 1
        minimum_variance = float("inf")
        for artifact in bundle.artifacts:
            path = manifest.parent / artifact.path
            total_bytes += artifact.bytes
            with Image.open(path) as image:
                variance = max(ImageStat.Stat(image.convert("RGB")).var)
            minimum_variance = min(minimum_variance, variance)
            if variance < 1.0:
                low_variance.append(f"{case_id}/{artifact.role}")
        records.append(
            {
                "case_id": case_id,
                "routed_board_sha256": board_sha,
                "manifest": manifest.relative_to(root).as_posix(),
                "bundle_fingerprint": bundle.bundle_fingerprint,
                "artifact_count": len(bundle.artifacts),
                "minimum_channel_variance": round(minimum_variance, 6),
            }
        )
    payload: dict[str, object] = {
        "schema": "pcbsmith-phase17-review-bundle-audit-v1",
        "case_count": len(records),
        "revision_bound_case_count": len(records),
        "artifact_count": sum(int(record["artifact_count"]) for record in records),
        "artifact_bytes": total_bytes,
        "low_variance_artifacts": sorted(low_variance),
        "renderer_sha256_counts": dict(sorted(renderer_hashes.items())),
        "kicad_cli_sha256_counts": dict(sorted(kicad_hashes.items())),
        "complete": len(records) == 40 and not low_variance,
        "cases": records,
    }
    payload["audit_fingerprint"] = fingerprint(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("experiments/phase17-routing-corpus-40"))
    args = parser.parse_args()
    root = args.root.resolve()
    result = audit(root)
    output = root / "review" / "qualified" / "audit-summary.json"
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "case_count",
                    "revision_bound_case_count",
                    "artifact_count",
                    "artifact_bytes",
                    "low_variance_artifacts",
                    "complete",
                )
            }
        )
    )
    if result["complete"] is not True:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
