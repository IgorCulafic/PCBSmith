# Test and production-check inventory

This report is an inventory and triage aid, not an instruction to delete tests by age or count.

## Scale

- 2,597 collected pytest cases.
- 1,885 authored test functions across 207 files.
- 238 authored functions use parametrization.
- 71 name-matched production check/validation functions, including 40 public entrypoints.

The collected-case count is therefore not a count of independent PCB rules. Parametrization, tamper matrices, and contract variants expand one authored contract into many cases.

## Static review leads

- Files importing production-private symbols: 43.
- Assertions containing numeric literals: 1713 (many are legitimate boundary contracts).
- Assertions containing literal SHA-like values: 118.
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
| 28 | 22 | 720 | `tests/unit/test_corridor_ir.py` |
| 27 | 26 | 808 | `tests/unit/kicad/test_virtual_drc.py` |
| 26 | 13 | 506 | `tests/unit/kicad/test_antenna_cutout.py` |
| 26 | 11 | 546 | `tests/unit/kicad/test_bus_escape_replay.py` |
| 26 | 17 | 764 | `tests/unit/kicad/test_corridor_exchange_preparation.py` |
| 26 | 8 | 541 | `tests/unit/test_corridor_guidance.py` |
| 25 | 17 | 831 | `tests/unit/kicad/test_negotiated_board.py` |

## Production function families

- design_checks: 19
- domain_or_contract: 38
- kicad_cli_adapter: 2
- semantic_evaluator: 2
- virtual_drc: 10

## Interpretation limits

- Static numeric-literal and private-import counts are review leads, not defects.
- Exact duplicate bodies do not detect semantically overlapping tests with different fixtures.
- Runtime attribution requires a timed full-suite run and is not inferred from source size.
- Candidate production functions are name-based; Pydantic validators and inline invariants are additional authorities.
