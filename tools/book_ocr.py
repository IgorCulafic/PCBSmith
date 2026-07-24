"""OCR the scanned reference books (no text layer) into the cache.

Pure-python: pypdfium2 rasterizes, RapidOCR (ONNX) recognizes. Writes
the same per-page cache layout as book_extract.py and updates the
manifest. Resumable: pages with existing non-empty output are skipped.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pypdfium2 as pdfium
from rapidocr_onnxruntime import RapidOCR

BOOKS_DIR = Path("D:/AI/PCB designer/Books")
CACHE_DIR = Path("D:/AI/PCB designer/.book-cache")

SCANNED: dict[str, str] = {
    "johnson-hsdd": "High-Speed Digital Design",
    "ipc-7351": "IPC-7351",
    "ipc-2222-original": "IPC-2222 eng",
    "ipc-7525-original": "IPC-7525 eng",
}


def _file_for(needle: str) -> Path:
    for path in BOOKS_DIR.iterdir():
        if needle.lower() in path.name.lower():
            return path
    raise SystemExit(f"No book file matching {needle!r}")


def ocr_book(slug: str) -> None:
    path = _file_for(SCANNED[slug])
    out_dir = CACHE_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    ocr = RapidOCR()
    pdf = pdfium.PdfDocument(str(path))
    total = len(pdf)
    done = 0
    for index in range(total):
        target = out_dir / f"p{index + 1:04d}.txt"
        if target.exists() and target.stat().st_size > 20:
            continue
        bitmap = pdf[index].render(scale=2.0)
        pil = bitmap.to_pil()
        image_path = out_dir / "_page.png"
        pil.save(image_path)
        result, _elapsed = ocr(str(image_path))
        lines = [entry[1] for entry in result] if result else []
        target.write_text("\n".join(lines), encoding="utf-8")
        done += 1
        if done % 25 == 0:
            print(f"{slug}: {index + 1}/{total}", flush=True)
    (out_dir / "_page.png").unlink(missing_ok=True)
    manifest_path = CACHE_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest[slug]["ocr"] = True
    manifest[slug]["empty_pages"] = 0
    manifest_path.write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"{slug}: OCR complete ({total} pages)")


if __name__ == "__main__":
    for slug in sys.argv[1:] or list(SCANNED):
        ocr_book(slug)
