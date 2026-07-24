# Test and production-check inventory

This report is an inventory and triage aid, not an instruction to delete tests by age or count.

## Scale

- 2,763 collected pytest cases.
- 2,033 authored test functions across 229 files.
- 244 authored functions use parametrization.
- 88 name-matched production check/validation functions, including 52 public entrypoints.

The collected-case count is therefore not a count of independent PCB rules. Parametrization, tamper matrices, and contract variants expand one authored contract into many cases.

## Static review leads

- Files importing production-private symbols: 46.
- Assertions containing numeric literals: 1800 (many are legitimate boundary contracts).
- Assertions containing literal SHA-like values: 118.
- Numeric assertions mentioning coordinate/scale fields: 112.
- Numeric assertions mentioning work/time/memory budgets: 141.
- Exact duplicate test-body groups: 2.
- Explicit sleep calls: 0; subprocess calls: 7.

## Largest files by collected cases

| Cases | Functions | Lines | File |
|---:|---:|---:|---|
| 52 | 20 | 878 | `tests/unit/kicad/test_bus_checked_commit.py` |
| 51 | 12 | 486 | `tests/unit/kicad/test_placement_serialization.py` |
| 51 | 27 | 1013 | `tests/unit/test_bus_geometry.py` |
| 44 | 19 | 794 | `tests/unit/kicad/test_assembly_retention.py` |
| 42 | 11 | 520 | `tests/unit/kicad/test_antenna_rf_validation.py` |
| 40 | 20 | 1073 | `tests/unit/kicad/test_bus_physical_swap_plan.py` |
| 39 | 15 | 689 | `tests/unit/kicad/test_placement_pilot_authority.py` |
| 39 | 30 | 569 | `tests/unit/test_routing_ir.py` |
| 38 | 21 | 815 | `tests/unit/test_bus_ir.py` |
| 36 | 30 | 997 | `tests/unit/kicad/test_corridor_planner.py` |
| 35 | 18 | 660 | `tests/unit/kicad/test_sensor_copper_removal.py` |
| 33 | 15 | 502 | `tests/unit/kicad/test_aggregate_thermometer_simulation_adapter.py` |
| 32 | 25 | 491 | `tests/unit/kicad/test_negotiated_resources.py` |
| 30 | 13 | 530 | `tests/unit/kicad/test_antenna_enclosure.py` |
| 30 | 13 | 379 | `tests/unit/kicad/test_antenna_semantics.py` |
| 30 | 15 | 885 | `tests/unit/kicad/test_placement_acceptance_manifest.py` |
| 30 | 12 | 257 | `tests/unit/test_placement_pose_authority.py` |
| 29 | 15 | 514 | `tests/unit/kicad/test_aggregate_reader_netlist_equality_adapter.py` |
| 28 | 19 | 721 | `tests/unit/kicad/test_decoupling_loop.py` |
| 28 | 22 | 720 | `tests/unit/test_corridor_ir.py` |
| 27 | 26 | 808 | `tests/unit/kicad/test_virtual_drc.py` |
| 26 | 13 | 506 | `tests/unit/kicad/test_antenna_cutout.py` |
| 26 | 11 | 546 | `tests/unit/kicad/test_bus_escape_replay.py` |
| 26 | 17 | 764 | `tests/unit/kicad/test_corridor_exchange_preparation.py` |
| 26 | 8 | 541 | `tests/unit/test_corridor_guidance.py` |

## Production function families

- design_checks: 19
- domain_or_contract: 55
- kicad_cli_adapter: 2
- semantic_evaluator: 2
- virtual_drc: 10

## Production-check ownership

- `engineering.project-gate`: 1
- `kicad.saved-board`: 12
- `layout.connector-protection-order`: 1
- `layout.decoupling-loop`: 1
- `layout.oscillator-zone`: 1
- `layout.return-adjacency`: 1
- `layout.semantic-process`: 19
- `layout.switching-hot-loop`: 1
- `module-local:pcbsmith.bootstrap_supply_ir`: 1
- `module-local:pcbsmith.bus_ir`: 1
- `module-local:pcbsmith.components`: 1
- `module-local:pcbsmith.cooling_assembly_ir`: 2
- `module-local:pcbsmith.evidence.divider_highpass_led`: 3
- `module-local:pcbsmith.gate_drive_ir`: 3
- `module-local:pcbsmith.gate_driver_migration_ir`: 1
- `module-local:pcbsmith.gate_driver_support_ir`: 1
- `module-local:pcbsmith.gate_supply_architecture_ir`: 1
- `module-local:pcbsmith.kicad.aggregate_exact_checker`: 1
- `module-local:pcbsmith.kicad.antenna_clearance`: 1
- `module-local:pcbsmith.kicad.antenna_cutout`: 1
- `module-local:pcbsmith.kicad.antenna_edge`: 1
- `module-local:pcbsmith.kicad.antenna_enclosure`: 1
- `module-local:pcbsmith.kicad.antenna_rf_validation`: 1
- `module-local:pcbsmith.kicad.antenna_semantics`: 1
- `module-local:pcbsmith.kicad.assembly_retention`: 1
- `module-local:pcbsmith.kicad.board_region`: 1
- `module-local:pcbsmith.kicad.bus_lcs_cost_physical_realization`: 1
- `module-local:pcbsmith.kicad.bus_lcs_cost_replay_checked_commit`: 1
- `module-local:pcbsmith.kicad.bus_lcs_physical_realization`: 1
- `module-local:pcbsmith.kicad.bus_physical_swap_replay_checked_commit`: 3
- `module-local:pcbsmith.kicad.bus_replay_checked_commit`: 1
- `module-local:pcbsmith.kicad.connector_zone`: 1
- `module-local:pcbsmith.kicad.neighbor_overhang`: 1
- `module-local:pcbsmith.kicad.placement_detail`: 1
- `module-local:pcbsmith.kicad.placement_exact`: 1
- `module-local:pcbsmith.kicad.placement_surrogates`: 1
- `module-local:pcbsmith.kicad.sensor_bridge`: 1
- `module-local:pcbsmith.kicad.sensor_copper_removal`: 1
- `module-local:pcbsmith.kicad.sensor_isolation`: 1
- `module-local:pcbsmith.kicad.sensor_validation`: 1
- `module-local:pcbsmith.kicad.switch_node_area_policy`: 1
- `module-local:pcbsmith.kicad.thermal_semantics`: 1
- `module-local:pcbsmith.kicad.thermometer_bus`: 1
- `module-local:pcbsmith.loss_stress_ir`: 1
- `module-local:pcbsmith.operating_scenario_ir`: 1
- `module-local:pcbsmith.project_brief`: 1
- `module-local:pcbsmith.protection_coordination_ir`: 1
- `module-local:pcbsmith.services.erc`: 1
- `module-local:pcbsmith.simulation.ngspice_thermometer`: 1
- `module-local:pcbsmith.surge_clamp_ir`: 1
- `module-local:pcbsmith.workflow_authority`: 1
- `workflow.conformance`: 1

