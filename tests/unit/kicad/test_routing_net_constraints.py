"""Per-net routing restrictions and paste-only pin regression coverage."""

import pytest
from tests.unit.kicad.test_routing_external_adapters import _layout, _request

from pcbsmith.kicad.freerouting_production import (
    constrain_freerouting_dsn,
    read_single_sided_routes,
)
from pcbsmith.kicad.library import _atom, _children, parse_sexpr
from pcbsmith.kicad.routing_external_adapters import _translation_ledger
from pcbsmith.production_routing import _pin_nets
from pcbsmith.routing_ir import RouteRequest


def restricted_request(**changes):
    c = dict(
        constraint_id="power-front", net_names=("/SIG",), allowed_layers=("F.Cu",), allow_vias=False
    )
    c.update(changes)
    r = _request(_layout())
    return RouteRequest.model_validate({**r.model_dump(), "net_layer_constraints": [c]})


DSN = (
    "(pcb x (unit um) (structure (layer F.Cu (type signal)) (layer B.Cu (type signal)) "
    "(boundary (rect pcb 0 0 30000 12000)) (via old) (rule (clearance 200))) "
    "(library (padstack old (shape (circle F.Cu 600)))) "
    "(network (net /SIG (pins A-1 B-1)) (net /AUX (pins C-1 D-1)) "
    "(class Default /SIG /AUX (circuit (use_via old)) "
    "(rule (width 400) (clearance 200)))))"
)


def two_net_request():
    r = restricted_request()
    raw = r.model_dump()
    net = dict(
        raw["target_domains"][0]["nets"][0], net_name="/AUX", terminal_object_ids=("aux:A", "aux:B")
    )
    raw["target_domains"][0]["nets"] = [*raw["target_domains"][0]["nets"], net]
    for key in ["width_constraints", "topology_constraints"]:
        item = dict(raw[key][0], constraint_id="aux:" + key)
        item["net_names" if key == "width_constraints" else "net_name"] = (
            ["/AUX"] if key == "width_constraints" else "/AUX"
        )
        if key == "topology_constraints":
            item["ordered_terminal_object_ids"] = ("aux:A", "aux:B")
        raw[key] = [*raw[key], item]
    raw["deterministic"]["route_order"] = ["/SIG", "/AUX"]
    return RouteRequest.model_validate(raw)


def test_dsn_splits_same_width_nets_and_retains_other_net_vias():
    r = two_net_request()
    data = constrain_freerouting_dsn(DSN, _layout(), r, 1)
    tree = parse_sexpr(data.decode())
    network = _children(tree, "network")[0]
    classes = {_atom(c[2]): c for c in _children(network, "class")}
    assert set(classes) == {"/SIG", "/AUX"}
    power = classes["/SIG"]
    circuit = _children(power, "circuit")[0]
    assert [_atom(x) for x in _children(circuit, "use_layer")[0][1:]] == ["F.Cu"]
    assert _atom(_children(circuit, "use_via")[0][1]) == "PCBSMITH_NoVia_F.Cu"
    assert _children(_children(power, "rule")[0], "clearance")
    assert _children(_children(classes["/AUX"], "circuit")[0], "use_via")
    assert constrain_freerouting_dsn(data.decode(), _layout(), r, 1) == data


@pytest.mark.parametrize(
    "change",
    [
        {"net_names": ["missing"]},
        {"allowed_layers": ["In1.Cu"]},
        {"allowed_layers": []},
        {"allow_vias": "false"},
    ],
)
def test_invalid_or_ambiguous_constraints_fail(change):
    with pytest.raises(ValueError):
        restricted_request(**change)


def test_overlap_rejected_and_historical_fingerprints_preserved():
    old = _request(_layout())
    raw = old.model_dump()
    assert "net_layer_constraints" not in raw
    assert RouteRequest.model_validate(raw).semantic_fingerprint() == old.semantic_fingerprint()
    r = restricted_request()
    assert r.semantic_fingerprint() != old.semantic_fingerprint()
    raw = r.model_dump()
    raw["net_layer_constraints"] = [
        *raw["net_layer_constraints"],
        {**raw["net_layer_constraints"][0], "constraint_id": "second"},
    ]
    with pytest.raises(ValueError, match="overlap"):
        RouteRequest.model_validate(raw)
    assert "power-front" in r.constraint_ids
    _, failures = _translation_ledger(r)
    assert failures[0].constraint_ids == ("power-front",)


@pytest.mark.parametrize(
    "layer,via,allowed",
    [
        ("F.Cu", False, True),
        ("B.Cu", False, False),
        ("F.Cu", True, False),
    ],
)
def test_native_readback_rejects_forbidden_layer_or_via_without_drc_dependency(
    tmp_path, layer, via, allowed
):
    source = tmp_path / "source.kicad_pcb"
    board = tmp_path / "route.kicad_pcb"
    source.write_text('(kicad_pcb (net 1 "/SIG"))')
    copper = f'(segment (start 21 21) (end 23 21) (width 0.4) (layer "{layer}") (net 1))'
    if via:
        copper += '(via (at 23 21) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 1))'
    board.write_text('(kicad_pcb (net 1 "/SIG")' + copper + ")")
    if allowed:
        result = read_single_sided_routes(board, source, _layout(), restricted_request())
        assert len(result.segments) == 1 and not result.vias
    else:
        with pytest.raises(ValueError, match="per-net"):
            read_single_sided_routes(board, source, _layout(), restricted_request())


