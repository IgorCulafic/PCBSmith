# R14B Local Agent Tool Loop

## Decision

PCBSmith will support a local text-agent loop before multimodal review. The
local model may ask PCBSmith to run a small set of approved tools, then must
submit a structured `final_plan`. PCBSmith still validates that plan and runs
the normal approval preview before any project files can change.

## Boundary

The local model is not a filesystem actor. It must not read, write, rename,
delete, or inspect raw files directly. It receives structured packages and can
only request named PCBSmith tools:

- `project_context`: current project facts and KiCad review references.
- `circuit_topologies`: supported topology guidance for a requested intent.
- `calculator`: deterministic engineering math, such as LC resonance and PCB
  spiral coil estimates.

The initial tool set is intentionally small. It proves the architecture without
letting the model bypass component rules, routing checks, or human approval.

## Flow

1. `local-agent-review` writes the normal AI brief and planner package.
2. The model receives the planner package, tool contract, previous tool results,
   and local-agent instructions.
3. The model returns one JSON action:
   - `tool_call` with a supported tool name and arguments; or
   - `final_plan` with a PCBSmith candidate plan.
4. PCBSmith executes supported tool calls itself and appends results to a
   transcript.
5. The final plan goes through `ai-plan-review` and the existing approval loop.

## Near-Term Follow-Up

Multimodal local review should be advisory and lower authority than deterministic
checks. It can inspect KiCad preview images later, but should produce revision
items rather than directly editing designs.
