"""Revision-bound visual review bundles for routed KiCad boards."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal, Self

from PIL import Image
from pydantic import Field, model_validator

from pcbsmith.semantic_ir import SemanticIrModel


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def latest_hash_bound_routed_board(case_dir: Path) -> tuple[str, Path]:
    """Return the latest retained route whose evidence names its exact board hash."""

    root = case_dir / "external" / "freerouting-v2.2.4"
    candidates: list[tuple[str, Path]] = []
    for attempt in root.glob("attempt-*"):
        evidence = attempt / "route-evidence.json"
        boards = tuple(attempt.glob("*-freerouting.kicad_pcb"))
        if not evidence.exists() or len(boards) != 1:
            continue
        payload = json.loads(evidence.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError(f"Expected JSON object: {evidence}")
        if payload.get("routed_board_sha256") == sha256_file(boards[0]):
            candidates.append((attempt.name, boards[0]))
    if not candidates:
        raise FileNotFoundError(f"No hash-bound routed attempt for {case_dir.name}")
    return sorted(candidates)[-1]


def _sha(value: str, name: str) -> str:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")
    return value


class ReviewArtifact(SemanticIrModel):
    role: Literal[
        "3d_top",
        "3d_bottom",
        "2d_top_all",
        "2d_top_copper",
        "2d_bottom_all",
        "2d_bottom_copper",
    ]
    path: str
    media_type: Literal["image/png"]
    sha256: str
    bytes: int = Field(gt=0)
    width_px: int = Field(ge=1920)
    height_px: int = Field(ge=1080)
    layers: tuple[str, ...] = ()
    mirrored: bool = False

    @model_validator(mode="after")
    def coherent(self) -> Self:
        _sha(self.sha256, "artifact sha256")
        if Path(self.path).name != self.path or self.path in {".", ".."}:
            raise ValueError("artifact path must be one safe filename")
        if Path(self.path).suffix.lower() != ".png":
            raise ValueError("review artifact must be a PNG filename")
        return self


class RoutedReviewBundle(SemanticIrModel):
    schema_id: Literal["pcbsmith-routed-review-bundle"] = "pcbsmith-routed-review-bundle"
    schema_version: Literal[1] = 1
    case_id: str
    routed_board_sha256: str
    routed_board_source: str
    route_attempt: str
    renderer_sha256: str
    kicad_cli_sha256: str
    kicad_cli_version: str
    artifacts: tuple[ReviewArtifact, ...]
    bundle_fingerprint: str

    @model_validator(mode="after")
    def coherent(self) -> Self:
        for name in ("routed_board_sha256", "renderer_sha256", "kicad_cli_sha256"):
            _sha(getattr(self, name), name)
        roles = tuple(sorted(artifact.role for artifact in self.artifacts))
        expected = tuple(
            sorted(
                (
                    "3d_top",
                    "3d_bottom",
                    "2d_top_all",
                    "2d_top_copper",
                    "2d_bottom_all",
                    "2d_bottom_copper",
                )
            )
        )
        if roles != expected:
            raise ValueError("review bundle must contain each required role exactly once")
        paths = tuple(artifact.path for artifact in self.artifacts)
        if len(set(paths)) != len(paths):
            raise ValueError("review bundle artifact paths must be unique")
        payload = self.model_dump(mode="json", exclude={"bundle_fingerprint"})
        if self.bundle_fingerprint != fingerprint(payload):
            raise ValueError("review bundle fingerprint is stale")
        return self


def validate_review_bundle(
    manifest_path: Path, *, expected_case_id: str, expected_board_sha256: str
) -> RoutedReviewBundle:
    """Validate a manifest, exact board binding, and every retained image hash."""

    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    bundle = RoutedReviewBundle.model_validate(raw)
    if bundle.case_id != expected_case_id:
        raise ValueError("review bundle case identity mismatch")
    if bundle.routed_board_sha256 != expected_board_sha256:
        raise ValueError("review bundle board hash mismatch")
    root = manifest_path.parent.resolve()
    for artifact in bundle.artifacts:
        path = (root / artifact.path).resolve()
        if path.parent != root:
            raise ValueError("review artifact escapes its bundle directory")
        if not path.is_file():
            raise FileNotFoundError(path)
        if path.stat().st_size != artifact.bytes:
            raise ValueError(f"review artifact size mismatch: {artifact.path}")
        if sha256_file(path) != artifact.sha256:
            raise ValueError(f"review artifact hash mismatch: {artifact.path}")
        with Image.open(path) as image:
            if image.format != "PNG":
                raise ValueError(f"review artifact is not PNG: {artifact.path}")
            if image.size != (artifact.width_px, artifact.height_px):
                raise ValueError(f"review artifact dimensions mismatch: {artifact.path}")
            image.verify()
    return bundle


def review_bundle_status(review_root: Path, *, case_id: str, board_sha256: str) -> str:
    """Return the qualification vocabulary without mistaking stale files for evidence."""

    case_root = review_root / "qualified" / case_id
    manifest = case_root / f"revision-{board_sha256[:12]}" / "review-manifest.json"
    if not case_root.exists():
        return "absent"
    if not manifest.exists():
        return "present_unbound"
    try:
        validate_review_bundle(
            manifest, expected_case_id=case_id, expected_board_sha256=board_sha256
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return "present_unbound"
    return "revision_bound"