@pytest.mark.parametrize(
    "number,kind,layers,drill,omitted",
    [
        ("", "smd", '"F.Paste"', "", True),
        ("", "smd", '"B.Paste"', "", True),
        ("", "smd", '"F.Cu" "F.Paste"', "", False),
        ("2", "smd", '"F.Paste"', "", False),
        ("", "smd", '"F.Paste"', "(drill 0.8)", False),
        ("", "thru_hole", '"F.Paste"', "", False),
        ("", "smd", "", "", False),
        ("", "smd", '"F.Mask"', "", False),
    ],
)
def test_pin_comparison_omits_only_proven_paste_apertures(
    tmp_path, number, kind, layers, drill, omitted
):
    p = tmp_path / "pad.kicad_pcb"
    p.write_text(
        '(kicad_pcb (footprint "Q" (property "Reference" "Q1") '
        f'(pad "{number}" {kind} rect (layers {layers}) {drill} (net "/DRAIN"))))'
    )
    assert _pin_nets(p) == ({} if omitted else {("Q1", number): "/DRAIN"})


def test_stacked_copper_disagreement_remains_blocked(tmp_path):
    p = tmp_path / "short.kicad_pcb"
    p.write_text(
        '(kicad_pcb (footprint "Q" (property "Reference" "Q1") '
        '(pad "2" smd rect (layers "F.Cu") (net "/DRAIN")) '
        '(pad "2" smd rect (layers "F.Cu") (net "/OTHER"))))'
    )
    with pytest.raises(ValueError, match="stacked native pads"):
        _pin_nets(p)


def test_multilayer_no_via_export_is_explicitly_unsupported():
    with pytest.raises(ValueError, match="exactly one copper layer"):
        constrain_freerouting_dsn(
            DSN, _layout(), restricted_request(allowed_layers=("F.Cu", "B.Cu")), 1
        )


@pytest.mark.parametrize("traces", [[], ["In1.Cu"], ["F.Cu", "F.Cu"]])
def test_trace_layers_cannot_expand_copper_permissions_or_be_ambiguous(traces):
    with pytest.raises(ValueError):
        restricted_request(allowed_trace_layers=traces)


def test_trace_only_restrictions_preserve_legacy_serialization_and_via_span():
    from tests.unit.kicad.test_four_layer_logic import LAYERS, four_layer_dsn, four_layer_request

    legacy = restricted_request().net_layer_constraints[0]
    assert "allowed_trace_layers" not in legacy.model_dump()
    request = four_layer_request(
        net_layer_constraints=[
            dict(
                constraint_id="outer-traces",
                net_names=["/SIG"],
                allowed_layers=LAYERS,
                allowed_trace_layers=["F.Cu", "B.Cu"],
                allow_vias=True,
            )
        ]
    )
    payload = constrain_freerouting_dsn(four_layer_dsn(), _layout(), request, 1)
    tree = parse_sexpr(payload.decode())
    cls = next(
        c for c in _children(_children(tree, "network")[0], "class") if _atom(c[2]) == "/SIG"
    )
    circuit = _children(cls, "circuit")[0]
    assert {_atom(v) for v in _children(circuit, "use_layer")[0][1:]} == {"F.Cu", "B.Cu"}
    assert "PCBSMITH_NoVia" not in str(_children(circuit, "use_via"))
    assert request.net_layer_constraints[0].allowed_layers == tuple(sorted(LAYERS))


@pytest.mark.parametrize("layer,allowed", [("F.Cu", True), ("In1.Cu", False), ("B.Cu", True)])
def test_native_reader_and_independent_validator_both_apply_trace_subset(tmp_path, layer, allowed):
    from tests.unit.kicad.test_four_layer_logic import LAYER_TABLE, LAYERS, four_layer_request
    from tests.unit.test_routing_candidate_ir import _complete_candidate

    from pcbsmith.routing_ir import RouteCandidateResult, validate_route_candidate_result

    request = four_layer_request(
        net_layer_constraints=[
            dict(
                constraint_id="outer-traces",
                net_names=["/SIG"],
                allowed_layers=LAYERS,
                allowed_trace_layers=["F.Cu", "B.Cu"],
                allow_vias=True,
            )
        ]
    )
    source, board = tmp_path / "source.kicad_pcb", tmp_path / "route.kicad_pcb"
    source.write_text("(kicad_pcb " + LAYER_TABLE + ' (net 1 "/SIG"))')
    board.write_text(
        "(kicad_pcb "
        + LAYER_TABLE
        + f' (net 1 "/SIG") (segment (start 21 21) (end 23 21) (width 0.4) '
        f'(layer "{layer}") (net 1)) (via (at 23 21) (size 0.6) '
        '(drill 0.3) (layers "F.Cu" "B.Cu") (net 1)))'
    )
    candidate_raw = _complete_candidate(request).model_dump()
    candidate_raw["segment_deltas"][0]["after"]["layer"] = layer
    candidate = RouteCandidateResult.model_validate(candidate_raw)
    if allowed:
        result = read_single_sided_routes(board, source, _layout(), request)
        assert len(result.vias) == 1 and result.segments[0].layer == layer
        validate_route_candidate_result(request, candidate)
    else:
        with pytest.raises(ValueError, match="per-net"):
            read_single_sided_routes(board, source, _layout(), request)
        with pytest.raises(ValueError, match="per-net trace layer"):
            validate_route_candidate_result(request, candidate)


