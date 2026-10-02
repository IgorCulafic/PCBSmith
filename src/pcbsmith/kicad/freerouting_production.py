"""One/two-layer rectangular production Freerouting bridge; native validation stays mandatory."""

from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from pcbsmith.kicad.board import BOARD_SHEET_ORIGIN_MM, BoardLayout, TrackSegment, ViaSpec
from pcbsmith.kicad.library import QuotedString, _atom, _children, parse_sexpr, serialize_sexpr
from pcbsmith.kicad.placement_readback import extract_kicad_board_readback
from pcbsmith.kicad.routing_backend_registry import run_registered_freerouting_candidate
from pcbsmith.kicad.routing_evidence import inspect_kicad_drc_report
from pcbsmith.kicad.routing_external_adapters import (
    ExternalToolBinding,
    verify_external_tool_binding,
)
from pcbsmith.routing_ir import RouteCandidateResult, RouteRequest
from pcbsmith.rule_profiles import PcbRuleProfile
from pcbsmith.semantic_ir import SemanticIrModel


class FreeroutingProductionConfig(SemanticIrModel):
    backend: Literal["router:freerouting-v2.3.0"] = "router:freerouting-v2.3.0"
    binding: ExternalToolBinding
    java_executable: str
    kicad_python: str
    process_seconds: int = Field(gt=0, le=900)
    max_passes: int = Field(gt=0, le=100)

    def preflight(self) -> None:
        verify_external_tool_binding(self.binding)
        for path in (self.java_executable, self.kicad_python):
            if not Path(path).is_file():
                raise ValueError("Freerouting native runtime is missing: " + path)


