# PCBSmith OpenAI-Compatible Review Pipeline Plan

## Steps

1. Add a service that orchestrates request file, brief, planner package, model candidate, and approval preview.
2. Add a CLI command for the full OpenAI-compatible review flow.
3. Keep dry-run as the default and wire `--apply` through the existing approval loop.
4. Add unit tests for dry-run and apply behavior with a mocked model response.
5. Add an integration test using a local mock HTTP endpoint.
6. Add the flow to `tools/dev_check.py`.
