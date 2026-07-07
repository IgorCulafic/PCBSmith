"""Reference-design ingestion (hardening plan 4.3).

A professional design's OUTPUT PACK (Altium/KiCad fab exports: BOM
spreadsheet, NC-drill report, schematic/fab-drawing PDFs, gerbers) is
machine-readable gold: the FLBACK-001 pack took minutes to mine by hand
and directly seeded component knowledge and fab-note structure. This
module turns such a folder into a stored, comparable record under
``ai_assets/references/<slug>/`` so every future pack becomes evidence
instead of a one-off reading session.

No third-party dependencies for the core: xlsx is a zip of XML, DRR/REP
are plain text. PDF text extraction uses pypdf when the ``[extraction]``
extra is installed and degrades to a note when it is not.
"""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

REFERENCES_DIR = Path(__file__).resolve().parents[2] / "ai_assets" / "references"


class ReferenceIngestError(RuntimeError):
    pass


@dataclass(frozen=True)
class DrillRow:
    tool: str
    size: str
    tolerance: str
    hole_type: str
    count: int
    plated: str


@dataclass(frozen=True)
class ReferenceRecord:
    slug: str
    name: str
    source_dir: str
    bom_rows: tuple[dict[str, str], ...] = ()
    drill_rows: tuple[DrillRow, ...] = ()
    pdf_texts: tuple[tuple[str, str], ...] = ()  # (file name, text)
    gerber_files: tuple[str, ...] = ()
    components: tuple[dict[str, object], ...] = ()
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_id": "pcbsmith-reference-record-v1",
            "slug": self.slug,
            "name": self.name,
            "source_dir": self.source_dir,
            "bom_rows": list(self.bom_rows),
            "drill_table": [
                {
                    "tool": row.tool,
                    "size": row.size,
                    "tolerance": row.tolerance,
                    "type": row.hole_type,
                    "count": row.count,
                    "plated": row.plated,
                }
                for row in self.drill_rows
            ],
            "pdf_files": [name for name, _ in self.pdf_texts],
            "gerber_files": list(self.gerber_files),
            "components": list(self.components),
            "notes": list(self.notes),
        }


def _xlsx_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        raw = archive.read("xl/sharedStrings.xml").decode("utf-8", "replace")
    except KeyError:
        return []
    items = re.findall(r"<si>(.*?)</si>", raw, re.S)
    return [
        "".join(re.findall(r"<t[^>]*>(.*?)</t>", item, re.S)) for item in items
    ]


def parse_bom_xlsx(path: Path) -> tuple[dict[str, str], ...]:
    """First-sheet rows as header-keyed dicts (Altium BOM layout)."""
    with zipfile.ZipFile(path) as archive:
        strings = _xlsx_shared_strings(archive)
        sheet_names = [
            name
            for name in archive.namelist()
            if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
        ]
        if not sheet_names:
            raise ReferenceIngestError(f"{path} has no worksheets.")
        sheet = archive.read(sorted(sheet_names)[0]).decode("utf-8", "replace")

    rows: list[list[str]] = []
    for row_xml in re.findall(r"<row[^>]*>(.*?)</row>", sheet, re.S):
        values: list[str] = []
        for cell in re.finditer(
            r"<c\b([^>]*)>(?:<v>(.*?)</v>)?", row_xml
        ):
            attrs, value = cell.group(1), cell.group(2)
            if value is None:
                continue
            if re.search(r'\bt="s"', attrs):
                index = int(value)
                values.append(strings[index] if index < len(strings) else "")
            else:
                values.append(value)
        if values:
            rows.append(values)
    if not rows:
        return ()
    header = rows[0]
    return tuple(
        {
            header[i]: cell
            for i, cell in enumerate(row)
            if i < len(header) and header[i]
        }
        for row in rows[1:]
    )


_DRR_ROW = re.compile(
    r"^(T\d+)\s+(\S+ \([^)]*\))\s+(\S+ \([^)]*\))\s+(\w+)\s+(\d+)\s+(\w+)",
    re.M,
)


