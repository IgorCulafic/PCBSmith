from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from pcbsmith.evidence.component_pin_evidence import (
    build_pin_extraction_prompt,
    component_pin_evidence_from_payload,
    parse_component_pin_payload,
)


def _payload() -> dict:
    return {
        "package": {
            "package_name": "QFN-4",
            "exact_variant": "EXACT-4Q",
            "pin_count": 4,
            "ordering_code": "4Q",
            "page": 2,
            "section": "Ordering information",
            "table": None,
            "figure": None,
        },
        "pins": [
            {
                "number": str(index),
                "name": name,
                "electrical_role": role,
                "functions": functions,
                "page": 3,
                "section": "Pin configuration",
                "table": "Table 1",
                "figure": None,
            }
            for index, name, role, functions in (
                (1, "VDD", "supply", []),
                (2, "SDA", "signal", ["I2C_SDA"]),
                (3, "SCL", "signal", ["I2C_SCL"]),
                (4, "GND", "ground", []),
            )
        ],
        "notes": [],
    }


def _build(payload: dict):
    return component_pin_evidence_from_payload(
        payload,
        manufacturer="Example",
        part_number="EXACT-4Q",
        source_sha256="a" * 64,
        source_local_path="datasheets/EXACT-4Q.pdf",
    )


def test_exact_package_pin_payload_is_source_bound_and_canonical() -> None:
    evidence = _build(_payload())

    assert evidence.package.pin_count == len(evidence.pins) == 4
    assert evidence.pins[1].functions == ("I2C_SDA",)
    assert evidence.pins[1].locator.local_file == "datasheets/EXACT-4Q.pdf"
    assert evidence.pin("4").name == "GND"


def test_pin_count_mismatch_fails_instead_of_accepting_partial_extraction() -> None:
    payload = _payload()
    payload["pins"].pop()

    with pytest.raises(ValidationError, match="pin count does not match"):
        _build(payload)


def test_duplicate_pin_and_wrong_variant_fail_closed() -> None:
    duplicate = _payload()
    duplicate["pins"][3]["number"] = "3"
    with pytest.raises(ValidationError, match="pin numbers must be unique"):
        _build(duplicate)

    wrong_variant = _payload()
    wrong_variant["package"]["exact_variant"] = "RELATED-8Q"
    with pytest.raises(ValidationError, match="exact_variant"):
        _build(wrong_variant)


def test_each_pin_requires_a_datasheet_locator() -> None:
    payload = _payload()
    payload["pins"][0].update(page=None, section=None, table=None, figure=None)

    with pytest.raises(ValidationError, match="pin evidence requires"):
        _build(payload)


def test_parser_is_strict_and_prompt_names_exact_variant_rules() -> None:
    raw = json.dumps(_payload())
    assert parse_component_pin_payload(raw)["package"]["pin_count"] == 4
    with pytest.raises(ValueError, match="valid JSON"):
        parse_component_pin_payload(f"Here is the result:\n{raw}")

    prompt = build_pin_extraction_prompt(
        manufacturer="Example",
        part_number="EXACT-4Q",
    )
    assert "every physical pin" in prompt
    assert "exactly equal" in prompt
    assert "Never fill missing values from a related package" in prompt