## Caller-coverage triage

- framework: 5
- observed: 33
- test_only: 22
- unobserved: 28

## Measured runtime attribution

- JUnit source: `D:\AI\PCB designer\.pcbsmith\verification\phase16-focused-junit.xml`
- Summed testcase time: 1.648 s

| Seconds | Test |
|---:|---|
| 1.103 | `tests/unit/core/test_geom.py::test_point_add_sub_inverse` |
| 0.107 | `tests/unit/test_project_engineering_gate.py::test_project_gate_cli_writes_the_replay_bound_completion_artifact` |
| 0.070 | `tests/unit/test_project_engineering_gate.py::test_result_without_reviewed_feature_and_incomplete_inventory_fail_closed` |
| 0.068 | `tests/unit/test_project_engineering_gate.py::test_applicable_result_cannot_be_silently_omitted_or_bound_to_another_board` |
| 0.059 | `tests/unit/test_project_engineering_gate.py::test_context_and_gate_result_reject_tampering` |
| 0.050 | `tests/unit/test_project_engineering_gate.py::test_retrieved_but_uninstalled_cad_asset_remains_unverified` |
| 0.049 | `tests/unit/core/test_geom.py::test_snap_is_idempotent` |
| 0.048 | `tests/unit/test_project_engineering_gate.py::test_gate_derives_applicability_consumes_real_result_and_can_be_ready` |
| 0.048 | `tests/unit/test_project_engineering_gate.py::test_unrevisioned_exact_part_document_remains_unverified` |
| 0.019 | `tests/unit/test_execution.py::test_orchestrator_reuses_gates_and_checkpoints_only_after_completion` |
| 0.004 | `tests/unit/test_execution.py::test_optional_failure_is_attention_required` |
| 0.003 | `tests/unit/test_execution.py::test_quick_profile_fail_fast_records_unexecuted_required_gate` |
| 0.002 | `tests/unit/test_workflow_authority.py::test_capability_and_registry_fingerprints_reject_tampering` |
| 0.002 | `tests/unit/test_workflow_authority.py::test_workflow_state_machine_requires_every_ordered_stage` |
| 0.001 | `tests/unit/core/test_geom.py::test_box_contains_closed_edges` |
| 0.001 | `tests/unit/core/test_geom.py::test_snap_half_grid_negative_rounds_away_from_zero` |
| 0.001 | `tests/unit/test_project_brief.py::test_normalization_is_repeatable_and_ready_only_when_resolved` |
| 0.001 | `tests/unit/test_workflow_authority.py::test_board_identity_change_invalidates_every_downstream_identity` |
| 0.001 | `tests/unit/test_workflow_authority.py::test_capability_map_covers_phases_1_through_15_and_registered_authorities` |
| 0.001 | `tests/unit/test_workflow_authority.py::test_deprecated_one_off_authority_cannot_satisfy_current_workflow` |
| 0.001 | `tests/unit/test_workflow_authority.py::test_external_provider_unavailability_never_authorizes_a_substitute` |
| 0.001 | `tests/unit/test_workflow_authority.py::test_failed_state_is_terminal` |
| 0.001 | `tests/unit/test_workflow_authority.py::test_human_decision_and_board_trigger_are_explicit` |
| 0.001 | `tests/unit/test_workflow_authority.py::test_incomplete_state_requires_reason_and_checkpoint_to_resume` |
| 0.001 | `tests/unit/test_workflow_authority.py::test_project_context_requires_every_category_exactly_once` |

## Interpretation limits

- Static numeric-literal and private-import counts are review leads, not defects.
- Exact duplicate bodies do not detect semantically overlapping tests with different fixtures.
- Runtime attribution requires a timed full-suite run and is not inferred from source size.
- Candidate production functions are name-based; Pydantic validators and inline invariants are additional authorities.
- Caller-reference counts are lexical triage signals; dynamic dispatch and same-file calls require manual review.
