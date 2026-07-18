"""Book text extraction toolkit for the layout-craft knowledge base.

Extracts text from the reference books (PDF via pypdf, EPUB via
zipfile+HTML strip) into a gitignored cache with per-page/per-chapter
files, and writes a sha256 manifest so notes can carry stable locators.
The BOOKS and the CACHE never enter git - only the distilled,
page-cited notes in docs/reference/books/ do.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import zipfile
from html.parser import HTMLParser
from pathlib import Path

BOOKS_DIR = Path("D:/AI/PCB designer/Books")
CACHE_DIR = Path("D:/AI/PCB designer/.book-cache")

# slug -> filename substring (unique per book)
BOOKS: dict[str, str] = {
    "johnson-hsdd": "High-Speed Digital Design",
    "ipc-2221b": "IPC-2221 Generic",
    "ott-emc": "Ott - Electromagnetic",
    "montrose-emc": "Printed Circuit Board Design Techniques",
    "bogatin-spi": "Signal and Power Integrity",
    "williams-cdc": "Circuit Designer",
    "ipc-7351": "IPC-7351",
    "ipc-a-610": "IPC-A-610",
    "coombs-pch": "Printed Circuits Handbook",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in ("style", "script"):
            self._skip += 1
        if tag in ("p", "div", "h1", "h2", "h3", "h4", "li", "br", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("style", "script") and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    text = "".join(parser.parts)
    return re.sub(r"\n{3,}", "\n\n", text)


def _file_for(slug: str) -> Path:
    needle = BOOKS[slug]
    for path in BOOKS_DIR.iterdir():
        if needle.lower() in path.name.lower():
            return path
    raise SystemExit(f"No book file matching {needle!r}")


def extract_pdf(slug: str) -> dict[str, object]:
    from pypdf import PdfReader

    path = _file_for(slug)
    out_dir = CACHE_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    reader = PdfReader(str(path))
    pages = len(reader.pages)
    empty = 0
    for index in range(pages):
        text = reader.pages[index].extract_text() or ""
        if len(text.strip()) < 20:
            empty += 1
        (out_dir / f"p{index + 1:04d}.txt").write_text(
            text, encoding="utf-8"
        )
    return {"pages": pages, "empty_pages": empty, "format": "pdf"}


def extract_epub(slug: str) -> dict[str, object]:
    path = _file_for(slug)
    out_dir = CACHE_DIR / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(path) as archive:
        names = [
            name for name in archive.namelist()
            if name.lower().endswith((".xhtml", ".html", ".htm"))
        ]
        for index, name in enumerate(sorted(names)):
            html = archive.read(name).decode("utf-8", errors="replace")
            text = _html_to_text(html)
            stem = re.sub(r"[^A-Za-z0-9._-]", "_", Path(name).name)
            (out_dir / f"c{index + 1:04d}-{stem}.txt").write_text(
                text, encoding="utf-8"
            )
            count += 1
    return {"chapters": count, "format": "epub"}


def main() -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    manifest: dict[str, object] = {}
    targets = sys.argv[1:] or list(BOOKS)
    for slug in targets:
        path = _file_for(slug)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if path.suffix.lower() == ".epub":
            info = extract_epub(slug)
        else:
            info = extract_pdf(slug)
        manifest[slug] = {
            "file": path.name, "sha256": digest, **info,
        }
        print(slug, json.dumps(info))
    manifest_path = CACHE_DIR / "manifest.json"
    existing = (
        json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest_path.exists() else {}
    )
    existing.update(manifest)
    manifest_path.write_text(
        json.dumps(existing, indent=2), encoding="utf-8"
    )
    print("manifest written")


if __name__ == "__main__":
    main()
