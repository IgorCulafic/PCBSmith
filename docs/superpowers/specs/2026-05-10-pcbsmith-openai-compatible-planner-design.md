# PCBSmith OpenAI-Compatible Planner Design

## Decision

PCBSmith will add a provider adapter for OpenAI-compatible chat completion APIs. The adapter is intentionally narrow: it sends an existing PCBSmith planner package to a model and accepts only a validated candidate command plan in return.

This keeps hosted models, local models, and future multi-agent planners inside the same approval loop:

1. PCBSmith builds an AI brief and planner package from project context.
2. The OpenAI-compatible adapter asks a model for candidate JSON only.
3. PCBSmith validates the candidate plan against the planner package contract.
4. The existing approval/review path dry-runs or applies the validated plan.
5. KiCad validation and previews remain the proof step.

## Scope

This phase adds the first real model adapter. It does not let a model edit KiCad files directly, execute shell commands, or bypass the deterministic plan checker.

The adapter supports:

- Local OpenAI-compatible servers such as LM Studio, llama.cpp server, Ollama-compatible gateways, or vLLM gateways when they expose `/v1/chat/completions`.
- Hosted OpenAI-compatible APIs with optional bearer token authentication.
- JSON-mode request bodies by default, with an escape hatch for local servers that do not implement `response_format`.
- Defensive parsing of model output, including plain JSON and fenced JSON.

## KiCad Artifact Direction

PCBSmith should support KiCad-style extensibility by leaning on KiCad-native project files rather than recreating CAD systems poorly.

Later phases should model these as KiCad-backed artifacts:

- Imported symbols, footprints, and component libraries.
- 3D model references for footprints and board previews.
- Multilayer boards and layer stack definitions.
- Vias, plated holes, keepouts, copper zones, and routing constraints.
- Gerber, drill, solder mask, solder paste, and manufacturing export files.
- KiCad-generated ERC, DRC, board SVG, schematic SVG, and manufacturing reports.

The AI layer should reason over manifests, context packages, visual previews, and KiCad reports, then propose structured edits that PCBSmith can validate.

## Acceptance Test

- A CLI command can call an OpenAI-compatible `/v1/chat/completions` endpoint using a planner package and write a candidate plan.
- The candidate plan is rejected if it is not valid JSON, does not match the KiCad plan schema, targets the wrong schematic, or uses disallowed command types.
- Tests use a local mock HTTP server, not a real model or network dependency.
- Existing deterministic AI demo flows continue to pass.
