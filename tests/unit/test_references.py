"""Reference-pack ingestion: BOM xlsx and NC-drill report parsing."""

from __future__ import annotations

import zipfile
from pathlib import Path

from pcbsmith.references import (
    ingest_reference_pack,
    parse_bom_xlsx,
    parse_drill_report,
    save_reference_record,
)

_SHARED = """<?xml version="1.0"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<si><t>Comment</t></si><si><t>Designator</t></si><si><t>Quantity</t></si>
<si><t>HD06-T</t></si><si><t>BR1</t></si>
<si><t>DNP</t></si><si><t>C8</t></si>
</sst>"""

_SHEET = (
    '<?xml version="1.0"?>\n<worksheet>\n<sheetData>\n'
    '<row r="1"><c r="A1" t="s"><v>0</v></c>'
    '<c r="B1" t="s"><v>1</v></c><c r="C1" t="s"><v>2</v></c></row>\n'
    '<row r="2"><c r="A2" t="s"><v>3</v></c>'
    '<c r="B2" t="s"><v>4</v></c><c r="C2"><v>1</v></c></row>\n'
    '<row r="3"><c r="A3" t="s"><v>5</v></c>'
    '<c r="B3" t="s"><v>6</v></c><c r="C3"><v>1</v></c></row>\n'
    "</sheetData>\n</worksheet>"
)

_DRR = (
    "NCDrill File Report For: Example.PcbDoc\n\n"
    "Tool       Hole Size               Hole Tolerance         "
    "      Hole Type       Hole Count   Plated         Tool Travel\n"
    "T1      14mil (0.356mm)         +/-3mil (0.076mm)         "
    "        Round             15        PTH        2.26inch (57.52mm)\n"
    "T8      126mil (3.2mm)          +/-3mil (0.076mm)         "
    "        Round             4         NPTH       5.24inch (133.01mm)\n"
)


def _write_xlsx(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/sharedStrings.xml", _SHARED)
        archive.writestr("xl/worksheets/sheet1.xml", _SHEET)


def test_bom_xlsx_rows_resolve_shared_strings(tmp_path: Path) -> None:
    bom = tmp_path / "bom.xlsx"
    _write_xlsx(bom)
    rows = parse_bom_xlsx(bom)
    assert rows == (
        {"Comment": "HD06-T", "Designator": "BR1", "Quantity": "1"},
        {"Comment": "DNP", "Designator": "C8", "Quantity": "1"},
    )


def test_drill_report_rows(tmp_path: Path) -> None:
    report = tmp_path / "Example.DRR"
    report.write_text(_DRR, encoding="utf-8")
    rows = parse_drill_report(report)
    assert len(rows) == 2
    assert rows[0].tool == "T1"
    assert rows[0].count == 15
    assert rows[0].plated == "PTH"
    assert rows[1].plated == "NPTH"


def test_ingest_pack_and_save(tmp_path: Path) -> None:
    pack = tmp_path / "Example-RevA"
    (pack / "Outputs" / "BOM").mkdir(parents=True)
    (pack / "Outputs" / "Drill").mkdir(parents=True)
    _write_xlsx(pack / "Outputs" / "BOM" / "bom.xlsx")
    (pack / "Outputs" / "Drill" / "Example.DRR").write_text(
        _DRR, encoding="utf-8"
    )
    (pack / "Outputs" / "Example.GTL").write_text("G04*", encoding="utf-8")

    record = ingest_reference_pack(pack)
    assert record.slug == "example-reva"
    assert len(record.bom_rows) == 2
    assert len(record.drill_rows) == 2
    assert record.gerber_files == ("Example.GTL",)

    record_file = save_reference_record(record, base_dir=tmp_path / "refs")
    assert record_file.exists()
    assert "HD06-T" in record_file.read_text(encoding="utf-8")


def test_odb_components_parse(tmp_path: Path) -> None:
    from pcbsmith.references import parse_odb_components

    layer = tmp_path / "odb" / "steps" / "pcb" / "layers" / "comp_+_bot"
    layer.mkdir(parents=True)
    (layer / "components").write_text(
        "# CMP 0\n"
        "CMP 10 1.0 0.5 270 N U1 UCC28881DR ;0=1\n"
        "PRP Manufacturer 'TI'\n",
        encoding="utf-8",
    )
    rows = parse_odb_components(tmp_path)
    assert rows == (
        {
            "reference": "U1",
            "value": "UCC28881DR",
            "x_mm": 25.4,
            "y_mm": 12.7,
            "rotation": 270.0,
            "side": "bottom",
        },
    )
