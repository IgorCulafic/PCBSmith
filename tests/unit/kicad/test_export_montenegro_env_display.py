from pcbsmith.generation.montenegro_env_display import (
    LED_COUNT,
    compose_montenegro_env_display,
)
from pcbsmith.kicad.export_montenegro_env_display import (
    PIN_NETS,
    U1_NC_PINS,
    export_montenegro_env_display_to_kicad,
)


def test_export_writes_readable_complete_schematic(tmp_path) -> None:
    circuit = compose_montenegro_env_display()
    artifacts = export_montenegro_env_display_to_kicad(
        circuit, tmp_path, project_name="montenegro-env-display-r001"
    )
    schematic = (tmp_path / "montenegro-env-display-r001.kicad_sch").read_text(encoding="utf-8")

    assert artifacts["schematic_file"].endswith(".kicad_sch")
    assert '(paper "A2")' in schematic
    assert schematic.count('property "Reference" "D') >= LED_COUNT
    assert schematic.count('property "Reference" "C') >= LED_COUNT + 7
    assert len(U1_NC_PINS) + len(PIN_NETS["U1"]) == 41
    assert f"LED_CHAIN_{LED_COUNT - 1:02d}" in schematic
    assert "USB_D+_MCU" in schematic
