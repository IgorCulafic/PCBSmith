from decimal import Decimal

from pcbsmith.gate_driver_migration_ir import (
    GateDriverFunctionMigration,
    GateDriverMigrationProfile,
    GateDriverPackageCandidate,
    GateDriverPinAssignment,
    MigrationDisposition,
    evaluate_gate_driver_migration,
)


def _candidate() -> GateDriverPackageCandidate:
    return GateDriverPackageCandidate(
        candidate_id="driver-candidate",
        orderable_part_number="DRV8334RGZR",
        manufacturer_status="ACTIVE",
        package_code="RGZ0048N",
        package_style="VQFN",
        signal_pin_count=2,
        thermal_pad_pin_number=3,
        body_width_mm=Decimal("7"),
        body_height_mm=Decimal("7"),
        pin_pitch_mm=Decimal("0.5"),
        proposed_footprint_id="Package_DFN_QFN:Texas_RGZ0048A",
        proposed_3d_model_id="Package_DFN_QFN.3dshapes/Texas_RGZ0048A.step",
        footprint_sha256="a" * 64,
        model_sha256="b" * 64,
        source_binding_ids=("source:driver",),
    )


def _assignment(pin: int) -> GateDriverPinAssignment:
    return GateDriverPinAssignment(
        pin_number=pin,
        function_id=f"pin-{pin}",
        proposed_net_id="PGND" if pin == 3 else f"net-{pin}",
        disposition=MigrationDisposition.REMAPPED,
        source_binding_ids=("source:driver",),
    )


def _migration(group_id: str) -> GateDriverFunctionMigration:
    return GateDriverFunctionMigration(
        function_group_id=group_id,
        disposition=MigrationDisposition.REMAPPED,
        source_function_ids=(f"old-{group_id}",),
        target_function_ids=(f"new-{group_id}",),
        notes=("Explicitly reviewed.",),
    )


def test_complete_pin_map_stays_conditional_while_authority_is_open() -> None:
    profile = GateDriverMigrationProfile(
        profile_id="migration:test",
        revision="1",
        current_part_id="old-driver",
        current_package_body_width_mm=Decimal("6"),
        current_package_body_height_mm=Decimal("6"),
        candidate=_candidate(),
        pin_assignments=(_assignment(1), _assignment(2), _assignment(3)),
        function_migrations=(_migration("gate-drive"),),
        required_function_group_ids=("gate-drive",),
        unresolved_authority_ids=("placement-review",),
        source_binding_ids=("source:driver",),
    )
    result = evaluate_gate_driver_migration(profile)
    assert result.disposition == "conditional_candidate"
    assert result.pin_map_complete
    assert result.selection_state == "not_selected"
    assert result.body_area_growth_ratio == Decimal("0.361111111111111111111111111")


def test_incomplete_pin_or_function_map_blocks_migration() -> None:
    profile = GateDriverMigrationProfile(
        profile_id="migration:test",
        revision="1",
        current_part_id="old-driver",
        current_package_body_width_mm=Decimal("6"),
        current_package_body_height_mm=Decimal("6"),
        candidate=_candidate(),
        pin_assignments=(_assignment(1),),
        function_migrations=(),
        required_function_group_ids=("gate-drive",),
        unresolved_authority_ids=(),
        source_binding_ids=("source:driver",),
    )
    result = evaluate_gate_driver_migration(profile)
    assert result.disposition == "blocked"
    assert result.missing_pin_numbers == (2, 3)
    assert result.missing_function_group_ids == ("gate-drive",)
