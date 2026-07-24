# PCBSmith R9 Template Library Design

## Purpose

R9 turns repeated circuit patterns into reusable source-controlled templates that
AI tools can compose into the current project. Templates are not generated KiCad
projects, screenshots, or old demos. They are stable callable definitions with
metadata, parameters, net ports, and builders that produce a `CircuitDesign`.

## Boundaries

Generated examples and smoke outputs remain under ignored output folders or
curated examples. They may prove a template works, but they are not the template
source of truth.

The template library lives in Python source under `src/pcbsmith/templates/`.
It exposes JSON-friendly metadata so hosted or local models can discover
available blocks without reading implementation code.

## Template Model

Each template has:

- `id`: stable identifier such as `led_string` or `power_input_2pin`.
- `title`: short user-facing name.
- `description`: compact AI/user explanation.
- `category`: grouping such as `power`, `led`, or `switching`.
- `parameters`: typed parameter metadata with defaults.
- `net_ports`: local net names the caller can bind to project nets.
- `tags`: search and retrieval tags.
- `builder`: function that turns a template use plus a reference allocator into
  a `CircuitDesign`.

Template uses are structured values:

- `template_id`
- optional `instance`
- optional `params`
- optional `net_bindings`

Internal nets must be namespaced by instance so the same template can be used
multiple times in one circuit.

## Initial Templates

R9 starts with templates we already discussed and partially implemented:

- `power_input_2pin`
- `decoupling_capacitor`
- `led_string`
- `low_side_mosfet_switch`
- `gpio_led_output`

These are intentionally small. Larger arrays and boards should be composed from
these blocks first, then later promoted to higher-level templates only when the
pattern is stable.

## AI Contract

The AI should discover templates through a registry/listing function and compose
them through a structured API. It should not copy KiCad files or create new
one-off Python scripts for common blocks.

The registry must return compact metadata suitable for RAG/local model context.
Detailed implementation stays in code and tests.

## Validation

Tests must prove:

- the registry lists known templates with parameters and net ports;
- unknown template IDs are rejected;
- repeated template uses allocate unique references;
- repeated template uses namespace internal nets;
- composed templates still render to a real KiCad schematic path through the
  existing circuit pipeline.

## Self-Review

No placeholders remain. The design is intentionally limited to reusable circuit
templates, not board-layout templates or GUI work. Board layout templates can be
added later on top of the same registry idea once the circuit template boundary
is stable.
