"""Retain confined project-local KiCad libraries beside an isolated candidate."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pcbsmith.kicad.library import QuotedString, parse_sexpr


def retain_project_libraries(source: Path, destination: Path) -> dict[Path, bytes]:
    """Copy local symbol/footprint libraries and return their source snapshots.

    Installed library variables stay external. This does not resolve model
    dependencies; model preflight remains the authority for those files.
    """
    source = source.resolve()
    destination = destination.resolve()
    if source == destination:
        raise ValueError("project libraries require an isolated destination")
    retained: dict[Path, bytes] = {}

    def copy_file(original: Path, target: Path) -> None:
        if original.is_symlink() or not original.is_file():
            raise ValueError("project library member is not a regular file")
        if not original.resolve().is_relative_to(source):
            raise ValueError("project library member escapes the source root")
        if not target.resolve().is_relative_to(destination):
            raise ValueError("project library member escapes the destination root")
        payload = original.read_bytes()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if not target.is_file() or target.read_bytes() != payload:
                raise ValueError("project library filename collision")
        else:
            target.write_bytes(payload)
        retained[original] = payload

    for table in ("sym-lib-table", "fp-lib-table"):
        table_file = source / table
        if not table_file.is_file():
            continue
        root = parse_sexpr(table_file.read_text(encoding="utf-8"))
        for entry in root[1:]:
            if not isinstance(entry, list) or not entry or entry[0] != "lib":
                continue
            uri = next(
                (
                    item[1]
                    for item in entry[1:]
                    if isinstance(item, list) and len(item) == 2 and item[0] == "uri"
                ),
                None,
            )
            value = uri.value if isinstance(uri, QuotedString) else str(uri or "")
            prefix = "${KIPRJMOD}/"
            if not value.startswith(prefix):
                if "${KIPRJMOD}" in value:
                    raise ValueError("project library URI must use ${KIPRJMOD}/relative-path")
                continue
            relative = Path(value[len(prefix) :])
            original = source / relative
            target = destination / relative
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or relative == Path(".")
                or not original.resolve().is_relative_to(source)
                or not target.resolve().is_relative_to(destination)
            ):
                raise ValueError("project library escapes the source/destination root")
            if not original.exists() or original.is_symlink():
                raise ValueError("project library is missing or is a symbolic link")
            if original.is_dir():
                if target.exists() and not target.is_dir():
                    raise ValueError("project library filename collision")
                target.mkdir(parents=True, exist_ok=True)
                for member in sorted(original.rglob("*")):
                    if member.is_symlink() or not member.resolve().is_relative_to(source):
                        raise ValueError("project library member escapes the source root")
                    if member.is_file():
                        copy_file(member, target / member.relative_to(original))
            else:
                copy_file(original, target)
    return retained


def retain_native_project(source_board: Path, destination: Path) -> dict[str, str]:
    """Retain native inputs, recursive local sheets/libraries/models and edit intent.

    Installed libraries stay external; this is project closure, not package qualification.
    """
    import hashlib

    from pcbsmith.manufacturing_lineage import native_input_hashes
    from pcbsmith.operations.file_transaction import (
        atomic_write,
        project_path,
        require_complete_project,
    )

    source_board = source_board.resolve()
    source = source_board.parent
    require_complete_project(source)
    if destination.resolve() == source:
        raise ValueError("native context requires an isolated destination")
    payloads: dict[Path, bytes] = {}

    def retain(path: Path) -> None:
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(source):
            raise ValueError("native dependency is missing, symbolic, or outside the project")
        payloads[path.resolve()] = path.read_bytes()

    for name in native_input_hashes(source_board):
        retain(source / name)
    visited: set[Path] = set()
    active: set[Path] = set()

    def sheets(path: Path) -> None:
        path = path.resolve()
        if path in active:
            raise ValueError("cyclic schematic sheet dependency")
        if path in visited:
            return
        retain(path)
        active.add(path)
        root = parse_sexpr(payloads[path].decode("utf-8"))
        for sheet in root:
            if not isinstance(sheet, list) or not sheet or sheet[0] != "sheet":
                continue
            filenames = [
                item[2].value if isinstance(item[2], QuotedString) else str(item[2])
                for item in sheet
                if isinstance(item, list)
                and len(item) >= 3
                and item[0] == "property"
                and (item[1].value if isinstance(item[1], QuotedString) else item[1]) == "Sheetfile"
            ]
            if len(filenames) != 1:
                raise ValueError("sheet needs one Sheetfile property")
            filename = filenames[0]
            if filename.startswith("${KIPRJMOD}/"):
                child = project_path(source, filename[len("${KIPRJMOD}/") :])
            else:
                if "${" in filename or Path(filename).is_absolute() or ".." in Path(filename).parts:
                    raise ValueError("unsupported sheet dependency path")
                child = path.parent / filename
            if child.suffix != ".kicad_sch":
                raise ValueError("sheet dependency must be a native schematic")
            sheets(child)
        active.remove(path)
        visited.add(path)

    if source_board.with_suffix(".kicad_sch").exists():
        sheets(source_board.with_suffix(".kicad_sch"))
    # Native model paths are relative to the PCB project, not the imported footprint.
    root = parse_sexpr(payloads[source_board].decode("utf-8"))
    for footprint in root:
        if not isinstance(footprint, list) or not footprint or footprint[0] != "footprint":
            continue
        for model in footprint:
            if not isinstance(model, list) or len(model) < 2 or model[0] != "model":
                continue
            raw = model[1].value if isinstance(model[1], QuotedString) else str(model[1])
            if raw.startswith("${KIPRJMOD}/"):
                retain(project_path(source, raw[len("${KIPRJMOD}/") :]))
            elif "${" not in raw and not Path(raw).is_absolute():
                retain(project_path(source, raw))
    ledger = source / ".pcbsmith/accepted-board-edits.json"
    if ledger.exists():
        retain(ledger)
    destination.mkdir(parents=True, exist_ok=True)
    for path, data in payloads.items():
        atomic_write(destination / path.relative_to(source), data)
    payloads.update(retain_project_libraries(source, destination))
    for path, data in payloads.items():
        if path.read_bytes() != data:
            raise ValueError("native dependency changed while retaining context")
    return {
        path.relative_to(source).as_posix(): hashlib.sha256(data).hexdigest()
        for path, data in payloads.items()
    }


def native_project_hashes(board: Path) -> dict[str, str]:
    """Inspect the same closure used by isolated native transactions."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="pcbsmith-native-context-") as work:
        return retain_native_project(board, Path(work))


