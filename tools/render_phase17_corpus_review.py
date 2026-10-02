"""Generate transactional, revision-bound review bundles for Phase 17 boards."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import uuid
from pathlib import Path

from PIL import Image

from pcbsmith.kicad.routed_review_bundle import (
    ReviewArtifact,
    RoutedReviewBundle,
    fingerprint,
    sha256_file,
    validate_review_bundle,
)
from pcbsmith.review.visual_package import rasterize_svg_with_resvg


def _case_dir(root: Path, case_id: str) -> Path:
    matches = sorted((root / "boards").glob(f"{case_id}-*"))
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected exactly one directory for {case_id}, found {matches}")
    return matches[0]


def _read_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return value


def _latest_board(case_dir: Path) -> tuple[str, Path]:
    root = case_dir / "external" / "freerouting-v2.2.4"
    candidates: list[tuple[str, Path]] = []
    for attempt in root.glob("attempt-*"):
        evidence = attempt / "route-evidence.json"
        boards = tuple(attempt.glob("*-freerouting.kicad_pcb"))
        if evidence.exists() and len(boards) == 1:
            payload = _read_object(evidence)
            if payload.get("routed_board_sha256") == sha256_file(boards[0]):
                candidates.append((attempt.name, boards[0]))
    if not candidates:
        raise FileNotFoundError(f"No hash-bound routed attempt for {case_dir.name}")
    return sorted(candidates)[-1]


def _run(command: tuple[str, ...]) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    if result.stderr:
        raise RuntimeError(f"Unexpected renderer diagnostics: {result.stderr.strip()}")
    return result.stdout.strip()


def _svg(
    kicad_cli: Path,
    board: Path,
    output: Path,
    layers: tuple[str, ...],
    *,
    mirror: bool,
) -> None:
    command = [
        str(kicad_cli),
        "pcb",
        "export",
        "svg",
        "--mode-single",
        "--output",
        str(output),
        "--layers",
        ",".join(layers),
        "--fit-page-to-board",
        "--exclude-drawing-sheet",
    ]
    if mirror:
        command.append("--mirror")
    command.append(str(board))
    _run(tuple(command))
    rasterize_svg_with_resvg(output, output.with_suffix(".png"), 2400, 1600, None)


def render_case(kicad_cli: Path, board: Path, output: Path) -> tuple[ReviewArtifact, ...]:
    """Render the canonical six-view set; callers may retain the four source SVGs."""

    output.mkdir(parents=True, exist_ok=True)
    for side in ("top", "bottom"):
        _run(
            (
                str(kicad_cli),
                "pcb",
                "render",
                "--output",
                str(output / f"3d-{side}-2560x1440.png"),
                "--width",
                "2560",
                "--height",
                "1440",
                "--side",
                side,
                "--quality",
                "high",
                "--background",
                "opaque",
                str(board),
            )
        )
    views = (
        (
            "2d_top_all",
            "2d-top-all.svg",
            ("F.Cu", "F.Silkscreen", "F.Fab", "Edge.Cuts"),
            False,
        ),
        ("2d_top_copper", "2d-top-copper.svg", ("F.Cu", "Edge.Cuts"), False),
        (
            "2d_bottom_all",
            "2d-bottom-all.svg",
            ("B.Cu", "B.Silkscreen", "B.Fab", "Edge.Cuts"),
            True,
        ),
        ("2d_bottom_copper", "2d-bottom-copper.svg", ("B.Cu", "Edge.Cuts"), True),
    )
    for _role, filename, layers, mirrored in views:
        _svg(kicad_cli, board, output / filename, layers, mirror=mirrored)

    specifications = (
        ("3d_top", "3d-top-2560x1440.png", (), False),
        ("3d_bottom", "3d-bottom-2560x1440.png", (), False),
        *(
            (role, Path(filename).with_suffix(".png").name, layers, mirrored)
            for role, filename, layers, mirrored in views
        ),
    )
    artifacts: list[ReviewArtifact] = []
    for role, filename, layers, mirrored in specifications:
        path = output / filename
        with Image.open(path) as image:
            width, height = image.size
            image.verify()
        artifacts.append(
            ReviewArtifact(
                role=role,
                path=filename,
                media_type="image/png",
                sha256=sha256_file(path),
                bytes=path.stat().st_size,
                width_px=width,
                height_px=height,
                layers=layers,
                mirrored=mirrored,
            )
        )
    return tuple(artifacts)


def _bundle(
    *,
    case_id: str,
    root: Path,
    attempt: str,
    board: Path,
    renderer: Path,
    kicad_cli: Path,
    artifacts: tuple[ReviewArtifact, ...],
) -> RoutedReviewBundle:
    payload: dict[str, object] = {
        "schema_id": "pcbsmith-routed-review-bundle",
        "schema_version": 1,
        "case_id": case_id,
        "routed_board_sha256": sha256_file(board),
        "routed_board_source": board.resolve().relative_to(root).as_posix(),
        "route_attempt": attempt,
        "renderer_sha256": sha256_file(renderer),
        "kicad_cli_sha256": sha256_file(kicad_cli),
        "kicad_cli_version": _run((str(kicad_cli), "--version")),
        "artifacts": [artifact.model_dump(mode="json") for artifact in artifacts],
    }
    payload["bundle_fingerprint"] = fingerprint(payload)
    return RoutedReviewBundle.model_validate(payload)


def render_bound_case(*, root: Path, kicad_cli: Path, case_id: str) -> Path:
    case_dir = _case_dir(root, case_id)
    attempt, board = _latest_board(case_dir)
    board_sha = sha256_file(board)
    case_root = root / "review" / "qualified" / case_id
    target = case_root / f"revision-{board_sha[:12]}"
    manifest = target / "review-manifest.json"
    if target.exists():
        validate_review_bundle(manifest, expected_case_id=case_id, expected_board_sha256=board_sha)
        return manifest
    case_root.mkdir(parents=True, exist_ok=True)
    staging = case_root / f".staging-{board_sha[:12]}-{uuid.uuid4().hex}"
    try:
        artifacts = render_case(kicad_cli, board, staging)
        bundle = _bundle(
            case_id=case_id,
            root=root,
            attempt=attempt,
            board=board,
            renderer=Path(__file__).resolve(),
            kicad_cli=kicad_cli,
            artifacts=artifacts,
        )
        staging_manifest = staging / "review-manifest.json"
        staging_manifest.write_text(
            json.dumps(bundle.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        validate_review_bundle(
            staging_manifest, expected_case_id=case_id, expected_board_sha256=board_sha
        )
        staging.rename(target)
        return manifest
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("experiments/phase17-routing-corpus-40"))
    parser.add_argument(
        "--kicad-cli",
        type=Path,
        default=Path(r"C:\Program Files\KiCad\10.0\bin\kicad-cli.exe"),
    )
    parser.add_argument("--cases", nargs="*")
    args = parser.parse_args()
    root = args.root.resolve()
    kicad_cli = args.kicad_cli.resolve()
    case_ids = tuple(
        args.cases
        or (
            path.name.split("-", 1)[0]
            for path in sorted((root / "boards").iterdir())
            if path.is_dir()
        )
    )
    for index, case_id in enumerate(case_ids, 1):
        manifest = render_bound_case(root=root, kicad_cli=kicad_cli, case_id=case_id)
        print(f"[{index}/{len(case_ids)}] {case_id}: {manifest}", flush=True)


if __name__ == "__main__":
    main()