def constrain_freerouting_dsn(
    payload: str, layout: BoardLayout, request: RouteRequest, edge_mm: float
) -> bytes:
    single = request.allowed_layers == ("F.Cu",)
    if not single and set(request.allowed_layers) != {"F.Cu", "B.Cu"}:
        raise ValueError("Freerouting bridge supports F.Cu or F.Cu/B.Cu")
    if (single and request.via_technologies) or (
        not single
        and (
            len(request.via_technologies) != 1
            or request.via_technologies[0].start_layer != "F.Cu"
            or request.via_technologies[0].end_layer != "B.Cu"
        )
    ):
        raise ValueError(
            "Freerouting requires no vias for F.Cu and one through-via technology for two layers"
        )
    if layout.outline is not None or layout.cutouts or layout.zones or layout.segments:
        raise ValueError("production DSN translation requires an unrouted rectangle")
    # SPECCTRA's quote declaration contains a bare quote, unlike KiCad S-expressions.
    tree = parse_sexpr(payload.replace('(string_quote ")', "(string_quote double_quote)"))
    if _atom(_children(tree, "unit")[0][1]) != "um":
        raise ValueError("DSN unit must be micrometres")
    structure = _children(tree, "structure")[0]
    structure[:] = [
        n
        for n in structure
        if not isinstance(n, list)
        or not n
        or _atom(n[0]) != "layer"
        or _atom(n[1]) in request.allowed_layers
    ]
    if {_atom(n[1]) for n in _children(structure, "layer")} != set(request.allowed_layers):
        raise ValueError("DSN requested copper layers missing")
    old_vias = {_atom(v) for n in _children(structure, "via") for v in n[1:]}
    structure[:] = [
        n for n in structure if not isinstance(n, list) or not n or _atom(n[0]) != "via"
    ]
    if single:
        # Freerouting 2.3.0 dereferences a net class's via rule even when vias
        # are disabled. Keep an inert, one-layer padstack to initialize that
        # rule; it is not a requested/manufacturable via technology. The DSN
        # has one copper layer, routing explicitly disables vias, and native
        # import still rejects every via or non-front copper object.
        via_name = "PCBSMITH_NoVia_Compatibility"
        library = _children(tree, "library")[0]
        library[:] = [
            n
            for n in library
            if not isinstance(n, list)
            or not n
            or n[0] != "padstack"
            or _atom(n[1]) not in old_vias | {via_name}
        ]
        library.append(
            [
                "padstack",
                QuotedString(via_name),
                ["shape", ["circle", "F.Cu", "600"]],
                ["attach", "off"],
            ]
        )
        structure.append(["via", QuotedString(via_name)])
        settings = _children(structure, "autoroute_settings")
        if len(settings) > 1:
            raise ValueError("DSN has ambiguous autoroute settings")
        if not settings:
            structure.append(["autoroute_settings"])
        settings_node = _children(structure, "autoroute_settings")[0]
        settings_node[:] = [
            n for n in settings_node if not isinstance(n, list) or not n or n[0] != "vias"
        ]
        settings_node.append(["vias", "off"])
    else:
        technology = request.via_technologies[0]
        diameter, drill = technology.diameter_mm * 1000, technology.drill_mm * 1000
        via_name = f"Via[0-1]_{diameter:g}:{drill:g}_um"
        library = _children(tree, "library")[0]
        library[:] = [
            n
            for n in library
            if not isinstance(n, list) or not n or n[0] != "padstack" or _atom(n[1]) not in old_vias
        ]
        library.append(
            [
                "padstack",
                QuotedString(via_name),
                ["shape", ["circle", "F.Cu", str(diameter)]],
                ["shape", ["circle", "B.Cu", str(diameter)]],
                ["attach", "off"],
            ]
        )
        structure.append(["via", QuotedString(via_name)])

    def via_choices(node: Any) -> None:
        if not isinstance(node, list):
            return
        if node and node[0] == "use_via":
            node[1:] = [QuotedString(via_name)]
        for n in node:
            if isinstance(n, list):
                via_choices(n)

    via_choices(tree)

    widths = {name: c.preferred_width_mm for c in request.width_constraints for name in c.net_names}
    clearance = max(c.minimum_clearance_mm for c in request.clearance_constraints)
    # A conservative centreline keep-in includes the largest trace radius.
    inset = (
        edge_mm + max([*widths.values(), *(v.diameter_mm for v in request.via_technologies)]) / 2
    )
    o = BOARD_SHEET_ORIGIN_MM
    x0, x1 = (o + inset) * 1000, (o + layout.width_mm - inset) * 1000
    y0, y1 = -(o + inset) * 1000, -(o + layout.height_mm - inset) * 1000
    boundary = _children(structure, "boundary")[0]
    boundary[:] = ["boundary", ["rect", "pcb", str(x0), str(y1), str(x1), str(y0)]]

    def gaps(node: Any) -> None:
        if isinstance(node, list):
            if node and _atom(node[0]) == "clearance":
                node[1] = str(clearance * 1000)
            for child in node:
                gaps(child)

    gaps(tree)
    # Each exported class must carry exactly the requested width for its nets.
    network = _children(tree, "network")[0]
    covered: set[str] = set()
    for cls in _children(network, "class"):
        if single:
            circuits = _children(cls, "circuit")
            if not circuits:
                cls.append(["circuit", ["use_via", QuotedString(via_name)]])
            elif not any(_children(circuit, "use_via") for circuit in circuits):
                circuits[0].append(["use_via", QuotedString(via_name)])
        nets = [_atom(n) for n in cls[2:] if not isinstance(n, list)]
        chosen = {widths[n] for n in nets if n in widths}
        if not chosen:
            continue
        if len(chosen) != 1:
            raise ValueError("DSN class mixes distinct requested widths")
        covered.update(n for n in nets if n in widths)
        rule = _children(cls, "rule")[0]
        rule[:] = [
            "rule",
            ["width", str(chosen.pop() * 1000)],
            ["clearance", str(clearance * 1000)],
        ]
    if covered != set(widths):
        raise ValueError("DSN classes omit requested nets")
    return (
        serialize_sexpr(tree).replace("(string_quote double_quote)", '(string_quote ")') + "\n"
    ).encode()


def constrain_single_sided_dsn(
    payload: str, layout: BoardLayout, request: RouteRequest, edge_mm: float
) -> bytes:
    """Compatibility entry point retaining the strict front-only contract."""
    if request.allowed_layers != ("F.Cu",) or request.via_technologies:
        raise ValueError("single-sided routing requires F.Cu only and no vias")
    return constrain_freerouting_dsn(payload, layout, request, edge_mm)


