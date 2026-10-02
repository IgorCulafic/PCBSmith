"""Ambiguous or malformed model authority must not obtain a readiness pass."""

import pytest

from pcbsmith.kicad.model_preflight import (
    ModelRegistryEntry,
    ModelRequirement,
    ModelTransformTolerance,
    preflight_board_models,
)


@pytest.fixture
def model_input(tmp_path):
    model = tmp_path / "part.step"
    model.write_bytes(b"synthetic model, not package qualification")
    board = tmp_path / "test.kicad_pcb"
    board.write_text(
        '(kicad_pcb (footprint "Test:Part" '
        '(property "Reference" "U1") (property "MPN" "PART-A") '
        '(model "part.step" (offset (xyz 0 0 0)) '
        "(scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))))",
        encoding="utf-8",
    )
    registry = ModelRegistryEntry(
        raw_path="part.step", classification="proxy", license_status="test"
    )
    requirement = ModelRequirement(reference="U1", accepted_classifications=("proxy",))
    return board, registry, requirement


def test_duplicate_normalized_registry_cannot_override_authority(model_input):
    board, entry, requirement = model_input
    override = entry.model_copy(update={"raw_path": "PART.STEP", "classification": "exact_package"})
    with pytest.raises(ValueError, match="duplicate model registry"):
        preflight_board_models(board, registry=(entry, override), requirements=(requirement,))


def test_duplicate_requirements_cannot_weaken_classification(model_input):
    board, entry, requirement = model_input
    strict = requirement.model_copy(update={"accepted_classifications": ("exact_package",)})
    with pytest.raises(ValueError, match="duplicate model requirement"):
        preflight_board_models(board, registry=(entry,), requirements=(strict, requirement))


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "invalid"])
def test_nonfinite_or_nonnumeric_transform_is_rejected(model_input, value):
    board, entry, requirement = model_input
    board.write_text(
        board.read_text(encoding="utf-8").replace("xyz 0 0 0", f"xyz {value} 0 0"), encoding="utf-8"
    )
    with pytest.raises(ValueError, match="finite"):
        preflight_board_models(board, registry=(entry,), requirements=(requirement,))


@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_nonfinite_tolerance_is_rejected(value):
    with pytest.raises(ValueError):
        ModelTransformTolerance(offset_mm=value)


@pytest.mark.parametrize(
    "replacement", ["(offset (xyz 0 0))", "(offset)", "(offset (xyz 0 0 0 1))"]
)
def test_malformed_transform_is_not_silently_defaulted(model_input, replacement):
    board, entry, requirement = model_input
    board.write_text(
        board.read_text(encoding="utf-8").replace("(offset (xyz 0 0 0))", replacement),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="transform"):
        preflight_board_models(board, registry=(entry,), requirements=(requirement,))


def test_duplicate_board_reference_is_ambiguous(model_input):
    board, entry, requirement = model_input
    text = board.read_text(encoding="utf-8")
    footprint = text[len("(kicad_pcb ") : -1]
    board.write_text("(kicad_pcb " + footprint + " " + footprint + ")", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate.*reference"):
        preflight_board_models(board, registry=(entry,), requirements=(requirement,))
