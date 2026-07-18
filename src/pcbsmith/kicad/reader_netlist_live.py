"""Live KiCad producer for the specialized reader-netlist equality adapter."""

from __future__ import annotations

import hashlib
import re
import stat
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from pcbsmith.kicad.aggregate_exact_checker import (
    ReaderNetlistEqualitySubcheckEvidence,
    StableAggregateExactCheckerPolicy,
)
from pcbsmith.kicad.board import (
    BoardLayout,
    BoardNetlist,
    canonical_kicad_netlist_xml_text,
    export_kicad_netlist_xml,
)
from pcbsmith.kicad.cli import find_kicad_cli, run_kicad_process
from pcbsmith.kicad.library import VENDORED_DIR
from pcbsmith.kicad.validate import canonical_kicad_erc_json_text, run_kicad_erc

_LIBRARY_ATOM = re.compile(r"[A-Za-z0-9_.+-]+")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stage_vendored_project_footprints(
    netlist: BoardNetlist, project_dir: Path
) -> tuple[str, tuple[tuple[str, str], ...]]:
    staged: dict[str, set[tuple[str, Path]]] = {}
    for component in netlist.components:
        try:
            library, name = component.footprint.split(":", 1)
        except ValueError as error:
            raise ValueError(f"invalid footprint library id {component.footprint!r}") from error
        if not _LIBRARY_ATOM.fullmatch(library) or not _LIBRARY_ATOM.fullmatch(name):
            raise ValueError(f"unsafe footprint library id {component.footprint!r}")
        source = VENDORED_DIR / f"{library}__{name}.kicad_mod"
        if not source.is_file():
            raise ValueError(
                "live reader evidence requires an exact vendored footprint source for "
                f"{component.footprint!r}"
            )
        staged.setdefault(library, set()).add((name, source))

    entries = []
    for library in sorted(staged):
        pretty_dir = project_dir / f"{library}.pretty"
        pretty_dir.mkdir(parents=True, exist_ok=True)
        for name, source in sorted(staged[library]):
            (pretty_dir / f"{name}.kicad_mod").write_text(
                source.read_text(encoding="utf-8"), encoding="utf-8"
            )
        entries.append(
            f'  (lib (name "{library}")(type "KiCad")'
            f'(uri "${{KIPRJMOD}}/{library}.pretty")(options "")(descr ""))'
        )
    table_text = "(fp_lib_table\n  (version 7)\n" + "\n".join(entries) + "\n)\n"
    (project_dir / "fp-lib-table").write_text(table_text, encoding="utf-8")
    sources = tuple(
        (f"{library}:{name}", _sha256_text(source.read_text(encoding="utf-8")))
        for library in sorted(staged)
        for name, source in sorted(staged[library])
    )
    return _sha256_text(table_text), sources


def _project_source_name(xml_text: str) -> str | None:
    root = ET.fromstring(xml_text)
    design = root.find("design")
    source = None if design is None else design.find("source")
    return None if source is None else source.text


def _is_reparse_point(path: Path) -> bool:
    if path.is_symlink():
        return True
    attributes = getattr(path.lstat(), "st_file_attributes", 0)
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _clean_owned_role_dir(output_root: Path, role: str) -> Path:
    resolved_output = output_root.resolve()
    managed_root = resolved_output / ".pcbsmith-reader-netlist-live"
    if (managed_root.exists() or managed_root.is_symlink()) and _is_reparse_point(
        managed_root
    ):
        raise ValueError("managed live-reader output directory cannot be a reparse point")
    resolved_managed = managed_root.resolve()
    if resolved_managed.parent != resolved_output:
        raise ValueError("managed live-reader output directory escaped output_root")
    role_dir = resolved_managed / role
    if (role_dir.exists() or role_dir.is_symlink()) and _is_reparse_point(role_dir):
        raise ValueError("managed live-reader role directory cannot be a reparse point")
    resolved_role = role_dir.resolve()
    if resolved_role.parent != resolved_managed:
        raise ValueError("managed live-reader role directory escaped its managed root")
    if resolved_role.exists():
        _remove_owned_tree(resolved_role)
    resolved_role.mkdir(parents=True, exist_ok=True)
    return resolved_role


def _remove_owned_tree(path: Path) -> None:
    """Remove one confined owned tree without following nested reparse points."""

    for child in path.iterdir():
        if _is_reparse_point(child):
            if child.is_dir():
                child.rmdir()
            else:
                child.unlink()
        elif child.is_dir():
            _remove_owned_tree(child)
        else:
            child.unlink()
    path.rmdir()