def read_single_sided_routes(
    board: Path, source: Path, layout: BoardLayout, request: RouteRequest
) -> BoardLayout:
    from pcbsmith.production_routing import native_save_readback_matches

    old = extract_kicad_board_readback(source.read_text(encoding="utf-8"))
    new = extract_kicad_board_readback(board.read_text(encoding="utf-8"))
    if new.zones or (new.vias and not request.via_technologies):
        raise ValueError("SES import added forbidden vias or zones")
    if not native_save_readback_matches(old, new.model_copy(update={"segments": (), "vias": ()})):
        raise ValueError("SES import changed immutable native placement or dependencies")
    tree = parse_sexpr(board.read_text(encoding="utf-8"))
    nets = {_atom(n[1]): _atom(n[2]) for n in _children(tree, "net") if len(n) > 2}
    widths = {name: c.preferred_width_mm for c in request.width_constraints for name in c.net_names}
    tracks = []

    def coordinate(value: Any) -> float:
        return float(Decimal(_atom(value)) - Decimal(str(BOARD_SHEET_ORIGIN_MM)))

    for seg in _children(tree, "segment"):
        start, end = _children(seg, "start")[0], _children(seg, "end")[0]
        net = _atom(_children(seg, "net")[0][1])
        net = nets.get(net, net)
        layer = _atom(_children(seg, "layer")[0][1])
        width = float(_atom(_children(seg, "width")[0][1]))
        if (
            layer not in request.allowed_layers
            or net not in widths
            or width + 0.000001 < widths[net]
        ):
            raise ValueError("SES route violates layer or requested minimum width")
        tracks.append(
            TrackSegment(
                coordinate(start[1]),
                coordinate(start[2]),
                coordinate(end[1]),
                coordinate(end[2]),
                layer,
                net,
                width,
            )
        )
    if not tracks:
        raise ValueError("SES import contains no tracks")
    vias = []
    for via in _children(tree, "via"):
        technology = request.via_technologies[0]
        layers = tuple(_atom(v) for v in _children(via, "layers")[0][1:])
        size = float(_atom(_children(via, "size")[0][1]))
        drill = float(_atom(_children(via, "drill")[0][1]))
        net = _atom(_children(via, "net")[0][1])
        net = nets.get(net, net)
        if (
            layers != ("F.Cu", "B.Cu")
            or net not in widths
            or abs(size - technology.diameter_mm) > 0.000001
            or abs(drill - technology.drill_mm) > 0.000001
        ):
            raise ValueError("SES via violates the declared through-via technology")
        at = _children(via, "at")[0]
        vias.append(ViaSpec(coordinate(at[1]), coordinate(at[2]), net, size, drill))
    return replace(layout, segments=tuple(tracks), vias=tuple(vias))


def route_freerouting_production(
    *,
    board: Path,
    layout: BoardLayout,
    request: RouteRequest,
    profile: PcbRuleProfile,
    config: FreeroutingProductionConfig,
    work: Path,
) -> RouteCandidateResult:
    from pcbsmith.board_job import require_library_worker
    from pcbsmith.production_generators import generate_nonmutating_kicad_drc

    require_library_worker()
    config.preflight()
    bridge = Path(__file__).resolve().parents[3] / "tools/kicad_dsn_ses_bridge.py"
    work = work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    widths = {n: c.preferred_width_mm for c in request.width_constraints for n in c.net_names}
    rules = work / "widths.json"
    rules.write_text(json.dumps(widths))

    def native(args: list[Any], label: str) -> None:
        completed = subprocess.run(
            [config.kicad_python, str(bridge), *map(str, args)],
            capture_output=True,
            timeout=90,
            check=False,
        )
        (work / (label + ".stdout.log")).write_bytes(completed.stdout)
        (work / (label + ".stderr.log")).write_bytes(completed.stderr)
        if completed.returncode:
            raise RuntimeError(label + " failed: " + completed.stderr.decode(errors="replace"))

    raw = work / "export.dsn"
    native(
        [
            "export",
            board.resolve(),
            raw,
            "--width-rules-json",
            rules,
            "--clearance-mm",
            profile.fab_spacing.minimum_copper_clearance_mm,
        ],
        "export",
    )
    dsn = constrain_freerouting_dsn(
        raw.read_text(), layout, request, profile.fab_spacing.minimum_copper_to_edge_mm
    )
    checked = False

    def importer(ses: Path) -> BoardLayout:
        nonlocal checked
        imported = work / "imported.kicad_pcb"
        native(["import", board.resolve(), ses, imported], "import")
        # The native checker needs the retained source project's schematic and rules.
        from pcbsmith.kicad.project_dependencies import native_project_hashes

        for relative in native_project_hashes(board):
            if relative == board.name:
                continue
            target = work / relative
            if Path(relative).stem == board.stem:
                target = target.with_name("imported" + target.suffix)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((board.parent / relative).read_bytes())
        result = read_single_sided_routes(imported, board, layout, request)
        report = work / "import-drc.json"
        generate_nonmutating_kicad_drc(imported, report)
        checked = inspect_kicad_drc_report(report).clean
        return result

    return run_registered_freerouting_candidate(
        registration_id=config.backend,
        request=request,
        source_layout=layout,
        candidate_directory=work,
        binding=config.binding,
        dsn_payload=dsn,
        ses_importer=importer,
        java_executable=config.java_executable,
        completion_verifier=lambda: checked,
    )
