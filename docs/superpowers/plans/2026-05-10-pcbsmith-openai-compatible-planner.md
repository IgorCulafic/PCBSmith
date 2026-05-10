# PCBSmith OpenAI-Compatible Planner Plan

## Steps

1. Add a service that builds OpenAI-compatible chat request payloads from planner packages.
2. Post requests with stdlib HTTP, optional bearer auth, timeout handling, and optional JSON mode.
3. Parse model responses into JSON candidate plans and validate them against the existing planner package contract.
4. Add a CLI command for the adapter.
5. Add unit tests for request shaping, auth, parsing, validation, and errors.
6. Add an integration test using a local mock `/v1/chat/completions` server.
7. Add a dev-check smoke path and run focused/full verification.
