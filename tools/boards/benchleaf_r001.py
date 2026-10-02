"""Reproduce the private BenchLeaf R001 design from retained engineering choices.

No release/human inspection is implied by running this script. Native reports
and failed attempts are retained under the chosen output root.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from pcbsmith.kicad.board import BoardLayout, export_kicad_netlist_xml, parse_board_netlist
from pcbsmith.kicad.export_divider_highpass_led import _label, _render_project, _symbol, _wire
from pcbsmith.kicad.identity import stable_kicad_uuid
from pcbsmith.kicad.library import QuotedString, load_footprint, parse_sexpr, serialize_sexpr
from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE, PcbRuleProfile

PROJECT = "benchleaf-3v3-r001"
PROMPT = "Ok, now lets try and make a new board.\n\nI'll let you decide on the design"
PARTS = {
    "J1": dict(
        symbol="Connector_Generic:Conn_01x02",
        value="5V INPUT",
        mpn="2.54mm 1x02 straight male header",
        footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
        pins={"1": "+5V_IN", "2": "GND"},
        position=(4, 13, 0),
        role="input-connector",
    ),
    "D1": dict(
        symbol="Device:D_Schottky",
        value="1N5817",
        mpn="1N5817-E3/54",
        footprint="Diode_THT:D_DO-41_SOD81_P12.70mm_Horizontal",
        pins={"1": "VIN_PROTECTED", "2": "+5V_IN"},
        position=(23, 8, 180),
        role="reverse-polarity",
    ),
    "C1": dict(
        symbol="Device:C",
        value="2.2uF 63V FILM",
        mpn="MKS2C042201K00KSSD",
        footprint="Capacitor_THT:C_Rect_L7.2mm_W7.2mm_P5.00mm_FKS2_FKP2_MKS2_MKP2",
        pins={"1": "VIN_PROTECTED", "2": "GND"},
        position=(23, 17, 180),
        role="input-capacitor",
    ),
    "U1": dict(
        symbol="Regulator_Linear:MCP1700x-330xxTO",
        value="MCP1700-3302E/TO",
        mpn="MCP1700-3302E/TO",
        footprint="Package_TO_SOT_THT:TO-92_Inline_Wide",
        pins={"1": "GND", "2": "VIN_PROTECTED", "3": "+3V3"},
        position=(23, 24.5, 0),
        role="linear-regulator",
    ),
    "C2": dict(
        symbol="Device:C",
        value="2.2uF 63V FILM",
        mpn="MKS2C042201K00KSSD",
        footprint="Capacitor_THT:C_Rect_L7.2mm_W7.2mm_P5.00mm_FKS2_FKP2_MKS2_MKP2",
        pins={"1": "+3V3", "2": "GND"},
        position=(28.08, 17, 0),
        role="output-capacitor",
    ),
    "J2": dict(
        symbol="Connector_Generic:Conn_01x02",
        value="3V3 OUT A",
        mpn="2.54mm 1x02 straight male header",
        footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
        pins={"1": "+3V3", "2": "GND"},
        position=(46, 13, 0),
        role="output-connector",
    ),
    "J3": dict(
        symbol="Connector_Generic:Conn_01x02",
        value="3V3 OUT B",
        mpn="2.54mm 1x02 straight male header",
        footprint="Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical",
        pins={"1": "+3V3", "2": "GND"},
        position=(46, 23, 0),
        role="output-connector",
    ),
    "R1": dict(
        symbol="Device:R",
        value="1k 1%",
        mpn="MRS25000C1001FCT00",
        footprint="Resistor_THT:R_Axial_DIN0207_L6.3mm_D2.5mm_P10.16mm_Horizontal",
        pins={"1": "LED_A", "2": "+3V3"},
        position=(35, 29, 0),
        role="led-resistor",
    ),
    "D2": dict(
        symbol="Device:LED",
        value="RED 3mm",
        mpn="WP710A10LID",
        footprint="LED_THT:LED_D3.0mm",
        pins={"1": "GND", "2": "LED_A"},
        position=(30, 34, 0),
        role="power-indicator",
    ),
}
for i, xy in enumerate(((4, 4), (46, 4), (4, 36), (46, 36)), 1):
    PARTS[f"H{i}"] = dict(
        symbol="Mechanical:MountingHole",
        value="M3 mounting",
        mpn="Unpopulated 3.2mm hole",
        footprint="MountingHole:MountingHole_3.2mm_M3",
        pins={},
        position=(*xy, 0),
        role="mounting-hole",
        populated=False,
    )
SYMLIB = Path("C:/Program Files/KiCad/10.0/share/kicad/symbols")


def write(path: Path, payload: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload.encode("utf-8"))


def dump(path: Path, obj):
    write(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def atom(n):
    return n.value if isinstance(n, QuotedString) else str(n)


def children(n, head):
    return [v for v in n[1:] if isinstance(v, list) and v and v[0] == head]


def child(n, head):
    return next(v for v in n[1:] if isinstance(v, list) and v and v[0] == head)


def official_symbol(symbol_id):
    lib, name = symbol_id.split(":")
    library = parse_sexpr((SYMLIB / (lib + ".kicad_sym")).read_text(encoding="utf-8"))
    lookup = {atom(n[1]): n for n in children(library, "symbol")}

    def resolve(key):
        n = copy.deepcopy(lookup[key])
        inherit = children(n, "extends")
        if not inherit:
            return n
        parent_name = atom(inherit[0][1])
        base = resolve(parent_name)
        overrides = {atom(p[1]): p for p in children(n, "property")}
        base = [
            p
            for p in base
            if not (isinstance(p, list) and p and p[0] == "property" and atom(p[1]) in overrides)
        ]
        base.extend(overrides.values())
        for s in children(base, "symbol"):
            s[1] = QuotedString(atom(s[1]).replace(parent_name + "_", key + "_", 1))
        base[1] = QuotedString(key)
        return base

    node = resolve(name)
    for s in children(node, "symbol"):
        s[1] = QuotedString(atom(s[1]).replace(name + "_", name.replace("-", "_") + "_", 1))
    node[1] = QuotedString(name.replace("-", "_"))
    return node


def profile():
    geo = DEFAULT_PCB_RULE_PROFILE.geometry.model_copy(
        update=dict(
            profile_id=PROJECT + "-home-target",
            basis="project_requirement",
            minimum_trace_width_mm=0.6,
            default_signal_trace_width_mm=0.6,
            default_power_trace_width_mm=0.8,
            routing_via_diameter_mm=1.8,
            routing_via_drill_mm=1.0,
            power_via_diameter_mm=1.8,
            power_via_drill_mm=1.0,
            minimum_finished_hole_mm=0.8,
            minimum_annular_ring_mm=0.3,
            solder_mask_process="none",
            minimum_solder_mask_web_mm=None,
            silkscreen_process="none",
            plated_through_vias_available=False,
            via_process="none",
            assembly_process="hand_soldering",
            trace_thermal_model_id="not_declared",
        )
    )
    spacing = DEFAULT_PCB_RULE_PROFILE.fab_spacing.model_copy(
        update=dict(
            profile_id=PROJECT + "-spacing",
            basis="project_requirement",
            minimum_copper_clearance_mm=0.4,
            minimum_copper_to_edge_mm=1.0,
            minimum_hole_to_copper_mm=0.3,
        )
    )
    p = DEFAULT_PCB_RULE_PROFILE.model_copy(update=dict(geometry=geo, fab_spacing=spacing))
    return PcbRuleProfile.model_validate(p.model_dump())


def prepare(root):
    inp = root / "input"
    eng = root / "engineering"
    inp.mkdir(parents=True, exist_ok=True)
    eng.mkdir(parents=True, exist_ok=True)
    symbols = {
        s: official_symbol(s)
        for s in sorted({p["symbol"] for p in PARTS.values()} | {"power:PWR_FLAG"})
    }
    write(
        inp / "BenchLeaf.kicad_sym",
        '(kicad_symbol_lib (version 20250114) (generator "pcbsmith")\n'
        + "\n".join(serialize_sexpr(s) for s in symbols.values())
        + "\n)\n",
    )
    write(
        inp / "sym-lib-table",
        '(sym_lib_table (version 7) (lib (name "BenchLeaf") (type "KiCad") '
        '(uri "${KIPRJMOD}/BenchLeaf.kicad_sym") (options "")'
        ' (descr "Flattened official KiCad 10 symbols; '
        'see engineering/library-sources.json")))\n',
    )
    # Embedded and local footprint files remain the exact installed KiCad definitions.
    libs = {p["footprint"].split(":")[0] for p in PARTS.values()}
    lib_records = []
    for fid in sorted({p["footprint"] for p in PARTS.values()}):
        f = load_footprint(fid)
        src = Path(f.source_file)
        lib, name = fid.split(":")
        dest = inp / (lib + ".pretty") / (name + ".kicad_mod")
        dest.parent.mkdir(exist_ok=True)
        dest.write_bytes(src.read_bytes())
        lib_records.append(
            dict(
                id=fid,
                source=str(src),
                sha256=hashlib.sha256(src.read_bytes()).hexdigest(),
                pads=[
                    dict(number=x.name, x=x.x_mm, y=x.y_mm, drill=x.drill_mm) for x in f.spec.pads
                ],
            )
        )
    write(
        inp / "fp-lib-table",
        "(fp_lib_table (version 7)\n"
        + "\n".join(
            f'(lib (name "{lib}") (type "KiCad") (uri "${{KIPRJMOD}}/{lib}.pretty") '
            '(options "") (descr "Retained official KiCad footprint"))'
            for lib in sorted(libs)
        )
        + "\n)\n",
    )
    dump(eng / "library-sources.json", lib_records)
    p = profile()
    dump(eng / "rule-profile.json", p.model_dump(mode="json"))
    project = json.loads(_render_project(profile=p, min_through_hole_mm=0.8))
    project["board"]["design_settings"]["rule_severities"] = {
        key: "warning"
        for key in (
            "lib_footprint_mismatch",
            "missing_courtyard",
            "track_not_centered_on_via",
            "tuning_profile_track_geometries",
            "footprint_filters_mismatch",
            "footprint_type_mismatch",
        )
    }
    dump(inp / (PROJECT + ".kicad_pro"), project)
    dump(
        eng / "design-spec.json",
        dict(
            project=PROJECT,
            prompt=PROMPT,
            width_mm=50,
            height_mm=40,
            authorization=(
                "User delegated selection of this new board to the assistant. No "
                "human inspection or fabrication approval has occurred."
            ),
            parts=PARTS,
            operating_contract=dict(
                input_v=[4.75, 5.25],
                external_output_current_max_a=0.05,
                source_current_limit_a=0.1,
                ambient_c=[15, 35],
                source_lead_max_m=0.3,
                prohibition=[
                    "No mains input",
                    "No direct USB host connection",
                    "Do not externally drive outputs",
                    "Not a precision 50 mA current limiter",
                ],
            ),
            manufacturing=(
                "Two copper layers, bottom-only electrical interconnect, no vias, "
                "no solder mask assumed. Geometry is a design target pending "
                "process coupon."
            ),
        ),
    )
    schematic(root, symbols)


def schematic(root, symbols):
    inp = root / "input"
    embedded = []
    for symbol in symbols.values():
        n = copy.deepcopy(symbol)
        n[1] = QuotedString("BenchLeaf:" + atom(n[1]))
        embedded.append(serialize_sexpr(n))
    symbols_at = {
        "J1": (35.56, 60.96, 0),
        "D1": (60.96, 60.96, 180),
        "U1": (101.6, 60.96, 0),
        "C1": (78.74, 73.66, 0),
        "C2": (127, 73.66, 0),
        "R1": (146.05, 73.66, 180),
        "D2": (146.05, 86.36, 90),
        "J2": (185.42, 63.5, 0),
        "J3": (185.42, 88.9, 0),
        "H1": (213.36, 63.5, 0),
        "H2": (228.6, 63.5, 0),
        "H3": (213.36, 88.9, 0),
        "H4": (228.6, 88.9, 0),
    }
    items = []
    for ref, p in PARTS.items():
        x, y, r = symbols_at[ref]
        lib = "BenchLeaf:" + p["symbol"].split(":")[1].replace("-", "_")
        reference_at = (x, y - 5.08)
        value_at = (x, y + 5.08)
        if ref.startswith(("C", "R")):
            reference_at = (x + 5.08, y - 1.27)
            value_at = (x + 8.89, y + 2.54)
        if ref == "U1":
            reference_at = (x - 2.54, y + 7.62)
            value_at = (x, y + 11.43)
        if ref == "D2":
            reference_at = (x + 5.08, y)
            value_at = (x + 10.16, y + 3.81)
        rendered = _symbol(
            lib,
            ref,
            p["value"],
            x,
            y,
            PROJECT,
            rotation=r,
            footprint=p["footprint"],
            pin_numbers=tuple(p["pins"]) or ("1",),
            in_bom=p.get("populated", True),
            reference_at=reference_at,
            value_at=value_at,
            extra_properties=(("MPN", p["mpn"]), ("Design_role", p["role"])),
        )
        if not p["pins"]:
            tree = parse_sexpr(rendered)
            tree = [n for n in tree if not (isinstance(n, list) and n and n[0] == "pin")]
            rendered = serialize_sexpr(tree)
        items.append(rendered)
    # Rail junctions are explicitly segmented; all nets have labels.
    wire_paths = [
        [(50.8, 60.96), (57.15, 60.96)],
        [(64.77, 60.96), (78.74, 60.96), (88.9, 60.96), (93.98, 60.96)],
        [(78.74, 60.96), (78.74, 69.85)],
        [(109.22, 60.96), (127, 60.96), (146.05, 60.96), (146.05, 69.85)],
        [(127, 60.96), (127, 69.85)],
        [
            (78.74, 77.47),
            (78.74, 100.33),
            (88.9, 100.33),
            (127, 100.33),
            (146.05, 100.33),
            (146.05, 90.17),
        ],
        [(127, 77.47), (127, 100.33)],
        [(146.05, 77.47), (146.05, 82.55)],
        [(101.6, 53.34), (101.6, 48.26)],
        [(30.48, 60.96), (22.86, 60.96)],
        [(30.48, 63.5), (22.86, 63.5)],
        [(180.34, 63.5), (172.72, 63.5)],
        [(180.34, 66.04), (172.72, 66.04)],
        [(180.34, 88.9), (172.72, 88.9)],
        [(180.34, 91.44), (172.72, 91.44)],
    ]
    for path in wire_paths:
        for a, b in zip(path, path[1:], strict=False):
            items.append(_wire(a, b))
    for net, x, y in [
        ("+5V_IN", 50.8, 60.96),
        ("VIN_PROTECTED", 78.74, 60.96),
        ("+3V3", 127, 60.96),
        ("LED_A", 146.05, 80.01),
        ("GND", 101.6, 48.26),
        ("GND", 78.74, 100.33),
        ("+5V_IN", 22.86, 60.96),
        ("GND", 22.86, 63.5),
        ("+3V3", 172.72, 63.5),
        ("GND", 172.72, 66.04),
        ("+3V3", 172.72, 88.9),
        ("GND", 172.72, 91.44),
    ]:
        items.append(_label(net, x, y))
    for i, xy in enumerate(
        [(78.74, 60.96), (88.9, 60.96), (127, 60.96), (88.9, 100.33), (127, 100.33)]
    ):
        items.append(
            f"(junction (at {xy[0]} {xy[1]}) (diameter 0) (color 0 0 0 0) "
            f'(uuid "{stable_kicad_uuid(PROJECT, "junction", str(i))}"))'
        )
    for i, xy in enumerate([(88.9, 60.96), (88.9, 100.33)], 1):
        items.append(
            _symbol(
                "BenchLeaf:PWR_FLAG",
                f"#FLG0{i}",
                "PWR_FLAG",
                *xy,
                PROJECT,
                in_bom=False,
                on_board=False,
                pin_count=1,
            )
        )
    texts = [
        (20.32, 20.32, 2.54, "BENCHLEAF / 3V3"),
        (20.32, 26.67, 1.52, "A small, hand-assembled sensor power supply - R001"),
        (20.32, 39.37, 1.27, "01   INPUT"),
        (55.88, 39.37, 1.27, "02   POLARITY + REGULATION"),
        (170.18, 39.37, 1.27, "03   OUTPUTS"),
        (208.28, 39.37, 1.27, "MECHANICAL"),
        (
            20.32,
            120.65,
            1.27,
            (
                "INPUT: regulated 4.75-5.25 V DC, current-limited bench source at "
                "100 mA; short leads (<0.3 m)."
            ),
        ),
        (
            20.32,
            127,
            1.27,
            (
                "OUTPUT: nominal 3.3 V; 50 mA external load TOTAL across J2 + J3. "
                "Never externally drive these outputs."
            ),
        ),
        (
            20.32,
            133.35,
            1.27,
            (
                "C1/C2: 2.2 uF +/-10% PET film, 63 V, 5 mm pitch. Verify regulator"
                " stability on the assembled board."
            ),
        ),
        (
            20.32,
            139.7,
            1.27,
            (
                "U1 TO-92, flat face: pin 1 GND / pin 2 VIN / pin 3 VOUT. Form "
                "leads to 2.54 mm pitch before fitting."
            ),
        ),
        (
            20.32,
            146.05,
            1.27,
            (
                "D1 band = cathode toward U1. D2 square pad = cathode. LED "
                "indicates voltage presence, not regulation accuracy."
            ),
        ),
        (
            20.32,
            152.4,
            1.27,
            (
                "All wiring on B.Cu. No vias; solder all component leads from "
                "below. 50 x 40 mm, 1.6 mm FR-4."
            ),
        ),
        (
            20.32,
            158.75,
            1.27,
            (
                "Bench prototype candidate. Electrical, thermal, stability and "
                "home-fabrication qualification are still required."
            ),
        ),
    ]
    for i, (x, y, size, text) in enumerate(texts):
        items.append(
            f"(text {json.dumps(text)} (at {x} {y} 0) "
            f"(effects (font (size {size} {size})) (justify left)) "
            f'(uuid "{stable_kicad_uuid(PROJECT, "note", str(i))}"))'
        )
    sch = (
        '(kicad_sch (version 20250114) (generator "pcbsmith") (uuid "'
        + stable_kicad_uuid(PROJECT, "root")
        + '") (paper "A4")\n(lib_symbols\n'
        + "\n".join(embedded)
        + ")\n"
        + "\n".join(items)
        + '\n(sheet_instances (path "/" (page "1"))))\n'
    )
    write(inp / (PROJECT + ".kicad_sch"), sch)
    export_kicad_netlist_xml(inp / (PROJECT + ".kicad_sch"))


def predesign(root):
    from pcbsmith.design_readiness import (
        ComponentCandidate,
        ComponentUseIntent,
        DesignReadinessStage,
        PowerConversionContract,
        PowerRailLoad,
        PowerSourceContract,
        SourceCurrentAuthority,
        SupportObservation,
        SupportRequirement,
        SupportRequirementKind,
        evaluate_design_readiness,
        review_component_alternatives,
        review_power_path,
        review_support_circuits,
    )
    from pcbsmith.kicad.concept_review import (
        ConceptItem,
        examine_concept,
        write_concept_review_package,
    )
    from pcbsmith.manufacturing_lineage import file_sha256
    from pcbsmith.predesign_contract import (
        BriefAmendmentSetV2,
        ComponentGeometryBindingV2,
        ConceptOverlayManifestV2,
        ElectricalDemandInventoryRecordV2,
        PredesignApprovalContractV2,
        PreRouteFeasibilityInputsV2,
        SourceDemandCoverageRecordV2,
        SourceDemandCoverageV2,
        artifact_sha256,
    )
    from pcbsmith.production_readiness import (
        PredesignReadinessBundle,
        ReadinessEvidenceFile,
        require_predesign_bundle,
    )
    from pcbsmith.project_brief import (
        AssetReference,
        ComponentRequirement,
        MechanicalRequirement,
        PlacementRequirement,
        ProjectBriefDraft,
        RequirementValue,
        normalize_project_brief,
    )
    from pcbsmith.prompt_examiner import ExaminedClaim, PromptResolution, SourceSpan, examine_prompt
    from pcbsmith.workflow_feasibility import NeckSection, PlacementEnvelope, PreRouteNetDemand

    eng = root / "engineering"
    prepare(root)
    netlist = parse_board_netlist(
        (root / "input/.pcbsmith/kicad" / (PROJECT + ".net.xml")).read_text(encoding="utf-8")
    )
    expected = {
        ("/" + net): sorted(
            (ref, pin) for ref, p in PARTS.items() for pin, n in p["pins"].items() if n == net
        )
        for net in {n for p in PARTS.values() for n in p["pins"].values()}
    }
    observed = {n.name: sorted(n.nodes) for n in netlist.nets}
    assert expected == observed, (expected, observed)
    dump(
        root / "checks/netlist-vs-design.json",
        dict(
            status="passed",
            expected=expected,
            observed=observed,
            method=(
                "Native KiCad XML compared with independently declared "
                "per-component pin intent; not an assembled-board test"
            ),
        ),
    )

    def val(key, value, unit=None):
        return RequirementValue(
            requirement_id=key,
            value=value,
            unit=unit,
            source="engineering",
            resolution="derived",
            source_text=PROMPT,
            rationale=(
                "Engineering choice under the user's explicit delegation; see "
                "design-spec.json and engineering-review.md."
            ),
        )

    outline = ((0.0, 0.0), (50.0, 0.0), (50.0, 40.0), (0.0, 40.0))
    write(
        eng / "outline.svg",
        (
            '<svg xmlns="http://www.w3.org/2000/svg" width="50mm" '
            'height="40mm" viewBox="0 0 50 40"><rect x="0" y="0" width="50" '
            'height="40" fill="none" stroke="black" stroke-width="0.1"/></svg>'
        ),
    )
    brief = normalize_project_brief(
        ProjectBriefDraft(
            project_id=PROJECT,
            title="BenchLeaf 3V3 sensor power",
            original_text=PROMPT,
            functional_requirements=(
                val("function.supply", "Regulated 3.3 V sensor power from regulated 5 V input"),
            ),
            electrical_requirements=(
                val("electrical.input-min", 4.75, "V"),
                val("electrical.input-max", 5.25, "V"),
                val("electrical.output", 3.3, "V"),
                val("electrical.external-current", 0.05, "A"),
            ),
            manufacturing_requirements=(
                val(
                    "manufacturing.bottom-routing",
                    "All electrical interconnect on B.Cu; no vias; 0.4 mm clearance target",
                ),
            ),
            mechanics=MechanicalRequirement(
                maximum_width_mm=val("mechanics.width", 50, "mm"),
                maximum_height_mm=val("mechanics.height", 40, "mm"),
                board_thickness_mm=val("mechanics.thickness", 1.6, "mm"),
                layer_count=val("manufacturing.layers", 2),
                outline_asset_id="outline",
                mounting_hole_diameter_mm=val("mechanics.mount-hole", 3.2, "mm"),
                mounting_hole_centers_mm=((4, 4), (46, 4), (4, 36), (46, 36)),
            ),
            components=tuple(
                ComponentRequirement(
                    component_id=ref,
                    quantity=1,
                    role=p["role"],
                    selection=p["mpn"],
                    footprint_id=p["footprint"],
                    side="front",
                    mounting="tht",
                    source="engineering",
                    resolution="derived",
                )
                for ref, p in PARTS.items()
            ),
            placements=tuple(
                PlacementRequirement(
                    placement_id="placement." + ref.lower(),
                    subject=ref,
                    relation=(
                        f"Reviewed anchor x={p['position'][0]} y={p['position'][1]} mm, "
                        f"rotation={p['position'][2]} degrees"
                    ),
                    side="front",
                    anchor_semantics="footprint pad-1 origin",
                    tolerance_mm=0.01,
                    resolution="derived",
                    source_text="Engineering selection: design-spec.json",
                )
                for ref, p in PARTS.items()
            ),
            artwork=(),
            assets=(
                AssetReference(
                    asset_id="outline",
                    purpose="outline",
                    source_file="outline.svg",
                    source_sha256=file_sha256(eng / "outline.svg"),
                    physical_width_mm=50,
                ),
            ),
            engineering_freedoms=(
                (
                    "User delegated circuit selection, geometry, layout, and "
                    "implementation for this new board."
                ),
            ),
        )
    )
    assert brief.outcome == "ready_for_concept", brief
    span = SourceSpan(span_id="request.delegation", start=0, end=len(PROMPT), exact_text=PROMPT)
    prompt = examine_prompt(
        project_id=PROJECT,
        original_text=PROMPT,
        spans=(span,),
        claims=(
            ExaminedClaim(
                claim_id="claim.delegated-design",
                field_path="engineering_freedoms",
                value="Choose and make a new board",
                resolution=PromptResolution.DERIVED,
                source_span_ids=(span.span_id,),
                rationale=(
                    "The user explicitly delegated the design; technical requirements "
                    "are engineering choices, not user-specified numerical limits."
                ),
            ),
        ),
        anchors=(),
    )
    concept = examine_concept(
        PROJECT,
        outline,
        tuple(
            ConceptItem(
                item_id=ref,
                label=ref + " " + p["value"],
                side="front",
                kind="footprint",
                anchor_mm=p["position"][:2],
                rotation_deg=p["position"][2],
                footprint_id=p["footprint"],
                containment="courtyard",
                requirement_resolution="derived",
                note=(
                    "Selected by authorized assistant delegate; no claim of human "
                    "visual inspection."
                ),
            )
            for ref, p in PARTS.items()
        ),
        tight_clearance_mm=0.5,
    )
    write_concept_review_package(concept, eng)
    assert concept.outcome == "ready_for_approval", concept
    ph, bh, ch = artifact_sha256(prompt), artifact_sha256(brief), artifact_sha256(concept)
    envelopes = tuple(
        PlacementEnvelope(
            envelope_id="env." + i.item.item_id,
            subject_id=i.item.item_id,
            polygon=i.envelope,
            source_geometry_sha256=ch,
        )
        for i in concept.items
    )
    # A declared coarse capacity screen, not proof that any particular route exists.
    neck = NeckSection(
        neck_id="transit-right",
        usable_width_mm=18,
        routing_layers=("B.Cu",),
        capacity_quantum_mm=0.2,
        source_geometry_sha256=concept.outline_sha256,
    )
    demands = tuple(
        PreRouteNetDemand(
            net_name=n.name,
            terminal_ids=tuple(ref + "/" + pin for ref, pin in n.nodes),
            trace_width_mm=0.8,
            clearance_mm=0.4,
            candidate_neck_ids=(neck.neck_id,),
            net_class_id="low-voltage",
            priority=i + 1,
        )
        for i, n in enumerate(netlist.nets)
    )
    inputs = PreRouteFeasibilityInputsV2.build(
        project_id=PROJECT,
        prompt_examination_sha256=ph,
        amended_brief_sha256=bh,
        board_outline=outline,
        board_outline_sha256=concept.outline_sha256,
        keepout_polygons=(),
        envelopes=envelopes,
        necks=(neck,),
        net_demands=demands,
    )
    feasible = inputs.evaluate()
    ih, fh = artifact_sha256(inputs), artifact_sha256(feasible)
    amendment = BriefAmendmentSetV2.build(
        project_id=PROJECT,
        prompt_examination_sha256=ph,
        board_outline_sha256=concept.outline_sha256,
        original_brief_sha256=bh,
        amended_brief_sha256=bh,
        patches=(),
    )
    reqids = tuple(
        v.requirement_id
        for v in (
            *brief.draft.functional_requirements,
            *brief.draft.electrical_requirements,
            *brief.draft.manufacturing_requirements,
            brief.draft.mechanics.maximum_width_mm,
            brief.draft.mechanics.maximum_height_mm,
            brief.draft.mechanics.board_thickness_mm,
            brief.draft.mechanics.layer_count,
            brief.draft.mechanics.mounting_hole_diameter_mm,
        )
    )
    record = SourceDemandCoverageRecordV2.build(
        demand_id="design.delegated-selection",
        source_span_ids=(span.span_id,),
        claim_ids=("claim.delegated-design",),
        anchor_ids=(),
        requirement_ids=reqids,
        component_ids=tuple(PARTS),
        placement_ids=tuple(p.placement_id for p in brief.draft.placements),
        asset_ids=("outline",),
        concept_item_ids=tuple(PARTS),
        feasibility_envelope_ids=tuple(e.envelope_id for e in envelopes),
        feasibility_net_names=tuple(n.net_name for n in demands),
    )
    coverage = SourceDemandCoverageV2.build(
        project_id=PROJECT,
        prompt_examination_sha256=ph,
        amended_brief_sha256=bh,
        board_outline_sha256=concept.outline_sha256,
        concept_review_sha256=ch,
        pre_route_inputs_sha256=ih,
        pre_route_feasibility_sha256=fh,
        component_geometry_bindings=tuple(
            ComponentGeometryBindingV2(
                component_id=ref, concept_item_ids=(ref,), feasibility_envelope_ids=("env." + ref,)
            )
            for ref in PARTS
        ),
        electrical_demand_inventory=tuple(
            ElectricalDemandInventoryRecordV2(
                net_name=n.net_name,
                terminal_ids=n.terminal_ids,
                source_claim_ids=("claim.delegated-design",),
                source_requirement_ids=("function.supply",),
            )
            for n in demands
        ),
        records=(record,),
    )
    overlays = tuple(
        ConceptOverlayManifestV2.build(
            project_id=PROJECT,
            prompt_examination_sha256=ph,
            board_outline_sha256=concept.outline_sha256,
            concept_review_sha256=ch,
            side=side,
            svg_path=f"engineering-overlay-{side}.svg",
            svg_sha256=file_sha256(eng / f"engineering-overlay-{side}.svg"),
            svg_bytes=(eng / f"engineering-overlay-{side}.svg").stat().st_size,
            png_path=f"engineering-overlay-{side}.png",
            png_sha256=file_sha256(eng / f"engineering-overlay-{side}.png"),
            png_bytes=(eng / f"engineering-overlay-{side}.png").stat().st_size,
        )
        for side in ("front", "back")
    )
    contract = PredesignApprovalContractV2.build(
        project_id=PROJECT,
        prompt_examination=prompt,
        original_brief=brief,
        amended_brief=brief,
        amendment_set=amendment,
        decisions=(),
        concept_review=concept,
        concept_tight_clearance_mm=0.5,
        overlay_manifests=overlays,
        pre_route_inputs=inputs,
        pre_route_feasibility=feasible,
        source_demand_coverage=coverage,
        asserted_approver_id="assistant-delegate-current-task",
        asserted_approver_role="authorized_delegate",
        recorded_at=datetime.now(UTC),
        capture_method="interactive_assertion",
    )
    # Alternatives retain actual roles; inapplicable alternatives are not selected.
    comparisons = []
    for ref, p in PARTS.items():
        if not p.get("populated", True):
            continue
        fp = load_footprint(p["footprint"]).spec
        w = fp.fab_rect[2] - fp.fab_rect[0]
        h = fp.fab_rect[3] - fp.fab_rect[1]
        capability = {
            "U1": "3v3-linear-regulation",
            "D1": "low-drop-polarity-block",
            "C1": "2u2-nonpolar-low-esr",
            "C2": "2u2-nonpolar-low-esr",
            "D2": "red-low-current-indication",
            "R1": "nominal-led-current-at-least-1p5ma",
        }.get(ref, "two-pin-power-connection")
        intent = ComponentUseIntent(
            intent_id="intent." + ref,
            role_id=p["role"],
            required_capabilities=(capability,),
            preferred_mounting="through_hole",
            hand_assembly_required=True,
            evidence_ids=("engineering", "libraries"),
        )
        candidate = ComponentCandidate(
            candidate_id=ref + ".selected",
            manufacturer_part_number=p["mpn"],
            capabilities=(capability,),
            mounting="through_hole",
            body_width_mm=w,
            body_height_mm=h,
            pin_count=len(p["pins"]),
            maximum_unit_current_a=0.0036 if ref == "D2" else 0.055,
            hand_assembly_suitable=True,
            model_classification="proxy" if ref in ("C1", "C2", "R1") else "exact_package",
            evidence_ids=("engineering", "libraries"),
            support_requirement_ids=(
                ("support.cin", "support.cout")
                if ref == "U1"
                else ("support.led-r",)
                if ref == "D2"
                else ()
            ),
        )
        if ref == "U1":
            alt = candidate.model_copy(
                update=dict(
                    candidate_id=ref + ".sot23",
                    manufacturer_part_number="MCP1700-3302E/TT",
                    mounting="smd",
                    body_width_mm=3.0,
                    body_height_mm=1.4,
                )
            )
        elif ref in ("C1", "C2"):
            alt = candidate.model_copy(
                update=dict(
                    candidate_id=ref + ".100v",
                    manufacturer_part_number="MKS2D042201N00KSSD",
                    body_width_mm=7.2,
                    body_height_mm=11.0,
                )
            )
        elif ref == "D1":
            # Same package but larger drop. The selected bound is 0.45 V at 1 A/25 C.
            alt = candidate.model_copy(
                update=dict(
                    candidate_id=ref + ".1n5819",
                    manufacturer_part_number="1N5819-E3/54",
                    capabilities=("higher-drop-polarity-block",),
                )
            )
        elif ref == "R1":
            alt = candidate.model_copy(
                update=dict(
                    candidate_id=ref + ".1k5",
                    manufacturer_part_number="MRS25000C1501FCT00",
                    capabilities=("nominal-led-current-1p07ma",),
                )
            )
        elif ref == "D2":
            alt = candidate.model_copy(
                update=dict(
                    candidate_id=ref + ".ordinary-led",
                    manufacturer_part_number="Unspecified ordinary red LED at 20mA",
                    capabilities=("red-indication-without-low-current-guarantee",),
                    model_classification="unknown",
                )
            )
        else:
            alt = candidate.model_copy(
                update=dict(
                    candidate_id=ref + ".screw-terminal",
                    manufacturer_part_number="Generic 2-pole 5.08mm screw terminal",
                    body_width_mm=10.16,
                    body_height_mm=9.0,
                    model_classification="unknown",
                )
            )
        comparisons.append(
            review_component_alternatives(
                intent=intent,
                candidates=(candidate, alt),
                selected_candidate_id=candidate.candidate_id,
            )
        )
    requirements = tuple(
        SupportRequirement(
            requirement_id=i,
            subject_reference=ref,
            kind=kind,
            minimum_value=minimum,
            maximum_value=maximum,
            units=units,
            source_ids=sources,
            rationale=rationale,
        )
        for i, ref, kind, minimum, maximum, units, sources, rationale in [
            (
                "support.cin",
                "U1",
                SupportRequirementKind.LOCAL_DECOUPLING,
                1.0,
                None,
                "uF",
                ("regulator", "capacitor", "engineering"),
                (
                    "C1 supplies local input charge; 2.2uF minus 10% tolerance = "
                    "1.98uF. Stability remains a bench qualification."
                ),
            ),
            (
                "support.cout",
                "U1",
                SupportRequirementKind.LOCAL_DECOUPLING,
                1.0,
                None,
                "uF",
                ("regulator", "capacitor", "engineering"),
                (
                    "C2 exceeds the minimum nominal capacitance. Film ESR at 1kHz is "
                    "derived below 2 ohm; full loop stability is not asserted."
                ),
            ),
            (
                "support.led-r",
                "D2",
                SupportRequirementKind.CURRENT_LIMITING,
                990.0,
                1010.0,
                "ohm",
                ("led", "resistor", "engineering"),
                "R1 sets typical LED current to 1.6mA; shorted LED current is also bounded by R1.",
            ),
        ]
    )
    observations = tuple(
        SupportObservation(
            requirement_id=r.requirement_id,
            disposition="verified",
            supporting_references=(part,),
            observed_value=value,
            evidence_ids=r.source_ids,
            rationale=(
                "Verified component-value design calculation, not a physical "
                "measurement or closed-loop stability test."
            ),
        )
        for r, part, value in zip(
            requirements, ("C1", "C2", "R1"), (1.98, 1.98, 1000.0), strict=True
        )
    )
    power = review_power_path(
        source=PowerSourceContract(
            source_id="specified-bench-source",
            rail_id="+5V_IN",
            voltage_v=5.25,
            available_continuous_current_a=0.1,
            available_peak_current_a=0.1,
            current_authority=SourceCurrentAuthority.DEDICATED_SUPPLY,
            current_detection_verified=False,
            direct_input_capacitance_uf=2.42,
            evidence_ids=("engineering",),
        ),
        loads=(
            PowerRailLoad(
                load_id="external-load-total",
                rail_id="+3V3",
                continuous_current_a=0.05,
                peak_current_a=0.05,
                evidence_ids=("engineering",),
            ),
            PowerRailLoad(
                load_id="led-worst-case-short",
                rail_id="+3V3",
                continuous_current_a=0.0036,
                peak_current_a=0.0036,
                evidence_ids=("engineering",),
            ),
            PowerRailLoad(
                load_id="ground-current-budget",
                rail_id="+5V_IN",
                continuous_current_a=0.0001,
                peak_current_a=0.0001,
                evidence_ids=("engineering",),
            ),
        ),
        conversions=(
            PowerConversionContract(
                conversion_id="D1-plus-U1",
                input_rail_id="+5V_IN",
                output_rail_id="+3V3",
                input_voltage_v=5.25,
                output_voltage_v=3.3,
                kind="linear",
                efficiency=3.3 / 5.25,
                maximum_output_current_a=0.25,
                thermal_verification_required=False,
                evidence_ids=("regulator", "engineering"),
            ),
        ),
    )
    readiness = evaluate_design_readiness(
        stage=DesignReadinessStage.PREDESIGN,
        component_reviews=tuple(comparisons),
        support_review=review_support_circuits(
            requirements=requirements, observations=observations
        ),
        power_review=power,
    )
    sources = {
        "engineering": "engineering-review.md",
        "libraries": "library-sources.json",
        "regulator": "mcp1700.pdf",
        "capacitor": "wima-mks2.pdf",
        "led": "led.pdf",
        "resistor": "mrs25.pdf",
        "diode": "1n5817.pdf",
    }
    bundle = PredesignReadinessBundle(
        approval=contract,
        readiness=readiness,
        evidence_files={
            k: ReadinessEvidenceFile(relative_path=v, sha256=file_sha256(eng / v))
            for k, v in sources.items()
        },
    )
    require_predesign_bundle(bundle, eng)
    write(eng / "predesign.json", bundle.model_dump_json(indent=2) + "\n")
    print("PREDESIGN", readiness.disposition)
    return bundle, netlist


def placement(root):
    from pcbsmith.production_generators import generate_registered_board_candidate

    bundle, netlist = predesign(root)
    from pcbsmith.kicad.board import FOOTPRINT_LIBRARY

    for part in PARTS.values():
        fid = part["footprint"]
        if fid not in FOOTPRINT_LIBRARY:
            FOOTPRINT_LIBRARY[fid] = load_footprint(fid).spec
    layout = BoardLayout(
        placements=tuple((c, PARTS[c.reference]["position"][0]) for c in netlist.components),
        segments=(),
        vias=(),
        width_mm=50,
        height_mm=40,
        part_y_mm=tuple((ref, p["position"][1]) for ref, p in PARTS.items()),
        part_rotation=tuple((ref, p["position"][2]) for ref, p in PARTS.items()),
    )
    attempt = (
        root
        / "attempts"
        / f"placement-{len(list((root / 'attempts').glob('placement-*'))) + 1:02d}"
    )
    board = generate_registered_board_candidate(
        generator_id="pcbsmith.kicad.board:generate_board",
        schematic_file=root / "input" / (PROJECT + ".kicad_sch"),
        output_directory=attempt,
        predesign=bundle,
        artifact_root=root / "engineering",
        builder_options=dict(layout=layout, profile=profile()),
    )
    print("BOARD", board)
    return board


def routed(root):
    """Construct the declared copper plan; this is manual routing, not an AI/router proof."""
    import shutil

    from pcbsmith.kicad.board import TrackSegment, render_board_from_layout
    from pcbsmith.manufacturing_lineage import file_sha256
    from pcbsmith.production_generators import generate_nonmutating_kicad_drc

    if (root / "design").exists() or any((root / "attempts").glob("manual-route-*")):
        raise ValueError(
            "Existing routed design: use production-edit-board for local revisions. "
            "This frozen manual-routing recipe is for fresh research reproduction only."
        )
    placement_board = placement(root)
    native = placement_board.parent
    out = (
        root
        / "attempts"
        / f"manual-route-{len(list((root / 'attempts').glob('manual-route-*'))) + 1:02d}"
    )
    shutil.copytree(native, out / "design")
    board = out / "design" / (PROJECT + ".kicad_pcb")
    netlist = parse_board_netlist(
        (native / ".pcbsmith/kicad" / (PROJECT + ".net.xml")).read_text(encoding="utf-8")
    )
    paths = {
        "+5V_IN": [[(4, 13), (4, 10), (6, 8), (10.3, 8)]],
        "VIN_PROTECTED": [[(23, 8), (23, 17), (25.54, 19.54), (25.54, 24.5)]],
        "+3V3": [
            [
                (28.08, 24.5),
                (28.08, 17),
                (28.08, 10.5),
                (45.5, 10.5),
                (48, 13),
                (48, 23),
                (48, 28),
                (47, 29),
                (45.16, 29),
            ],
            [(48, 13), (46, 13)],
            [(48, 23), (46, 23)],
        ],
        "GND": [
            [(4, 15.54), (7, 18.54), (18, 18.54), (18, 17)],
            [
                (18, 18.54),
                (18, 24.5),
                (23, 24.5),
                (23, 27.5),
                (33.08, 27.5),
                (33.08, 17),
                (43, 17),
                (44, 16),
                (44, 15.54),
                (46, 15.54),
            ],
            [(44, 16), (44, 25.54), (46, 25.54)],
            [(23, 27.5), (23, 31), (26, 34), (30, 34)],
        ],
        "LED_A": [[(35, 29), (35, 31.54), (32.54, 34)]],
    }
    segments = tuple(
        TrackSegment(*a, *b, "B.Cu", "/" + name, 0.6 if name == "LED_A" else 0.8)
        for name, chains in paths.items()
        for chain in chains
        for a, b in zip(chain, chain[1:], strict=False)
    )

    def text(label, x, y, size=1, layer="F.SilkS"):
        return (
            f'(gr_text {json.dumps(label)} (at {x + 20} {y + 20}) (layer "{layer}") '
            f"(effects (font (size {size} {size}) (thickness {size * 0.15}))))"
        )

    graphics = (
        text("BENCHLEAF", 25, 3.8, 1.8),
        text("3V3 / R001", 25, 6, 1),
        text("5V IN", 8, 12, 1),
        text("GND", 8, 16.1, 0.9),
        text("3V3 A", 40, 12, 0.9),
        text("3V3 B", 40, 22, 0.9),
        text("50mA TOTAL", 37, 8.2, 0.9),
        text("5V REGULATED INPUT", 11, 24, 0.9),
        text("NO OUTPUT BACKFEED", 11, 27, 0.8),
        text("BOTTOM SOLDER / NO VIAS", 13, 30, 0.8),
        text("POWER", 31.2, 37.2, 0.9),
        text("G  IN  OUT", 25.5, 30.5, 0.8),
    )
    layout = BoardLayout(
        placements=tuple((c, PARTS[c.reference]["position"][0]) for c in netlist.components),
        segments=segments,
        vias=(),
        width_mm=50,
        height_mm=40,
        part_y_mm=tuple((ref, p["position"][1]) for ref, p in PARTS.items()),
        part_rotation=tuple((ref, p["position"][2]) for ref, p in PARTS.items()),
        graphics=graphics,
        part_reference_at=(
            ("U1", (2.54, 3.2, 0)),
            ("C1", (-1.0, 4.7, 0)),
            ("C2", (2.5, 4.8, 0)),
            ("R1", (5.08, 2.4, 0)),
            ("J1", (0, -2.3, 0)),
            ("J2", (0, -2.3, 0)),
            ("J3", (0, -2.3, 0)),
        ),
    )
    write(board, render_board_from_layout(netlist, layout, profile=profile()))
    dump(
        out / "manual-routing.json",
        dict(
            producer="assistant-reviewed-explicit-copper-plan",
            automatic_router_used=False,
            source_placement=str(placement_board.relative_to(root)),
            source_sha256=file_sha256(placement_board),
            board_sha256=file_sha256(board),
            paths=paths,
            profile=profile().model_dump(mode="json"),
            production_release="not_evaluated; manual path has no accepted native-router receipt",
        ),
    )
    generate_nonmutating_kicad_drc(board, out / "drc.json")
    print("ROUTED", board)
    return board


def review(root):
    import shutil

    from pcbsmith.kicad.model_preflight import (
        ModelRegistryEntry,
        ModelRequirement,
        preflight_board_models,
    )
    from pcbsmith.manufacturing_lineage import file_sha256
    from pcbsmith.review.visual_package import (
        RenderProfile,
        ReviewFeatures,
        generate_visual_review_package,
    )

    attempts = sorted((root / "attempts").glob("manual-route-*"))
    chosen = attempts[-1]
    data = json.loads((chosen / "drc.json").read_text(encoding="utf-8"))
    assert not any(
        data[k] for k in ("violations", "unconnected_items", "schematic_parity", "ignored_checks")
    )
    target = root / "design"
    if target.exists():
        raise ValueError("Final design folder exists; preserve it and choose a revision")
    shutil.copytree(
        chosen / "design", target, ignore=shutil.ignore_patterns(".pcbsmith", "*.kicad_prl")
    )
    board = target / (PROJECT + ".kicad_pcb")
    variables = {
        f"KICAD{version}_3DMODEL_DIR": "C:/Program Files/KiCad/10.0/share/kicad/3dmodels"
        for version in (8, 9, 10)
    }
    provisional = preflight_board_models(board, variables=variables)
    registry = tuple(
        ModelRegistryEntry(
            raw_path=m.raw_path,
            classification="proxy" if m.reference in ("C1", "C2", "R1") else "exact_package",
            license_status=(
                "Installed official KiCad library, private review use; retain "
                "upstream licensing before redistribution"
            ),
            part_number=PARTS[m.reference]["mpn"],
            local_path=m.resolved_path,
            expected_sha256=m.sha256,
            expected_transform=m.transform,
        )
        for m in {m.raw_path: m for m in provisional.models}.values()
    )
    requirements = tuple(
        ModelRequirement(
            reference=ref,
            accepted_classifications=("proxy",)
            if ref in ("C1", "C2", "R1")
            else ("exact_package",),
        )
        for ref, p in PARTS.items()
        if p.get("populated", True)
    )
    preflight = preflight_board_models(
        board,
        variables=variables,
        registry=registry,
        requirements=requirements,
        applicability="applicable",
    )
    write(root / "checks/model-preflight.json", preflight.model_dump_json(indent=2) + "\n")
    print("MODEL PREFLIGHT", preflight.status, flush=True)
    before = file_sha256(board)
    manifest = generate_visual_review_package(
        board_file=board,
        output_dir=root / "visual-review",
        stage="final",
        features=ReviewFeatures(has_holes=True),
        model_preflight=preflight,
        profile=RenderProfile(three_d_long_edge_px=1920),
        progress=lambda msg: print(msg, flush=True),
    )
    assert file_sha256(board) == before
    dump(
        root / "checks/render-summary.json",
        dict(
            board_sha256=before,
            status=manifest.package_status,
            artifacts=len(manifest.artifacts),
            missing=[a.artifact_id for a in manifest.artifacts if a.state == "missing"],
        ),
    )
    print("VISUAL", manifest.package_status, flush=True)
    return board


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["prepare", "predesign", "placement", "routed", "review"])
    parser.add_argument("--root", type=Path, default=Path("outputs") / PROJECT)
    parser.add_argument("--research", action="store_true", help="frozen manual reproduction only")
    args = parser.parse_args()
    if not args.research:
        parser.error(
            "this frozen recipe requires --research; use the supported workflow for new work"
        )
    {
        "prepare": prepare,
        "predesign": predesign,
        "placement": placement,
        "routed": routed,
        "review": review,
    }[args.stage](args.root.resolve())
