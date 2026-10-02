from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from pcbsmith.kicad.routed_review_bundle import (
    fingerprint,
    review_bundle_status,
    sha256_file,
    validate_review_bundle,
)

ROLES = (
    "3d_top",
    "3d_bottom",
    "2d_top_all",
    "2d_top_copper",
    "2d_bottom_all",
    "2d_bottom_copper",
)


def _bundle(root: Path, case_id: str, board_sha: str) -> Path:
    bundle = root / "qualified" / case_id / f"revision-{board_sha[:12]}"
    bundle.mkdir(parents=True)
    artifacts = []
    for index, role in enumerate(ROLES):
        path = bundle / f"view-{index}.png"
        Image.new("RGB", (1920, 1080), (index, index, index)).save(path)
        artifacts.append(
            {
                "role": role,
                "path": path.name,
                "media_type": "image/png",
                "sha256": sha256_file(path),
                "bytes": path.stat().st_size,
                "width_px": 1920,
                "height_px": 1080,
                "layers": [],
                "mirrored": False,
            }
        )
    payload = {
        "schema_id": "pcbsmith-routed-review-bundle",
        "schema_version": 1,
        "case_id": case_id,
        "routed_board_sha256": board_sha,
        "routed_board_source": "boards/example.kicad_pcb",
        "route_attempt": "attempt-03",
        "renderer_sha256": "a" * 64,
        "kicad_cli_sha256": "b" * 64,
        "kicad_cli_version": "10.0.3",
        "artifacts": artifacts,
    }
    payload["bundle_fingerprint"] = fingerprint(payload)
    manifest = bundle / "review-manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    return manifest


def test_exact_bundle_is_revision_bound(tmp_path: Path) -> None:
    board_sha = "c" * 64
    manifest = _bundle(tmp_path, "RC01", board_sha)

    result = validate_review_bundle(
        manifest, expected_case_id="RC01", expected_board_sha256=board_sha
    )

    assert len(result.artifacts) == 6
    assert (
        review_bundle_status(tmp_path, case_id="RC01", board_sha256=board_sha) == "revision_bound"
    )


def test_artifact_tamper_downgrades_bundle(tmp_path: Path) -> None:
    board_sha = "d" * 64
    manifest = _bundle(tmp_path, "RC02", board_sha)
    (manifest.parent / "view-0.png").write_bytes(b"tampered")

    with pytest.raises(ValueError, match="artifact size mismatch"):
        validate_review_bundle(manifest, expected_case_id="RC02", expected_board_sha256=board_sha)
    assert (
        review_bundle_status(tmp_path, case_id="RC02", board_sha256=board_sha) == "present_unbound"
    )


def test_stale_board_revision_is_not_accepted(tmp_path: Path) -> None:
    _bundle(tmp_path, "RC03", "e" * 64)

    assert review_bundle_status(tmp_path, case_id="RC03", board_sha256="f" * 64) == (
        "present_unbound"
    )
    assert review_bundle_status(tmp_path, case_id="RC04", board_sha256="f" * 64) == "absent"
