"""Source-checked, unrouted no-connect net-binding repair; no copper geometry edits."""

from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from pcbsmith.kicad.board import canonical_kicad_netlist_xml_text, export_kicad_netlist_xml
from pcbsmith.kicad.library import parse_sexpr, serialize_sexpr
from pcbsmith.kicad.native_edits import atom, children, object_id, object_inventory, reference


def plan_no_connect_repair(
    source: Path, terminals: tuple[tuple[str, str], ...], maximum_changed_objects: int
) -> tuple[bytes, dict[str, Any]]:
    """Remove only obsolete synthetic nets on explicitly NC native schematic pins."""
    if not terminals or len(set(terminals)) != len(terminals):
        raise ValueError("unique no-connect terminals required")
    tree = parse_sexpr(source.read_text(encoding="utf-8"))
    if not tree or tree[0] != "kicad_pcb":
        raise ValueError("source is not a native KiCad board")
    if any(children(tree, kind) for kind in ("segment", "arc", "via", "zone")):
        raise ValueError("no-connect repair requires an unrouted board")
    before = object_inventory(tree)
    xml = export_kicad_netlist_xml(source.with_suffix(".kicad_sch")).read_text(encoding="utf-8")
    native = ET.fromstring(xml)
    bindings: dict[tuple[str, str], str] = {}
    seen: set[tuple[str, str]] = set()
    for net in native.iter("net"):
        nodes = tuple(net.iter("node"))
        for node in nodes:
            key = (node.get("ref", ""), node.get("pin", ""))
            if key in seen:
                raise ValueError("duplicate native schematic terminal")
            seen.add(key)
            if (
                len(nodes) == 1
                and net.get("name", "").startswith("unconnected-")
                and "no_connect" in node.get("pintype", "").split("+")
            ):
                bindings[key] = net.get("name", "")
    allowed = set()
    for ref, pin in terminals:
        if (ref, pin) not in bindings:
            raise ValueError(f"{ref}.{pin} is not an explicit isolated native no-connect")
        matches = [
            (i, n)
            for i, n in enumerate(tree)
            if isinstance(n, list) and n[0] == "footprint" and reference(n) == ref
        ]
        if len(matches) != 1:
            raise ValueError("missing or ambiguous no-connect footprint")
        index, footprint = matches[0]
        pads = [p for p in children(footprint, "pad") if atom(p[1]) == pin]
        if len(pads) != 1:
            raise ValueError("no-connect repair requires one exact numbered pad")
        pad = pads[0]
        if (
            "locked" in footprint
            or children(footprint, "locked")
            or "locked" in pad
            or children(pad, "locked")
        ):
            raise ValueError("locked no-connect target")
        nets = children(pad, "net")
        if len(nets) != 1 or atom(nets[0][-1]) != bindings[(ref, pin)]:
            raise ValueError("pad does not carry the exact native synthetic no-connect net")
        pad.remove(nets[0])
        allowed.add(object_id(footprint, index))
    after = object_inventory(tree)
    changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    if set(changed) != allowed or len(changed) > maximum_changed_objects:
        raise ValueError("no-connect repair changed protected objects or exceeded its bound")
    payload = (serialize_sexpr(tree) + "\n").encode()
    if object_inventory(parse_sexpr(payload.decode())) != after:
        raise ValueError("no-connect serialization changed object semantics")
    return payload, {
        "changed_ids": changed,
        "protected_ids": sorted(before.keys() - allowed),
        "before": before,
        "after": after,
        "generator_invocations": 0,
        "router_invocations": 0,
        "endpoint_policy": "geometry unchanged; only explicit NC nets removed",
        "no_connect_terminals": [list(t) for t in terminals],
        "native_netlist_sha256": hashlib.sha256(
            canonical_kicad_netlist_xml_text(xml).encode()
        ).hexdigest(),
    }
