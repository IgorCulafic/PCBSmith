"""One/two/four-layer rectangular Freerouting bridge; native validation stays mandatory."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from pcbsmith.kicad.board import BOARD_SHEET_ORIGIN_MM, BoardLayout, TrackSegment, ViaSpec, _mm
from pcbsmith.kicad.library import (
    QuotedString,
    SList,
    _atom,
    _children,
    parse_sexpr,
    serialize_sexpr,
)
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
    from pcbsmith.copper_layers import ordered_copper_layers

    copper_layers = ordered_copper_layers(request.allowed_layers)
    single = copper_layers == ("F.Cu",)
    if (single and request.via_technologies) or (
        not single
        and (
            len(request.via_technologies) != 1
            or request.via_technologies[0].start_layer != "F.Cu"
            or request.via_technologies[0].end_layer != "B.Cu"
        )
    ):
        raise ValueError(
            "Freerouting requires no vias for F.Cu and one through-via technology otherwise"
        )
    if layout.outline is not None or layout.cutouts or layout.zones or layout.segments:
        raise ValueError("production DSN translation requires an unrouted rectangle")
    # SPECCTRA's quote declaration contains a bare quote, unlike KiCad S-expressions.
    tree = parse_sexpr(payload.replace('(string_quote ")', "(string_quote double_quote)"))
    if _atom(_children(tree, "unit")[0][1]) != "um":
        raise ValueError("DSN unit must be micrometres")
    structure = _children(tree, "structure")[0]
    source_layers = tuple(_atom(n[1]) for n in _children(structure, "layer"))
    expected_source = ("F.Cu", "B.Cu") if single else copper_layers
    allowed_source_stacks = (("F.Cu",), expected_source) if single else (expected_source,)
    if source_layers not in allowed_source_stacks:
        raise ValueError("DSN copper layers differ from physical stack order")
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
    if tuple(_atom(n[1]) for n in _children(structure, "layer")) != copper_layers:
        raise ValueError("DSN copper layers differ from physical stack order")
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
        via_name = f"Via[0-{len(copper_layers) - 1}]_{diameter:g}:{drill:g}_um"
        library = _children(tree, "library")[0]
        library[:] = [
            n
            for n in library
            if not isinstance(n, list) or not n or n[0] != "padstack" or _atom(n[1]) not in old_vias
        ]
        via_shapes: list[SList] = [
            ["shape", ["circle", name, str(diameter)]] for name in copper_layers
        ]
        library.append(
            [
                "padstack",
                QuotedString(via_name),
                *via_shapes,
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
    restrictions = {n: c for c in request.net_layer_constraints for n in c.net_names}
    if restrictions:
        if _children(network, "class_class"):
            raise ValueError("per-net restrictions cannot split DSN class-pair rules")
        expanded = []
        for cls in _children(network, "class"):
            nets = [_atom(n) for n in cls[2:] if not isinstance(n, list)]
            groups: dict[tuple[Any, ...], list[str]] = {}
            for name in nets:
                restriction = restrictions.get(name)
                key = (
                    widths.get(name),
                    restriction.allowed_layers if restriction else request.allowed_layers,
                    restriction.effective_trace_layers if restriction else request.allowed_layers,
                    restriction.allow_vias if restriction else True,
                )
                groups.setdefault(key, []).append(name)
            if len(groups) <= 1:
                expanded.append(cls)
                continue
            for names in groups.values():
                suffix = hashlib.sha256(json.dumps(sorted(names)).encode()).hexdigest()[:16]
                expanded.append(
                    [
                        "class",
                        QuotedString(_atom(cls[1]) + "__pcbsmith_" + suffix),
                        *(QuotedString(n) for n in names),
                        *(deepcopy(n) for n in cls[2:] if isinstance(n, list)),
                    ]
                )
        network[:] = [n for n in network if not (isinstance(n, list) and n and n[0] == "class")]
        for restriction in restrictions.values():
            if restriction.allow_vias:
                continue
            if len(restriction.effective_trace_layers) != 1:
                raise ValueError("Freerouting no-via nets must select exactly one copper layer")
            layer = restriction.effective_trace_layers[0]
            no_via_name = "PCBSMITH_NoVia_" + layer
            compatibility_stack: list[Any] = [
                "padstack",
                QuotedString(no_via_name),
                ["shape", ["circle", QuotedString(layer), "600"]],
                ["attach", "off"],
            ]
            existing = [n for n in _children(library, "padstack") if _atom(n[1]) == no_via_name]
            if existing and existing != [compatibility_stack]:
                raise ValueError("reserved no-via padstack conflicts with DSN input")
            if not existing:
                # Same inert one-layer compatibility padstack used by the
                # front-only bridge. It cannot span copper faces. Post-import
                # validation still rejects every actual via on this net.
                library.append(compatibility_stack)
            via_node = _children(structure, "via")[0]
            if no_via_name not in {_atom(n) for n in via_node[1:]}:
                via_node.append(QuotedString(no_via_name))
        network.extend(expanded)
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
        if covered.intersection(n for n in nets if n in widths):
            raise ValueError("DSN assigns a requested net to multiple classes")
        covered.update(n for n in nets if n in widths)
        if restrictions and len(_children(cls, "rule")) != 1:
            raise ValueError("per-net DSN classes require one unambiguous rule scope")
        rule = _children(cls, "rule")[0]
        rule[:] = [
            "rule",
            ["width", str(chosen.pop() * 1000)],
            ["clearance", str(clearance * 1000)],
        ]
        policies = [restrictions[n] for n in nets if n in restrictions]
        if policies:
            policy = policies[0]
            if _children(cls, "layer_rule"):
                raise ValueError("per-net restrictions cannot override DSN layer-specific rules")
            circuits = _children(cls, "circuit")
            if not circuits:
                cls.append(["circuit"])
                circuits = _children(cls, "circuit")
            for circuit in circuits:
                circuit[:] = [
                    n
                    for n in circuit
                    if not (isinstance(n, list) and n and n[0] in {"use_layer", "use_via"})
                ]
            circuits[0].append(
                ["use_layer", *(QuotedString(v) for v in policy.effective_trace_layers)]
            )
            cls[:] = [n for n in cls if not (isinstance(n, list) and n and n[0] == "via_rule")]
            if policy.allow_vias:
                circuits[0].append(["use_via", QuotedString(via_name)])
            else:
                circuits[0].append(
                    ["use_via", QuotedString("PCBSMITH_NoVia_" + policy.effective_trace_layers[0])]
                )
        elif restrictions:
            # An empty named rule must never become the default for other nets.
            circuits = _children(cls, "circuit")
            if not circuits:
                cls.append(["circuit", ["use_via", QuotedString(via_name)]])
            elif not any(_children(c, "use_via") for c in circuits):
                circuits[0].append(["use_via", QuotedString(via_name)])
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


def normalize_serialized_route_segments(tracks: list[TrackSegment]) -> tuple[TrackSegment, ...]:
    """Drop collapsed edges only when their serialized copper is exactly redundant.

    The native writer rounds board coordinates to micrometres. A shorter SES edge
    can therefore become a zero-length track. Its circular copper must be fully
    covered by a retained same-net/layer stadium before it can be omitted.
    """

    def point(x: float, y: float) -> tuple[float, float]:
        return (float(_mm(x + BOARD_SHEET_ORIGIN_MM)), float(_mm(y + BOARD_SHEET_ORIGIN_MM)))

    geometry = [(t, point(t.x1, t.y1), point(t.x2, t.y2)) for t in tracks]
    retained = [(t, a, b) for t, a, b in geometry if a != b]
    for track, start, end in geometry:
        if start != end:
            continue
        covered = False
        for other, a, b in retained:
            if other.net_name != track.net_name or other.layer != track.layer:
                continue
            dx, dy = b[0] - a[0], b[1] - a[1]
            fraction = max(
                0.0,
                min(1.0, ((start[0] - a[0]) * dx + (start[1] - a[1]) * dy) / (dx * dx + dy * dy)),
            )
            distance = math.hypot(start[0] - a[0] - fraction * dx, start[1] - a[1] - fraction * dy)
            if distance + float(_mm(track.width_mm)) / 2 <= float(_mm(other.width_mm)) / 2:
                covered = True
                break
        if not covered:
            raise ValueError("SES edge collapses at native precision without redundant copper")
    return tuple(t for t, _, _ in retained)


def read_single_sided_routes(
    board: Path, source: Path, layout: BoardLayout, request: RouteRequest
) -> BoardLayout:
    from pcbsmith.production_routing import native_save_readback_matches

    if len(request.allowed_layers) == 4:
        from pcbsmith.copper_layers import ordered_copper_layers
        from pcbsmith.kicad.copper_layers import saved_copper_layers

        for path in (source, board):
            if saved_copper_layers(parse_sexpr(path.read_text(encoding="utf-8"))) != (
                ordered_copper_layers(request.allowed_layers)
            ):
                raise ValueError("SES copper stack differs from the routing request")
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
    restrictions = {n: c for c in request.net_layer_constraints for n in c.net_names}

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
        if net in restrictions and layer not in restrictions[net].effective_trace_layers:
            raise ValueError(f"SES route violates per-net layer constraint: {net} on {layer}")
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
        if net in restrictions and (
            not restrictions[net].allow_vias
            or not set(request.allowed_layers).issubset(restrictions[net].allowed_layers)
        ):
            raise ValueError(f"SES via violates per-net layer/via constraint: {net}")
        at = _children(via, "at")[0]
        vias.append(ViaSpec(coordinate(at[1]), coordinate(at[2]), net, size, drill))
    return replace(layout, segments=normalize_serialized_route_segments(tracks), vias=tuple(vias))


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
        (work / "serialized-segment-normalization.json").write_text(
            json.dumps(
                {
                    "policy": "drop-only-fully-covered-native-collapsed-edges-v1",
                    "imported_board_sha256": hashlib.sha256(imported.read_bytes()).hexdigest(),
                    "imported_segments": len(
                        _children(parse_sexpr(imported.read_text(encoding="utf-8")), "segment")
                    ),
                    "retained_segments": len(result.segments),
                    "native_copper_preserved": True,
                    "native_checks_still_required": True,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
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
