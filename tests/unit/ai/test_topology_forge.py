"""Topology forge (Track 8.3): the propose-verify loop, mock-driven."""

from __future__ import annotations

import json

from pcbsmith.ai.topology_forge import (
    extract_json,
    forge_topology,
    verify_topology_spec,
)

GOOD_SPEC = {
    "components": [
        {"reference": "J1", "role": "power_connector", "value": "12V IN",
         "footprint": (
             "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
         )},
        {"reference": "R1", "role": "led_series_resistor", "value": "1k",
         "footprint": "Resistor_SMD:R_0603_1608Metric"},
        {"reference": "D1", "role": "indicator_led", "value": "green",
         "footprint": "LED_SMD:LED_0603_1608Metric"},
    ],
    "pin_nets": {
        "J1": {"1": "VIN", "2": "GND"},
        "R1": {"1": "VIN", "2": "LED_A"},
        "D1": {"1": "GND", "2": "LED_A"},
    },
}


def test_good_spec_verifies_clean() -> None:
    assert verify_topology_spec(GOOD_SPEC) == ()


def test_verifier_localizes_errors() -> None:
    broken = json.loads(json.dumps(GOOD_SPEC))
    broken["components"][1]["footprint"] = "Nope:NotReal"
    del broken["pin_nets"]["D1"]["1"]
    broken["pin_nets"]["R1"]["2"] = "FLOATY"
    findings = verify_topology_spec(broken)
    text = "\n".join(findings)
    assert "R1: footprint 'Nope:NotReal'" in text
    assert "D1.1: pad has no net" in text
    assert "net FLOATY: only R1.2" in text


def test_forge_converges_on_feedback() -> None:
    broken = json.loads(json.dumps(GOOD_SPEC))
    broken["components"][2]["footprint"] = "LED_SMD:LED_Wrong"
    replies = iter((
        "Here you go:\n```json\n" + json.dumps(broken) + "\n```",
        json.dumps(GOOD_SPEC),
    ))
    prompts: list[str] = []

    def scripted(prompt: str) -> str:
        prompts.append(prompt)
        return next(replies)

    result = forge_topology("12V LED indicator", scripted, max_iterations=3)
    assert result.status == "accepted"
    assert result.iterations == 2
    # The second prompt carried the verifier's findings back.
    assert "LED_Wrong" in prompts[1]
    assert "verifier rejected" in prompts[1]


def test_forge_rejects_garbage() -> None:
    result = forge_topology(
        "anything", lambda prompt: "I cannot help with that.",
        max_iterations=2,
    )
    assert result.status == "invalid"
    assert result.findings_history[-1] == (
        "reply contained no parseable JSON object",
    )


def test_extract_json_finds_fenced_and_bare() -> None:
    assert extract_json('noise {"a": 1} noise') == {"a": 1}
    assert extract_json("```json\n{\"b\": 2}\n```") == {"b": 2}
    assert extract_json("no json here") is None
