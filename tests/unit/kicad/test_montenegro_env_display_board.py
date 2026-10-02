from pcbsmith.kicad.montenegro_env_display_board import (
    FIXED_BACK_PLACEMENTS,
    MONTENEGRO_ROUTING_PROFILE,
    MONTENEGRO_RULE_PROFILE,
)


def test_usb_receptacle_is_edge_facing_and_sensor_is_not_in_narrow_peninsula() -> None:
    assert FIXED_BACK_PLACEMENTS["J1"] == (7.50, 75.00, 270.0)
    assert FIXED_BACK_PLACEMENTS["U3"] == (17.00, 75.00, 180.0)
    assert FIXED_BACK_PLACEMENTS["U4"] == (35.00, 122.00, 0.0)


def test_routing_uses_margin_above_the_manufacturing_clearance() -> None:
    geometry = MONTENEGRO_RULE_PROFILE.geometry
    assert geometry.minimum_trace_width_mm == 0.15
    assert geometry.routing_via_diameter_mm == 0.55
    assert geometry.routing_via_drill_mm == 0.30
    assert MONTENEGRO_RULE_PROFILE.fab_spacing.minimum_copper_clearance_mm == 0.15
    assert MONTENEGRO_ROUTING_PROFILE.fab_spacing.minimum_copper_clearance_mm == 0.18