@pytest.mark.parametrize("layer,allow_vias", [("B.Cu", False), ("F.Cu", True)])
def test_global_candidate_validator_also_enforces_restrictions(layer, allow_vias):
    from tests.unit.test_routing_candidate_ir import _complete_candidate
    from tests.unit.test_routing_candidate_ir import _request as ir_request

    from pcbsmith.routing_ir import validate_route_candidate_result

    raw = ir_request().model_dump()
    raw["net_layer_constraints"] = [
        dict(
            constraint_id="power-layer",
            net_names=["/SIG"],
            allowed_layers=[layer],
            allow_vias=allow_vias,
        )
    ]
    request = RouteRequest.model_validate(raw)
    candidate = _complete_candidate(request)  # This synthetic candidate is on F.Cu.
    if layer == "F.Cu":
        validate_route_candidate_result(request, candidate)
    else:
        with pytest.raises(ValueError, match="per-net layer"):
            validate_route_candidate_result(request, candidate)


def test_ordinary_request_carries_the_typed_constraints():
    from types import SimpleNamespace

    from tests.unit.kicad.test_routing_candidate_transaction import _fixture, _snapshot

    from pcbsmith.production_routing import _request as ordinary_request
    from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

    layout, netlist = _fixture()
    snapshot, _ = _snapshot(layout, netlist)
    entry = SimpleNamespace(
        budget_profile_name="deep", saved_board_sha256=snapshot.identity.board_sha256
    )
    expected = restricted_request().net_layer_constraints
    result = ordinary_request(
        snapshot, layout, netlist, DEFAULT_PCB_RULE_PROFILE, entry, net_layer_constraints=expected
    )
    assert result.net_layer_constraints == expected


@pytest.mark.parametrize("kind", ["via", "zone"])
def test_candidate_cannot_hide_forbidden_vias_or_zones(kind):
    from tests.unit.test_routing_candidate_ir import _complete_candidate
    from tests.unit.test_routing_candidate_ir import _request as ir_request

    from pcbsmith.routing_ir import RouteViaDelta, RouteZoneDelta, validate_route_candidate_result

    raw = ir_request().model_dump()
    raw["net_layer_constraints"] = [
        dict(
            constraint_id="power-front",
            net_names=["/SIG"],
            allowed_layers=["F.Cu"],
            allow_vias=False,
        )
    ]
    request = RouteRequest.model_validate(raw)
    candidate = _complete_candidate(request)
    fields = dict(mutation_id="extra", operation="add", object_id="extra")
    if kind == "via":
        technology = request.via_technologies[0]
        delta = RouteViaDelta(
            **fields,
            after=dict(
                net_name="/SIG",
                position=dict(x_mm=3, y_mm=3),
                **technology.model_dump(exclude={"constraint_id"}),
            ),
        )
        candidate = candidate.model_copy(update={"via_deltas": (delta,)})
    else:
        delta = RouteZoneDelta(
            **fields,
            after=dict(
                net_name="/SIG",
                layer="B.Cu",
                boundary=[dict(x_mm=1, y_mm=1), dict(x_mm=3, y_mm=1), dict(x_mm=1, y_mm=3)],
                clearance_mm=0.2,
            ),
        )
        candidate = candidate.model_copy(update={"zone_deltas": (delta,)})
    with pytest.raises(ValueError, match="per-net"):
        validate_route_candidate_result(request, candidate)


def test_native_research_backend_cannot_silently_consume_new_restrictions():
    from pcbsmith.kicad.routing_candidate_adapter import _translation_consumption
    from pcbsmith.rule_profiles import DEFAULT_PCB_RULE_PROFILE

    _, failures = _translation_consumption(restricted_request(), profile=DEFAULT_PCB_RULE_PROFILE)
    assert any("power-front" in f.constraint_ids for f in failures)


def test_duplicate_dsn_class_assignments_block():
    bad = DSN.replace("(class Default", "(class Duplicate /SIG (rule (width 400))) (class Default")
    with pytest.raises(ValueError, match="multiple classes"):
        constrain_freerouting_dsn(bad, _layout(), two_net_request(), 1)


def test_no_via_compatibility_stack_cannot_be_supplied_as_through_via():
    bad = DSN.replace(
        "(library",
        '(library (padstack "PCBSMITH_NoVia_F.Cu" '
        "(shape (circle F.Cu 600)) (shape (circle B.Cu 600)))",
    )
    with pytest.raises(ValueError, match="reserved no-via padstack"):
        constrain_freerouting_dsn(bad, _layout(), two_net_request(), 1)
