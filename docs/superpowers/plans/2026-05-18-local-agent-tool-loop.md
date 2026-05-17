# R14B Local Agent Tool Loop Plan

## Goal

Let a local OpenAI-compatible model use PCBSmith tools before it submits a
candidate plan, while preserving the same validation and approval loop.

## Steps

1. Add tests for the local-agent instruction boundary, safe tool contract, and a
   tool-call-then-final-plan run.
2. Implement `pcbsmith.ai.local_agent` with transcript writing, tool execution,
   noisy JSON extraction, and approval-preview handoff.
3. Expose the loop as `local-agent-review` in the CLI.
4. Document the local-agent boundary in roadmap and handoff notes.
5. Verify with unit tests, focused CLI integration tests, linting, and full
   pytest.
