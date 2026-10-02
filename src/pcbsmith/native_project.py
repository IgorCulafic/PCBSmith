"""Declarative single-sheet native project preparation; no PCB or approval producer.

Resolve installed symbols/footprints, retain exact local dependencies, require complete
pin intent (None means deliberate NC), and compare native XML connectivity with it.
Generation/review/routing remain owned by the production boundaries.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from pcbsmith.kicad.asset_resolution import AssetPin, resolve_pinned_asset
from pcbsmith.kicad.board import BoardNetlist, export_kicad_netlist_xml, parse_board_netlist
from pcbsmith.kicad.export_divider_highpass_led import _label, _render_project, _symbol, _wire
from pcbsmith.kicad.floorplan import FloorplanCorridor
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.library import (
    QuotedString,
    SList,
    _atom,
    _children,
    load_footprint,
    parse_sexpr,
    serialize_sexpr,
)
from pcbsmith.rule_profiles import PcbRuleProfile


class ProjectPart(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    reference: str = Field(pattern=r"^[A-Z]+[0-9]+$")
    symbol: str
    value: str
    footprint: str
    mpn: str
    role: str
    pins: dict[str, str | None]
    schematic_at: tuple[float, float]
    board_at: tuple[float, float, float]
    populated: bool = True


class NativeProjectSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    schema_id: str = "pcbsmith-native-project-v1"
    project_id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    title: str
    user_request: str
    width_mm: float = Field(gt=0)
    height_mm: float = Field(gt=0)
    profile: PcbRuleProfile
    parts: tuple[ProjectPart, ...] = Field(min_length=1)
    driven_power_nets: tuple[str, ...] = ()
    power_flag_positions: dict[str, tuple[float, float]] = Field(default_factory=dict)
    notes: tuple[str, ...] = ()
    floorplan_corridors: tuple[FloorplanCorridor, ...] = ()
    asset_pins: tuple[AssetPin, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> Self:
        if self.schema_id != "pcbsmith-native-project-v1":
            raise ValueError("Unsupported project schema")
        pin_keys = [(p.kind, p.library_id) for p in self.asset_pins]
        if len(pin_keys) != len(set(pin_keys)):
            raise ValueError("Duplicate asset pin")
        expected_assets = {("symbol", "power:PWR_FLAG")} | {
            (kind, getattr(p, kind)) for p in self.parts for kind in ("symbol", "footprint")
        }
        if not set(pin_keys) <= expected_assets:
            raise ValueError("Asset pin is not used by this project")
        refs = [p.reference for p in self.parts]
        if len(refs) != len(set(refs)):
            raise ValueError("Duplicate component reference")
        for p in self.parts:
            if any(abs(v / 1.27 - round(v / 1.27)) > 1e-7 for v in p.schematic_at):
                raise ValueError("Schematic anchors must use the 1.27 mm connection grid")
            if any(not math.isfinite(v) for v in (*p.schematic_at, *p.board_at)):
                raise ValueError("Coordinates must be finite")
            for net in p.pins.values():
                if net is not None and not re.fullmatch(r"[A-Za-z0-9_+.-]+", net):
                    raise ValueError("Net must be an unqualified local label")
        nets = {n for p in self.parts for n in p.pins.values() if n is not None}
        if not set(self.driven_power_nets) <= nets:
            raise ValueError("Power flag net is absent")
        if not set(self.power_flag_positions) <= set(self.driven_power_nets):
            raise ValueError("Power flag position targets an undeclared driven net")
        for pose in self.power_flag_positions.values():
            if any(not math.isfinite(v) or abs(v / 1.27 - round(v / 1.27)) > 1e-7 for v in pose):
                raise ValueError("Power flag positions must use the finite 1.27 mm grid")
        return self


def resolve_symbol(
    symbol_id: str, symbol_root: Path, *, source_file: Path | None = None
) -> tuple[SList, Path]:
    """Flatten official inheritance, rejecting cycles and unsupported multi-unit parts."""
    if not re.fullmatch(r"[A-Za-z0-9_+-]+:[A-Za-z0-9_.+-]+", symbol_id):
        raise ValueError("Invalid symbol identifier")
    library, name = symbol_id.split(":")
    from pcbsmith.kicad.symbols import symbol_source_file

    source = source_file or symbol_source_file(symbol_id, installed_root=symbol_root)
    tree = parse_sexpr(source.read_text(encoding="utf-8"))
    lookup = {_atom(s[1]): s for s in _children(tree, "symbol")}

    def resolve(key: str, visited: set[str]) -> SList:
        if key in visited:
            raise ValueError("Symbol inheritance cycle")
        n = copy.deepcopy(lookup[key])
        extends = _children(n, "extends")
        if extends:
            parent = _atom(extends[0][1])
            base = resolve(parent, visited | {key})
            overrides = {_atom(p[1]): p for p in _children(n, "property")}
            base = [
                p
                for p in base
                if not (
                    isinstance(p, list) and p and p[0] == "property" and _atom(p[1]) in overrides
                )
            ]
            base.extend(overrides.values())
            for child in _children(base, "symbol"):
                child[1] = QuotedString(_atom(child[1]).replace(parent + "_", key + "_", 1))
            base[1] = QuotedString(key)
            n = base
        return n

    node = resolve(name, set())
    for unit in _children(node, "symbol"):
        suffix = _atom(unit[1]).rsplit("_", 2)
        if len(suffix) != 3 or suffix[1] not in {"0", "1"}:
            raise ValueError("Multi-unit symbols require a dedicated unit-aware adapter")
    return node, source


def symbol_pins(node: SList) -> dict[str, SList]:
    pins = {}
    for unit in _children(node, "symbol"):
        # Alternate De Morgan graphics must not duplicate electrical pins.
        if _atom(unit[1]).rsplit("_", 1)[-1] not in {"0", "1"}:
            continue
        for pin in _children(unit, "pin"):
            number = _atom(_children(pin, "number")[0][1])
            if number in pins:
                raise ValueError("Stacked pin numbers are not supported by this adapter")
            pins[number] = pin
    return pins


def inspect_native_input_closure(
    spec: NativeProjectSpec, schematic: Path, xml: Path
) -> tuple[BoardNetlist, dict[str, Any]]:
    """Compare exact native XML to declared identities and every connected pin.

    Pure inspection: callers must actually export XML from this schematic before
    retaining this report as preparation evidence. This is not package qualification.
    """
    schematic_bytes = schematic.read_bytes()
    xml_bytes = xml.read_bytes()
    netlist = parse_board_netlist(xml_bytes.decode("utf-8"))
    findings: list[str] = []
    declared = {part.reference: part for part in spec.parts}
    # The board-oriented parser intentionally filters non-board/unknown references.
    # At this authority boundary, silently discarded unexpected references are errors.
    xml_root = ET.fromstring(xml_bytes)
    for element in (*xml_root.iter("comp"), *xml_root.iter("node")):
        ref = element.get("ref", "")
        if not ref.startswith("#") and ref not in declared:
            findings.append(f"undeclared native reference: {ref}")
    # Deliberate NC terminals are omitted from board connectivity, but remain
    # source-bound obligations. Do not let that filtering hide an extra pin,
    # a duplicate terminal, or a connected pin that was declared NC.
    raw_terminals: set[tuple[str, str]] = set()
    for node in xml_root.iter("node"):
        ref, pin = node.get("ref", ""), node.get("pin", "")
        if ref.startswith("#"):
            continue
        if (ref, pin) in raw_terminals:
            findings.append(f"duplicate native terminal: {ref}.{pin}")
        raw_terminals.add((ref, pin))
        if "no_connect" in (node.get("pintype") or "").split("+"):
            part = declared.get(ref)
            if part is None or pin not in part.pins:
                findings.append(f"undeclared native terminal: {ref}.{pin}")
            elif part.pins[pin] is not None:
                findings.append(f"invalid native no-connect: {ref}.{pin}")
    components = {part.reference: part for part in netlist.components}
    if len(components) != len(netlist.components):
        findings.append("duplicate native component reference")
    if set(components) != set(declared):
        findings.append("native component reference coverage differs from specification")
    for ref in sorted(set(components) & set(declared)):
        native, part = components[ref], declared[ref]
        fields = dict(native.fields)
        if len(fields) != len(native.fields):
            findings.append(f"{ref}: duplicate native component field")
        for name, actual, expected in (
            ("value", native.value, part.value),
            ("footprint", native.footprint, part.footprint),
            ("MPN", fields.get("MPN"), part.mpn),
        ):
            if actual != expected:
                findings.append(f"{ref}: native {name} differs from specification")
    expected_nets: dict[str, list[tuple[str, str]]] = {}
    for part in spec.parts:
        for pin, net_name in part.pins.items():
            if net_name is not None:
                expected_nets.setdefault("/" + net_name, []).append((part.reference, pin))
    expected_nets = {name: sorted(nodes) for name, nodes in expected_nets.items()}
    actual_nets: dict[str, list[tuple[str, str]]] = {}
    seen_terminals: set[tuple[str, str]] = set()
    seen_names: set[str] = set()
    for net in netlist.nets:
        if net.name in seen_names:
            findings.append(f"duplicate native net name: {net.name}")
        seen_names.add(net.name)
        for ref, pin in net.nodes:
            if (ref, pin) in seen_terminals:
                findings.append(f"duplicate native terminal: {ref}.{pin}")
            seen_terminals.add((ref, pin))
            declared_part = declared.get(ref)
            if declared_part is None or pin not in declared_part.pins:
                findings.append(f"undeclared native terminal: {ref}.{pin}")
            elif net.name.startswith("unconnected-") and (
                declared_part.pins[pin] is not None or len(net.nodes) != 1
            ):
                findings.append(f"invalid native no-connect: {ref}.{pin}")
        if not net.name.startswith("unconnected-"):
            actual_nets[net.name] = sorted(net.nodes)
    if expected_nets != actual_nets:
        findings.append("native pin connectivity differs from specification")
    report = {
        "schema_id": "pcbsmith-native-input-closure-v1",
        "status": "failed" if findings else "passed",
        "expected": expected_nets,
        "observed": actual_nets,
        "findings": findings,
        "method": "Native KiCad XML compared against declared component identities and pin intent",
        "production_accepted": False,
        "schematic_sha256": hashlib.sha256(schematic_bytes).hexdigest(),
        "netlist_sha256": hashlib.sha256(xml_bytes).hexdigest(),
        "specification_sha256": hashlib.sha256(spec.model_dump_json().encode("utf-8")).hexdigest(),
        "limitations": (
            "MPN text equality is not datasheet pin-map or physical package qualification."
        ),
    }
    return netlist, report


def require_native_input_closure(spec: NativeProjectSpec, project: Path) -> BoardNetlist:
    """Reject stale or legacy unbound preparation before deriving layout inputs."""
    recorded = json.loads((project / "netlist-vs-intent.json").read_text(encoding="utf-8"))
    netlist, current = inspect_native_input_closure(
        spec,
        project / (spec.project_id + ".kicad_sch"),
        project / ".pcbsmith/kicad" / (spec.project_id + ".net.xml"),
    )
    if recorded.get("schema_id") != current["schema_id"]:
        raise ValueError("Legacy native report lacks input closure; refresh supported preparation")
    for name in ("schematic_sha256", "netlist_sha256", "specification_sha256"):
        if recorded.get(name) != current[name]:
            raise ValueError(f"Missing or stale native input closure: {name}")
    if recorded.get("status") != "passed" or current["status"] != "passed":
        raise ValueError("Native input closure failed: " + "; ".join(current["findings"]))
    return netlist


def prepare_native_project(spec: NativeProjectSpec, output: Path, symbol_root: Path) -> Path:
    """Fresh draft only. Native XML mismatch leaves a failed attempt for inspection."""
    from pcbsmith.board_job import require_library_worker

    require_library_worker()
    if output.exists():
        raise ValueError("Project preparation requires a fresh output directory")
    pinned_sources = {
        (p.kind, p.library_id): resolve_pinned_asset(p, symbol_root=symbol_root)
        for p in spec.asset_pins
    }
    resolved, footprints = {}, {}
    for part in spec.parts:
        if part.symbol not in resolved:
            resolved[part.symbol] = resolve_symbol(
                part.symbol, symbol_root, source_file=pinned_sources.get(("symbol", part.symbol))
            )
        actual = symbol_pins(resolved[part.symbol][0])
        if set(actual) != set(part.pins):
            raise ValueError(
                f"{part.reference}: incomplete or invalid pin intent: "
                f"{set(actual) ^ set(part.pins)}"
            )
        fp = load_footprint(
            part.footprint, source_file=pinned_sources.get(("footprint", part.footprint))
        )
        fp_pins = {p.name for p in fp.spec.pads if p.name}
        if set(actual) != fp_pins:
            raise ValueError(f"{part.reference}: symbol/footprint pin set mismatch")
        footprints[part.footprint] = fp
    flag, flag_source = resolve_symbol(
        "power:PWR_FLAG", symbol_root, source_file=pinned_sources.get(("symbol", "power:PWR_FLAG"))
    )
    output.mkdir(parents=True)
    (output / "design-spec.json").write_text(
        spec.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    records, embedded, local_symbols = [], [], []
    symbol_ids = {}
    for sid, (node, source) in {**resolved, "power:PWR_FLAG": (flag, flag_source)}.items():
        local = sid.replace(":", "__")
        n = copy.deepcopy(node)
        original_name = _atom(n[1])
        for child in _children(n, "symbol"):
            child[1] = QuotedString(_atom(child[1]).replace(original_name + "_", local + "_", 1))
        n[1] = QuotedString(local)
        local_symbols.append(serialize_sexpr(n))
        n[1] = QuotedString("Project:" + local)
        embedded.append(serialize_sexpr(n))
        symbol_ids[sid] = "Project:" + local
        records.append(
            {
                "kind": "symbol",
                "resolution": "pinned_hit" if ("symbol", sid) in pinned_sources else "local_hit",
                "fetch_count": 0,
                "id": sid,
                "source": str(source),
                "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            }
        )
    (output / "Project.kicad_sym").write_text(
        '(kicad_symbol_lib (version 20250114) (generator "pcbsmith")\n'
        + "\n".join(local_symbols)
        + ")\n",
        encoding="utf-8",
    )
    (output / "sym-lib-table").write_text(
        '(sym_lib_table (lib (name "Project") (type "KiCad") '
        '(uri "${KIPRJMOD}/Project.kicad_sym") (options "") '
        '(descr "Retained symbol definitions")))\n',
        encoding="utf-8",
    )
    libs = set()
    for fid, fp in footprints.items():
        lib, name = fid.split(":")
        libs.add(lib)
        dest = output / (lib + ".pretty") / (name + ".kicad_mod")
        dest.parent.mkdir(exist_ok=True)
        dest.write_bytes(fp.source_file.read_bytes())
        records.append(
            {
                "kind": "footprint",
                "resolution": "pinned_hit" if ("footprint", fid) in pinned_sources else "local_hit",
                "fetch_count": 0,
                "id": fid,
                "source": str(fp.source_file),
                "sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
            }
        )
    (output / "fp-lib-table").write_text(
        "(fp_lib_table\n"
        + "\n".join(
            f'(lib (name "{lib}") (type "KiCad") '
            f'(uri "${{KIPRJMOD}}/{lib}.pretty") (options "") '
            '(descr "Retained official footprint"))'
            for lib in sorted(libs)
        )
        + ")\n",
        encoding="utf-8",
    )
    (output / "library-sources.json").write_text(
        json.dumps(records, indent=2) + "\n", encoding="utf-8"
    )
    project = json.loads(
        _render_project(
            profile=spec.profile, min_through_hole_mm=spec.profile.geometry.minimum_finished_hole_mm
        )
    )
    project["board"]["design_settings"]["rule_severities"]["lib_footprint_mismatch"] = "error"
    (output / (spec.project_id + ".kicad_pro")).write_text(
        json.dumps(project, indent=2) + "\n", encoding="utf-8"
    )
    items = []
    power_anchors: dict[str, tuple[float, float]] = {}
    for part in spec.parts:
        x, y = part.schematic_at
        pins = symbol_pins(resolved[part.symbol][0])
        ref_at, value_at = (x, y - 10.16), (x, y - 7.62)
        if part.reference.startswith(("R", "C")):
            ref_at, value_at = (x + 5.08, y - 1.27), (x + 8.89, y + 2.54)
        elif part.reference.startswith("Q"):
            ref_at, value_at = (x + 10.16, y - 2.54), (x + 10.16, y + 1.27)
        elif part.reference.startswith("U"):
            top = max(float(_atom(_children(pin, "at")[0][2])) for pin in pins.values())
            right = max(float(_atom(_children(pin, "at")[0][1])) for pin in pins.values())
            ref_at, value_at = (
                (x + right + 7.62, y - top - 2.54),
                (x + right + 7.62, y - top + 1.27),
            )
        rendered = _symbol(
            symbol_ids[part.symbol],
            part.reference,
            part.value,
            x,
            y,
            spec.project_id,
            pin_numbers=tuple(part.pins) or ("1",),
            footprint=part.footprint,
            in_bom=part.populated,
            reference_at=ref_at,
            value_at=value_at,
            extra_properties=(("MPN", part.mpn), ("Design_role", part.role)),
        )
        if not part.pins:
            tree = parse_sexpr(rendered)
            tree = [n for n in tree if not (isinstance(n, list) and n and n[0] == "pin")]
            rendered = serialize_sexpr(tree)
        items.append(rendered)
        for number, pin in symbol_pins(resolved[part.symbol][0]).items():
            at = _children(pin, "at")[0]
            px = x + float(_atom(at[1]))
            py = y - float(_atom(at[2]))
            a = math.radians(float(_atom(at[3])))
            net = part.pins[number]
            if net is None:
                items.append(
                    f"(no_connect (at {px:g} {py:g}) "
                    f'(uuid "{stable_kicad_uuid(spec.project_id, part.reference, number, "nc")}"))'
                )
                continue
            ex = round(px - 5.08 * math.cos(a), 5)
            ey = round(py + 5.08 * math.sin(a), 5)
            items.append(_wire((px, py), (ex, ey)))
            label = parse_sexpr(_label(net, ex, ey))
            effects = _children(label, "effects")[0]
            effects.append(["justify", "right" if ex < px else "left"])
            items.append(serialize_sexpr(label))
            power_anchors.setdefault(net, (ex, ey))
    for index, net in enumerate(spec.driven_power_nets, 1):
        anchor = spec.power_flag_positions.get(net, power_anchors[net])
        if net in spec.power_flag_positions:
            end = (anchor[0], round(anchor[1] + 5.08, 5))
            items.extend((_wire(anchor, end), _label(net, *end)))
        items.append(
            _symbol(
                symbol_ids["power:PWR_FLAG"],
                f"#FLG0{index}",
                "PWR_FLAG",
                anchor[0],
                anchor[1],
                spec.project_id,
                pin_count=1,
                on_board=False,
                in_bom=False,
            )
        )
    for i, note in enumerate((spec.title, *spec.notes)):
        items.append(
            f"(text {json.dumps(note)} (at 15 {15 + i * 5} 0) "
            "(effects (font (size 1.5 1.5)) (justify left)) "
            f'(uuid "{stable_kicad_uuid(spec.project_id, "note", str(i))}"))'
        )
    schematic = output / (spec.project_id + ".kicad_sch")
    schematic.write_text(
        '(kicad_sch (version 20250114) (generator "pcbsmith") (uuid "'
        + stable_kicad_uuid(spec.project_id, "root")
        + '") (paper "A3")\n(lib_symbols\n'
        + "\n".join(embedded)
        + ")\n"
        + "\n".join(items)
        + '\n(sheet_instances (path "/" (page "1"))))\n',
        encoding="utf-8",
    )
    from pcbsmith.kicad.native_format import upgrade_generated_native_file

    upgrade_generated_native_file(schematic, output / "schematic-format.json")
    xml = export_kicad_netlist_xml(schematic)
    _, report = inspect_native_input_closure(spec, schematic, xml)
    (output / "netlist-vs-intent.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    if report["status"] != "passed":
        raise ValueError("Native input closure failed: " + "; ".join(report["findings"]))
    return schematic


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--symbol-root", type=Path, required=True)
    args = parser.parse_args()
    import sys

    from pcbsmith.board_job import require_worker

    require_worker("pcbsmith.native_project", sys.argv[1:])

    spec = NativeProjectSpec.model_validate_json(args.spec.read_text(encoding="utf-8"))
    print(prepare_native_project(spec, args.output, args.symbol_root))


if __name__ == "__main__":
    main()
