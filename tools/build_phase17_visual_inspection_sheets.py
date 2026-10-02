"""Build hash-bound contact sheets for manual Phase 17 corpus inspection."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROLES = (
    "3d_top",
    "3d_bottom",
    "2d_top_all",
    "2d_top_copper",
    "2d_bottom_all",
    "2d_bottom_copper",
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def build(review_root: Path, output: Path) -> dict[str, object]:
    manifests = tuple(sorted(review_root.glob("*/revision-*/review-manifest.json")))
    if len(manifests) != 40:
        raise ValueError(f"expected 40 canonical review manifests, found {len(manifests)}")
    output.mkdir(parents=True, exist_ok=True)
    font = ImageFont.load_default(size=18)
    title_font = ImageFont.load_default(size=24)
    sources: list[dict[str, object]] = []
    by_role: dict[str, list[tuple[str, str, Path]]] = {role: [] for role in ROLES}
    for manifest_path in manifests:
        manifest = _read(manifest_path)
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list):
            raise TypeError(f"manifest artifacts are malformed: {manifest_path}")
        artifacts_by_role = {
            str(item["role"]): item for item in artifacts if isinstance(item, dict)
        }
        if set(artifacts_by_role) != set(ROLES):
            raise ValueError(f"manifest role set is incomplete: {manifest_path}")
        case_id = str(manifest["case_id"])
        board_sha = str(manifest["routed_board_sha256"])
        artifact_records: dict[str, object] = {}
        source_record: dict[str, object] = {
            "case_id": case_id,
            "board_sha256": board_sha,
            "manifest": manifest_path.relative_to(review_root).as_posix(),
            "manifest_sha256": _sha256(manifest_path),
            "artifacts": artifact_records,
        }
        for role in ROLES:
            artifact = artifacts_by_role[role]
            path = manifest_path.parent / str(artifact["path"])
            digest = _sha256(path)
            if digest != artifact["sha256"]:
                raise ValueError(f"image hash mismatch: {path}")
            artifact_records[role] = {
                "path": path.relative_to(review_root).as_posix(),
                "sha256": digest,
            }
            by_role[role].append((case_id, board_sha, path))
        sources.append(source_record)
    sheets: list[dict[str, object]] = []
    tile_width = 480
    tile_image_height = 300
    tile_label_height = 34
    columns = 4
    rows = 5
    title_height = 54
    for role in ROLES:
        records = sorted(by_role[role])
        for page_index, start in enumerate(range(0, len(records), columns * rows), start=1):
            page = records[start : start + columns * rows]
            sheet = Image.new(
                "RGB",
                (
                    columns * tile_width,
                    title_height + rows * (tile_image_height + tile_label_height),
                ),
                "#20242b",
            )
            draw = ImageDraw.Draw(sheet)
            draw.text(
                (18, 14),
                f"Phase 17 canonical review - {role} - page {page_index}/2",
                font=title_font,
                fill="white",
            )
            for offset, (case_id, board_sha, path) in enumerate(page):
                column = offset % columns
                row = offset // columns
                x = column * tile_width
                y = title_height + row * (tile_image_height + tile_label_height)
                with Image.open(path) as source:
                    image = source.convert("RGB")
                    image.thumbnail(
                        (tile_width - 12, tile_image_height - 12), Image.Resampling.LANCZOS
                    )
                    image_x = x + (tile_width - image.width) // 2
                    image_y = y + (tile_image_height - image.height) // 2
                    sheet.paste(image, (image_x, image_y))
                draw.rectangle(
                    (x, y, x + tile_width - 1, y + tile_image_height + tile_label_height - 1),
                    outline="#59636f",
                    width=1,
                )
                draw.text(
                    (x + 12, y + tile_image_height + 6),
                    f"{case_id}  revision {board_sha[:12]}",
                    font=font,
                    fill="#f2f4f7",
                )
            sheet_path = output / f"{role}-page-{page_index}.png"
            sheet.save(sheet_path, format="PNG", optimize=True)
            sheets.append(
                {
                    "role": role,
                    "page": page_index,
                    "case_ids": [item[0] for item in page],
                    "path": sheet_path.name,
                    "sha256": _sha256(sheet_path),
                    "width_px": sheet.width,
                    "height_px": sheet.height,
                }
            )
    index: dict[str, object] = {
        "schema": "pcbsmith-phase17-visual-inspection-index-v1",
        "review_root": review_root.as_posix(),
        "canonical_manifest_count": len(manifests),
        "source_image_count": len(manifests) * len(ROLES),
        "roles": list(ROLES),
        "sources": sources,
        "contact_sheets": sheets,
        "inspection_status": "pending_manual_visual_review",
        "acceptance_boundary": (
            "Contact sheets support systematic human/AI visual inspection; their generation and "
            "hash validation do not approve board quality."
        ),
    }
    index["index_fingerprint"] = hashlib.sha256(
        json.dumps(index, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    (output / "inspection-index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return index


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--review-root",
        type=Path,
        default=Path("experiments/phase17-routing-corpus-40/review/qualified"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("experiments/phase17-routing-corpus-40/review/human-inspection-2026-08-15"),
    )
    args = parser.parse_args()
    result = build(args.review_root.resolve(), args.output.resolve())
    contact_sheets = result["contact_sheets"]
    if not isinstance(contact_sheets, list):
        raise TypeError("contact sheet result is malformed")
    print(
        json.dumps(
            {
                "manifests": result["canonical_manifest_count"],
                "source_images": result["source_image_count"],
                "contact_sheets": len(contact_sheets),
                "index_fingerprint": result["index_fingerprint"],
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
