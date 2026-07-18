"""KiCad save/read-back authority for shaped placement serialization.

The neutral R5 serializer proves deterministic emission.  This opt-in gate
writes that exact board twice, lets the pinned local KiCad CLI parse/refill/save
it, and compares a closed semantic read-back surface.  It is intentionally not
a general KiCad-to-``BoardLayout`` importer.
"""

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.kicad.board_serialization import parse_canonical_board_netlist_snapshot
from pcbsmith.kicad.cli import find_kicad_cli, run_kicad_process
from pcbsmith.kicad.library import VENDORED_DIR, QuotedString, SExpr, parse_sexpr
from pcbsmith.kicad.validate import run_kicad_drc
from pcbsmith.placement_ir import PlacementIrModel
from pcbsmith.placement_serialization_ir import PlacementSerializationAuthority

_GRAPHIC_HEADS = frozenset(
    {"gr_arc", "gr_bezier", "gr_circle", "gr_curve", "gr_line", "gr_poly", "gr_rect", "gr_text"}
)
_FILL_HEADS = frozenset({"filled_polygon", "fill_segments"})
_SETUP_DEFAULTS = {
    "allow_soldermask_bridges_in_footprints": "no",
    "capping": "no",
    "filling": "no",
    "pad_to_mask_clearance": "0",
}
_ORDERED_HEADS = frozenset(
    {
        "at",
        "drill",
        "end",
        "layers",
        "mid",
        "offset",
        "pts",
        "rotate",
        "scale",
        "size",
        "start",
        "xy",
        "xyz",
    }
)
_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_LIBRARY_ATOM = re.compile(r"^[A-Za-z0-9_.+-]+$")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_atom(value: str) -> str:
    if not _NUMBER.fullmatch(value):
        return value
    try:
        decimal = Decimal(value)
    except InvalidOperation:
        return value
    if not decimal.is_finite():
        raise ValueError("KiCad read-back contains a non-finite numeric atom")
    rendered = format(decimal, "f")
    if "." in rendered:
        rendered = rendered.rstrip("0").rstrip(".")
    if rendered in {"", "-0", "+0"}:
        return "0"
    return rendered


def _scalar(node: SExpr) -> str | None:
    if isinstance(node, QuotedString):
        return node.value
    if isinstance(node, str):
        return node
    return None


def _net_name(node: list[SExpr], net_names: dict[str, str]) -> str | None:
    if _head(node) != "net" or len(node) < 2:
        return None
    explicit = _scalar(node[-1])
    if explicit is None:
        return None
    if len(node) >= 3 and isinstance(node[-1], QuotedString):
        return node[-1].value
    return net_names.get(explicit, explicit if not _NUMBER.fullmatch(explicit) else None)


def _all_no_clause(node: list[SExpr]) -> bool:
    return bool(node[1:]) and all(
        isinstance(child, list) and len(child) == 2 and _scalar(child[1]) == "no"
        for child in node[1:]
    )


def _all_value_clause(node: list[SExpr], value: str) -> bool:
    return bool(node[1:]) and all(
        isinstance(child, list) and len(child) == 2 and _scalar(child[1]) == value
        for child in node[1:]
    )


def _is_default_text_effects(node: list[SExpr]) -> bool:
    if _head(node) != "effects" or len(node) != 2 or not isinstance(node[1], list):
        return False
    font = node[1]
    return (
        _head(font) == "font"
        and len(font) == 2
        and isinstance(font[1], list)
        and _head(font[1]) == "size"
        and tuple(_scalar(item) for item in font[1][1:]) == ("1.27", "1.27")
    )


def _is_implicit_default(node: SExpr, parent_head: str | None) -> bool:
    if not isinstance(node, list) or len(node) < 2:
        return False
    head = _head(node)
    value = _scalar(node[1])
    if (
        parent_head == "footprint"
        and head in {"duplicate_pad_numbers_are_jumpers", "embedded_fonts"}
        and value == "no"
    ):
        return True
    if parent_head == "via" and (
        (head in {"capping", "filling"} and value == "no")
        or (head in {"covering", "plugging"} and _all_no_clause(node))
        or (head == "tenting" and _all_value_clause(node, "none"))
    ):
        return True
    if parent_head == "zone" and head == "filled_areas_thickness" and value == "no":
        return True
    if parent_head == "zone" and ((head == "priority" and value == "0") or head == "net_name"):
        return True
    if parent_head == "fill" and head == "island_removal_mode" and value == "0":
        return True
    if parent_head == "gr_text" and _is_default_text_effects(node):
        return True
    return False


