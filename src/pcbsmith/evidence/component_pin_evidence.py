"""Exact-package pin evidence for schematic review.

This is a PCBSmith-native implementation informed by the public Pinscope
package/pin extraction workflow. It deliberately strengthens the boundary:
an extraction is not usable when the exact package variant, source locator,
pin-count equality, or unique pin identity is missing.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal, Self

from pydantic import Field, model_validator

from pcbsmith.evidence.models import EvidenceLocator
from pcbsmith.routed_copper_graph_ir import require_identity, require_sha256
from pcbsmith.semantic_ir import SemanticIrModel

PinElectricalRole = Literal[
    "supply",
    "ground",
    "signal",
    "configuration",
    "clock",
    "thermal_pad",
    "no_connect",
    "other",
    "unknown",
]


def _canonical_strings(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    canonical = tuple(sorted(require_identity(value, field_name) for value in values))
    if len(canonical) != len(set(canonical)):
        raise ValueError(f"{field_name} must contain unique values")
    return canonical


def _locator_has_position(locator: EvidenceLocator) -> bool:
    return any(
        value is not None
        for value in (locator.page, locator.section, locator.table, locator.figure)
    )


class DatasheetPinEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-datasheet-pin-evidence"] = (
        "pcbsmith-datasheet-pin-evidence"
    )
    schema_version: Literal[1] = 1
    number: str
    name: str
    electrical_role: PinElectricalRole
    functions: tuple[str, ...] = ()
    locator: EvidenceLocator

    @model_validator(mode="after")
    def pin_is_located_and_canonical(self) -> Self:
        require_identity(self.number, "pin number")
        require_identity(self.name, "pin name")
        if not _locator_has_position(self.locator):
            raise ValueError("pin evidence requires a page, section, table, or figure locator")
        object.__setattr__(
            self,
            "functions",
            _canonical_strings(self.functions, "pin functions"),
        )
        return self


class DatasheetPackageEvidence(SemanticIrModel):
    schema_id: Literal["pcbsmith-datasheet-package-evidence"] = (
        "pcbsmith-datasheet-package-evidence"
    )
    schema_version: Literal[1] = 1
    package_name: str
    exact_variant: str
    pin_count: int = Field(gt=0)
    ordering_code: str | None = None
    locator: EvidenceLocator

    @model_validator(mode="after")
    def package_is_exact_and_located(self) -> Self:
        require_identity(self.package_name, "package_name")
        require_identity(self.exact_variant, "exact_variant")
        if self.ordering_code is not None:
            require_identity(self.ordering_code, "ordering_code")
        if not _locator_has_position(self.locator):
            raise ValueError(
                "package evidence requires a page, section, table, or figure locator"
            )
        return self


class ComponentPinEvidence(SemanticIrModel):
    """A source-bound, exact-variant pin table."""

    schema_id: Literal["pcbsmith-component-pin-evidence"] = (
        "pcbsmith-component-pin-evidence"
    )
    schema_version: Literal[1] = 1
    manufacturer: str
    part_number: str
    source_sha256: str
    source_local_path: str
    extraction_status: Literal["machine_extracted", "human_reviewed"]
    package: DatasheetPackageEvidence
    pins: tuple[DatasheetPinEvidence, ...] = Field(min_length=1)
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def pin_table_matches_exact_package(self) -> Self:
        require_identity(self.manufacturer, "manufacturer")
        require_identity(self.part_number, "part_number")
        require_identity(self.source_local_path, "source_local_path")
        require_sha256(self.source_sha256, "source_sha256")
        if self.package.exact_variant.casefold() != self.part_number.casefold():
            raise ValueError("package exact_variant must match the selected part_number")
        pins = tuple(sorted(self.pins, key=lambda item: _pin_sort_key(item.number)))
        numbers = tuple(item.number for item in pins)
        if len(numbers) != len(set(numbers)):
            raise ValueError("datasheet pin numbers must be unique")
        if len(pins) != self.package.pin_count:
            raise ValueError(
                "datasheet pin count does not match exact-package pin_count "
                f"({len(pins)} != {self.package.pin_count})"
            )
        notes = tuple(require_identity(note, "notes") for note in self.notes)
        object.__setattr__(self, "pins", pins)
        object.__setattr__(self, "notes", notes)
        return self

    def pin(self, number: str) -> DatasheetPinEvidence | None:
        return next((item for item in self.pins if item.number == number), None)


def _pin_sort_key(value: str) -> tuple[int, int | str, str]:
    stripped = value.strip()
    if stripped.isdigit():
        return (0, int(stripped), stripped)
    return (1, stripped.casefold(), stripped)


PIN_EXTRACTION_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "package": {
            "type": "object",
            "properties": {
                "package_name": {"type": "string"},
                "exact_variant": {"type": "string"},
                "pin_count": {"type": "integer", "minimum": 1},
                "ordering_code": {"type": ["string", "null"]},
                "page": {"type": ["integer", "null"]},
                "section": {"type": ["string", "null"]},
                "table": {"type": ["string", "null"]},
                "figure": {"type": ["string", "null"]},
            },
            "required": [
                "package_name",
                "exact_variant",
                "pin_count",
                "ordering_code",
                "page",
                "section",
                "table",
                "figure",
            ],
            "additionalProperties": False,
        },
        "pins": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "number": {"type": "string"},
                    "name": {"type": "string"},
                    "electrical_role": {
                        "type": "string",
                        "enum": [
                            "supply",
                            "ground",
                            "signal",
                            "configuration",
                            "clock",
                            "thermal_pad",
                            "no_connect",
                            "other",
                            "unknown",
                        ],
                    },
                    "functions": {"type": "array", "items": {"type": "string"}},
                    "page": {"type": ["integer", "null"]},
                    "section": {"type": ["string", "null"]},
                    "table": {"type": ["string", "null"]},
                    "figure": {"type": ["string", "null"]},
                },
                "required": [
                    "number",
                    "name",
                    "electrical_role",
                    "functions",
                    "page",
                    "section",
                    "table",
                    "figure",
                ],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["package", "pins", "notes"],
    "additionalProperties": False,
}


def build_pin_extraction_prompt(
    *,
    manufacturer: str,
    part_number: str,
) -> str:
    """Build the exact-variant extraction request used by PDF-capable clients."""

    return (
        "Extract the complete pin table for an exact component/package variant.\n"
        f"Manufacturer: {manufacturer}\n"
        f"Exact part number: {part_number}\n\n"
        "Rules:\n"
        "- Use only the package/ordering variant matching the exact part number above.\n"
        "- Include every physical pin, ball, and exposed/thermal pad exactly once.\n"
        "- Preserve datasheet pin numbers and pin names verbatim.\n"
        "- Record alternate functions without inferring undocumented functions.\n"
        "- Classify electrical_role conservatively; use unknown when ambiguous.\n"
        "- Give a page plus section/table/figure locator for the package and every pin.\n"
        "- Never fill missing values from a related package or family member.\n"
        "- The pins array length must exactly equal package.pin_count.\n"
        "Return only JSON matching the supplied schema."
    )


def component_pin_evidence_from_payload(
    payload: Mapping[str, Any],
    *,
    manufacturer: str,
    part_number: str,
    source_sha256: str,
    source_local_path: str,
    extraction_status: Literal["machine_extracted", "human_reviewed"] = (
        "machine_extracted"
    ),
) -> ComponentPinEvidence:
    """Validate a structured extraction payload and bind every locator to its source."""

    package_raw = payload.get("package")
    pins_raw = payload.get("pins")
    notes_raw = payload.get("notes", ())
    if not isinstance(package_raw, Mapping):
        raise ValueError("pin extraction payload package must be an object")
    if not isinstance(pins_raw, list):
        raise ValueError("pin extraction payload pins must be an array")
    if not isinstance(notes_raw, list):
        raise ValueError("pin extraction payload notes must be an array")

    package = DatasheetPackageEvidence(
        package_name=str(package_raw.get("package_name", "")),
        exact_variant=str(package_raw.get("exact_variant", "")),
        pin_count=package_raw.get("pin_count"),
        ordering_code=_optional_string(package_raw.get("ordering_code")),
        locator=_locator(package_raw, source_local_path),
    )
    pins = tuple(
        DatasheetPinEvidence(
            number=str(item.get("number", "")),
            name=str(item.get("name", "")),
            electrical_role=item.get("electrical_role", "unknown"),
            functions=tuple(item.get("functions", ())),
            locator=_locator(item, source_local_path),
        )
        for item in pins_raw
        if isinstance(item, Mapping)
    )
    if len(pins) != len(pins_raw):
        raise ValueError("pin extraction payload contains a non-object pin entry")
    return ComponentPinEvidence(
        manufacturer=manufacturer,
        part_number=part_number,
        source_sha256=source_sha256,
        source_local_path=source_local_path,
        extraction_status=extraction_status,
        package=package,
        pins=pins,
        notes=tuple(str(note) for note in notes_raw),
    )


def parse_component_pin_payload(raw: str) -> Mapping[str, Any]:
    """Parse a strict JSON object without accepting prose-wrapped partial arrays."""

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError("pin extraction response was not valid JSON") from error
    if not isinstance(payload, Mapping):
        raise ValueError("pin extraction response root must be an object")
    return payload


def _locator(value: Mapping[str, Any], source_local_path: str) -> EvidenceLocator:
    page = value.get("page")
    return EvidenceLocator(
        local_file=source_local_path,
        page=page if isinstance(page, int) and not isinstance(page, bool) else None,
        section=_optional_string(value.get("section")),
        table=_optional_string(value.get("table")),
        figure=_optional_string(value.get("figure")),
    )


def _optional_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
