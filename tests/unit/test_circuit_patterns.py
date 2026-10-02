"""Synthetic pattern controls, not real board acceptance or physical evidence."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest
from tests.unit.test_engineering_preview import inputs  # noqa: F401

from pcbsmith.calculators.passive import led_current_limit_bounds
from pcbsmith.circuit_patterns import CircuitPatternSet, inspect_circuit_patterns
from pcbsmith.design_readiness import SupportObservation, SupportRequirement
from pcbsmith.engineering_preview import EngineeringInputs, evaluate_engineering_inputs
from pcbsmith.manufacturing_lineage import file_sha256


@pytest.fixture
def pattern_fixture(inputs):  # noqa: F811
    root, engineering = inputs
    xml = root / "native.net.xml"
    xml.write_text("""<export><components>
      <comp ref="D1"><value>LED</value><footprint>LED:THT</footprint>
      <fields><field name="MPN">SYNTHETIC-z</field></fields></comp>
      <comp ref="R1"><value>2k</value><footprint>R:THT</footprint>
      <fields><field name="MPN">SYNTHETIC-R</field></fields></comp>
      </components><nets><net name="GND"><node ref="D1" pin="1"/></net>
      <net name="LED_A"><node ref="D1" pin="2"/><node ref="R1" pin="2"/></net>
      <net name="5V"><node ref="R1" pin="1"/></net></nets></export>""")
    config = dict(
        native_netlist_evidence_id="native",
        patterns=[
            dict(
                pattern_id="led",
                kind="indicator",
                rail_high="5V",
                rail_low="GND",
                parts=dict(
                    led=dict(
                        reference="D1",
                        value="LED",
                        footprint="LED:THT",
                        mpn="SYNTHETIC-z",
                        pins={"1": "GND", "2": "LED_A"},
                    ),
                    resistor=dict(
                        reference="R1",
                        value="2k",
                        footprint="R:THT",
                        mpn="SYNTHETIC-R",
                        pins={"1": "5V", "2": "LED_A"},
                    ),
                ),
                source_locators={"source": "Synthetic fixture paragraph 1"},
                operating_conditions="4.75 to 5.25 V; synthetic test only",
                placement_requirements="Series path reviewed separately",
                protection_assumptions="No reverse drive; bounded bench source",
                physical_tests=["Measure current and brightness"],
                support_requirement_ids=["led-limit"],
                limits=dict(
                    current=dict(
                        minimum=0, maximum=0.003, allowed_minimum=0, allowed_maximum=0.01, units="A"
                    ),
                    resistor_power=dict(
                        minimum=0, maximum=0.015, allowed_minimum=0, allowed_maximum=0.25, units="W"
                    ),
                ),
                indicator=dict(
                    supply_min_v=4.75,
                    supply_max_v=5.25,
                    forward_min_v=0,
                    forward_max_v=2.5,
                    resistance_ohms=2000,
                    resistance_tolerance=0.01,
                ),
            )
        ],
    )
    for limit in config["patterns"][0]["limits"].values():
        limit["evidence_scope"] = "operating_envelope"
    engineering["support_requirements"] = [
        SupportRequirement(
            requirement_id="led-limit",
            subject_reference="D1",
            kind="current_limiting",
            source_ids=("circuit-patterns",),
            rationale="Synthetic pattern contract",
        ).model_dump()
    ]
    engineering["support_observations"] = [
        SupportObservation(
            requirement_id="led-limit",
            disposition="verified",
            supporting_references=("R1",),
            evidence_ids=("source",),
            rationale="Synthetic fixture only",
        ).model_dump()
    ]
    return root, engineering, config, xml


def bind(root, engineering, config, xml):
    pattern_file = root / "patterns.json"
    pattern_file.write_text(json.dumps(config))
    for key, path in (("circuit-patterns", pattern_file), ("native", xml)):
        engineering["evidence_files"][key] = dict(relative_path=path.name, sha256=file_sha256(path))
    (root / "component-readiness.json").write_text(
        json.dumps(dict(source_inputs={str(xml): file_sha256(xml)}))
    )
    return EngineeringInputs.model_validate(engineering)


def check(fixture):
    root, engineering, config, xml = fixture
    return evaluate_engineering_inputs(
        bind(root, engineering, config, xml), expected_references={"D1"}, artifact_root=root
    )


def test_real_consumer_valid_pattern(pattern_fixture):
    report = check(pattern_fixture)
    assert not report.blockers
    root, _, config, xml = pattern_fixture
    before = {p.name: file_sha256(p) for p in root.iterdir() if p.is_file()}
    result = inspect_circuit_patterns(CircuitPatternSet.model_validate(config), xml)
    assert result["approval_granted"] is False
    assert result["calculations"]["led"]["current_max_a"] == pytest.approx(5.25 / 1980)
    assert before == {p.name: file_sha256(p) for p in root.iterdir() if p.is_file()}


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("reverse", "pin_or_polarity"),
        ("missing", "missing_component"),
        ("mpn", "identity_mismatch"),
        ("rating", "outside_supported_rating"),
        ("understate", "calculation_outside"),
        ("omit_support", "obligation omitted"),
        ("missing_source", "lack retained"),
        ("unbind", "lacks its source"),
    ],
)
def test_existing_consumer_rejects_faults(pattern_fixture, mutation, expected):
    root, eng, config, xml = pattern_fixture
    p = config["patterns"][0]
    if mutation == "reverse":
        xml.write_text(xml.read_text().replace('ref="D1" pin="1"', 'ref="D1" pin="9"'))
    elif mutation == "missing":
        p["parts"]["resistor"]["reference"] = "R2"
        eng["support_observations"][0]["supporting_references"] = ["R2"]
    elif mutation == "mpn":
        p["parts"]["resistor"]["mpn"] = "WRONG"
    elif mutation == "rating":
        p["limits"]["current"]["allowed_maximum"] = 0.002
    elif mutation == "understate":
        p["limits"]["current"]["maximum"] = 0.001
    elif mutation == "omit_support":
        eng["support_requirements"] = []
        eng["support_observations"] = []
    elif mutation == "missing_source":
        p["source_locators"] = {"missing": "p1"}
    elif mutation == "unbind":
        eng["support_requirements"][0]["source_ids"] = ["source"]
    with pytest.raises(ValueError, match=expected):
        check(pattern_fixture)


def test_other_native_inventory_rejected(pattern_fixture):
    root, eng, config, xml = pattern_fixture
    typed = bind(root, eng, config, xml)
    (root / "component-readiness.json").write_text(
        json.dumps(dict(source_inputs={"other.net.xml": "0" * 64}))
    )
    with pytest.raises(ValueError, match="differs from current native inventory"):
        evaluate_engineering_inputs(typed, expected_references={"D1"}, artifact_root=root)


def test_stale_pattern_source_rejected(pattern_fixture):
    root, eng, config, xml = pattern_fixture
    typed = bind(root, eng, config, xml)
    (root / "patterns.json").write_text("{}")
    with pytest.raises(ValueError, match="source evidence changed"):
        evaluate_engineering_inputs(typed, expected_references={"D1"}, artifact_root=root)


@pytest.mark.parametrize(
    "kind,roles,limits",
    [
        ("connector", {"connector": "led"}, {"voltage": ("V", 5, 50), "current": ("A", 0.01, 1)}),
        (
            "supply_bypass",
            {"device": "led", "capacitor": "resistor"},
            {"voltage": ("V", 5, 50), "capacitance": ("F", 1e-6, 2e-6), "esr": ("ohm", 0.2, 2)},
        ),
    ],
)
def test_pattern_shapes_require_all_roles_and_limits(pattern_fixture, kind, roles, limits):
    _, _, config, _ = pattern_fixture
    p = config["patterns"][0]
    p["parts"] = {role: p["parts"][old] for role, old in roles.items()}
    p["kind"] = kind
    p["indicator"] = None
    p["limits"] = {
        k: dict(
            units=u,
            minimum=0,
            maximum=v,
            allowed_minimum=0,
            allowed_maximum=m,
            evidence_scope="operating_envelope",
        )
        for k, (u, v, m) in limits.items()
    }
    for part in p["parts"].values():
        part["pins"] = {"1": "5V", "2": "GND"}
    if kind == "supply_bypass":
        p["parts"]["capacitor"]["value"] = "1uF"
    CircuitPatternSet.model_validate(config)
    missing = deepcopy(config)
    missing["patterns"][0]["parts"].pop(next(iter(roles)))
    with pytest.raises(ValueError, match="required roles"):
        CircuitPatternSet.model_validate(missing)
    p["limits"].pop(next(iter(limits)))
    with pytest.raises(ValueError, match="operating limits"):
        CircuitPatternSet.model_validate(config)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_nonfinite_or_negative_rating_rejected(pattern_fixture, value):
    config = pattern_fixture[2]
    config["patterns"][0]["limits"]["current"]["maximum"] = value
    with pytest.raises(ValueError):
        CircuitPatternSet.model_validate(config)


def test_led_bounds_do_not_round_away_overload():
    bounds = led_current_limit_bounds(
        supply_min_v=5,
        supply_max_v=5,
        forward_min_v=0,
        forward_max_v=2,
        resistance_ohms=1999,
        resistance_tolerance=0,
    )
    assert bounds["current_max_a"] > 0.0025
    assert bounds["power_max_w"] > 0.0125


def test_led_no_conduction_and_invalid_intervals():
    args = dict(
        supply_min_v=1,
        supply_max_v=2,
        forward_min_v=3,
        forward_max_v=4,
        resistance_ohms=1000,
        resistance_tolerance=0,
    )
    assert set(led_current_limit_bounds(**args).values()) == {0}
    for change in (
        {"supply_min_v": 3},
        {"resistance_tolerance": 1},
        {"supply_max_v": float("nan")},
        {"supply_max_v": True},
    ):
        with pytest.raises(ValueError):
            led_current_limit_bounds(**(args | change))


@pytest.mark.parametrize("scope", ["single_frequency_only", "unverified"])
def test_limited_evidence_cannot_claim_operating_envelope(pattern_fixture, scope):
    pattern_fixture[2]["patterns"][0]["limits"]["current"]["evidence_scope"] = scope
    with pytest.raises(ValueError, match="operating_envelope_unverified"):
        check(pattern_fixture)


def test_calculator_cannot_use_a_different_resistor(pattern_fixture):
    pattern_fixture[2]["patterns"][0]["indicator"]["resistance_ohms"] = 3000
    with pytest.raises(ValueError, match="resistance differs"):
        check(pattern_fixture)


def test_parallel_resistor_is_not_a_series_limiter(pattern_fixture):
    p = pattern_fixture[2]["patterns"][0]
    p["parts"]["resistor"]["pins"] = dict(p["parts"]["led"]["pins"])
    with pytest.raises(ValueError, match="series resistor"):
        check(pattern_fixture)


def test_wrong_support_reference_fails(pattern_fixture):
    pattern_fixture[1]["support_observations"][0]["supporting_references"] = ["R9"]
    with pytest.raises(ValueError, match="supporting component"):
        check(pattern_fixture)


@pytest.mark.parametrize("kind", ["supply_bypass", "connector"])
def test_supply_and_connector_faults_use_existing_consumer(pattern_fixture, kind):
    root, engineering, config, xml = pattern_fixture
    p = config["patterns"][0]
    led, resistor = p["parts"]["led"], p["parts"]["resistor"]
    for part in (led, resistor):
        part["pins"] = {"1": "5V", "2": "GND"}
    resistor["value"] = "1uF"
    p["kind"] = kind
    p["indicator"] = None
    p["parts"] = (
        {"device": led, "capacitor": resistor} if kind == "supply_bypass" else {"connector": led}
    )
    values = (
        {
            "voltage": (0, 5, 0, 50, "V"),
            "capacitance": (0.9e-6, 1.1e-6, 0.8e-6, 10e-6, "F"),
            "esr": (0, 0.2, 0, 2, "ohm"),
        }
        if kind == "supply_bypass"
        else {"voltage": (0, 5, 0, 50, "V"), "current": (0, 0.01, 0, 1, "A")}
    )
    p["limits"] = {
        key: dict(
            minimum=lo,
            maximum=hi,
            allowed_minimum=alo,
            allowed_maximum=ahi,
            units=unit,
            evidence_scope="operating_envelope",
        )
        for key, (lo, hi, alo, ahi, unit) in values.items()
    }
    if kind == "connector":
        engineering["support_observations"][0]["supporting_references"] = ["D1"]
    xml.write_text(
        xml.read_text().replace("<value>2k</value>", "<value>1uF</value>").split("<nets>")[0]
        + '<nets><net name="5V"><node ref="D1" pin="1"/>'
        '<node ref="R1" pin="1"/></net><net name="GND"><node ref="D1" pin="2"/>'
        '<node ref="R1" pin="2"/></net></nets></export>'
    )
    assert not check(pattern_fixture).blockers
    # Actual native connectivity is reversed without changing the expected contract.
    good = xml.read_text()
    xml.write_text(
        good.replace('ref="R1" pin="1"', 'ref="R1" pin="9"')
        if kind == "supply_bypass"
        else good.replace('ref="D1" pin="1"', 'ref="D1" pin="9"')
    )
    with pytest.raises(ValueError, match="pin_or_polarity"):
        check(pattern_fixture)
    xml.write_text(good)
    p["limits"]["voltage"]["maximum"] = 51
    with pytest.raises(ValueError, match="outside_supported_rating"):
        check(pattern_fixture)
    if kind == "supply_bypass":
        p["limits"]["voltage"]["maximum"] = 5
        import xml.etree.ElementTree as ET

        doc = ET.fromstring(good)
        components = doc.find("components")
        components.remove(components.findall("comp")[1])
        xml.write_text(ET.tostring(doc, encoding="unicode"))
        with pytest.raises(ValueError, match="missing_component"):
            check(pattern_fixture)


@pytest.mark.parametrize(
    "text,expected", [("100nF", 1e-7), ("2.2uF", 2.2e-6), ("1µF", 1e-6), ("470p", 470e-12)]
)
def test_capacitance_values(text, expected):
    from pcbsmith.calculators.passive import parse_capacitance_farads

    assert parse_capacitance_farads(text) == pytest.approx(expected)


def test_extracted_resistance_parser_retains_simulation_behavior():
    from pcbsmith.calculators.passive import parse_resistance_ohms
    from pcbsmith.simulation.ngspice_thermometer import _ohms

    assert _ohms is parse_resistance_ohms
    for text, expected in (("270R", 270), ("1k", 1000), ("2.2M", 2.2e6)):
        assert _ohms(text) == expected


def test_annotated_resistance_and_tolerance_are_bound(pattern_fixture):
    _, _, config, xml = pattern_fixture
    p = config["patterns"][0]
    p["parts"]["resistor"]["value"] = "2k 1%"
    xml.write_text(xml.read_text().replace("<value>2k</value>", "<value>2k 1%</value>"))
    assert not check(pattern_fixture).blockers
    p["indicator"]["resistance_tolerance"] = 0.005
    with pytest.raises(ValueError, match="understates native resistor tolerance"):
        check(pattern_fixture)