def _normalized(
    node: SExpr,
    net_names: dict[str, str],
    *,
    parent_head: str | None = None,
) -> Any:
    if isinstance(node, QuotedString):
        return {"quoted": node.value}
    if isinstance(node, str):
        return {"atom": _canonical_atom(node)}
    head = _head(node)
    if head == "net":
        name = _net_name(node, net_names)
        if name is not None:
            return [{"atom": "net"}, {"quoted": name}]
    if head == "uuid" and len(node) == 2:
        value = _scalar(node[1])
        if value is not None:
            return [{"atom": "uuid"}, {"quoted": value}]
    if head == "fill" and len(node) == 2 and _scalar(node[1]) in {"none", "no"}:
        return [{"atom": "fill"}, {"atom": "no"}]
    if head == "fp_rect":
        start = next(
            (child for child in node[1:] if isinstance(child, list) and _head(child) == "start"),
            None,
        )
        end = next(
            (child for child in node[1:] if isinstance(child, list) and _head(child) == "end"),
            None,
        )
        if start is not None and end is not None and len(start) == 3 and len(end) == 3:
            x1, y1 = start[1], start[2]
            x2, y2 = end[1], end[2]
            polygon: list[SExpr] = [
                "fp_poly",
                [
                    "pts",
                    ["xy", x1, y1],
                    ["xy", x2, y1],
                    ["xy", x2, y2],
                    ["xy", x1, y2],
                ],
                *(child for child in node[1:] if child is not start and child is not end),
            ]
            return _normalized(polygon, net_names, parent_head=parent_head)
    normalized = [
        _normalized(child, net_names, parent_head=head)
        for child in node
        if not _is_implicit_default(child, head)
    ]
    if head in _ORDERED_HEADS:
        return normalized
    prefix_length = 1
    while prefix_length < len(node) and not isinstance(node[prefix_length], list):
        prefix_length += 1
    ordered_prefix = normalized[:prefix_length]
    clauses = normalized[prefix_length:]
    clauses.sort(key=lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")))
    return [*ordered_prefix, *clauses]


def _head(node: SExpr) -> str | None:
    if not isinstance(node, list) or not node or not isinstance(node[0], str):
        return None
    return node[0]


def _direct_layer(node: list[SExpr]) -> str | None:
    for child in node[1:]:
        if (
            isinstance(child, list)
            and len(child) >= 2
            and child[0] == "layer"
            and isinstance(child[1], QuotedString)
        ):
            return child[1].value
    return None


def _canonical_item(
    node: list[SExpr],
    net_names: dict[str, str],
    *,
    strip_fill: bool = False,
) -> str:
    if not node:
        raise ValueError("KiCad semantic item cannot be empty")
    fixed_prefix = node[:2] if _head(node) == "footprint" else node[:1]
    tail = node[len(fixed_prefix) :]
    if strip_fill:
        tail = [child for child in tail if _head(child) not in _FILL_HEADS]
    parent_head = _head(node)
    normalized_tail = [
        _normalized(child, net_names, parent_head=parent_head)
        for child in tail
        if not _is_implicit_default(child, parent_head)
    ]
    # Direct board/footprint clauses are unordered for this preservation gate;
    # ordered point/path children remain ordered inside each clause.
    normalized_tail.sort(key=lambda value: json.dumps(value, sort_keys=True, separators=(",", ":")))
    return json.dumps(
        [
            *(_normalized(child, net_names) for child in fixed_prefix),
            *normalized_tail,
        ],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _walk_lists(node: SExpr) -> list[list[SExpr]]:
    if not isinstance(node, list):
        return []
    result = [node]
    for child in node:
        result.extend(_walk_lists(child))
    return result


def _canonical_net_entry(name: str) -> str:
    return json.dumps(
        [{"atom": "net"}, {"quoted": name}],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _canonical_layers(root: list[SExpr]) -> tuple[str, ...]:
    layer_table = next(
        (item for item in root[1:] if isinstance(item, list) and _head(item) == "layers"),
        None,
    )
    declared: dict[str, str] = {}
    if layer_table is not None:
        for entry in layer_table[1:]:
            if not isinstance(entry, list) or len(entry) < 3:
                continue
            name = _scalar(entry[1])
            layer_type = _scalar(entry[2])
            if name is not None and layer_type is not None:
                declared[name] = layer_type
    used: set[str] = {"F.Cu", "B.Cu"}
    for item in _walk_lists(root):
        head = _head(item)
        if head == "layer" and len(item) >= 2:
            name = _scalar(item[1])
            if name is not None:
                used.add(name)
        elif head == "layers":
            for child in item[1:]:
                name = _scalar(child)
                if name is not None:
                    used.add(name)
    return tuple(
        json.dumps(
            [{"quoted": name}, {"atom": declared.get(name, "user")}],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        for name in sorted(used)
    )


def _canonical_setup(node: list[SExpr], net_names: dict[str, str]) -> str | None:
    retained: list[SExpr] = []
    for child in node[1:]:
        head = _head(child)
        if head == "pcbplotparams":
            continue
        if isinstance(child, list) and head in _SETUP_DEFAULTS and len(child) >= 2:
            value = _scalar(child[1])
            if value is not None and _canonical_atom(value) == _SETUP_DEFAULTS[head]:
                continue
        if isinstance(child, list) and head in {"covering", "plugging"}:
            if _all_no_clause(child):
                continue
        if isinstance(child, list) and head == "tenting" and _all_value_clause(child, "yes"):
            continue
        retained.append(child)
    if not retained:
        return None
    return _canonical_item([node[0], *retained], net_names)


class KiCadBoardReadbackSnapshot(PlacementIrModel):
    """Closed shaped-board surface compared across one KiCad save."""

    schema_id: Literal["pcbsmith-kicad-board-readback-snapshot"] = (
        "pcbsmith-kicad-board-readback-snapshot"
    )
    schema_version: Literal[1] = 1
    footprints: tuple[str, ...]
    edge_cuts: tuple[str, ...]
    board_graphics: tuple[str, ...]
    zones: tuple[str, ...]
    segments: tuple[str, ...]
    vias: tuple[str, ...]
    nets: tuple[str, ...]
    layers: tuple[str, ...]
    setup: tuple[str, ...]

    @model_validator(mode="after")
    def entries_are_canonical_json_multisets(self) -> Self:
        for field_name in (
            "footprints",
            "edge_cuts",
            "board_graphics",
            "zones",
            "segments",
            "vias",
            "nets",
            "layers",
            "setup",
        ):
            entries = getattr(self, field_name)
            for entry in entries:
                if (
                    json.dumps(
                        json.loads(entry),
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    )
                    != entry
                ):
                    raise ValueError(f"{field_name} contains noncanonical JSON")
            object.__setattr__(self, field_name, tuple(sorted(entries)))
        return self


def extract_kicad_board_readback(board_text: str) -> KiCadBoardReadbackSnapshot:
    """Parse and fingerprint every shaped-board field this gate claims."""

    root = parse_sexpr(board_text)
    if not root or root[0] != "kicad_pcb":
        raise ValueError("read-back artifact is not a kicad_pcb s-expression")
    net_names = {
        str(raw[1]): raw[2].value
        for raw in root[1:]
        if isinstance(raw, list)
        and _head(raw) == "net"
        and len(raw) >= 3
        and isinstance(raw[1], str)
        and isinstance(raw[2], QuotedString)
    }
    categories: dict[str, list[str]] = {
        "footprints": [],
        "edge_cuts": [],
        "board_graphics": [],
        "zones": [],
        "segments": [],
        "vias": [],
        "nets": [],
        "layers": [],
        "setup": [],
    }
    for raw in root[1:]:
        if not isinstance(raw, list):
            continue
        head = _head(raw)
        if head == "footprint":
            categories["footprints"].append(_canonical_item(raw, net_names))
        elif head in _GRAPHIC_HEADS:
            target = "edge_cuts" if _direct_layer(raw) == "Edge.Cuts" else "board_graphics"
            categories[target].append(_canonical_item(raw, net_names))
        elif head == "zone":
            categories["zones"].append(_canonical_item(raw, net_names, strip_fill=True))
        elif head == "segment":
            categories["segments"].append(_canonical_item(raw, net_names))
        elif head == "via":
            categories["vias"].append(_canonical_item(raw, net_names))
        elif head == "setup":
            setup = _canonical_setup(raw, net_names)
            if setup is not None:
                categories["setup"].append(setup)
    referenced_nets: set[str] = set()
    for item in _walk_lists(root):
        name = _net_name(item, net_names)
        if name is not None and name != "":
            referenced_nets.add(name)
    categories["nets"] = [_canonical_net_entry(name) for name in sorted(referenced_nets)]
    categories["layers"] = list(_canonical_layers(root))
    return KiCadBoardReadbackSnapshot(**categories)


class PlacementKiCadSaveRoundtripAuthority(PlacementIrModel):
    """Two deterministic KiCad saves bound to one R5 serialization authority."""

    schema_id: Literal["pcbsmith-placement-kicad-save-roundtrip"] = (
        "pcbsmith-placement-kicad-save-roundtrip"
    )
    schema_version: Literal[2] = 2
    serialization_authority: PlacementSerializationAuthority
    kicad_cli_version: str = Field(min_length=1)
    initial_board_text: str = Field(min_length=1)
    saved_board_text: str = Field(min_length=1)
    initial_board_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    saved_board_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    repeated_saved_board_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    initial_snapshot: KiCadBoardReadbackSnapshot
    saved_snapshot: KiCadBoardReadbackSnapshot
    drc_status: Literal["passed", "failed"]
    drc_findings: tuple[str, ...] = ()
    drc_report_json: str = Field(min_length=2)
    drc_report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    drc_report_normalization: Literal["canonical_json_without_top_level_execution_date"] = (
        "canonical_json_without_top_level_execution_date"
    )
    require_drc_pass: bool = True
    authority_scope: Literal["kicad_parse_save_readback_and_drc"] = (
        "kicad_parse_save_readback_and_drc"
    )

    @model_validator(mode="after")
    def retained_tool_authority_is_complete(self) -> Self:
        serialization = PlacementSerializationAuthority.model_validate_json(
            self.serialization_authority.model_dump_json()
        )
        if serialization != self.serialization_authority:
            raise ValueError("serialization authority failed exact reconstruction")
        if self.initial_board_text != serialization.rendered_board_text:
            raise ValueError("KiCad initial board is not the retained serialization artifact")
        if self.initial_board_sha256 != _sha256_text(self.initial_board_text):
            raise ValueError("KiCad initial board checksum is stale")
        if self.saved_board_sha256 != _sha256_text(self.saved_board_text):
            raise ValueError("KiCad saved board checksum is stale")
        if self.repeated_saved_board_sha256 != self.saved_board_sha256:
            raise ValueError("repeated KiCad saves are not byte-identical")
        if extract_kicad_board_readback(self.initial_board_text) != self.initial_snapshot:
            raise ValueError("retained initial KiCad read-back snapshot is stale")
        if extract_kicad_board_readback(self.saved_board_text) != self.saved_snapshot:
            raise ValueError("retained saved KiCad read-back snapshot is stale")
        if self.initial_snapshot != self.saved_snapshot:
            raise ValueError("KiCad save changed the closed shaped-board semantic surface")
        try:
            report = json.loads(self.drc_report_json)
        except json.JSONDecodeError as error:
            raise ValueError("retained KiCad DRC report is invalid JSON") from error
        if not isinstance(report, dict) or "date" in report:
            raise ValueError(
                "retained KiCad DRC report must omit only its top-level execution date"
            )
        canonical_report = json.dumps(
            report,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        if canonical_report != self.drc_report_json:
            raise ValueError("retained KiCad DRC report is not canonical")
        if self.drc_report_sha256 != _sha256_text(self.drc_report_json):
            raise ValueError("retained KiCad DRC report checksum is stale")
        if self.require_drc_pass and (self.drc_status != "passed" or self.drc_findings):
            raise ValueError("KiCad DRC did not pass the required save-roundtrip gate")
        return self


def _canonical_report_text(path: Path) -> str:
    if not path.exists():
        raise ValueError("KiCad DRC did not write its JSON report")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError("KiCad DRC report is invalid JSON") from error
    if not isinstance(payload, dict):
        raise ValueError("KiCad DRC report root is not an object")
    # KiCad writes the wall-clock invocation timestamp here. It changes no
    # DRC semantics and would otherwise make identical runs fingerprint
    # differently; all tool/configuration/finding fields remain retained.
    payload.pop("date", None)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def _stage_vendored_project_footprints(
    authority: PlacementSerializationAuthority,
    run_dir: Path,
) -> None:
    """Expose vendored footprint sources to KiCad's project library resolver.

    The board already embeds the exact geometry loaded from these sources.  A
    project-local table prevents KiCad from reporting a false environment
    warning for deliberately vendored/test-only library nicknames during the
    live DRC pass.  Installed-only libraries remain resolved by KiCad's global
    table and are not copied.
    """

    netlist = parse_canonical_board_netlist_snapshot(authority.source_netlist_snapshot_json)
    staged: dict[str, list[tuple[str, Path]]] = {}
    for component in netlist.components:
        try:
            library, name = component.footprint.split(":", 1)
        except ValueError as error:
            raise ValueError(
                f"invalid footprint library id {component.footprint!r}"
            ) from error
        if not _LIBRARY_ATOM.fullmatch(library) or not _LIBRARY_ATOM.fullmatch(name):
            raise ValueError(f"unsafe footprint library id {component.footprint!r}")
        source = VENDORED_DIR / f"{library}__{name}.kicad_mod"
        if source.exists():
            staged.setdefault(library, []).append((name, source))
    if not staged:
        return

    table_entries = []
    for library in sorted(staged):
        pretty_dir = run_dir / f"{library}.pretty"
        pretty_dir.mkdir(parents=True, exist_ok=True)
        for name, source in sorted(set(staged[library])):
            (pretty_dir / f"{name}.kicad_mod").write_text(
                source.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        table_entries.append(
            f'  (lib (name "{library}")(type "KiCad")'
            f'(uri "${{KIPRJMOD}}/{library}.pretty")(options "")(descr ""))'
        )
    table = "(fp_lib_table\n  (version 7)\n" + "\n".join(table_entries) + "\n)\n"
    (run_dir / "fp-lib-table").write_text(table, encoding="utf-8")


def verify_placement_kicad_save_roundtrip(
    authority: PlacementSerializationAuthority,
    output_root: Path,
    *,
    require_drc_pass: bool = True,
) -> PlacementKiCadSaveRoundtripAuthority:
    """Run two real KiCad parse/refill/save/DRC passes and retain their evidence."""

    serialization = PlacementSerializationAuthority.model_validate_json(authority.model_dump_json())
    if serialization != authority:
        raise ValueError("serialization authority failed exact reconstruction")
    install = find_kicad_cli()
    if install is None:
        raise RuntimeError("KiCad CLI is unavailable")
    version = run_kicad_process((install.path, "version"))
    if version.returncode != 0 or not version.stdout.strip():
        raise RuntimeError("KiCad CLI version could not be read")

    saved_texts: list[str] = []
    reports = []
    report_text = ""
    for index in (1, 2):
        run_dir = output_root / f"run-{index}"
        run_dir.mkdir(parents=True, exist_ok=True)
        _stage_vendored_project_footprints(serialization, run_dir)
        board_file = run_dir / "placement-roundtrip.kicad_pcb"
        board_file.write_text(serialization.rendered_board_text, encoding="utf-8")
        report_file = run_dir / ".pcbsmith" / "kicad" / "drc.json"
        # A failed CLI invocation must never be allowed to reuse a report from
        # an earlier run in the same output directory.
        report_file.unlink(missing_ok=True)
        report = run_kicad_drc(board_file, schematic_parity=False)
        if report.status == "unavailable":
            raise RuntimeError("KiCad CLI became unavailable during the roundtrip")
        saved_texts.append(board_file.read_text(encoding="utf-8"))
        reports.append(report)
        current_report = _canonical_report_text(report_file)
        if index == 1:
            report_text = current_report
    if saved_texts[0] != saved_texts[1]:
        raise ValueError("repeated KiCad save-roundtrip artifacts are not byte-identical")
    if reports[0].status != reports[1].status or reports[0].findings != reports[1].findings:
        raise ValueError("repeated KiCad DRC outcomes differ")

    initial = serialization.rendered_board_text
    saved = saved_texts[0]
    return PlacementKiCadSaveRoundtripAuthority(
        serialization_authority=serialization,
        kicad_cli_version=version.stdout.strip(),
        initial_board_text=initial,
        saved_board_text=saved,
        initial_board_sha256=_sha256_text(initial),
        saved_board_sha256=_sha256_text(saved),
        repeated_saved_board_sha256=_sha256_text(saved_texts[1]),
        initial_snapshot=extract_kicad_board_readback(initial),
        saved_snapshot=extract_kicad_board_readback(saved),
        drc_status=reports[0].status,
        drc_findings=reports[0].findings,
        drc_report_json=report_text,
        drc_report_sha256=_sha256_text(report_text),
        require_drc_pass=require_drc_pass,
    )
