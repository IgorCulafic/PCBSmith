from __future__ import annotations

from pathlib import Path

from pcbsmith.kicad.kicad_library_index import (
    build_kicad_library_index,
    find_kicad_library_roots,
    kicad_library_roots_from_cli,
)


def test_kicad_library_roots_from_cli_uses_installed_share_layout() -> None:
    roots = kicad_library_roots_from_cli(
        Path("C:/Program Files/KiCad/10.0/bin/kicad-cli.exe")
    )

    assert roots.symbols_dir == Path("C:/Program Files/KiCad/10.0/share/kicad/symbols")
    assert roots.footprints_dir == Path(
        "C:/Program Files/KiCad/10.0/share/kicad/footprints"
    )
    assert roots.source == "kicad-cli layout"


def test_find_kicad_library_roots_falls_back_to_known_share_candidates() -> None:
    roots = find_kicad_library_roots(
        Path("C:/Users/pitch/scoop/shims/kicad-cli.exe"),
        candidate_roots=(Path("D:/KiCad/share/kicad"),),
        exists=lambda path: str(path).replace("\\", "/")
        in {
            "D:/KiCad/share/kicad/symbols",
            "D:/KiCad/share/kicad/footprints",
        },
    )

    assert roots.symbols_dir == Path("D:/KiCad/share/kicad/symbols")
    assert roots.footprints_dir == Path("D:/KiCad/share/kicad/footprints")
    assert roots.source == "known library path"


def test_build_kicad_library_index_reads_symbols_and_footprints(tmp_path: Path) -> None:
    symbols_dir = tmp_path / "symbols"
    footprints_dir = tmp_path / "footprints"
    resistor_dir = footprints_dir / "Resistor_SMD.pretty"
    symbols_dir.mkdir()
    resistor_dir.mkdir(parents=True)
    (symbols_dir / "Device.kicad_sym").write_text(
        """
(kicad_symbol_lib
\t(symbol "R"
\t\t(symbol "R_0_1")
\t)
\t(symbol "C"
\t)
)
""".lstrip(),
        encoding="utf-8",
    )
    (resistor_dir / "R_0603_1608Metric.kicad_mod").write_text(
        "(footprint \"R_0603_1608Metric\")\n",
        encoding="utf-8",
    )

    index = build_kicad_library_index(
        symbols_dir=symbols_dir,
        footprints_dir=footprints_dir,
        symbol_libraries=("Device",),
        footprint_libraries=("Resistor_SMD",),
    )

    assert index["schema"] == "pcbsmith-kicad-library-index-v1"
    assert index["symbols"] == [
        {"library": "Device", "name": "C", "id": "Device:C"},
        {"library": "Device", "name": "R", "id": "Device:R"},
    ]
    assert index["footprints"] == [
        {
            "library": "Resistor_SMD",
            "name": "R_0603_1608Metric",
            "id": "Resistor_SMD:R_0603_1608Metric",
        }
    ]
    assert index["symbol_count"] == 2
    assert index["footprint_count"] == 1
