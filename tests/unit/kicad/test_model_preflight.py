from __future__ import annotations

import hashlib
from pathlib import Path

from pcbsmith.kicad.model_preflight import (
    ModelRegistryEntry,
    ModelRequirement,
    ModelTransform,
    preflight_board_models,
)


def _board(tmp_path: Path, model_path: str) -> Path:
    board = tmp_path / "fixture.kicad_pcb"
    board.write_text(
        f'''(kicad_pcb
  (version 20241229)
  (generator pcbnew)
  (footprint "Sensor_Fixture"
    (layer "F.Cu")
    (property "Reference" "U1")
    (model "{model_path}"
      (offset (xyz 1 2 3))
      (scale (xyz 1 1 1))
      (rotate (xyz 0 0 90))))
)''',
        encoding="utf-8",
    )
    return board


def test_resolves_registered_exact_model_and_retains_transform(tmp_path: Path) -> None:
    model = tmp_path / "models" / "sht31.step"
    model.parent.mkdir()
    model.write_bytes(b"ISO-10303-21; fixture")
    board = _board(tmp_path, "${FIXTURE_MODELS}/sht31.step")
    raw = "${FIXTURE_MODELS}/sht31.step"
    report = preflight_board_models(
        board,
        variables={"FIXTURE_MODELS": str(model.parent)},
        registry=(
            ModelRegistryEntry(
                raw_path=raw,
                classification="exact_package",
                license_status="manufacturer_local_cache",
                part_number="SHT31-DIS",
                expected_sha256=hashlib.sha256(model.read_bytes()).hexdigest(),
                expected_transform=ModelTransform(
                    offset_xyz=("1.0", "2.0", "3.0"),
                    rotate_xyz=("0", "0", "90"),
                ),
            ),
        ),
        requirements=(
            ModelRequirement(
                reference="U1",
                accepted_classifications=("exact_package",),
            ),
        ),
    )

    assert report.status == "passed"
    assert report.models[0].status == "resolved"
    assert report.models[0].part_number == "SHT31-DIS"
    assert report.models[0].transform.offset_xyz == ("1", "2", "3")
    assert report.models[0].transform.rotate_xyz == ("0", "0", "90")
    assert report.models[0].transform_alignment == "passed"


def test_required_model_with_shifted_registered_transform_fails(
    tmp_path: Path,
) -> None:
    model = tmp_path / "shifted.step"
    model.write_bytes(b"ISO-10303-21; shifted")
    board = _board(tmp_path, "shifted.step")
    report = preflight_board_models(
        board,
        registry=(
            ModelRegistryEntry(
                raw_path="shifted.step",
                classification="exact_package",
                license_status="fixture",
                expected_transform=ModelTransform(
                    offset_xyz=("0", "0", "0"),
                    rotate_xyz=("0", "0", "0"),
                ),
            ),
        ),
        requirements=(
            ModelRequirement(
                reference="U1",
                accepted_classifications=("exact_package",),
            ),
        ),
    )

    assert report.status == "failed"
    assert report.models[0].transform_alignment == "failed"
    assert any("differs from registered" in item for item in report.models[0].findings)


def test_required_proxy_must_be_explicitly_accepted(tmp_path: Path) -> None:
    model = tmp_path / "proxy.wrl"
    model.write_text("#VRML V2.0 utf8", encoding="utf-8")
    board = _board(tmp_path, "proxy.wrl")
    registry = (
        ModelRegistryEntry(
            raw_path="proxy.wrl",
            classification="proxy",
            license_status="project_generated",
            redistributable=True,
        ),
    )

    rejected = preflight_board_models(
        board,
        registry=registry,
        requirements=(
            ModelRequirement(reference="U1", accepted_classifications=("exact_package",)),
        ),
    )
    accepted = preflight_board_models(
        board,
        registry=registry,
        requirements=(ModelRequirement(reference="U1", accepted_classifications=("proxy",)),),
    )

    assert rejected.status == "failed"
    assert accepted.status == "passed"


def test_unresolved_optional_model_is_attention_not_silent_success(tmp_path: Path) -> None:
    board = _board(tmp_path, "${MISSING_MODEL_DIR}/part.step")

    report = preflight_board_models(board)

    assert report.status == "attention_required"
    assert report.models[0].status == "unresolved"
    assert "MISSING_MODEL_DIR" in report.models[0].findings[0]


def test_missing_required_reference_fails(tmp_path: Path) -> None:
    board = _board(tmp_path, "relative.step")

    report = preflight_board_models(
        board,
        requirements=(
            ModelRequirement(reference="U99", accepted_classifications=("complete_module",)),
        ),
    )

    assert report.status == "failed"
    assert "absent" in report.findings[0]


def test_registry_local_path_overrides_an_unresolved_board_variable(tmp_path: Path) -> None:
    model = tmp_path / "private" / "exact.step"
    model.parent.mkdir()
    model.write_bytes(b"ISO-10303-21; exact")
    raw = "${PCBSMITH_3DMODEL_DIR}/exact.step"
    board = _board(tmp_path, raw)

    report = preflight_board_models(
        board,
        registry=(
            ModelRegistryEntry(
                raw_path=raw,
                local_path=str(model),
                classification="exact_package",
                license_status="local_cache_only",
            ),
        ),
        requirements=(
            ModelRequirement(reference="U1", accepted_classifications=("exact_package",)),
        ),
    )

    assert report.status == "passed"
    assert report.models[0].resolved_path == str(model.resolve())
