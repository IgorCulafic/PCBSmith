# PCBSmith R10-R14 Intelligence Foundation Plan

## Goal

Move PCBSmith from demo-specific generation toward reusable circuit
intelligence: topology selection, deterministic math boundaries, richer
component roles, and a roadmap for validation/reporting and local AI.

## Scope

- Add a source-controlled topology selector.
- Expose topology selection through the CLI and AI planner package.
- Expand component catalog and component-selection intents for metal detector
  prerequisites without making a detector board yet.
- Update roadmap, handoff, decision log, and presentation brief.

## Implementation Steps

1. Add failing tests for topology selection, AI-facing topology contract, and
   planner rules.
2. Implement `pcbsmith.knowledge.circuit_topologies`.
3. Add `circuit-topologies` CLI.
4. Add topology contract to AI planner packages before component selection.
5. Add failing tests for detector-adjacent catalog entries and selection intents.
6. Add local symbol/footprint metadata and catalog entries for BJTs, comparator,
   op-amp, buzzer, and terminal block.
7. Add component-selection intents for BJT, comparator, buzzer, terminal input,
   trim adjustment, op-amp buffer, and LC sensing.
8. Update project docs so future sessions inherit the topology/math-first
   decision.
9. Run focused tests and then a broader verification set.

## Verification

- `python -m pytest tests/unit/knowledge/test_circuit_topologies.py`
- `python -m pytest tests/unit/knowledge/test_component_catalog.py`
- `python -m pytest tests/unit/knowledge/test_component_selection.py`
- `python -m pytest tests/unit/ai/test_ai_planner_package.py`
- CLI smoke for `circuit-topologies metal-detector`.

## Follow-Up

R11 should add the deterministic calculator modules. The metal detector board
should wait until the coil, resonance, and threshold calculations are available
as callable tools.
