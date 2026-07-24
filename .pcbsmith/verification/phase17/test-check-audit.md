# Test and production-check inventory

This report is an inventory and triage aid, not an instruction to delete tests by age or count.

## Scale

- 2,799 collected pytest cases.
- 2,069 authored test functions across 235 files.
- 244 authored functions use parametrization.
- 93 name-matched production check/validation functions, including 54 public entrypoints.

The collected-case count is therefore not a count of independent PCB rules. Parametrization, tamper matrices, and contract variants expand one authored contract into many cases.

## Static review leads

- Files importing production-private symbols: 48.
- Assertions containing numeric literals: 1819 (many are legitimate boundary contracts).
- Assertions containing literal SHA-like values: 118.
- Numeric assertions mentioning coordinate/scale fields: 113.
- Numeric assertions mentioning work/time/memory budgets: 143.
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
- domain_or_contract: 60
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
- `module-local:pcbsmith.production_workflow`: 4
- `module-local:pcbsmith.project_brief`: 1
- `module-local:pcbsmith.protection_coordination_ir`: 1
- `module-local:pcbsmith.services.erc`: 1
- `module-local:pcbsmith.simulation.ngspice_thermometer`: 1
- `module-local:pcbsmith.surge_clamp_ir`: 1
- `module-local:pcbsmith.workflow_authority`: 1
- `module-local:pcbsmith.workflow_feasibility`: 1
- `workflow.conformance`: 1

## Caller-coverage triage

- framework: 6
- observed: 34
- test_only: 24
- unobserved: 29

## Measured runtime attribution

- JUnit source: `D:\AI\PCB designer\.pcbsmith\verification\phase17\full-suite-junit.xml`
- Summed testcase time: 640.720 s

| Seconds | Test |
|---:|---|
| 32.082 | `tests/unit/kicad/test_astar_router.py::test_reroutes_flyback_fb_net_verifier_clean` |
| 30.755 | `tests/unit/kicad/test_negotiated_grid.py::test_layer_specific_track_and_via_permissions_steer_to_back_copper` |
| 28.331 | `tests/unit/kicad/test_astar_router.py::test_routes_entire_flyback_board_from_bare_placements` |
| 18.876 | `tests/unit/kicad/test_bus_physical_swap_candidate.py::test_candidate_input_order_repeat_and_clearance_authority_are_deterministic` |
| 16.502 | `tests/unit/kicad/test_bus_physical_swap_candidate_transaction.py::test_truthful_physical_candidate_replaces_once_and_preserves_foreign_state` |
| 16.339 | `tests/unit/kicad/test_bus_physical_swap_candidate.py::test_truthful_success_binds_all_physical_prefixes_and_preserves_foreign_ledger` |
| 13.227 | `tests/unit/kicad/test_servo555_board.py::test_rect_pad_corners_are_covered_for_the_router` |
| 12.641 | `tests/integration/test_divider_highpass_led_authority_cli.py::test_authority_cli_truthfully_marks_pcbs_fallback_when_kicad_spice_fails` |
| 12.620 | `tests/unit/kicad/test_servo555_board.py::test_power_nets_carry_the_forty_mil_width` |
| 12.580 | `tests/unit/kicad/test_servo555_board.py::test_every_physical_switch_pad_gets_copper` |
| 12.492 | `tests/unit/kicad/test_servo555_board.py::test_silk_text_height_and_edge_containment_are_checked` |
| 12.456 | `tests/unit/kicad/test_servo555_board.py::test_router_layout_is_virtually_clean_and_passes_design_checks` |
| 12.362 | `tests/integration/test_divider_highpass_led_authority_cli.py::test_authority_cli_uses_cached_evidence_manifest` |
| 12.297 | `tests/integration/test_divider_highpass_led_authority_cli.py::test_authority_cli_writes_kicad_and_authority_bundle` |
| 12.187 | `tests/unit/kicad/test_servo555_board.py::test_traces_are_not_over_segmented` |
| 12.178 | `tests/unit/kicad/test_bus_physical_swap_candidate.py::test_missing_duplicate_or_member_swapped_physical_prefixes_reject` |
| 12.008 | `tests/unit/kicad/test_bus_physical_swap_composition.py::test_result_coverage_and_fingerprint_tamper_rejects` |
| 10.713 | `tests/unit/kicad/test_bus_physical_swap_composition.py::test_successive_swap_plan_composes_all_connected_member_prefixes` |
| 9.283 | `tests/unit/kicad/test_bus_physical_swap_composition.py::test_input_set_order_is_canonical_and_repeat_is_deterministic` |
| 8.435 | `tests/unit/kicad/test_bus_physical_swap_replay_checked_commit.py::test_checked_envelope_json_rejects_nested_materialized_evidence_tamper` |
| 8.394 | `tests/unit/kicad/test_bus_physical_swap_replay_checked_commit.py::test_accepted_exact_commit_checks_full_physical_and_foreign_copper_once` |
| 7.513 | `tests/unit/kicad/test_bus_physical_swap_composition.py::test_failed_plan_and_missing_duplicate_or_unused_inputs_reject` |
| 7.437 | `tests/unit/kicad/test_corridor_guided_shaped.py::test_real_shaped_corridor_plan_guides_detailed_route_deterministically` |
| 6.574 | `tests/unit/kicad/test_bus_physical_swap_candidate.py::test_one_less_member_per_member_and_total_budgets_are_typed[budget1-per_member_expansion_budget-m0-1]` |
| 6.398 | `tests/unit/kicad/test_bus_physical_swap_composition.py::test_boundary_endpoint_geometry_and_carrier_membership_tamper_rejects` |

## Interpretation limits

- Static numeric-literal and private-import counts are review leads, not defects.
- Exact duplicate bodies do not detect semantically overlapping tests with different fixtures.
- Runtime attribution requires a timed full-suite run and is not inferred from source size.
- Candidate production functions are name-based; Pydantic validators and inline invariants are additional authorities.
- Caller-reference counts are lexical triage signals; dynamic dispatch and same-file calls require manual review.