@contextmanager
def project_footprint_scope(project: Path) -> Iterator[None]:
    """Project-relative libraries win; source manifests validate retained hashes."""
    import hashlib
    import json

    from pcbsmith.kicad.library import _PROJECT_FOOTPRINTS, _PROJECT_LIBRARY_NAMES, _atom, _children
    from pcbsmith.operations.file_transaction import project_path

    table = project / "fp-lib-table"
    mapping = {}
    library_names = set()
    if table.is_file():
        root = parse_sexpr(table.read_text(encoding="utf-8"))
        for entry in _children(root, "lib"):
            name = _atom(_children(entry, "name")[0][1])
            uri = _atom(_children(entry, "uri")[0][1])
            if not uri.startswith("${KIPRJMOD}/"):
                continue
            library_names.add(name)
            directory = project_path(project.resolve(), uri[len("${KIPRJMOD}/") :])
            if not directory.is_dir() or directory.is_symlink():
                raise ValueError("Missing project-local footprint library")
            for path in directory.glob("*.kicad_mod"):
                if path.is_symlink() or not path.resolve().is_relative_to(project.resolve()):
                    raise ValueError("Project footprint escapes the project")
                key = name + ":" + path.stem
                if key in mapping:
                    raise ValueError("Duplicate project footprint")
                mapping[key] = path.resolve()
    manifest = project / "library-sources.json"
    if manifest.is_file():
        for record in json.loads(manifest.read_text(encoding="utf-8")):
            if record["kind"] != "footprint":
                continue
            retained_path = mapping.get(record["id"])
            if (
                retained_path is None
                or hashlib.sha256(retained_path.read_bytes()).hexdigest() != record["sha256"]
            ):
                raise ValueError("Retained project footprint hash mismatch")
    token = _PROJECT_FOOTPRINTS.set(mapping)
    names_token = _PROJECT_LIBRARY_NAMES.set(frozenset(library_names))
    try:
        yield
    finally:
        _PROJECT_FOOTPRINTS.reset(token)
        _PROJECT_LIBRARY_NAMES.reset(names_token)
