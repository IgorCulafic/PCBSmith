# PCBSmith OpenAI-Compatible Review Pipeline Design

## Decision

PCBSmith will provide a single dry-run-first command that turns a user request into a model-backed approval preview:

1. Read a request text file.
2. Build the AI engineering brief.
3. Build the provider-neutral planner package.
4. Call an OpenAI-compatible model endpoint.
5. Validate the returned candidate plan.
6. Run the existing approval preview, applying only when `--apply` is explicitly passed.

This command is a convenience wrapper around existing safer primitives. It does not give the model direct write access to project files.

## Output Folder

Every run writes its intermediate artifacts into a chosen output directory:

- `ai-brief.json`
- `ai-planner-package.json`
- `candidate-plan.json`

These files are intentionally kept inspectable so model behavior can become future training/evaluation data.

## Acceptance Test

- A mocked local OpenAI-compatible endpoint can drive the full CLI command without real network or model dependencies.
- The default command path is a dry run and does not mutate project files.
- Passing `--apply` applies only after the candidate plan passes the existing validator.