def verify_reader_netlist_equality_live(
    *,
    layout: BoardLayout,
    netlist: BoardNetlist,
    policy: StableAggregateExactCheckerPolicy,
    subcheck_id: str,
    subcheck_version: str,
    machine_schematic_text: str,
    reader_schematic_text: str,
    machine_schematic_artifact_id: str,
    reader_schematic_artifact_id: str,
    schematic_file_name: str,
    output_root: Path,
    config_identity: str,
    config: Any,
) -> ReaderNetlistEqualitySubcheckEvidence:
    """Run real ERC and netlist export for two retained schematic artifacts.

    The two schematics live in separate directories under one identical file
    name.  The file stem must equal the project name embedded by the renderer;
    retaining it explicitly prevents KiCad from rewriting symbol-instance
    paths under an accidental temporary project identity.
    """

    schematic_name = Path(schematic_file_name)
    if (
        schematic_name.name != schematic_file_name
        or schematic_name.suffix != ".kicad_sch"
        or not schematic_name.stem
    ):
        raise ValueError("schematic_file_name must be a bare .kicad_sch file name")

    install = find_kicad_cli()
    if install is None:
        raise RuntimeError("KiCad CLI is unavailable")
    executable_sha256 = _sha256_file(install.path)
    version = run_kicad_process((install.path, "version"))
    if version.returncode != 0 or not version.stdout.strip():
        raise RuntimeError("KiCad CLI version could not be read")

    artifacts: list[tuple[str, str]] = []
    erc_json: list[str] = []
    reports = []
    staged_authorities: list[tuple[str, tuple[tuple[str, str], ...]]] = []
    project_text = '{"meta":{"version":1}}\n'
    for role, text in (
        ("machine", machine_schematic_text),
        ("reader", reader_schematic_text),
    ):
        role_dir = _clean_owned_role_dir(output_root, role)
        (role_dir / f"{schematic_name.stem}.kicad_pro").write_text(
            project_text, encoding="utf-8"
        )
        staged_authorities.append(_stage_vendored_project_footprints(netlist, role_dir))
        schematic_file = role_dir / schematic_name
        schematic_file.write_text(text, encoding="utf-8")
        report = run_kicad_erc(schematic_file, finder=lambda: install)
        report_file = role_dir / ".pcbsmith" / "kicad" / "erc.json"
        if not report_file.is_file():
            raise RuntimeError(f"{role} ERC did not retain its JSON report")
        retained_erc_json = canonical_kicad_erc_json_text(
            report_file.read_text(encoding="utf-8")
        )
        netlist_file = export_kicad_netlist_xml(schematic_file, finder=lambda: install)
        retained_xml = canonical_kicad_netlist_xml_text(
            netlist_file.read_text(encoding="utf-8")
        )
        if _project_source_name(retained_xml) != schematic_file_name:
            raise RuntimeError(f"{role} netlist export changed the retained project identity")
        artifacts.append((text, retained_xml))
        erc_json.append(retained_erc_json)
        reports.append(report)

    if staged_authorities[0] != staged_authorities[1]:
        raise RuntimeError("machine and reader staged dependency authorities differ")
    if _sha256_file(install.path) != executable_sha256:
        raise RuntimeError("KiCad CLI executable changed during live reader production")
    table_sha256, vendored_sources = staged_authorities[0]
    effective_config = {
        "caller_config": config,
        "schematic_file_name": schematic_file_name,
        "project_file_sha256": _sha256_text(project_text),
        "fp_lib_table_sha256": table_sha256,
        "vendored_footprint_sources": vendored_sources,
        "kicad_executable_sha256": executable_sha256,
        "logical_operations": (
            "version",
            "sch erc --format json",
            "sch export netlist --format kicadxml",
        ),
        "retained_artifacts_are_canonicalized": True,
        "raw_artifact_root": ".pcbsmith-reader-netlist-live",
    }

    return ReaderNetlistEqualitySubcheckEvidence.build(
        subcheck_id=subcheck_id,
        subcheck_version=subcheck_version,
        layout=layout,
        netlist=netlist,
        policy=policy,
        machine_schematic_artifact_id=machine_schematic_artifact_id,
        machine_schematic_text=machine_schematic_text,
        machine_schematic_artifact_sha256=_sha256_text(artifacts[0][0]),
        reader_schematic_artifact_id=reader_schematic_artifact_id,
        reader_schematic_text=reader_schematic_text,
        reader_schematic_artifact_sha256=_sha256_text(artifacts[1][0]),
        machine_netlist_xml_text=artifacts[0][1],
        reader_netlist_xml_text=artifacts[1][1],
        tool_id="kicad-cli",
        tool_version=version.stdout.strip(),
        config_identity=config_identity,
        config=effective_config,
        machine_erc_report_json=erc_json[0],
        reader_erc_report_json=erc_json[1],
        machine_erc_report=reports[0],
        reader_erc_report=reports[1],
    )