def parse_drill_report(path: Path) -> tuple[DrillRow, ...]:
    """Tool rows from an Altium .DRR NC-drill report."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return tuple(
        DrillRow(
            tool=match.group(1),
            size=match.group(2),
            tolerance=match.group(3),
            hole_type=match.group(4),
            count=int(match.group(5)),
            plated=match.group(6),
        )
        for match in _DRR_ROW.finditer(text)
    )


_ODB_CMP = re.compile(
    r"^CMP\s+\S+\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s+\S+\s+(\S+)\s+(\S+)",
    re.M,
)
_ODB_INCH_MM = 25.4


def parse_odb_components(odb_root: Path) -> tuple[dict[str, object], ...]:
    """Component placements from an extracted ODB++ tree (inches -> mm).

    Looks for the standard ``comp_+_top`` / ``comp_+_bot`` layers under
    any ``steps/*/layers`` directory. Placement data is the part of a
    fab pack the PDFs cannot deliver machine-readably.
    """
    rows: list[dict[str, object]] = []
    for components_file in sorted(odb_root.rglob("components")):
        layer = components_file.parent.name
        if layer == "comp_+_top":
            side = "top"
        elif layer == "comp_+_bot":
            side = "bottom"
        else:
            continue
        text = components_file.read_text(encoding="utf-8", errors="replace")
        for match in _ODB_CMP.finditer(text):
            rows.append(
                {
                    "reference": match.group(4),
                    "value": match.group(5),
                    "x_mm": round(float(match.group(1)) * _ODB_INCH_MM, 2),
                    "y_mm": round(float(match.group(2)) * _ODB_INCH_MM, 2),
                    "rotation": float(match.group(3)),
                    "side": side,
                }
            )
    return tuple(rows)


def _pdf_text(path: Path) -> str | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    reader = PdfReader(str(path))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def ingest_reference_pack(
    source_dir: Path, *, slug: str | None = None
) -> ReferenceRecord:
    if not source_dir.is_dir():
        raise ReferenceIngestError(f"{source_dir} is not a directory.")
    project_files = sorted(source_dir.glob("*.PrjPcb")) + sorted(
        source_dir.glob("*.kicad_pro")
    )
    name = project_files[0].stem if project_files else source_dir.name
    record_slug = slug or re.sub(r"[^a-z0-9]+", "-", source_dir.name.lower()).strip("-")

    notes: list[str] = []

    bom_rows: tuple[dict[str, str], ...] = ()
    bom_files = sorted(source_dir.rglob("*.xlsx"))
    if bom_files:
        bom_rows = parse_bom_xlsx(bom_files[0])
        if len(bom_files) > 1:
            notes.append(
                f"Multiple xlsx files; ingested {bom_files[0].name} only."
            )
    else:
        notes.append("No BOM spreadsheet found.")

    drill_rows: tuple[DrillRow, ...] = ()
    drr_files = sorted(source_dir.rglob("*.DRR"))
    if drr_files:
        drill_rows = parse_drill_report(drr_files[0])

    pdf_texts: list[tuple[str, str]] = []
    for pdf in sorted(source_dir.rglob("*.PDF")) + sorted(source_dir.rglob("*.pdf")):
        text = _pdf_text(pdf)
        if text is None:
            notes.append(
                f"pypdf not installed; {pdf.name} text was not extracted."
            )
            break
        pdf_texts.append((pdf.name, text))

    components = parse_odb_components(source_dir)

    gerbers = tuple(
        sorted(
            path.name
            for path in source_dir.rglob("*")
            if path.suffix.upper()
            in (".GTL", ".GBL", ".GTO", ".GBO", ".GTS", ".GBS", ".GTP", ".GBP")
        )
    )

    return ReferenceRecord(
        slug=record_slug,
        name=name,
        source_dir=str(source_dir),
        bom_rows=bom_rows,
        drill_rows=drill_rows,
        pdf_texts=tuple(pdf_texts),
        gerber_files=gerbers,
        components=components,
        notes=tuple(notes),
    )


def save_reference_record(
    record: ReferenceRecord, *, base_dir: Path | None = None
) -> Path:
    target = (base_dir or REFERENCES_DIR) / record.slug
    target.mkdir(parents=True, exist_ok=True)
    record_file = target / "reference.json"
    record_file.write_text(
        json.dumps(record.as_dict(), indent=2) + "\n", encoding="utf-8"
    )
    for pdf_name, text in record.pdf_texts:
        stem = re.sub(r"[^A-Za-z0-9._-]+", "_", pdf_name)
        (target / f"{stem}.txt").write_text(text, encoding="utf-8")
    return record_file
